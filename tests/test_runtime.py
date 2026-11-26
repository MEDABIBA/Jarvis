from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from jarvis.llm.schemas import TurnEvent
from jarvis.runtime import run_turn
from jarvis.speech.output import SpeechOutput
from jarvis.speech.service import SpeechService
from jarvis.speech.types import AudioChunk, SpeechError


def event(kind, **values):
    return TurnEvent(turn_id="turn", kind=kind, **values)


def scripted(*events):
    closed = Event()

    def stream(text):
        try:
            yield from events
        finally:
            closed.set()

    return SimpleNamespace(handle_stream=stream), closed


def test_text_only_progress_and_authoritative_final_answer():
    engine, closed = scripted(
        event("text_delta", text="Checking. "),
        event("tool_start", tool_name="lookup"),
        event("tool_end", tool_name="lookup"),
        event("text_delta", text="Final answer."),
        event("complete", answer="Final answer."),
    )
    printed = []
    result = run_turn(engine, "question", on_text=printed.append, cancel=Event())
    assert printed == ["Checking. ", "Final answer."]
    assert result.answer == "Final answer."
    assert result.question == "question"
    assert result.turn_id == "turn"
    assert closed.is_set()


def test_speech_receives_public_deltas_and_tool_boundary():
    engine, _ = scripted(
        event("text_delta", text="Checking."),
        event("tool_start", tool_name="lookup"),
        event("text_delta", text="Done."),
        event("complete", answer="Done."),
    )
    speech = Mock()
    result = run_turn(
        engine,
        "question",
        on_text=lambda _: None,
        cancel=Event(),
        speech=speech,
        locale="pl-PL",
    )
    speech.start.assert_called_once_with("pl-PL")
    session = speech.start.return_value
    assert session.feed.call_args_list[0].args == ("Checking.",)
    assert session.feed.call_args_list[1].args == ("Done.",)
    session.boundary.assert_called_once()
    session.finish.assert_called_once()
    session.cancel.assert_not_called()
    assert result.answer == "Done."


def test_backend_error_is_printed_but_not_spoken():
    engine, closed = scripted(
        event("error", text="Backend error", answer="Backend error", error="failed")
    )
    printed = []
    speech = Mock()
    result = run_turn(
        engine, "question", on_text=printed.append, cancel=Event(), speech=speech
    )
    assert printed == ["\nBackend error"]
    assert result.answer == "Backend error"
    speech.start.return_value.feed.assert_not_called()
    speech.start.return_value.cancel.assert_called_once()
    speech.start.return_value.finish.assert_not_called()
    assert closed.is_set()


def test_cancel_closes_engine_before_next_tool_can_run():
    cancel = Event()
    tool = Mock()
    closed = Event()

    def stream(text):
        try:
            yield event("text_delta", text="Checking.")
            tool()
            yield event("complete", answer="Done")
        finally:
            closed.set()

    speech = Mock()
    result = run_turn(
        SimpleNamespace(handle_stream=stream),
        "question",
        on_text=lambda _: cancel.set(),
        cancel=cancel,
        speech=speech,
    )
    assert result is None
    assert closed.is_set()
    tool.assert_not_called()
    speech.start.return_value.cancel.assert_called_once()


def test_already_cancelled_turn_does_not_start_engine_or_speech():
    cancel = Event()
    cancel.set()
    started = Mock()

    def stream(text):
        started()
        yield event("complete", answer="Done")

    speech = Mock()
    assert (
        run_turn(
            SimpleNamespace(handle_stream=stream),
            "question",
            on_text=lambda _: None,
            cancel=cancel,
            speech=speech,
        )
        is None
    )
    started.assert_not_called()
    speech.start.assert_not_called()


def test_speech_start_failure_does_not_lose_text():
    engine, _ = scripted(
        event("text_delta", text="Answer"), event("complete", answer="Answer")
    )
    speech = Mock()
    speech.start.side_effect = SpeechError("Unavailable")
    printed = []
    result = run_turn(
        engine, "question", on_text=printed.append, cancel=Event(), speech=speech
    )
    assert printed == ["Answer"]
    assert result.answer == "Answer"


def test_consumer_failure_cancels_speech_and_closes_engine():
    engine, closed = scripted(event("text_delta", text="Hello"))
    speech = Mock()
    with pytest.raises(ValueError, match="UI failed"):
        run_turn(
            engine,
            "question",
            on_text=Mock(side_effect=ValueError("UI failed")),
            cancel=Event(),
            speech=speech,
        )
    assert closed.is_set()
    speech.start.return_value.cancel.assert_called_once()


def test_missing_terminal_event_is_an_error():
    engine, closed = scripted(event("text_delta", text="Partial"))
    with pytest.raises(RuntimeError, match="terminal event"):
        run_turn(engine, "question", on_text=lambda _: None, cancel=Event())
    assert closed.is_set()


def test_audio_starts_before_llm_completion():
    heard = Event()
    spoken = []

    class Provider:
        name = "fake"
        group = "local"

        def synthesize(self, text, locale, **kwargs):
            spoken.append((text, locale))
            yield AudioChunk(b"\x00\x00", 24000)

        def close(self):
            pass

    class Player:
        def write(self, chunk, cancel):
            heard.set()

        def finish(self):
            pass

        def abort(self):
            pass

    def stream(text):
        yield event("text_delta", text="Pierwsze zdanie. ")
        assert heard.wait(2), "Audio waited for the full LLM answer"
        yield event("text_delta", text="Koniec")
        yield event("complete", answer="Pierwsze zdanie. Koniec")

    output = SpeechOutput(SpeechService([Provider()]), player_factory=Player)
    try:
        result = run_turn(
            SimpleNamespace(handle_stream=stream),
            "question",
            on_text=lambda _: None,
            cancel=Event(),
            speech=output,
            locale="pl-PL",
        )
        assert result.answer == "Pierwsze zdanie. Koniec"
        assert spoken == [("Pierwsze zdanie.", "pl-PL"), ("Koniec", "pl-PL")]
    finally:
        output.close()
