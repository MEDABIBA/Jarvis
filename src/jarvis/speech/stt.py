from functools import cache
import sounddevice as sd
import soundfile as sf
from pathlib import Path
from loguru import logger
from RealtimeSTT.audio_recorder import AudioToTextRecorder

def play_sound():
    route = Path("src/jarvis/assets/sounds/voice_assistant_input.mp3").resolve()
    data,samplerate = sf.read(route)
    data = sd.play(data)

def on_wake_word():
    logger.info(
            "Wake word detected! Listening for command..."
        )
    play_sound()

@cache
def get_recorder() -> AudioToTextRecorder:
    """Initialize the continuous speech recognition and wake word engine."""
    logger.info("Initializing RealtimeSTT recorder with wake word 'jarvis'...")
    return AudioToTextRecorder(
        model="tiny",
        device="cuda",
        compute_type="int8",
        batch_size=1,
        wake_words="jarvis",
        wake_word_timeout=2,
        post_speech_silence_duration=0.2,
        wake_words_sensitivity=0.8,
        on_wakeword_detected=lambda: on_wake_word(),
        on_recording_stop=lambda: logger.info("stopped"),
        spinner=False,
    )
