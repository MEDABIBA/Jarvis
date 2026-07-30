from handle import handle
from tts import speak, speaking
from RealtimeSTT.audio_recorder import AudioToTextRecorder
import queue as q
import threading

queue: q.Queue[str] = q.Queue()

tts_enabled = True  # Strict state, for replacement


def input_loop():
    while True:
        text = input("> ")
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
    recorder = AudioToTextRecorder(
        model="small",
        device="cpu",
        compute_type="int8",
        batch_size=1,
        wake_words="jarvis",
        wake_word_timeout=5,
        post_speech_silence_duration=2,
        wake_words_sensitivity=1,
        spinner=False,
    )

    threading.Thread(target=input_loop, daemon=True).start()
    threading.Thread(target=voice_loop, args=[recorder], daemon=True).start()

    try:
        while True:
            try:
                text = queue.get(timeout=0.5)
            except q.Empty:
                continue
            try:
                prompt = {"role": "user", "content": text}
                res = handle(prompt)["message"]["content"]
                print("Jarvis: ", res)
                if tts_enabled and res:
                    speak(res)
            except Exception as e:
                print(f" Error: {e}")

    except KeyboardInterrupt:
        print("\nShutting down.")
    finally:
        recorder.shutdown()


if __name__ == "__main__":
    main()
