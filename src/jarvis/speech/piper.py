"""Lazy, exact-locale Piper synthesis. No playback or cloud dependencies."""

import importlib
from collections.abc import Iterator
from contextlib import suppress
from pathlib import Path
from threading import Event
from time import monotonic
from typing import Any

from jarvis.speech.types import AudioChunk, SpeechCancelled, SpeechError


class PiperProvider:
    name = "piper"
    group = "local"

    def __init__(self, voices_dir: Path, voices: dict[str, str]) -> None:
        self._voices_dir = voices_dir.resolve()
        self._voices = dict(voices)
        self._cache: dict[str, Any] = {}
        self._closed = False

    def _check(self, cancel: Event, deadline: float | None) -> None:
        if cancel.is_set() or self._closed:
            raise SpeechCancelled()
        if deadline is not None and monotonic() >= deadline:
            raise SpeechError("Piper first-audio deadline exceeded")

    def _voice(self, locale: str) -> Any:
        if locale in self._cache:
            return self._cache[locale]
        relative = self._voices.get(locale)
        if not relative:
            raise SpeechError("No Piper voice for requested locale")
        model = (self._voices_dir / relative).resolve()
        if Path(relative).is_absolute() or not model.is_relative_to(self._voices_dir):
            raise SpeechError("Piper model must be inside voices directory")
        if not model.is_file():
            raise SpeechError("Piper voice model is missing")
        try:
            voice_type = importlib.import_module("piper").PiperVoice
        except (ImportError, AttributeError):
            raise SpeechError("Piper dependency is unavailable") from None
        try:
            voice = voice_type.load(model)
        except Exception:
            raise SpeechError("Piper voice model could not be loaded") from None
        self._cache[locale] = voice
        return voice

    def synthesize(
        self, text: str, locale: str, *, cancel: Event, deadline: float
    ) -> Iterator[AudioChunk]:
        """Stream Piper int16 chunks; deadline applies only until first PCM.

        Model loading and native inference cannot be preempted. Cancellation and
        deadline are checked on both sides of loading and each first-audio step.
        Calls are intended to be serialized by the speech worker.
        """
        stream = None
        try:
            self._check(cancel, deadline)
            voice = self._voice(locale)
            self._check(cancel, deadline)
            stream = iter(voice.synthesize(text))
            received = False
            while True:
                self._check(cancel, None if received else deadline)
                try:
                    chunk = next(stream)
                except StopIteration:
                    break
                self._check(cancel, None if received else deadline)
                data = chunk.audio_int16_bytes
                if not data:
                    continue
                received = True
                yield AudioChunk(
                    data=data,
                    sample_rate=chunk.sample_rate,
                    channels=getattr(chunk, "sample_channels", 1),
                )
            self._check(cancel, None if received else deadline)
            if not received:
                raise SpeechError("Piper returned no audio")
        except (SpeechCancelled, SpeechError):
            raise
        except Exception:
            raise SpeechError("Piper synthesis failed") from None
        finally:
            if stream is not None:
                with suppress(Exception):
                    close = getattr(stream, "close", None)
                    if close is not None:
                        close()

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._cache.clear()
