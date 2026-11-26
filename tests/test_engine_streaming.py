from unittest.mock import Mock

import pytest

from jarvis import engine
from jarvis.llm.schemas import (
    ChatMessage,
    LLMStreamEvent,
    ModelResponse,
    ToolCall,
    ToolCallFunction,
)


def message(text="", calls=None):
    return ChatMessage(
        turn_id="provider-id", role="assistant", content=text, tool_calls=calls
    )


def call(id="call-id", name="lookup", **arguments):
    return ToolCall(id=id, function=ToolCallFunction(name=name, arguments=arguments))


def complete(msg):
    return LLMStreamEvent(kind="message_complete", message=msg)


def text(value):
    return LLMStreamEvent(kind="text_delta", text=value)


@pytest.fixture
def assistant(monkeypatch):
    monkeypatch.setattr(engine, "generate_dynamic_prompt", lambda: "mock system prompt")
    monkeypatch.setattr(engine.AssistantEngine, "read_memory_timestamp", lambda self: 0)
    monkeypatch.setattr(engine.state, "active_model", "gpt")
    monkeypatch.setattr(engine, "AVAILABLE_TOOLS", [])
    monkeypatch.setattr(engine, "TOOL_REGISTRY", {})
    return engine.AssistantEngine()


def scripted(monkeypatch, *rounds):
    remaining = iter(rounds)
    seen = []
    closed = []

    def stream(history, tools, *, backend=None):
        seen.append((list(history), backend))
        try:
            for event in next(remaining):
                if isinstance(event, Exception):
                    raise event
                yield event
        finally:
            closed.append(True)

    monkeypatch.setattr(engine, "stream_llm", stream)
    return seen, closed


def test_multi_round_tools_only_public_progress_and_final_answer(
    assistant, monkeypatch
):
    lookup = Mock(side_effect=["SECRET RESULT 1", "SECRET RESULT 2"])
    monkeypatch.setattr(engine, "TOOL_REGISTRY", {"lookup": lookup})
    seen, closed = scripted(
        monkeypatch,
        [
            text("Checking. "),
            complete(message("Checking. ", [call("first", query="private 1")])),
        ],
        [
            text("One more check. "),
            complete(message("One more check. ", [call("second", query="private 2")])),
        ],
        [text("Final "), text("answer"), complete(message("Final answer"))],
    )
    events = list(assistant.handle_stream("question"))
    assert [e.kind for e in events] == [
        "text_delta",
        "tool_start",
        "tool_end",
        "text_delta",
        "tool_start",
        "tool_end",
        "text_delta",
        "text_delta",
        "complete",
    ]
    assert [e.text for e in events if e.kind == "text_delta"] == [
        "Checking. ",
        "One more check. ",
        "Final ",
        "answer",
    ]
    assert events[-1].answer == "Final answer"
    assert len({e.turn_id for e in events}) == 1
    assert [e.tool_call_id for e in events if e.kind == "tool_start"] == [
        "first",
        "second",
    ]
    assert all(
        not e.text and not e.answer for e in events if e.kind.startswith("tool_")
    )
    assert [m.role for m in assistant.history] == [
        "system",
        "user",
        "assistant",
        "tool",
        "assistant",
        "tool",
        "assistant",
    ]
    assert [m.content for m in assistant.history if m.role == "tool"] == [
        "SECRET RESULT 1",
        "SECRET RESULT 2",
    ]
    assert all(m.turn_id == events[-1].turn_id for m in assistant.history[1:])
    assert all(backend == "gpt" for _, backend in seen)
    assert len(closed) == 3
    assert lookup.call_count == 2


def test_interleaved_tool_calls_execute_in_message_order_after_complete(
    assistant, monkeypatch
):
    executed = []

    def lookup(value):
        executed.append(value)
        return value

    monkeypatch.setattr(engine, "TOOL_REGISTRY", {"lookup": lookup})
    scripted(
        monkeypatch,
        [
            text("Working"),
            complete(message("Working", [call("a", value=1), call("b", value=2)])),
        ],
        [text("Done"), complete(message("Done"))],
    )
    events = assistant.handle_stream("question")
    assert next(events).kind == "text_delta"
    assert executed == []
    assert next(events).kind == "tool_start"
    assert executed == []
    assert next(events).kind == "tool_end"
    assert executed == [1]
    rest = list(events)
    assert executed == [1, 2]
    assert rest[-1].answer == "Done"


def test_partial_backend_error_explicit_and_persisted_once(assistant, monkeypatch):
    _, closed = scripted(
        monkeypatch, [text("Partial "), text("answer"), RuntimeError("offline")]
    )
    events = list(assistant.handle_stream("question"))
    assert [e.kind for e in events] == ["text_delta", "text_delta", "error"]
    assert events[-1].error == "offline"
    assert events[-1].answer == "Backend error: offline"
    assert [m.content for m in assistant.history] == [
        "mock system prompt",
        "question",
        "Partial answer",
    ]
    assert assistant.history[-1].tool_calls is None
    assert len(closed) == 1


def test_error_before_any_text_leaves_user_message(assistant, monkeypatch):
    scripted(monkeypatch, [RuntimeError("no connection")])
    events = list(assistant.handle_stream("question"))
    assert [e.kind for e in events] == ["error"]
    assert [m.role for m in assistant.history] == ["system", "user"]


def test_error_after_tools_keeps_completed_results(assistant, monkeypatch):
    lookup = Mock(return_value="private result")
    monkeypatch.setattr(engine, "TOOL_REGISTRY", {"lookup": lookup})
    scripted(
        monkeypatch, [complete(message(calls=[call()]))], [RuntimeError("offline")]
    )
    events = list(assistant.handle_stream("question"))
    assert [e.kind for e in events] == ["tool_start", "tool_end", "error"]
    assert assistant.history[-1].role == "tool"
    assert assistant.history[-1].content == "private result"
    lookup.assert_called_once_with()


def test_missing_completion_does_not_execute_tools(assistant, monkeypatch):
    lookup = Mock()
    monkeypatch.setattr(engine, "TOOL_REGISTRY", {"lookup": lookup})
    scripted(monkeypatch, [text("partial")])
    events = list(assistant.handle_stream("question"))
    assert events[-1].kind == "error"
    assert "complete message" in events[-1].answer
    lookup.assert_not_called()


def test_handle_compatibility_returns_final_not_progress(assistant, monkeypatch):
    monkeypatch.setattr(
        engine, "TOOL_REGISTRY", {"lookup": Mock(return_value="private result")}
    )
    scripted(
        monkeypatch,
        [text("Progress"), complete(message("Progress", [call()]))],
        [text("Answer"), complete(message("Answer"))],
    )
    answer, turn_id = assistant.handle("question")
    assert answer == "Answer"
    assert turn_id == assistant.history[-1].turn_id


def test_handle_compatibility_returns_backend_error(assistant, monkeypatch):
    scripted(monkeypatch, [RuntimeError("offline")])
    answer, turn_id = assistant.handle("question")
    assert answer == "Backend error: offline"
    assert turn_id == assistant.history[-1].turn_id


def test_snapshot_backend_across_tool_rounds_and_compaction(assistant, monkeypatch):
    assistant.max_tokens_per_history = 0
    assistant.max_tokens_per_history_local_model = 100000
    compact_backends = []

    def compact(*, backend=None):
        compact_backends.append(backend)
        engine.state.active_model = "claude"

    def lookup():
        engine.state.active_model = "local"
        return "private result"

    monkeypatch.setattr(assistant, "_compact", compact)
    monkeypatch.setattr(engine, "TOOL_REGISTRY", {"lookup": lookup})
    seen, _ = scripted(
        monkeypatch, [complete(message(calls=[call()]))], [complete(message("final"))]
    )
    events = list(assistant.handle_stream("question"))
    assert compact_backends == ["gpt"]
    assert [backend for _, backend in seen] == ["gpt", "gpt"]
    assert events[-1].answer == "final"


def test_compaction_forwards_backend_to_compat_client(assistant, monkeypatch):
    assistant.history.extend(
        ChatMessage(turn_id=str(i), role="user", content=f"old {i}") for i in range(8)
    )
    llm = Mock(return_value=ModelResponse(message=message("summary")))
    monkeypatch.setattr(engine, "call_llm", llm)
    assistant._compact(backend="claude")
    assert llm.call_args.kwargs["backend"] == "claude"
    assert "<conversation_summary>" in assistant.history[1].content


def test_cancel_during_text_closes_stream_and_preserves_partial(assistant, monkeypatch):
    lookup = Mock()
    monkeypatch.setattr(engine, "TOOL_REGISTRY", {"lookup": lookup})
    _, closed = scripted(
        monkeypatch, [text("Partial"), complete(message("Partial", [call()]))]
    )
    events = assistant.handle_stream("question")
    assert next(events).text == "Partial"
    events.close()  # GeneratorExit must not become a backend-error event.
    assert closed == [True]
    assert assistant.history[-1].content == "Partial"
    assert assistant.history[-1].tool_calls is None
    assert list(events) == []
    lookup.assert_not_called()


def test_cancel_at_tool_start_does_not_execute_and_repairs_history(
    assistant, monkeypatch
):
    lookup = Mock()
    monkeypatch.setattr(engine, "TOOL_REGISTRY", {"lookup": lookup})
    scripted(monkeypatch, [complete(message(calls=[call("a"), call("b")]))])
    events = assistant.handle_stream("question")
    assert next(events).kind == "tool_start"
    events.close()
    lookup.assert_not_called()
    assert [m.tool_call_id for m in assistant.history if m.role == "tool"] == ["a", "b"]
    assert all("cancelled" in m.content for m in assistant.history if m.role == "tool")


def test_cancel_between_tools_preserves_first_and_skips_second(assistant, monkeypatch):
    lookup = Mock(return_value="first result")
    monkeypatch.setattr(engine, "TOOL_REGISTRY", {"lookup": lookup})
    scripted(monkeypatch, [complete(message(calls=[call("a"), call("b")]))])
    events = assistant.handle_stream("question")
    assert next(events).kind == "tool_start"
    assert next(events).kind == "tool_end"
    events.close()
    assert lookup.call_count == 1
    results = [m for m in assistant.history if m.role == "tool"]
    assert results[0].content == "first result"
    assert results[1].tool_call_id == "b"
    assert "cancelled" in results[1].content


@pytest.mark.parametrize("registered", [False, True])
def test_unknown_and_failing_tool_results_remain_private(
    assistant, monkeypatch, registered
):
    if registered:
        monkeypatch.setattr(
            engine,
            "TOOL_REGISTRY",
            {"lookup": Mock(side_effect=ValueError("private failure"))},
        )
    scripted(
        monkeypatch,
        [complete(message(calls=[call()]))],
        [text("Handled"), complete(message("Handled"))],
    )
    events = list(assistant.handle_stream("question"))
    assert [e.text for e in events if e.kind == "text_delta"] == ["Handled"]
    assert events[-1].answer == "Handled"
    result = next(m.content for m in assistant.history if m.role == "tool")
    assert "private failure" in result if registered else "does not exist" in result


def test_tool_iteration_limit_produces_complete_fallback(assistant, monkeypatch):
    assistant.max_tool_iterations = 1
    monkeypatch.setattr(
        engine, "TOOL_REGISTRY", {"lookup": Mock(return_value="result")}
    )
    scripted(monkeypatch, [complete(message(calls=[call()]))])
    events = list(assistant.handle_stream("question"))
    assert [e.kind for e in events] == [
        "tool_start",
        "tool_end",
        "text_delta",
        "complete",
    ]
    assert (
        events[-1].answer
        == "I reached the maximum limit of tool actions for this step."
    )
    assert assistant.history[-1].content == events[-1].answer


def test_empty_final_answer_still_completes(assistant, monkeypatch):
    scripted(monkeypatch, [complete(message())])
    events = list(assistant.handle_stream("question"))
    assert len(events) == 1
    assert events[0].kind == "complete"
    assert events[0].text == events[0].answer == ""
