from loguru import logger

from jarvis.core.config import AppSettings
from jarvis.speech.piper import PiperProvider
from jarvis.speech.service import SpeechService
from jarvis.speech.types import SpeechProvider


def build_speech_service(settings: AppSettings) -> SpeechService:
    speech = settings.speech
    providers: list[SpeechProvider] = []
    if speech.provider in ("azure_sdk", "azure_rest"):
        if speech.azure_key and speech.azure_region:
            from jarvis.speech.azure import AzureRestProvider, AzureSdkProvider

            args = (
                speech.azure_key.get_secret_value(),
                speech.azure_region,
                speech.azure_voices,
            )
            if speech.provider == "azure_sdk":
                providers.append(AzureSdkProvider(*args))
            providers.append(AzureRestProvider(*args))
        else:
            logger.warning("Azure speech key or region missing; using local speech")
    if speech.provider != "text":
        providers.append(PiperProvider(settings.voices_dir, speech.piper_voices))
    return SpeechService(
        providers,
        first_audio_timeout=speech.first_audio_timeout,
        cooldown=speech.cooldown,
    )
