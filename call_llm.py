from collections.abc import Callable
from schemas import Message
from config import LOCAL_LLM, claude_client
from state import state
from anthropic.types import MessageParam
from jarvis_message import SYSTEM_PROMPT

import ollama

def to_anthropic(messages: list[Message]) -> list[MessageParam]:
    res = []
    for m in messages:
        role = m["role"]
        if role in ("system", "user", "assistant"):
            res.append({"content": m["content"], "role": role})
    return res

def call_llm(messages: list[Message], tools: list[Callable] | None = None):
    match state.model:
        case "local":
            return ollama.chat(model=LOCAL_LLM, messages=messages, tools=tools)
        case "claude":
            return claude_client().messages.create(
                max_tokens=4096,
                system=SYSTEM_PROMPT,
                messages=to_anthropic(messages),
                model="claude-opus-5", # hardcoded
                # tools
            )
        case "gemini":
            pass
        case "gpt":
            pass