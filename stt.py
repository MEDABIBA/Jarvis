from RealtimeSTT.audio_recorder import AudioToTextRecorder
from functools import cache

@cache
def get_recorder() -> AudioToTextRecorder:
    return AudioToTextRecorder(
        model="small",
        device="cpu",
        compute_type="int8",
        batch_size=1,
        wake_words="jarvis",
        wake_word_timeout=5,
        post_speech_silence_duration=2,
        wake_words_sensitivity=1,
        on_wakeword_detected=lambda: print("I`m listening"),
        spinner=False,
    )