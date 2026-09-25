import re
from functools import cache
from threading import Event
from typing import Literal

import numpy as np
import sounddevice as sd
from loguru import logger
from piper import PiperVoice

from jarvis.core.config import get_settings

Language = Literal["en", "ru", "pl"]

is_speaking = Event()

_POLISH_RE = re.compile(r"[ąćęłńóśźż]", re.IGNORECASE)
_CYRILLIC_RE = re.compile(r"[а-я]", re.IGNORECASE)  # ruff: ignore[RUF001]
_ALLOWED = ".,!?;:-'"

_CODE_FENCE_RE = re.compile(r"```.*?```", re.DOTALL)

VOICE_CONFIG: dict[Language, str] = {
    "en": "EN/en_GB-northern_english_male-medium.onnx",
    "ru": "RU/ru_RU-ruslan-medium.onnx",
    "pl": "PL/pl_PL-mc_speech-medium.onnx",
}


def detect_language(text: str) -> Language:
    """Heuristic language detection based on distinctive character sets."""
    if _POLISH_RE.search(text):
        return "pl"
    if _CYRILLIC_RE.search(text):
        return "ru"
    return "en"


def to_speech(
    text: str,
) -> str:  # Needs improvement: filter big numbers, links, mails, ip adressess, etc.
    """Strip code blocks and unpronounceable symbols from an assistant reply."""
    text = _CODE_FENCE_RE.sub(" ", text)
    if text.count("```") % 2:
        text = text.split("```")[0]

    text = text.replace("_", " ")

    res: list[str] = []
    for el in text:
        if el.isalnum() or el.isspace() or el in _ALLOWED:
            res.append(el)

    return " ".join("".join(res).split())


@cache
def get_voice(lang: Language) -> PiperVoice:
    """Load and cache Piper TTS ONNX voice models."""
    settings = get_settings()
    voice_rel_path = VOICE_CONFIG[lang]
    model_path = (settings.voices_dir / voice_rel_path).resolve()

    if not model_path.exists():
        raise FileNotFoundError(
            f"Voice model file not found: {model_path}. "
            f"Download via python -m piper.download_voices"
        )

    logger.debug("Loading Piper TTS voice model: {}", model_path)
    return PiperVoice.load(model_path)


def speak(text: str) -> None:
    """Synthesize text and play audio synchronously via sounddevice."""
    parsed_text = to_speech(text)
    if not parsed_text.strip():
        return

    is_speaking.set()
    try:
        lang = detect_language(parsed_text)
        voice = get_voice(lang)
        chunks = list(voice.synthesize(parsed_text))
        if not chunks:
            return

        audio_bytes = b"".join(c.audio_int16_bytes for c in chunks)
        audio = np.frombuffer(audio_bytes, dtype=np.int16)

        sd.play(audio, samplerate=chunks[0].sample_rate)
        sd.wait()
    except Exception as err:
        logger.error("TTS playback failed: {}", err)
    finally:
        is_speaking.clear()
