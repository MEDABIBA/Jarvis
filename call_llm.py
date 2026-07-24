from schemas import Message

import ollama

def call_llm(messages: list[Message], tools=None):
    return ollama.chat(
        model="qwen:7b",
        messages=messages,
        tools=tools
    )