import subprocess
import sys
from collections.abc import Iterator
from queue import Empty, Queue
from threading import Event, Thread, current_thread
from time import monotonic
from types import SimpleNamespace

import pytest
from loguru import logger

from jarvis.speech import output as speech_output
from jarvis.speech.output import Player, SoundDevicePlayer, SpeechOutput
from jarvis.speech.service import SpeechService
from jarvis.speech.types import AudioChunk, SpeechCancelled, SpeechError

PCM = AudioChunk(b"\x01\x00" * 20, 22050)


class Provider:
    name = "test-provider"
    group = "local"

    def __init__(self, items=(PCM,), action=None):
        self.items = items
        self.action = action
        self.calls = []
        self.threads = []
        self.called = Event()
        self.stream_closed = Event()
        self.closed = 0

    def synthesize(self, text, locale, *, cancel, deadline):
        self.calls.append((text, locale))
        self.threads.append(current_thread())
        self.called.set()
        try:
            if self.action:
                self.action(cancel)
            for item in self.items:
                if isinstance(item, Exception):
                    raise item
                yield item
        finally:
            self.stream_closed.set()

    def close(self):
        self.closed += 1


class FakePlayer:
    def __init__(self, *, speaking=None, failure=None, drain=None):
        self.chunks = []
        self.written = Event()
        self.finished = Event()
        self.aborted = Event()
        self.abort_calls = 0
        self.finish_calls = 0
        self.speaking = speaking
        self.failure = failure
        self.drain = drain

    def write(self, chunk, cancel):
        if self.speaking is not None:
            assert self.speaking.is_set()
        if self.aborted.is_set() or cancel.is_set():
            raise SpeechCancelled()
        self.chunks.append(chunk)
        self.written.set()
        if self.failure:
            raise self.failure

    def finish(self):
        self.finish_calls += 1
        self.finished.set()
        if self.drain:
            assert self.drain.wait(2)

    def abort(self):
        self.abort_calls += 1
        self.aborted.set()
        if self.drain:
            self.drain.set()


@pytest.fixture
def messages():
    result = []
    sink = logger.add(lambda msg: result.append(str(msg)), format="{message}")
    yield result
    logger.remove(sink)


@pytest.fixture
def make_output():
    outputs = []

    def make(provider=None, *, player=None, providers=None, **kwargs):
        provider = provider if provider is not None else Provider()
        players = []

        def factory() -> Player:
            instance = player if player is not None else FakePlayer()
            players.append(instance)
            return instance

        service = SpeechService(providers if providers is not None else [provider])
        output = SpeechOutput(service, player_factory=factory, **kwargs)
        outputs.append(output)
        return output, provider, players

    yield make
    for output in outputs:
        output.close()


def test_incremental_first_sentence_plays_before_finish_and_flushes_tail(make_output):
    player = FakePlayer()
    output, provider, _ = make_output(player=player)
    session = output.start("en-GB")
    session.feed("First.")
    assert not provider.called.is_set()
    session.feed(" Tail without punctuation")
    assert player.written.wait(1)
    assert not session.done.is_set()
    assert provider.calls == [("First.", "en-GB")]
    session.finish()
    assert session.done.is_set()
    assert provider.calls == [
        ("First.", "en-GB"),
        ("Tail without punctuation", "en-GB"),
    ]
    assert player.chunks == [PCM, PCM]
    assert player.finish_calls == 2
    assert not player.aborted.is_set()
    session.feed("Ignored. ")
    session.boundary()
    session.finish()
    assert len(provider.calls) == 2


def test_finish_waits_for_queue_space_without_disabling_final_tail(make_output):
    release = Event()
    provider = Provider(action=lambda cancel: release.wait(3))
    output, _, _ = make_output(provider, queue_size=1)
    session = output.start("en-GB")
    session.feed("First. ")
    assert provider.called.wait(1)
    session.feed("Second. Final tail")
    finishing = Thread(target=session.finish)
    finishing.start()
    try:
        assert not session._ending.wait(0.05)
        assert not session.done.is_set()
        release.set()
        finishing.join(2)
        assert not finishing.is_alive()
        assert not session.turn.failed
        assert [text for text, _ in provider.calls] == [
            "First.",
            "Second.",
            "Final tail",
        ]
    finally:
        release.set()
        session.cancel()
        finishing.join(1)


def test_final_tail_survives_queue_poll_ending_race(make_output, monkeypatch):
    entered, release = Event(), Event()

    class PollQueue(Queue):
        def get(self, *args, **kwargs):
            if not entered.is_set():
                entered.set()
                assert release.wait(2)
                raise Empty
            return super().get(*args, **kwargs)

    monkeypatch.setattr(speech_output, "Queue", PollQueue)
    output, provider, _ = make_output()
    session = output.start("en-GB")
    assert entered.wait(1)
    session.feed("Tail")
    finishing = Thread(target=session.finish)
    finishing.start()
    try:
        assert session._ending.wait(1)
        release.set()
        finishing.join(2)
        assert not finishing.is_alive()
        assert provider.calls == [("Tail", "en-GB")]
    finally:
        release.set()
        session.cancel()
        finishing.join(1)


def test_boundary_flushes_progress_and_resets_unterminated_fence(make_output):
    player = FakePlayer()
    output, provider, _ = make_output(player=player)
    session = output.start("en-GB")
    session.feed("Working ```python\nSECRET")
    session.boundary()
    assert player.written.wait(1)
    session.feed("Next message")
    session.boundary()
    session.feed("Tail")
    session.finish()
    assert [text for text, _ in provider.calls] == ["Working", "Next message", "Tail"]


@pytest.mark.parametrize("width", [1, 2, 7])
def test_split_code_fences_and_stable_locale(make_output, width):
    output, provider, _ = make_output(queue_size=16)
    session = output.start("pl-PL")
    text = "First. ```py\nSECRET.foo().\n``` See https://example.com/a. Tail"
    for i in range(0, len(text), width):
        session.feed(text[i : i + width])
    session.finish()
    assert provider.calls == [
        ("First.", "pl-PL"),
        ("See example kropka com ukośnik a.", "pl-PL"),
        ("Tail", "pl-PL"),
    ]


def test_segment_limit_and_empty_normalized_text(make_output):
    output, provider, players = make_output(max_segment_length=16, queue_size=16)
    session = output.start("ru-RU")
    session.feed("😀!!! ")
    session.boundary()
    session.feed("x" * 49)
    session.finish()
    assert [len(text) for text, _ in provider.calls] == [3, 16, 16, 16, 1]
    assert all(locale == "ru-RU" for _, locale in provider.calls)
    assert len(players) == 1
    empty = output.start("en-GB")
    empty.feed("```python\nsecret")
    empty.finish()
    assert len(players) == 1


def test_overload_is_nonblocking_disables_rest_of_turn_no_fallback(
    make_output, messages
):
    release = Event()
    provider = Provider(action=lambda cancel: release.wait(3))
    fallback = Provider()
    fallback.name = "fallback"
    output, _, players = make_output(providers=[provider, fallback], queue_size=1)
    session = output.start("en-GB")
    try:
        session.feed("First. ")
        assert provider.called.wait(1)
        session.feed("Queued. ")
        before = monotonic()
        session.feed("Overflow. ")
        session.finish()
        assert monotonic() - before < 0.3
        assert session.done.is_set() and session.turn.failed
        for _ in range(20):
            session.feed("Text continues. ")
            session.boundary()
        assert len(provider.calls) == 1
        assert not fallback.calls and not players
        assert sum("queue full" in msg for msg in messages) == 1
    finally:
        release.set()
    assert provider.stream_closed.wait(1)
    assert not fallback.calls and not players


@pytest.mark.parametrize(
    "items",
    [
        (SpeechError("secret credential"),),
        (PCM, SpeechError("secret credential")),
        (PCM, RuntimeError("secret credential")),
    ],
)
def test_failed_turn_stays_silent_and_logs_safe_status(make_output, messages, items):
    provider = Provider(items=items)
    output, _, players = make_output(provider)
    session = output.start("en-GB")
    session.feed("First. ")
    assert session.done.wait(1)
    session.feed("Never retry. ")
    session.boundary()
    session.finish()
    assert len(provider.calls) == 1
    assert session.turn.failed
    assert provider.stream_closed.is_set()
    assert not players or players[0].aborted.is_set()
    assert any("text only" in msg for msg in messages)
    assert all("secret credential" not in msg for msg in messages)


def test_error_after_chunk_never_calls_fallback(make_output):
    first = Provider(items=(PCM, SpeechError("failed")))
    fallback = Provider()
    fallback.name = "fallback"
    output, _, players = make_output(providers=[first, fallback])
    session = output.start("en-GB")
    session.feed("First. Second. ")
    session.finish()
    assert len(first.calls) == 1
    assert not fallback.calls
    assert players[0].chunks == [PCM]
    assert session.turn.started and session.turn.failed


def test_fallback_provider_logged_once_per_turn(make_output, messages):
    first = Provider(items=(SpeechError("unavailable"),))
    fallback = Provider()
    fallback.name = "fallback"
    output, _, _ = make_output(providers=[first, fallback])
    session = output.start("en-GB")
    session.feed("First. Second. ")
    session.finish()
    assert session.turn.provider == "fallback"
    assert len(first.calls) == 1 and len(fallback.calls) == 2
    assert sum("Speech provider: fallback" in msg for msg in messages) == 1


@pytest.mark.parametrize("where", ["write", "finish"])
def test_player_errors_close_partial_iterator_without_provider_fallback(
    make_output, messages, where
):
    first = Provider(items=(PCM, PCM))
    fallback = Provider()
    fallback.name = "fallback"
    player = FakePlayer(failure=RuntimeError("private device details"))
    if where == "finish":
        player.failure = None

        def fail_finish():
            raise RuntimeError("private device details")

        player.finish = fail_finish
    output, _, _ = make_output(providers=[first, fallback], player=player)
    session = output.start("en-GB")
    session.feed("First. Second. ")
    session.finish()
    assert len(first.calls) == 1 and not fallback.calls
    assert first.stream_closed.is_set()
    assert player.aborted.is_set() and session.turn.failed
    assert any("Speech output failed" in msg for msg in messages)
    assert all("private device details" not in msg for msg in messages)


def test_cancel_immediate_idempotent_closes_partial_iterator(make_output):
    release = Event()
    entered = Event()
    closed = Event()
    provider = Provider()

    def synthesize(*args, **kwargs) -> Iterator[AudioChunk]:
        try:
            yield PCM
            entered.set()
            release.wait(3)  # Non-cooperative native next() cannot be forcibly closed.
            yield PCM
        finally:
            closed.set()

    provider.synthesize = synthesize
    speaking = Event()
    player = FakePlayer(speaking=speaking)
    output, _, _ = make_output(provider, player=player, speaking=speaking)
    session = output.start("en-GB")
    try:
        session.feed("First. ")
        assert entered.wait(1) and speaking.is_set()
        before = monotonic()
        output.cancel()
        output.cancel()
        session.cancel()
        session.finish()
        assert monotonic() - before < 0.3
        assert session.done.is_set() and session.turn.failed
        assert not speaking.is_set()
        assert player.abort_calls == 1
        assert player.finish_calls == 0
        assert player.chunks == [PCM]
    finally:
        release.set()
    assert closed.wait(1)
    session._thread.join(1)
    assert not session._thread.is_alive()
    assert player.abort_calls == 1
    assert player.finish_calls == 1


def test_speaking_only_during_audio_and_drain_not_sentence_gaps(make_output):
    cleared, drain = Event(), Event()

    class SpeakingEvent(Event):
        def clear(self):
            super().clear()
            cleared.set()

    speaking = SpeakingEvent()
    player = FakePlayer(speaking=speaking, drain=drain)
    output, provider, _ = make_output(player=player, speaking=speaking)
    session = output.start("en-GB")
    assert not speaking.is_set()
    session.feed("First. ")
    assert player.finished.wait(1)
    assert speaking.is_set()  # stop/drain is still audible.
    drain.set()
    assert cleared.wait(1)
    assert not speaking.is_set() and not session.done.is_set()
    session.feed("Tail")
    session.finish()
    assert len(provider.calls) == 2
    assert not speaking.is_set()


def test_fresh_turn_state_and_cancelled_old_session_cannot_clear_new_speaking(
    make_output,
):
    speaking = Event()
    output, provider, players = make_output(speaking=speaking)
    old = output.start("pl-PL")
    old.feed("```unterminated")
    old.cancel()
    fresh = output.start("en-GB")
    assert fresh.turn is not old.turn
    assert not fresh.turn.started and not fresh.turn.failed
    # Hold the new worker between first and second chunk.
    release = Event()
    entered = Event()

    def source(*args, **kwargs):
        yield PCM
        entered.set()
        release.wait(3)

    provider.synthesize = source
    try:
        fresh.feed("New sentence. ")
        assert entered.wait(1)
        assert speaking.is_set()
        old.cancel()
        assert speaking.is_set()
    finally:
        release.set()
    fresh.finish()
    assert fresh.turn is not old.turn
    assert len(players) == 1
    assert not speaking.is_set()


def test_stuck_worker_disables_new_sessions_without_spawning_workers(make_output):
    release = Event()
    provider = Provider(action=lambda cancel: release.wait(3))
    output, _, players = make_output(provider)
    old = output.start("en-GB")
    try:
        old.feed("First. ")
        assert provider.called.wait(1)
        output.cancel()
        worker = old._thread
        for _ in range(5):
            disabled = output.start("pl-PL")
            assert disabled.done.is_set() and disabled.turn.failed
            assert disabled._thread is None
            disabled.feed("Ignored. ")
            disabled.finish()
            assert output._worker is worker
        assert len(provider.calls) == 1 and not players
    finally:
        release.set()
    worker.join(1)
    assert not worker.is_alive()
    fresh = output.start("ru-RU")
    fresh.feed("Fresh. ")
    fresh.finish()
    assert len(provider.calls) == 2 and len(players) == 1
    assert provider.calls[-1] == ("Fresh.", "ru-RU")
    assert provider.threads[0] is not provider.threads[1]


def test_one_worker_serializes_sentences_and_turn_replacement(make_output):
    output, provider, players = make_output(queue_size=32)
    old = output.start("en-GB")
    old.feed("Old partial")
    fresh = output.start("pl-PL")
    fresh.feed("First. Second. Third. ")
    fresh.finish()
    assert old.done.is_set()
    assert provider.calls == [
        (text, "pl-PL") for text in ("First.", "Second.", "Third.")
    ]
    assert len(set(provider.threads)) == 1
    assert len(players) == 1 and players[0].finish_calls == 3


def test_close_is_idempotent_cancels_and_closes_service_once(make_output):
    output, provider, _ = make_output()
    session = output.start("en-GB")
    before = monotonic()
    output.close()
    output.close()
    assert monotonic() - before < 0.3
    assert provider.closed == 1
    assert session.done.is_set() and session.turn.failed
    disabled = output.start("en-GB")
    assert disabled.done.is_set()
    disabled.feed("Ignored. ")
    disabled.finish()
    assert not provider.calls


@pytest.mark.parametrize("kwargs", [{"queue_size": 0}, {"max_segment_length": 15}])
def test_invalid_queue_or_segment_limits(kwargs):
    with pytest.raises(ValueError):
        SpeechOutput(SpeechService([]), **kwargs)


class RawStream:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.writes = []
        self.starts = self.stops = self.aborts = self.closes = 0
        self.on_start = self.on_write = self.on_stop = self.on_abort = None
        self.active = set()
        self.operations = []

    def _operate(self, name):
        assert not self.active, f"Concurrent native operations: {self.active}, {name}"
        self.active.add(name)
        self.operations.append((name, current_thread()))
        try:
            callback = getattr(self, f"on_{name}")
            if callback:
                callback()
        finally:
            self.active.remove(name)

    def start(self):
        self.starts += 1
        self._operate("start")

    def write(self, data):
        self.writes.append(bytes(data))
        self._operate("write")

    def stop(self):
        self.stops += 1
        self._operate("stop")

    def abort(self):
        self.aborts += 1
        self._operate("abort")

    def close(self):
        assert not self.active, f"Close during native operation: {self.active}"
        self.operations.append(("close", current_thread()))
        self.closes += 1


@pytest.fixture
def sounddevice(monkeypatch):
    streams = []

    def create(**kwargs):
        stream = RawStream(**kwargs)
        streams.append(stream)
        return stream

    monkeypatch.setitem(
        sys.modules, "sounddevice", SimpleNamespace(RawOutputStream=create)
    )
    return streams


def test_module_and_constructors_do_not_import_audio_or_microphone_dependencies():
    # A fresh interpreter avoids imports performed by other speech tests.
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; from jarvis.speech.output import SpeechOutput, SoundDevicePlayer; "
            "from jarvis.speech.service import SpeechService; "
            "SoundDevicePlayer(); SpeechOutput(SpeechService([])).close(); "
            "assert not {'sounddevice', 'numpy', 'RealtimeSTT', 'piper'} & sys.modules.keys()",
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr


def test_raw_player_lazy_bounded_writes_format_changes_and_drain(sounddevice):
    player = SoundDevicePlayer()
    assert sounddevice == []
    cancel = Event()
    chunk = AudioChunk(b"\x01\x00" * 10000, 1000, 2)
    player.write(chunk, cancel)
    first = sounddevice[0]
    assert first.kwargs == {"samplerate": 1000, "channels": 2, "dtype": "int16"}
    assert b"".join(first.writes) == chunk.data
    assert len(first.writes) > 1
    assert max(map(len, first.writes)) <= 80
    player.write(chunk, cancel)
    assert len(sounddevice) == 1
    player.write(PCM, cancel)
    assert first.stops == first.closes == 1
    second = sounddevice[1]
    player.finish()
    player.finish()
    assert second.stops == second.closes == 1
    player.write(PCM, cancel)  # Normal finish does not permanently abort the player.
    player.finish()
    assert len(sounddevice) == 3


def test_raw_cancel_between_bounded_writes_stops_and_never_reopens(sounddevice):
    player, cancel = SoundDevicePlayer(), Event()
    player.write(PCM, cancel)
    stream = sounddevice[0]
    stream.on_write = cancel.set
    before = len(stream.writes)
    with pytest.raises(SpeechCancelled):
        player.write(AudioChunk(PCM.data * 1000, PCM.sample_rate), cancel)
    assert len(stream.writes) == before + 1
    assert stream.aborts == stream.closes == 1
    cancel.clear()
    player.abort()
    player.finish()
    with pytest.raises(SpeechCancelled):
        player.write(PCM, cancel)
    assert len(sounddevice) == 1 and stream.closes == 1


@pytest.mark.parametrize("operation", ["start", "write", "stop", "abort"])
def test_raw_cancel_defers_destruction_until_native_operation_returns(
    monkeypatch, operation
):
    entered, release = Event(), Event()
    streams, errors = [], []

    def block():
        entered.set()
        assert release.wait(3)

    def create(**kwargs):
        stream = RawStream(**kwargs)
        setattr(stream, f"on_{operation}", block)
        streams.append(stream)
        return stream

    monkeypatch.setitem(
        sys.modules, "sounddevice", SimpleNamespace(RawOutputStream=create)
    )
    player = SoundDevicePlayer()

    def play():
        try:
            player.write(PCM, Event())
            if operation == "abort":
                player.abort()
            player.finish()
        except SpeechCancelled:
            pass
        except Exception as exc:
            errors.append(exc)
        finally:
            player.finish()
            player.finish()

    worker = Thread(target=play)
    worker.start()
    try:
        assert entered.wait(1)
        stream = streams[0]
        before = monotonic()
        requesters = [Thread(target=player.abort) for _ in range(8)]
        for requester in requesters:
            requester.start()
        for requester in requesters:
            requester.join(0.2)
            assert not requester.is_alive()
        assert monotonic() - before < 0.3
        assert worker.is_alive()
        assert stream.active == {operation}
        assert stream.closes == 0
        assert stream.aborts == (1 if operation == "abort" else 0)
    finally:
        release.set()
        worker.join(1)
    assert not worker.is_alive() and not errors
    assert stream.closes == 1
    assert stream.aborts == (0 if operation == "stop" else 1)
    assert len(stream.writes) == (0 if operation == "start" else 1)
    assert all(thread is worker for _, thread in stream.operations)
    player.abort()
    with pytest.raises(SpeechCancelled):
        player.write(PCM, Event())
    assert len(streams) == 1 and stream.closes == 1


def test_raw_abort_during_open_closes_unpublished_stream(monkeypatch):
    entered, release = Event(), Event()
    streams, errors = [], []

    def create(**kwargs):
        stream = RawStream(**kwargs)
        streams.append(stream)
        entered.set()
        assert release.wait(2)
        return stream

    monkeypatch.setitem(
        sys.modules, "sounddevice", SimpleNamespace(RawOutputStream=create)
    )
    player = SoundDevicePlayer()

    def write():
        try:
            player.write(PCM, Event())
        except SpeechCancelled as exc:
            errors.append(exc)

    worker = Thread(target=write)
    worker.start()
    try:
        assert entered.wait(1)
        before = monotonic()
        player.abort()
        player.abort()
        assert monotonic() - before < 0.2
        assert streams[0].closes == streams[0].aborts == 0
    finally:
        release.set()
        worker.join(1)
    assert len(errors) == 1
    assert streams[0].closes == streams[0].aborts == 1
    assert streams[0].starts == 0 and not streams[0].writes
    assert all(thread is worker for _, thread in streams[0].operations)


def test_session_cancel_keeps_owner_cleanup_after_stuck_synthesis(sounddevice):
    entered, release = Event(), Event()
    provider = Provider()

    def source(*args, **kwargs):
        yield PCM
        entered.set()
        assert release.wait(3)
        yield PCM

    provider.synthesize = source
    output = SpeechOutput(SpeechService([provider]))
    session = output.start("en-GB")
    session.feed("First. ")
    try:
        assert entered.wait(1)
        stream = sounddevice[0]
        before = monotonic()
        output.cancel()
        session.cancel()
        session.finish()
        assert monotonic() - before < 0.3
        assert session.done.is_set() and session.turn.failed
        assert stream.aborts == stream.closes == 0
        assert not output._speaking.is_set()
        # done does not permit another worker to use the native stream/service.
        disabled = output.start("en-GB")
        assert disabled.done.is_set() and disabled._thread is None
        assert stream.closes == 0
    finally:
        release.set()
        session._thread.join(1)
        output.close()
    assert not session._thread.is_alive()
    assert stream.aborts == stream.closes == 1
    assert stream.stops == 0
    assert stream.writes == [PCM.data]
    assert all(thread is session._thread for _, thread in stream.operations)


def test_raw_idle_abort_requires_owner_finish_and_never_drains(sounddevice):
    player = SoundDevicePlayer()
    player.write(PCM, Event())
    stream = sounddevice[0]
    for _ in range(10):
        player.abort()
    assert stream.aborts == stream.closes == 0
    player.finish()
    player.finish()
    player.abort()
    assert stream.aborts == stream.closes == 1
    assert stream.stops == 0


def test_raw_abort_before_any_write_never_imports_or_opens(sounddevice):
    player = SoundDevicePlayer()
    player.abort()
    player.abort()
    with pytest.raises(SpeechCancelled):
        player.write(PCM, Event())
    assert sounddevice == []
