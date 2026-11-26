import json
from collections.abc import Generator
from contextlib import closing
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any
from uuid import uuid4

import anthropic
import ollama
from loguru import logger
from ollama import Message
from openai import OpenAI, omit

from jarvis.core.config import get_settings
from jarvis.core.state import state
from jarvis.llm.adapters import (
    to_anthropic,
    to_anthropic_tools,
    to_openai,
    to_openai_tools,
)
from jarvis.llm.prompts import generate_dynamic_prompt
from jarvis.llm.schemas import (
    ChatMessage,
    LLMStreamEvent,
    ModelResponse,
    Provider,
    Tool,
    ToolCall,
    ToolCallFunction,
)


@lru_cache(maxsize=8)
def _openai_client(api_key: str, base_url: str | None) -> OpenAI:
    return OpenAI(api_key=api_key, base_url=base_url, max_retries=0)


@lru_cache(maxsize=8)
def _anthropic_client(api_key: str) -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=api_key, max_retries=0)


def _get(value: Any, key: str, default: Any = None) -> Any:
    return (
        value.get(key, default)
        if isinstance(value, dict)
        else getattr(value, key, default)
    )


def _usage(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    return value if isinstance(value, dict) else value.model_dump(exclude_none=True)


@dataclass
class _ToolBuffer:
    id: str | None = None
    name: str = ""
    arguments: dict[str, Any] = field(default_factory=dict)
    fragments: list[str] = field(default_factory=list)

    def finish(self) -> ToolCall:
        # JSON is deliberately not parsed until the entire message has completed.
        arguments = (
            json.loads("".join(self.fragments) or "{}")
            if self.fragments
            else self.arguments
        )
        if not isinstance(arguments, dict):
            raise ValueError("Tool arguments must be a JSON object")
        return ToolCall(
            id=self.id or str(uuid4()),
            function=ToolCallFunction(name=self.name, arguments=arguments),
        )


def _stream_backend(
    messages: list[ChatMessage],
    tools: list[Tool],
    backend: str,
    provider: Provider,
    use_tools: bool,
) -> Generator[LLMStreamEvent]:
    text: list[str] = []
    calls: dict[int, _ToolBuffer] = {}
    usage: dict[str, Any] = {}
    message_id = str(uuid4())
    finished = False
    raw: Any = None

    if backend == "local":
        raw_messages = [
            Message(
                role=m.role,
                content=m.content or "",
                tool_name=m.name,
                tool_calls=[
                    Message.ToolCall(
                        function=Message.ToolCall.Function(
                            name=tc.function.name, arguments=tc.function.arguments
                        )
                    )
                    for tc in m.tool_calls or []
                ]
                or None,
            )
            for m in messages
        ]
        stream = ollama.chat(
            model=provider.model,
            messages=raw_messages,
            tools=tools if use_tools else None,
            stream=True,
        )
    elif backend == "claude":
        if not provider.api_key:
            raise ValueError("Anthropic API key is not configured.")
        stream = _anthropic_client(provider.api_key.get_secret_value()).messages.create(
            model=provider.model,
            max_tokens=4096,
            system=generate_dynamic_prompt(),
            messages=to_anthropic(messages),
            tools=to_anthropic_tools(tools) if use_tools else anthropic.omit,
            output_config={"effort": "medium"},
            cache_control={"type": "ephemeral", "ttl": "1h"},
            stream=True,
        )
    else:
        if not provider.api_key:
            raise ValueError(f"API key for '{backend}' is not configured.")
        stream = _openai_client(
            provider.api_key.get_secret_value(), provider.gateway_url
        ).chat.completions.create(
            model=provider.model,
            messages=to_openai(messages),
            tools=to_openai_tools(tools) if use_tools else omit,
            stream=True,
        )

    # SDK streams and Ollama's generator all expose close(). In particular,
    # GeneratorExit must unwind this finally, not enter the retry path.
    try:
        block_types: dict[int, str] = {}
        for raw in stream:
            delta_text = ""
            if backend == "local":
                msg = _get(raw, "message")
                delta_text = _get(msg, "content") or ""
                for tc in _get(msg, "tool_calls") or []:
                    fn = _get(tc, "function")
                    index = _get(tc, "index", _get(fn, "index"))
                    if index is None:
                        # Ollama emits complete calls rather than indexed JSON deltas.
                        index = len(calls)
                    call = calls.setdefault(index, _ToolBuffer())
                    call.id = _get(tc, "id") or call.id
                    call.name = _get(fn, "name") or call.name
                    args = _get(fn, "arguments") or {}
                    if isinstance(args, str):
                        call.fragments.append(args)
                    else:
                        call.arguments.update(args)
                if _get(raw, "done", False):
                    finished = True
                    usage = {
                        key: _get(raw, key)
                        for key in ("prompt_eval_count", "eval_count")
                        if _get(raw, key) is not None
                    }
            elif backend == "claude":
                event_type = _get(raw, "type")
                index = _get(raw, "index", 0)
                if event_type == "message_start":
                    msg = _get(raw, "message")
                    message_id = _get(msg, "id") or message_id
                    usage.update(_usage(_get(msg, "usage")))
                elif event_type == "content_block_start":
                    block = _get(raw, "content_block")
                    block_types[index] = _get(block, "type")
                    if block_types[index] == "text":
                        delta_text = _get(block, "text") or ""
                    elif block_types[index] == "tool_use":
                        calls[index] = _ToolBuffer(
                            id=_get(block, "id"),
                            name=_get(block, "name"),
                            arguments=_get(block, "input") or {},
                        )
                elif event_type == "content_block_delta":
                    delta = _get(raw, "delta")
                    if (
                        _get(delta, "type") == "text_delta"
                        and block_types.get(index) == "text"
                    ):
                        delta_text = _get(delta, "text") or ""
                    elif _get(delta, "type") == "input_json_delta" and index in calls:
                        calls[index].fragments.append(_get(delta, "partial_json") or "")
                elif event_type == "message_delta":
                    usage.update(_usage(_get(raw, "usage")))
                    if _get(_get(raw, "delta"), "stop_reason") == "max_tokens":
                        logger.warning(
                            "Response faced max_tokens limit; raise the limit"
                        )
                elif event_type == "message_stop":
                    finished = True
                elif event_type == "error":
                    raise RuntimeError(f"Anthropic stream error: {_get(raw, 'error')}")
            else:
                message_id = _get(raw, "id") or message_id
                usage.update(_usage(_get(raw, "usage")))
                for choice in _get(raw, "choices") or []:
                    if _get(choice, "index", 0) != 0:
                        continue
                    delta = _get(choice, "delta")
                    delta_text = _get(delta, "content") or ""
                    for tc in _get(delta, "tool_calls") or []:
                        if _get(tc, "type") not in (None, "function"):
                            continue
                        call = calls.setdefault(_get(tc, "index", 0), _ToolBuffer())
                        call.id = _get(tc, "id") or call.id
                        fn = _get(tc, "function")
                        call.name += _get(fn, "name") or ""
                        call.fragments.append(_get(fn, "arguments") or "")
                    if _get(choice, "finish_reason") is not None:
                        finished = True
            if delta_text:
                text.append(delta_text)
                yield LLMStreamEvent(kind="text_delta", text=delta_text)
    finally:
        close = getattr(stream, "close", None)
        if close is not None:
            close()

    if not finished:
        raise RuntimeError("LLM stream ended before message completion")
    yield LLMStreamEvent(
        kind="message_complete",
        message=ChatMessage(
            turn_id=message_id,
            role="assistant",
            content="".join(text),
            tool_calls=[calls[index].finish() for index in sorted(calls)] or None,
        ),
        usage=usage or None,
        raw_response=raw,
    )


def stream_llm(
    messages: list[ChatMessage],
    tools: list[Tool],
    *,
    backend: str | None = None,
) -> Generator[LLMStreamEvent]:
    """Stream public text, then exactly one fully assembled assistant message.

    Backend errors propagate. Closing this iterator closes the network stream.
    Tool-support fallback is attempted once, and only before any public text.
    """
    backend = backend if backend is not None else state.active_model
    settings = get_settings()
    if backend not in settings.providers:
        raise NotImplementedError(
            f"Backend '{backend}' is not yet supported, try to change the model"
        )
    provider = settings.providers[backend]
    use_tools = bool(tools) and state.support_tools
    emitted = False
    for attempt in range(2):
        try:
            with closing(
                _stream_backend(messages, tools, backend, provider, use_tools)
            ) as events:
                for event in events:
                    emitted = True
                    yield event
            return
        except Exception as err:
            if (
                attempt == 0
                and use_tools
                and not emitted
                and "does not support tools" in str(err).lower()
            ):
                logger.warning("Model lacks tool support; retrying once without tools")
                use_tools = False
                if state.active_model == backend:
                    state.support_tools = False
                continue
            logger.exception("LLM dispatch failed for backend {}", backend)
            raise


def call_llm(
    messages: list[ChatMessage],
    tools: list[Tool],
    *,
    backend: str | None = None,
) -> ModelResponse:
    """Compatibility consumer for callers (including history compaction)."""
    with closing(stream_llm(messages, tools, backend=backend)) as events:
        for event in events:
            if event.kind == "message_complete" and event.message is not None:
                return ModelResponse(
                    message=event.message, raw_response=event.raw_response
                )
    raise RuntimeError("LLM stream did not produce a complete message")
