from __future__ import annotations

from collections.abc import Callable
from contextlib import closing
from threading import Event
from typing import TYPE_CHECKING

from loguru import logger

from jarvis.llm.schemas import SessionData
from jarvis.speech.types import SpeechError

if TYPE_CHECKING:
    from jarvis.engine import AssistantEngine
    from jarvis.speech.output import SpeechOutput


def run_turn(
    engine: AssistantEngine,
    text: str,
    *,
    on_text: Callable[[str], None],
    cancel: Event,
    speech: SpeechOutput | None = None,
    locale: str = "en-GB",
) -> SessionData | None:
    """Consume engine events without tying the engine to a terminal or speaker."""
    session = None
    if speech is not None and not cancel.is_set():
        try:
            session = speech.start(locale)
        except SpeechError:
            logger.warning("Speech output unavailable; continuing with text")
    completed = False
    try:
        with closing(engine.handle_stream(text)) as events:
            while not cancel.is_set():
                try:
                    event = next(events)
                except StopIteration:
                    raise RuntimeError("Turn ended without a terminal event") from None
                if cancel.is_set():
                    break
                if event.kind == "text_delta":
                    on_text(event.text)
                    if session is not None:
                        session.feed(event.text)
                elif event.kind == "tool_start":
                    if session is not None:
                        session.boundary()
                elif event.kind in ("complete", "error"):
                    completed = event.kind == "complete"
                    if not completed:
                        on_text(f"\n{event.text}")
                    return SessionData(
                        question=text, answer=event.answer, turn_id=event.turn_id
                    )
        return None
    finally:
        if session is not None:
            if completed and not cancel.is_set():
                session.finish()
            else:
                session.cancel()
