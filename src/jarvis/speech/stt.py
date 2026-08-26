from functools import cache

from loguru import logger
from RealtimeSTT.audio_recorder import AudioToTextRecorder


@cache
def get_recorder() -> AudioToTextRecorder:
    """Initialize the continuous speech recognition and wake word engine."""
    logger.info("Initializing RealtimeSTT recorder with wake word 'jarvis'...")
    return AudioToTextRecorder(
        model="small",
        device="cpu",
        compute_type="int8",
        batch_size=1,
        wake_words="jarvis",
        wake_word_timeout=5,
        post_speech_silence_duration=2,
        wake_words_sensitivity=0.6,
        on_wakeword_detected=lambda: logger.info(
            "Wake word detected! Listening for command..."
        ),
        spinner=False,
    )
