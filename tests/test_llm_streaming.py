from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from pydantic import SecretStr

from jarvis.llm import client
from jarvis.llm.schemas import ChatMessage, Provider, ToolCall, ToolCallFunction


class FakeStream:
    def __init__(self, events):
        self.events = iter(events)
        self.closed = False

    def __iter__(self):
        return self

    def __next__(self):
        event = next(self.events)
        if isinstance(event, Exception):
            raise event
        return event

    def close(self):
        self.closed = True


def chunk(content=None, *, calls=None, finish=None, reasoning=None, usage=None):
    return {
        "id": "response-id",
        "choices": [
            {
                "index": 0,
                "delta": {
                    "content": content,
                    "tool_calls": calls,
                    "reasoning_content": reasoning,
                },
                "finish_reason": finish,
            }
        ],
        "usage": usage,
    }


def tool_delta(index, *, id=None, name=None, arguments=None):
    return {
        "index": index,
        "id": id,
        "type": "function",
        "function": {"name": name, "arguments": arguments},
    }


def echo(value: str):
    return value


@pytest.fixture(autouse=True)
def settings(monkeypatch):
    providers = {
        backend: Provider(
            model="mock-model", protocol=protocol, api_key=SecretStr("mock-key")
        )
        for backend, protocol in [
            ("gpt", "openai"),
            ("claude", "anthropic"),
            ("local", "local"),
        ]
    }
    monkeypatch.setattr(
        client, "get_settings", lambda: SimpleNamespace(providers=providers)
    )
    monkeypatch.setattr(client.state, "active_model", "gpt")
    monkeypatch.setattr(client.state, "support_tools", True)
    return providers


def openai_stream(monkeypatch, *streams):
    create = Mock(side_effect=streams)
    factory = Mock(
        return_value=SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=create))
        )
    )
    monkeypatch.setattr(client, "_openai_client", factory)
    return create


def test_openai_interleaved_tools_split_json_and_public_text(monkeypatch):
    stream = FakeStream(
        [
            chunk(reasoning="private chain of thought"),
            chunk(
                "Checking. ",
                calls=[tool_delta(1, id="second", name="echo", arguments='{"value":')],
            ),
            chunk(
                calls=[tool_delta(0, id="first", name="ec", arguments='{"value":"a')]
            ),
            chunk(
                calls=[
                    tool_delta(1, arguments='"b"}'),
                    tool_delta(0, name="ho", arguments='bc"}'),
                ]
            ),
            chunk("Done", finish="tool_calls"),
            {"choices": [], "usage": {"completion_tokens": 12}},
        ]
    )
    create = openai_stream(monkeypatch, stream)
    events = list(client.stream_llm([], [echo]))
    assert [e.text for e in events if e.kind == "text_delta"] == ["Checking. ", "Done"]
    complete = events[-1]
    assert complete.kind == "message_complete"
    assert complete.message.content == "Checking. Done"
    assert complete.message.turn_id == "response-id"
    assert [t.id for t in complete.message.tool_calls] == ["first", "second"]
    assert [t.function.name for t in complete.message.tool_calls] == ["echo", "echo"]
    assert [t.function.arguments for t in complete.message.tool_calls] == [
        {"value": "abc"},
        {"value": "b"},
    ]
    assert complete.usage == {"completion_tokens": 12}
    assert stream.closed
    assert create.call_args.kwargs["stream"] is True


def test_anthropic_blocks_ignore_thinking_and_assemble_tool_json(monkeypatch):
    stream = FakeStream(
        [
            {
                "type": "message_start",
                "message": {
                    "id": "anthropic-id",
                    "usage": {"input_tokens": 7, "output_tokens": 0},
                },
            },
            {
                "type": "content_block_start",
                "index": 0,
                "content_block": {"type": "thinking", "thinking": "secret"},
            },
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "thinking_delta", "thinking": "private"},
            },
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "signature_delta", "signature": "secret"},
            },
            {
                "type": "content_block_start",
                "index": 1,
                "content_block": {"type": "text", "text": "Hello"},
            },
            {
                "type": "content_block_delta",
                "index": 1,
                "delta": {"type": "text_delta", "text": ", Shef"},
            },
            {
                "type": "content_block_start",
                "index": 2,
                "content_block": {
                    "type": "tool_use",
                    "id": "tool-id",
                    "name": "echo",
                    "input": {},
                },
            },
            {
                "type": "content_block_delta",
                "index": 2,
                "delta": {"type": "input_json_delta", "partial_json": '{"value":'},
            },
            {
                "type": "content_block_delta",
                "index": 2,
                "delta": {
                    "type": "input_json_delta",
                    "partial_json": '"secret tool input"}',
                },
            },
            {
                "type": "message_delta",
                "delta": {"stop_reason": "tool_use"},
                "usage": {"output_tokens": 9},
            },
            {"type": "message_stop"},
        ]
    )
    create = Mock(return_value=stream)
    monkeypatch.setattr(
        client,
        "_anthropic_client",
        Mock(return_value=SimpleNamespace(messages=SimpleNamespace(create=create))),
    )
    events = list(client.stream_llm([], [echo], backend="claude"))
    assert [e.text for e in events[:-1]] == ["Hello", ", Shef"]
    complete = events[-1]
    assert complete.message.turn_id == "anthropic-id"
    assert complete.message.content == "Hello, Shef"
    assert complete.message.tool_calls[0].id == "tool-id"
    assert complete.message.tool_calls[0].function.arguments == {
        "value": "secret tool input"
    }
    assert complete.usage == {"input_tokens": 7, "output_tokens": 9}
    assert stream.closed


def test_ollama_preserves_tools_history_and_ignores_thinking(monkeypatch):
    history = [
        ChatMessage(
            turn_id="1",
            role="assistant",
            content="Checking",
            tool_calls=[
                ToolCall(
                    id="id",
                    function=ToolCallFunction(name="echo", arguments={"value": "old"}),
                )
            ],
        ),
        ChatMessage(
            turn_id="1", role="tool", name="echo", tool_call_id="id", content="old"
        ),
    ]
    stream = FakeStream(
        [
            {"message": {"thinking": "private", "content": ""}, "done": False},
            {
                "message": {
                    "content": "Checking again",
                    "tool_calls": [
                        {"function": {"name": "echo", "arguments": {"value": "new"}}}
                    ],
                }
            },
            {
                "message": {
                    "tool_calls": [
                        {"function": {"name": "echo", "arguments": {"value": "second"}}}
                    ]
                },
                "done": True,
                "eval_count": 5,
                "prompt_eval_count": 10,
            },
        ]
    )
    chat = Mock(return_value=stream)
    monkeypatch.setattr(client.ollama, "chat", chat)
    events = list(client.stream_llm(history, [echo], backend="local"))
    assert [e.text for e in events[:-1]] == ["Checking again"]
    assert [t.function.arguments for t in events[-1].message.tool_calls] == [
        {"value": "new"},
        {"value": "second"},
    ]
    assert all(t.id for t in events[-1].message.tool_calls)
    assert events[-1].usage == {"eval_count": 5, "prompt_eval_count": 10}
    assert chat.call_args.kwargs["messages"][0].tool_calls[0].function.arguments == {
        "value": "old"
    }
    assert chat.call_args.kwargs["messages"][1].tool_name == "echo"
    assert stream.closed


@pytest.mark.parametrize("backend", ["gpt", "claude", "local"])
def test_generator_close_closes_network_without_completing(monkeypatch, backend):
    if backend == "gpt":
        stream = FakeStream([chunk("first"), chunk("second", finish="stop")])
        openai_stream(monkeypatch, stream)
    elif backend == "claude":
        stream = FakeStream(
            [
                {
                    "type": "content_block_start",
                    "index": 0,
                    "content_block": {"type": "text", "text": "first"},
                },
                {"type": "message_stop"},
            ]
        )
        monkeypatch.setattr(
            client,
            "_anthropic_client",
            Mock(
                return_value=SimpleNamespace(
                    messages=SimpleNamespace(create=Mock(return_value=stream))
                )
            ),
        )
    else:
        stream = FakeStream([{"message": {"content": "first"}}, {"done": True}])
        monkeypatch.setattr(client.ollama, "chat", Mock(return_value=stream))
    events = client.stream_llm([], [], backend=backend)
    assert next(events).text == "first"
    events.close()
    assert stream.closed
    assert list(events) == []


def test_unsupported_tools_retry_once_before_public_text(monkeypatch):
    first = FakeStream(
        [chunk(reasoning="discarded"), RuntimeError("model does not support tools")]
    )
    second = FakeStream([chunk("only answer", finish="stop")])
    create = openai_stream(monkeypatch, first, second)
    events = list(client.stream_llm([], [echo]))
    assert [e.text for e in events[:-1]] == ["only answer"]
    assert create.call_count == 2
    assert create.call_args_list[0].kwargs["tools"] is not client.omit
    assert create.call_args_list[1].kwargs["tools"] is client.omit
    assert client.state.support_tools is False
    assert first.closed and second.closed


def test_retry_discards_buffered_tools_from_failed_attempt(monkeypatch):
    first = FakeStream(
        [
            chunk(
                calls=[tool_delta(0, id="discard", name="echo", arguments='{"value":')]
            ),
            RuntimeError("does not support tools"),
        ]
    )
    second = FakeStream([chunk("fresh answer", finish="stop")])
    openai_stream(monkeypatch, first, second)
    events = list(client.stream_llm([], [echo]))
    assert events[-1].message.content == "fresh answer"
    assert events[-1].message.tool_calls is None
    assert first.closed and second.closed


@pytest.mark.parametrize("arguments", [None, "", "{}"])
def test_empty_tool_arguments_are_empty_object(monkeypatch, arguments):
    stream = FakeStream(
        [
            chunk(
                calls=[tool_delta(0, id="empty", name="no_args", arguments=arguments)],
                finish="tool_calls",
            )
        ]
    )
    openai_stream(monkeypatch, stream)
    events = list(client.stream_llm([], [echo]))
    assert events[-1].message.tool_calls[0].function.arguments == {}


@pytest.mark.parametrize(
    "reason", ["length", "content_filter", "stop", "function_call", "unknown", None]
)
@pytest.mark.parametrize("arguments", [None, "", '{"value":"complete"}', '{"value":'])
def test_openai_abnormal_tool_completion_never_emits_message(
    monkeypatch, reason, arguments
):
    stream = FakeStream(
        [
            chunk("Progress"),
            chunk(calls=[tool_delta(0, id="tool", name="echo", arguments=arguments)]),
            chunk(finish=reason),
            {"choices": [], "usage": {"completion_tokens": 12}},
        ]
    )
    create = openai_stream(monkeypatch, stream)
    events = client.stream_llm([], [echo])
    assert next(events).text == "Progress"
    expected = "before message completion" if reason is None else "Refusing tool calls"
    with pytest.raises(RuntimeError, match=expected):
        list(events)
    assert stream.closed
    assert create.call_count == 1


def anthropic_stream(monkeypatch, stream):
    create = Mock(return_value=stream)
    monkeypatch.setattr(
        client,
        "_anthropic_client",
        Mock(return_value=SimpleNamespace(messages=SimpleNamespace(create=create))),
    )
    return create


def anthropic_tool_events(arguments, reason):
    events = [
        {
            "type": "content_block_start",
            "index": 0,
            "content_block": {"type": "text", "text": "Progress"},
        },
        {
            "type": "content_block_start",
            "index": 1,
            "content_block": {
                "type": "tool_use",
                "id": "tool",
                "name": "echo",
                "input": {},
            },
        },
    ]
    if arguments is not None:
        events.append(
            {
                "type": "content_block_delta",
                "index": 1,
                "delta": {"type": "input_json_delta", "partial_json": arguments},
            }
        )
    events.extend(
        [
            {
                "type": "message_delta",
                "delta": {"stop_reason": reason},
                "usage": {"output_tokens": 9},
            },
            {"type": "message_stop"},
        ]
    )
    return events


@pytest.mark.parametrize(
    "reason", ["max_tokens", "refusal", "pause_turn", "end_turn", "stop_sequence", None]
)
@pytest.mark.parametrize("arguments", [None, "", '{"value":"complete"}', '{"value":'])
def test_anthropic_abnormal_tool_completion_never_emits_message(
    monkeypatch, reason, arguments
):
    stream = FakeStream(anthropic_tool_events(arguments, reason))
    create = anthropic_stream(monkeypatch, stream)
    events = client.stream_llm([], [echo], backend="claude")
    assert next(events).text == "Progress"
    with pytest.raises(RuntimeError, match="Refusing tool calls"):
        list(events)
    assert stream.closed
    assert create.call_count == 1


@pytest.mark.parametrize("arguments", [None, "", "{}"])
def test_anthropic_normal_empty_arguments_are_empty_object(monkeypatch, arguments):
    stream = FakeStream(anthropic_tool_events(arguments, "tool_use"))
    anthropic_stream(monkeypatch, stream)
    events = list(client.stream_llm([], [echo], backend="claude"))
    assert events[-1].kind == "message_complete"
    assert events[-1].message.tool_calls[0].function.arguments == {}
    assert stream.closed


def test_anthropic_tool_completion_requires_message_stop(monkeypatch):
    stream = FakeStream(anthropic_tool_events('{"value":"complete"}', "tool_use")[:-1])
    anthropic_stream(monkeypatch, stream)
    events = client.stream_llm([], [echo], backend="claude")
    assert next(events).text == "Progress"
    with pytest.raises(RuntimeError, match="before message completion"):
        list(events)
    assert stream.closed


@pytest.mark.parametrize(
    "backend, reason",
    [
        ("gpt", "length"),
        ("gpt", "content_filter"),
        ("claude", "max_tokens"),
        ("claude", "refusal"),
        ("claude", "pause_turn"),
    ],
)
def test_abnormal_text_only_completion_returns_received_text(
    monkeypatch, backend, reason
):
    if backend == "gpt":
        stream = FakeStream([chunk("Partial text"), chunk(finish=reason)])
        openai_stream(monkeypatch, stream)
    else:
        stream = FakeStream(
            [
                {
                    "type": "content_block_start",
                    "index": 0,
                    "content_block": {"type": "text", "text": "Partial text"},
                },
                {"type": "message_delta", "delta": {"stop_reason": reason}},
                {"type": "message_stop"},
            ]
        )
        anthropic_stream(monkeypatch, stream)
    events = list(client.stream_llm([], [], backend=backend))
    assert [event.kind for event in events] == ["text_delta", "message_complete"]
    assert events[-1].message.content == "Partial text"
    assert events[-1].message.tool_calls is None
    assert stream.closed


@pytest.mark.parametrize(
    "reason", [None, "stop", "tool_calls", "length", "content_filter"]
)
def test_ollama_tool_completion_reason(monkeypatch, reason):
    stream = FakeStream(
        [
            {
                "message": {
                    "tool_calls": [{"function": {"name": "no_args", "arguments": {}}}]
                },
                "done": True,
                "done_reason": reason,
            }
        ]
    )
    monkeypatch.setattr(client.ollama, "chat", Mock(return_value=stream))
    events = client.stream_llm([], [echo], backend="local")
    if reason in (None, "stop", "tool_calls"):
        assert list(events)[-1].message.tool_calls[0].function.arguments == {}
    else:
        with pytest.raises(RuntimeError, match="Refusing tool calls"):
            list(events)
    assert stream.closed


def test_ollama_indexed_argument_fragments(monkeypatch):
    stream = FakeStream(
        [
            {
                "message": {
                    "tool_calls": [
                        {
                            "index": 1,
                            "id": "b",
                            "function": {"name": "echo", "arguments": '{"value":'},
                        }
                    ]
                }
            },
            {
                "message": {
                    "tool_calls": [
                        {
                            "index": 0,
                            "id": "a",
                            "function": {
                                "name": "echo",
                                "arguments": {"value": "first"},
                            },
                        }
                    ]
                }
            },
            {
                "message": {
                    "tool_calls": [{"index": 1, "function": {"arguments": '"second"}'}}]
                },
                "done": True,
            },
        ]
    )
    monkeypatch.setattr(client.ollama, "chat", Mock(return_value=stream))
    events = list(client.stream_llm([], [echo], backend="local"))
    assert [c.id for c in events[-1].message.tool_calls] == ["a", "b"]
    assert [c.function.arguments for c in events[-1].message.tool_calls] == [
        {"value": "first"},
        {"value": "second"},
    ]


def test_unsupported_tools_retry_is_bounded(monkeypatch):
    create = openai_stream(
        monkeypatch,
        RuntimeError("does not support tools"),
        RuntimeError("does not support tools"),
    )
    with pytest.raises(RuntimeError, match="does not support tools"):
        list(client.stream_llm([], [echo]))
    assert create.call_count == 2


def test_no_retry_or_mixed_output_after_text(monkeypatch):
    stream = FakeStream([chunk("partial"), RuntimeError("does not support tools")])
    create = openai_stream(monkeypatch, stream)
    events = client.stream_llm([], [echo])
    assert next(events).text == "partial"
    with pytest.raises(RuntimeError, match="does not support tools"):
        next(events)
    assert create.call_count == 1
    assert client.state.support_tools is True
    assert stream.closed


@pytest.mark.parametrize("arguments", ['{"value":', "[1, 2]"])
def test_invalid_tool_json_never_produces_complete_message(monkeypatch, arguments):
    stream = FakeStream(
        [
            chunk(
                calls=[tool_delta(0, id="tool", name="echo", arguments=arguments)],
                finish="tool_calls",
            )
        ]
    )
    openai_stream(monkeypatch, stream)
    with pytest.raises(ValueError):
        list(client.stream_llm([], [echo]))
    assert stream.closed


def test_premature_eof_is_error_not_complete(monkeypatch):
    stream = FakeStream([chunk("partial")])
    openai_stream(monkeypatch, stream)
    events = client.stream_llm([], [])
    assert next(events).text == "partial"
    with pytest.raises(RuntimeError, match="before message completion"):
        next(events)
    assert stream.closed


def test_call_llm_compatibility_accumulates_message(monkeypatch):
    stream = FakeStream([chunk("one "), chunk("two", finish="stop")])
    openai_stream(monkeypatch, stream)
    response = client.call_llm([], [], backend="gpt")
    assert response.message.content == "one two"
    assert response.message.role == "assistant"
    assert response.raw_response is not None
    assert stream.closed


def test_backend_snapshot_does_not_follow_global_change(monkeypatch):
    stream = FakeStream([chunk("first"), chunk("second", finish="stop")])
    create = openai_stream(monkeypatch, stream)
    events = client.stream_llm([], [])
    assert next(events).text == "first"
    client.state.active_model = "local"
    assert list(events)[-1].message.content == "firstsecond"
    assert create.call_count == 1


def test_cached_clients_reused(monkeypatch):
    client._openai_client.cache_clear()
    client._anthropic_client.cache_clear()
    openai_factory = Mock()
    anthropic_factory = Mock()
    monkeypatch.setattr(client, "OpenAI", openai_factory)
    monkeypatch.setattr(client.anthropic, "Anthropic", anthropic_factory)
    try:
        assert client._openai_client("key", "url") is client._openai_client(
            "key", "url"
        )
        assert client._anthropic_client("key") is client._anthropic_client("key")
        assert openai_factory.call_count == anthropic_factory.call_count == 1
    finally:
        client._openai_client.cache_clear()
        client._anthropic_client.cache_clear()
