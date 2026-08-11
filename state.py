from dataclasses import dataclass
from config import available_models

@dataclass
class State:
    model: str = 'local'
    available_models = available_models()
    tts: bool = True    # text to speech
    stt: bool = True    # speech to text


state = State()