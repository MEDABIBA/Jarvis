"""Provider orchestration without playback, implicit providers, or retries.

A turn starts conservatively at the first yielded PCM, not speaker acknowledgement.
Cloud attempts share one first-audio deadline per sentence. Local providers receive
an independent fresh budget, even after cloud exhaustion; deadlines are cooperative
so local model loading/inference is best effort, not forcibly interrupted.

Consume or explicitly close each returned iterator before starting another sentence.
SpeechError means the caller should retain text output; a failed turn stays silent.
"""

from collections.abc import Iterator, Sequence
from contextlib import suppress
from math import isfinite
from threading import Event
from time import monotonic

from jarvis.speech.types import (
    AudioChunk,
    SpeechCancelled,
    SpeechError,
    SpeechProvider,
    SpeechTurn,
)


class SpeechService:
    def __init__(
        self,
        providers: Sequence[SpeechProvider],
        *,
        first_audio_timeout: float = 5,
        cooldown: float = 30,
    ) -> None:
        if not isfinite(first_audio_timeout) or first_audio_timeout <= 0:
            raise ValueError("first_audio_timeout must be finite and positive")
        if not isfinite(cooldown) or cooldown < 0:
            raise ValueError("cooldown must be finite and nonnegative")
        self._providers = tuple(providers)
        self._timeout = first_audio_timeout
        self._cooldown = cooldown
        self._unavailable: dict[tuple[str, str], float] = {}
        self._azure_until = 0.0
        self._closed = False

    def _check(self, cancel: Event) -> None:
        if cancel.is_set() or self._closed:
            raise SpeechCancelled()

    def _record_failure(
        self, provider: SpeechProvider, locale: str, error: SpeechError
    ) -> None:
        delay = self._cooldown
        retry = error.retry_after
        if retry is not None and isfinite(retry) and retry >= 0:
            delay = max(delay, retry)
        until = monotonic() + delay
        if error.scope == "azure" and provider.group == "azure":
            self._azure_until = max(self._azure_until, until)
        else:
            key = (provider.name, locale)
            self._unavailable[key] = max(self._unavailable.get(key, 0), until)

    def synthesize(
        self, text: str, locale: str, *, cancel: Event, turn: SpeechTurn
    ) -> Iterator[AudioChunk]:
        """Yield validated int16 PCM; never switch providers after turn start.

        Empty provider streams are failures. Unexpected exceptions are sanitized
        provider failures. Cancellation never triggers fallback or cooldown.
        """
        self._check(cancel)
        if turn.failed or not text.strip():
            return
        cloud_deadline = monotonic() + self._timeout
        for provider in self._providers:
            self._check(cancel)
            if turn.provider is not None and provider.name != turn.provider:
                continue
            now = monotonic()
            if (
                self._unavailable.get((provider.name, locale), 0) > now
                or (provider.group == "azure" and self._azure_until > now)
                or (provider.group != "local" and now >= cloud_deadline)
            ):
                continue
            deadline = (
                now + self._timeout if provider.group == "local" else cloud_deadline
            )
            stream = None
            error = None
            received = False
            try:
                stream = iter(
                    provider.synthesize(text, locale, cancel=cancel, deadline=deadline)
                )
                while True:
                    self._check(cancel)
                    if not received and monotonic() >= deadline:
                        raise SpeechError("Speech first-audio deadline exceeded")
                    try:
                        chunk = next(stream)
                    except StopIteration:
                        break
                    self._check(cancel)
                    if not isinstance(chunk, AudioChunk):
                        raise SpeechError("Invalid speech audio chunk")
                    if (
                        chunk.sample_rate <= 0
                        or chunk.channels <= 0
                        or not isinstance(chunk.data, bytes)
                        or len(chunk.data) % (2 * chunk.channels)
                    ):
                        raise SpeechError("Invalid speech PCM format")
                    if not chunk.data:
                        continue
                    if not received and monotonic() >= deadline:
                        raise SpeechError("Speech first-audio deadline exceeded")
                    received = True
                    turn.started = True
                    turn.provider = provider.name
                    yield chunk
                self._check(cancel)
                if not received:
                    raise SpeechError("Speech provider returned no audio")
                return
            except SpeechCancelled:
                turn.failed = True
                raise
            except SpeechError as exc:
                error = exc
            except Exception:
                # Native/provider exceptions may contain credentials or raw text.
                error = SpeechError("Speech provider failed")
            finally:
                if stream is not None:
                    with suppress(Exception):
                        close = getattr(stream, "close", None)
                        if close is not None:
                            close()
            self._check(cancel)
            self._record_failure(provider, locale, error)
            if turn.started or turn.provider is not None:
                turn.failed = True
                raise error from None
        turn.failed = True
        raise SpeechError("No speech provider available") from None

    def close(self) -> None:
        """Close every distinct provider once; cleanup failures are non-fatal."""
        if self._closed:
            return
        self._closed = True
        seen: set[int] = set()
        for provider in self._providers:
            if id(provider) not in seen:
                seen.add(id(provider))
                with suppress(Exception):
                    provider.close()
