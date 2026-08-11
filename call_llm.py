from collections.abc import Callable
from schemas import Message
from config import LOCAL_LLM
from state import state

import ollama


def call_llm(messages: list[Message], tools: list[Callable] | None = None):
    match state.model:
        case "local":
            return ollama.chat(model=LOCAL_LLM, messages=messages, tools=tools)
        case "claude":
            pass
        case "gemini":
            pass
        case "gpt":
            pass