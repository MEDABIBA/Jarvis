import queue as q
import sys
import threading

from loguru import logger
from prompt_toolkit import PromptSession
from prompt_toolkit.patch_stdout import patch_stdout
from RealtimeSTT.audio_recorder import AudioToTextRecorder

from jarvis import __version__
from jarvis.core.config import get_settings
from jarvis.core.logging import setup_logging
from jarvis.core.state import state
from jarvis.engine import AssistantEngine
from jarvis.speech.stt import get_recorder
from jarvis.speech.tts import VOICE_CONFIG, get_voice, is_speaking, speak
from jarvis.ui.keybindings import make_bindings

task_queue: q.Queue[str] = q.Queue()


def input_loop(session: PromptSession) -> None:
    """Read terminal input line-by-line using prompt_toolkit."""
    with patch_stdout():
        while True:
            try:
                text = session.prompt("> ")
                if text and text.strip():
                    task_queue.put(text.strip())
            except (EOFError, KeyboardInterrupt):
                break


def voice_loop(recorder: AudioToTextRecorder) -> None:
    """Continuously poll audio transcription from RealtimeSTT."""
    while True:
        try:
            text = recorder.text()
            if is_speaking.is_set():
                continue
            if isinstance(text, str) and text.strip():
                logger.info("Captured voice input: '{}'", text)
                task_queue.put(text.strip())
        except Exception as err:
            logger.error("Error in voice capture loop: {}", err)


def main() -> None:
    setup_logging()
    settings = get_settings()

    settings.sandbox.mkdir(parents=True, exist_ok=True)
    logger.info("Starting Jarvis v{}", __version__)
    logger.info("[Sandbox: {}]", settings.sandbox.resolve())
    logger.info("Local model: {}", settings.providers["local"].model)

    recorder = get_recorder()
    engine = AssistantEngine()
    session: PromptSession = PromptSession(key_bindings=make_bindings(recorder))

    threading.Thread(target=input_loop, args=[session], daemon=True).start()
    threading.Thread(target=voice_loop, args=[recorder], daemon=True).start()

    # Warm up voices
    for voice in VOICE_CONFIG:
        threading.Thread(target=get_voice, args=[voice], daemon=True).start()

    print("\nJarvis is ready! Speak ('jarvis ...') or type commands below.")
    print("Hotkeys: F1 (Switch Model) | F2 (Toggle Mic) | F3 (Toggle Speech)\n")

    try:
        while True:
            try:
                text = task_queue.get()
            except q.Empty:
                continue

            print(f"\nUser: {text}")
            answer = engine.handle(text)
            print(f"Jarvis: {answer}\n")

            if state.tts_enabled and answer:
                speak(answer)

    except KeyboardInterrupt:
        logger.info("Shutdown requested by user.")
    finally:
        recorder.shutdown()
        logger.info("Jarvis stopped cleanly.")
        sys.exit(0)


if __name__ == "__main__":
    main()
