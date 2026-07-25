from collections.abc import Callable
from schemas import Message

import ollama
import os

LLM_MODEL = os.environ["LLM_MODEL"]

def call_llm(messages: list[Message], tools: list[Callable] | None = None):
    return ollama.chat(
        model=LLM_MODEL,
        messages=messages,
        tools=tools
    )