from prompt_toolkit.key_binding import KeyBindings
from RealtimeSTT.audio_recorder import AudioToTextRecorder

from jarvis.core.state import state


def make_bindings(recorder: AudioToTextRecorder) -> KeyBindings:
    """Construct global runtime hotkeys for interactive console control."""
    bindings = KeyBindings()

    @bindings.add("f1")
    def _switch_model(event) -> None:
        new_model = state.cycle_model()
        state.support_tools = True
        print(f"\n[F1] Backend model changed to: {new_model}")

    @bindings.add("f2")
    def _switch_stt(event) -> None:
        is_active = state.toggle_stt()
        recorder.set_microphone(is_active)
        print(f"\n[F2] Microphone input: {'ON' if is_active else 'MUTED'}")

    @bindings.add("f3")
    def _switch_tts(event) -> None:
        is_active = state.toggle_tts()
        print(f"\n[F3] Voice output synthesis: {'ON' if is_active else 'MUTED'}")

    return bindings
