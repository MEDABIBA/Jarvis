import inspect
import json
from collections.abc import Iterable

from anthropic.types import ToolParam
from anthropic.types.content_block_param import ContentBlockParam
from anthropic.types.message_param import MessageParam
from openai.types.chat import ChatCompletionMessageParam, ChatCompletionToolUnionParam

from jarvis.llm.schemas import ChatMessage, Tool

TYPE_MAP = {
    str: "string",
    bool: "boolean",
    int: "integer",
    float: "number",
}


def to_anthropic(messages: list[ChatMessage]) -> list[MessageParam]:
    """Convert internal history structure to the anthropic api params"""
    res: list[MessageParam] = []
    for m in messages:
        role = m.role
        if role == "assistant" and m.tool_calls:
            block: list[ContentBlockParam] = []
            if m.content:
                block.append({"type": "text", "text": m.content})
            block.extend(
                {
                    "type": "tool_use",
                    "id": tc.id or "",
                    "name": tc.function.name,
                    "input": tc.function.arguments,
                }
                for tc in m.tool_calls
            )
            res.append({"role": "assistant", "content": block})
        elif role in ("user", "assistant") and m.content:
            res.append({"role": role, "content": m.content})
        elif role == "tool":
            res.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": m.tool_call_id or "",
                            "content": m.content or "",
                        }
                    ],
                }
            )
    return res


def signature_schema(tool: Tool):
    signature = inspect.signature(tool)
    properties: dict[str, dict[str, str]] = {}
    required: list[str] = []
    for name, param in signature.parameters.items():
        json_type = TYPE_MAP.get(param.annotation, "string")
        properties[name] = {"type": json_type}
        if param.default is inspect.Parameter.empty:
            required.append(name)
    return properties, required


def to_anthropic_tools(tools: list[Tool]) -> list[ToolParam]:
    """Convert python tools to Anthropic tool specs"""
    specs: list[ToolParam] = []
    for tool in tools:
        properties, required = signature_schema(tool)
        specs.append(
            {
                "name": tool.__name__,
                "description": inspect.getdoc(tool) or "None",
                "input_schema": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                },
            }
        )
    return specs


def to_openai(messages: list[ChatMessage]) -> list[ChatCompletionMessageParam]:
    """Convert internal history structure to the openai compatible protocol params"""
    res: list[ChatCompletionMessageParam] = []
    for m in messages:
        role = m.role
        if role == "assistant" and m.tool_calls:
            res.append(
                {
                    "role": "assistant",
                    "content": m.content or "",
                    "tool_calls": [
                        {
                            "type": "function",
                            "id": tc.id or "",
                            "function": {
                                "name": tc.function.name,
                                "arguments": json.dumps(tc.function.arguments),
                            },
                        }
                        for tc in m.tool_calls
                    ],
                }
            )
        elif role == "assistant" and m.content:
            res.append({"role": role, "content": m.content})
        elif role == "user":
            res.append({"role": role, "content": m.content or ""})
        elif role == "system":
            res.append({"role": role, "content": m.content or ""})
        elif role == "tool":
            res.append(
                {
                    "role": "tool",
                    "tool_call_id": m.tool_call_id or "",
                    "content": m.content or "",
                }
            )
    return res


def to_openai_tools(tools: list[Tool]) -> Iterable[ChatCompletionToolUnionParam]:
    """Convert python tools to openai compatible protocol tool specs"""
    specs: Iterable[ChatCompletionToolUnionParam] = []
    for tool in tools:
        properties, required = signature_schema(tool)
        specs.append(
            {
                "type": "function",
                "function": {
                    "name": tool.__name__,
                    "description": inspect.getdoc(tool) or "None",
                    "parameters": {
                        "type": "object",
                        "properties": properties,
                        "required": required,
                        # "additionalProperties": False,
                    },
                    "strict": False,
                },
            }
        )
    return specs
