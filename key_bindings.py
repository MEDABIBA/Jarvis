from state import state
from RealtimeSTT.audio_recorder import AudioToTextRecorder
from prompt_toolkit.key_binding import KeyBindings

def make_bindings(recorder: AudioToTextRecorder):
    bindings = KeyBindings()
    
    @bindings.add("f3")
    def switch_tts(event):
        """Bind a key to switch the text-to-speech mode"""
        state.tts = not state.tts
        print(f"TTS is {'on' if state.tts else 'off'}")
    
    
    @bindings.add("f2")
    
    def switch_stt(event):
        """Bind a key to turn on/off your microphone"""
        state.stt = not state.stt
        recorder.set_microphone(state.stt)
        print(f"Microphone is {'on' if state.stt else 'off'}")

    return bindings