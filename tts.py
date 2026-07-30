import numpy as np
import sounddevice as sd
from pathlib import Path
from piper import PiperVoice
from typing import Literal
import threading
import re

_language = Literal["en", "ru", "pl"]
cache: dict[str, PiperVoice] = {}
speaking = threading.Event()

VOICES: dict[str, str] = {
    "en": "voices/EN/en_GB-alan-medium.onnx",
    "ru": "voices/RU/ru_RU-denis-medium.onnx",
    "pl": "voices/PL/pl_PL-bass-high.onnx",
}

_POLISH = re.compile("[ąćęłńóśźż]", re.IGNORECASE)
_CYRILLIC = re.compile("[а-я]", re.IGNORECASE)


def detect_language(text: str) -> _language:
    if _POLISH.search(text):
        return "pl"
    elif _CYRILLIC.search(text):
        return "ru"
    else:
        return "en"


def get_voice(language: _language):
    if not language in cache.keys():
        model = Path(VOICES[language]).resolve()
        cache[language] = PiperVoice.load(model)
    return cache[language]


def get_audio(voice: PiperVoice, text: str):
    chunks = list(voice.synthesize(text))
    audio = np.frombuffer(
        b"".join(c.audio_int16_bytes for c in chunks),
        dtype=np.int16,
    )
    sd.play(audio, samplerate=chunks[0].sample_rate)
    sd.wait()


def speak(text: str):
    """Play a text through the default output device
    Args:
        language: The language in which the text wil be written
        text: Text to speech"""
    speaking.set()
    language: _language = detect_language(text)
    voice = get_voice(language)
    get_audio(voice, text)
    speaking.clear()
