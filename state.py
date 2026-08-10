from dataclasses import dataclass


@dataclass
class State:
    tts: bool = True    # text to speech
    stt: bool = True    # speech to text


state = State()