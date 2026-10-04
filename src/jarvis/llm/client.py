import json

import anthropic
import ollama
from loguru import logger
from ollama import Message
from openai import OpenAI, omit
from openai.types.chat import ChatCompletion

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
    ModelResponse,
    Tool,
    ToolCall,
    ToolCallFunction,
)


def call_llm(
    messages: list[ChatMessage],
    tools: list[Tool],
) -> ModelResponse:
    """Route LLM chat requests dynamically to the active backend."""
    settings = get_settings()
    backend = state.active_model

    logger.debug("Dispatching chat turn to LLM backend: {}", backend)

    try:
        match backend:
            case "local":
                raw_msgs: list[Message] = [
                    Message(role=m.role, content=m.content or "")
                    for m in messages
                    if m.content is not None
                ]
                response = ollama.chat(
                    model=settings.providers["local"].model,
                    messages=raw_msgs,
                    tools=tools if state.support_tools else None,
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
                if not settings.providers["claude"].api_key:
                    raise ValueError("Anthropic API key is not configured.")
                client = anthropic.Anthropic(
                    api_key=settings.providers["claude"].api_key.get_secret_value()
                )

                resp = client.messages.create(
                    model=settings.providers["claude"].model,
                    max_tokens=4096,
                    system=generate_dynamic_prompt(),
                    messages=to_anthropic(messages),
                    tools=to_anthropic_tools(tools),
                    output_config={"effort": "medium"},
                    cache_control={"type": "ephemeral"},
                )

                if resp.stop_reason == "max_tokens":
                    logger.warning("Response faced max_tokens limit; raise the limit")

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

            case x if x in settings.providers:
                provider = settings.providers[x]
                if provider.api_key is None:
                    raise ValueError(f"API key for '{x}' is not configured.")

                client = OpenAI(
                    api_key=provider.api_key.get_secret_value()
                    if provider.api_key
                    else None,
                    base_url=provider.gateway_url,
                )

                res: ChatCompletion = client.chat.completions.create(
                    model=settings.providers[x].model,
                    messages=to_openai(messages),
                    tools=to_openai_tools(tools) if state.support_tools else omit,
                )
                message = res.choices[0].message

                tool_calls_parsed = [
                    ToolCall(
                        id=call.id,
                        function=ToolCallFunction(
                            name=call.function.name,
                            arguments=json.loads(call.function.arguments or "{}"),
                        ),
                    )
                    for call in message.tool_calls or []
                    if call.type == "function"
                ]

                return ModelResponse(
                    message=ChatMessage(
                        role="assistant",
                        content=message.content,
                        tool_calls=tool_calls_parsed,
                    ),
                    raw_response=res,
                )

            case _:
                raise NotImplementedError(
                    f"Backend '{backend}' is not yet supported, try to change the model"
                )
    except Exception as e:
        if "does not support tools" in str(e):
            logger.warning("Model lacks tool support; retrying without tools")
            state.support_tools = False
            return call_llm(messages, tools)
        logger.exception("LLM dispatch failed with error {}", backend)
        raise
