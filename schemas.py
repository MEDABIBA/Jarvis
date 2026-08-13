from typing import TypedDict, Literal


class Message(TypedDict):
    role: Literal["system", "user", "assistant", "tool"]
    content: str
