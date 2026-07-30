from collections.abc import Callable
from schemas import Message
from config import LLM_MODEL

import ollama


def call_llm(messages: list[Message], tools: list[Callable] | None = None):
    return ollama.chat(model=LLM_MODEL, messages=messages, tools=tools)
