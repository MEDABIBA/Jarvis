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


class LLMStreamEvent(BaseModel):
    """Only public assistant text is incremental; tool calls arrive fully assembled."""

    kind: Literal["text_delta", "message_complete"]
    text: str = ""
    message: ChatMessage | None = None
    usage: dict[str, Any] | None = None
    raw_response: Any = None


class TurnEvent(BaseModel):
    """Engine progress. Only a complete event's answer is the final response.

    Text before a tool call is public progress, not part of the final answer.
    Error is terminal (there is no following complete event).
    """

    turn_id: str
    kind: Literal["text_delta", "tool_start", "tool_end", "complete", "error"]
    text: str = ""
    answer: str = ""
    tool_name: str | None = None
    tool_call_id: str | None = None
    error: str | None = None


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
