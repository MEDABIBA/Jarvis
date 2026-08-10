from RealtimeSTT.audio_recorder import AudioToTextRecorder
import os
from dotenv import load_dotenv

load_dotenv()

recorder = AudioToTextRecorder(
    model="small",
    device="cpu",
    compute_type="int8",
    batch_size=1,
    wake_words="jarvis",
    wake_word_timeout=5,
    post_speech_silence_duration=2,
    wake_words_sensitivity=1,
    on_wakeword_detected=lambda: print("I`m listening"),
    spinner=False
)

LLM_MODEL = os.environ["LLM_MODEL"]
if not LLM_MODEL:
    raise RuntimeError("LLM_MODEL is not set — add it to .env")

SANDBOX = os.environ["SANDBOX"]
SKIP: set[str] = {".venv", "__pycache__", ".git", "node_modules", ".vscode"}
