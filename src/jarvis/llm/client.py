from collections.abc import Callable
from typing import Any

import anthropic
import ollama
from loguru import logger

from jarvis.core.config import get_settings
from jarvis.core.state import state
from jarvis.llm.prompts import SYSTEM_PROMPT
from jarvis.llm.schemas import ChatMessage, ModelResponse, ToolCall, ToolCallFunction


def _format_tools_for_anthropic(tools: list[Callable]) -> list[dict[str, Any]]:
    # Anthropic tool formatting helper
    tool_specs: list[dict[str, Any]] = []
    for fn in tools:
        tool_specs.append(
            {
                "name": fn.__name__,  # ty: ignore[unresolved-attribute]
                "description": (fn.__doc__ or "").strip(),
                "input_schema": {
                    "type": "object",
                    "properties": {},  # Model extracts based on signature/docstring
                },
            }
        )
    return tool_specs


def call_llm(
    messages: list[ChatMessage],
    tools: list[Callable] | None = None,
) -> ModelResponse:
    """Route LLM chat requests dynamically to the active backend."""
    settings = get_settings()
    backend = state.active_model

    logger.debug("Dispatching chat turn to LLM backend: {}", backend)

    match backend:
        case "local":
            raw_msgs = [
                {"role": m.role, "content": m.content or ""}
                for m in messages
                if m.content is not None
            ]
            response = ollama.chat(
                model=settings.local_llm,
                messages=raw_msgs,
                tools=tools,
            )

            msg_dict = response.message
            tool_calls_parsed = None
            if msg_dict.tool_calls:
                tool_calls_parsed = [
                    ToolCall(
                        function=ToolCallFunction(
                            name=tc.function.name,
                            arguments=tc.function.arguments or {},
                        )
                    )
                    for tc in msg_dict.tool_calls
                ]

            return ModelResponse(
                message=ChatMessage(
                    role="assistant",
                    content=msg_dict.content,
                    tool_calls=tool_calls_parsed,
                ),
                raw_response=response,
            )

        case "claude":
            if not settings.anthropic_api_key:
                raise ValueError("Anthropic API key is not configured.")

            client = anthropic.Anthropic(
                api_key=settings.anthropic_api_key.get_secret_value()
            )

            anthropic_messages: list[dict[str, Any]] = []
            for m in messages:
                if m.role == "system":
                    continue
                if m.role in ("user", "assistant"):
                    anthropic_messages.append(
                        {"role": m.role, "content": m.content or ""}
                    )

            resp = client.messages.create(
                model="claude-3-7-sonnet-20250219",
                max_tokens=2048,
                system=SYSTEM_PROMPT,
                messages=anthropic_messages,  # ty: ignore[invalid-argument-type]
            )

            text_content = ""
            for block in resp.content:
                if getattr(block, "type", "") == "text":
                    text_content += block.text

            return ModelResponse(
                message=ChatMessage(
                    role="assistant",
                    content=text_content,
                ),
                raw_response=resp,
            )

        case _:
            raise NotImplementedError(f"Backend '{backend}' is not yet supported.")
