from collections.abc import Callable

import anthropic
import ollama
from loguru import logger

from jarvis.core.config import get_settings
from jarvis.core.state import state
from jarvis.llm.adapters import to_anthropic, to_anthropic_tools
from jarvis.llm.prompts import SYSTEM_PROMPT
from jarvis.llm.schemas import ChatMessage, ModelResponse, ToolCall, ToolCallFunction


def call_llm(
    messages: list[ChatMessage],
    tools: list[Callable],
) -> ModelResponse:
    """Route LLM chat requests dynamically to the active backend."""
    settings = get_settings()
    backend = state.active_model

    logger.debug("Dispatching chat turn to LLM backend: {}", backend)

    try:
        match backend:
            case "local":
                raw_msgs = [
                    {"role": m.role, "content": m.content or ""}
                    for m in messages
                    if m.content is not None
                ]
                params = {
                    "model":settings.local_model,
                    "messages":raw_msgs
                }
                if state.support_tools:
                    params["tools"] = tools
                response = ollama.chat(**params)

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
                    tools=to_anthropic_tools(tools),
                    output_config={"effort": "medium"},
                    cache_control={"type": "ephemeral"},
                )

                logger.debug(
                    "tokens: fresh={} write={} read={} out={}",
                    resp.usage.input_tokens,
                    resp.usage.cache_creation_input_tokens,
                    resp.usage.cache_read_input_tokens,
                    resp.usage.output_tokens,
                )
                text_content = ""
                for block in resp.content:
                    if block.type == "text":
                        text_content += block.text

                parsed_tools: list[ToolCall] = [
                    ToolCall(
                        id=block.id,
                        function=ToolCallFunction(
                            name=block.name,
                            arguments=block.input,
                        ),
                    )
                    for block in resp.content
                    if block.type == "tool_use"
                ]
                return ModelResponse(
                    message=ChatMessage(
                        role="assistant", content=text_content, tool_calls=parsed_tools
                    ),
                    raw_response=resp,
                )

            case _:
                raise NotImplementedError(f"Backend '{backend}' is not yet supported.")
    except Exception as e:
        if "does not support tools" in str(e):
            logger.warning("Model lacks tool support; retrying without tools")
            state.support_tools = False
            return call_llm(messages, tools)
        logger.exception("LLM dispatch failed with error {}", backend)
        raise
