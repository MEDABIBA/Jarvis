from collections.abc import Callable

import anthropic
import ollama
from anthropic.types import MessageParam
from loguru import logger

from jarvis.core.config import get_settings
from jarvis.core.state import state
from jarvis.llm.prompts import SYSTEM_PROMPT
from jarvis.llm.schemas import ChatMessage, ModelResponse, ToolCall, ToolCallFunction


def to_anthropic(messages: list[ChatMessage]) -> list[MessageParam]:
    """Convert internal history structure to the anthropic api params"""
    res: list[MessageParam] = []
    for m in messages:
        role = m.role
        if role in ("user", "assistant"):
            res.append({"content": m.content or "", "role": role})
    return res


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
                model=settings.local_model,
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

            resp = client.messages.create(
                model=settings.anthropic_model,
                max_tokens=4096,
                system=SYSTEM_PROMPT,
                messages=to_anthropic(messages),
            )

            text_content = ""
            for block in resp.content:
                if block.type == "text":
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
