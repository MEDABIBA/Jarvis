from handle import handle
from tts import speak, speaking
from key_bindings import make_bindings
from state import state
from prompt_toolkit import PromptSession
from prompt_toolkit.patch_stdout import patch_stdout
from RealtimeSTT.audio_recorder import AudioToTextRecorder
from config import recorder
import queue as q
import threading

queue: q.Queue[str] = q.Queue()

session = PromptSession(key_bindings=make_bindings(recorder))

def input_loop():
    with patch_stdout():
        while True:
            text = session.prompt("> ")
            if text.strip():
                queue.put(text)


def voice_loop(recorder: AudioToTextRecorder):
    while True:
        text = recorder.text()
        if speaking.is_set():
            continue
        if isinstance(text, str) and text.strip():
            queue.put(text)


def main():

    threading.Thread(target=input_loop, daemon=True).start()
    threading.Thread(target=voice_loop, args=[recorder], daemon=True).start()

    try:
        while True:
            try:
                text = queue.get(timeout=0.5)
            except q.Empty:
                continue
            try:
                print("Let me think")
                prompt = {"role": "user", "content": text}
                res = handle(prompt)["message"]["content"]
                print("Jarvis: ", res)
                if state.tts and res:
                    speak(res)
            except Exception as e:
                print(f" Error: {e}")

    except KeyboardInterrupt:
        print("\nShutting down.")
    finally:
        recorder.shutdown()


if __name__ == "__main__":
    main()
