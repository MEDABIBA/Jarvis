from RealtimeSTT.audio_recorder import AudioToTextRecorder
import os
from dotenv import load_dotenv
import anthropic
from functools import cache

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

MODEL_KEYS = {
    "local": None,
    "claude": "ANTHROPIC_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "gpt": "GPT_API_KEY",
}

def available_models() -> list[str]:
    res = []
    for name, env_var in MODEL_KEYS.items():
        if env_var is not None:
            value = os.environ.get(env_var, "").strip()
            if not value:
               continue  
            if "api-key" in value.lower():
                continue          
        res.append(name)
    return res

LOCAL_LLM = os.environ["LOCAL_LLM"]

SANDBOX = os.environ["SANDBOX"]

SKIP: set[str] = {".venv", "__pycache__", ".git", "node_modules", ".vscode"}

@cache
def claude_client():
    ANTHROPIC_API = os.environ["ANTHROPIC_API_KEY"]
    claude = anthropic.Anthropic(api_key=ANTHROPIC_API)
    return claude
