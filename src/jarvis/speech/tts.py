from functools import cache
from threading import Event

from jarvis.core.config import get_settings
from jarvis.speech.factory import build_speech_service
from jarvis.speech.output import SpeechOutput
from jarvis.speech.text import to_speech

__all__ = ["get_speech_output", "is_speaking", "speak", "to_speech"]

is_speaking = Event()


@cache
def get_speech_output() -> SpeechOutput:
    settings = get_settings()
    return SpeechOutput(
        build_speech_service(settings),
        queue_size=settings.speech.queue_size,
        max_segment_length=settings.speech.max_segment_length,
        speaking=is_speaking,
    )


def speak(text: str, locale: str | None = None) -> None:
    """Compatibility entry point for a complete reply; CLI uses streamed input."""
    session = get_speech_output().start(locale or get_settings().speech.locale)
    try:
        session.feed(text)
    finally:
        session.finish()
