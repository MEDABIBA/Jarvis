from dataclasses import dataclass, field
from threading import Lock

from loguru import logger

from jarvis.core.config import get_settings


@dataclass
class AppState:
    """Thread-safe runtime state management."""

    active_model: str = "local"
    support_tools: bool = True
    tts_enabled: bool = False
    stt_enabled: bool = True
    _lock: Lock = field(default_factory=Lock, init=False, repr=False)

    def cycle_model(self) -> str:
        with self._lock:
            available = get_settings().available_models
            if len(available) <= 1:
                logger.warning("No additional cloud LLM API keys configured.")
                return self.active_model

            current_idx = (
                available.index(self.active_model)
                if self.active_model in available
                else 0
            )
            next_idx = (current_idx + 1) % len(available)
            self.active_model = available[next_idx]
            logger.info("Switched active model backend to: {}", self.active_model)
            return self.active_model

    def toggle_tts(self) -> bool:
        with self._lock:
            self.tts_enabled = not self.tts_enabled
            logger.info(
                "Text-to-Speech playback: {}",
                "ENABLED" if self.tts_enabled else "DISABLED",
            )
            return self.tts_enabled

    def toggle_stt(self) -> bool:
        with self._lock:
            self.stt_enabled = not self.stt_enabled
            logger.info(
                "Microphone input capture: {}",
                "ENABLED" if self.stt_enabled else "DISABLED",
            )
            return self.stt_enabled


state = AppState()
