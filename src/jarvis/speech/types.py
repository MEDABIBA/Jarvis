from collections.abc import Iterator
from dataclasses import dataclass
from threading import Event
from typing import Literal, Protocol


@dataclass(frozen=True)
class AudioChunk:
    """Signed little-endian 16-bit PCM. No container headers."""

    data: bytes
    sample_rate: int
    channels: int = 1


class SpeechCancelled(Exception):
    pass


class SpeechError(Exception):
    def __init__(
        self,
        message: str,
        *,
        scope: Literal["provider", "azure"] = "provider",
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message)
        self.scope = scope
        self.retry_after = retry_after


class SpeechProvider(Protocol):
    name: str
    group: str

    def synthesize(
        self, text: str, locale: str, *, cancel: Event, deadline: float
    ) -> Iterator[AudioChunk]: ...

    def close(self) -> None: ...


@dataclass
class SpeechTurn:
    """State belongs to one response, never to a global client session."""

    started: bool = False
    failed: bool = False
    provider: str | None = None
