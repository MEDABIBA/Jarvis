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

    @bindings.add("f1")
    def switch_model(event):
        """Change the available LLM"""
        if len(state.available_models) == 1:
            print("The LLM`s is not connected to the application, try to adding the LLM`s API")
            return
        index = state.available_models.index(state.model)
        model = state.available_models[index + 1]  if len(state.available_models) - 1 > index else state.available_models[0]
        state.model = model
        print(f"Model is switched to the {model} model")

    return bindings