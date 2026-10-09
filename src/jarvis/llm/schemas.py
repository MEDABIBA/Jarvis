from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field, SecretStr


class ToolCallFunction(BaseModel):
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class ToolCall(BaseModel):
    id: str | None = None
    type: str = "function"
    function: ToolCallFunction


class ChatMessage(BaseModel):
    turn_id: str
    role: Literal["system", "user", "assistant", "tool"]
    content: str | None = None
    tool_calls: list[ToolCall] | None = None
    tool_call_id: str | None = None
    name: str | None = None


class ModelResponse(BaseModel):
    message: ChatMessage
    raw_response: Any = None


class Tool(Protocol):
    __name__: str

    def __call__(self, *args: Any, **kwargs: Any) -> Any: ...


class Provider(BaseModel):
    """Connection details for one LLM backend."""

    model: str
    protocol: Literal["anthropic", "openai", "local"]
    api_key: SecretStr | None = None
    gateway_url: str | None = None


class SessionData(BaseModel):
    question: str
    answer: str
    # tools: str
    turn_id: str
