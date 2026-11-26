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
from jarvis.runtime import run_turn
from jarvis.speech.stt import get_recorder
from jarvis.speech.tts import get_speech_output, is_speaking
from jarvis.sql.history import get_database
from jarvis.tools.google.auth import google_auth
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
    speech = get_speech_output()
    turn_cancel = threading.Event()

    def cancel_current_turn() -> None:
        turn_cancel.set()
        speech.cancel()

    session: PromptSession = PromptSession(
        key_bindings=make_bindings(
            recorder, stop_speech=speech.cancel, cancel_turn=cancel_current_turn
        )
    )

    threading.Thread(target=input_loop, args=[session], daemon=True).start()
    threading.Thread(target=voice_loop, args=[recorder], daemon=True).start()

    # google authentication
    threading.Thread(target=google_auth, daemon=True).start()

    print("\nJarvis is ready! Speak ('jarvis ...') or type commands below.")
    print(
        "Hotkeys: F1 (Switch Model) | F2 (Toggle Mic) | "
        "F3 (Toggle Speech) | F4 (Cancel Reply)\n"
    )

    try:
        while True:
            try:
                text = task_queue.get()
            except q.Empty:
                continue

            print(f"\nUser: {text}")
            turn_cancel.clear()
            print("Jarvis: ", end="", flush=True)
            result = run_turn(
                engine,
                text,
                on_text=lambda delta: print(delta, end="", flush=True),
                cancel=turn_cancel,
                speech=speech
                if state.tts_enabled and settings.speech.provider != "text"
                else None,
                locale=settings.speech.locale,
            )
            if result is not None:
                get_database().push(result)
            else:
                print("\n[Reply cancelled]", end="")
            print("\n")

    except KeyboardInterrupt:
        logger.info("Shutdown requested by user.")
    except Exception as err:
        logger.error("Shutting down with error: {}", err)
    finally:
        speech.close()
        recorder.shutdown()
        logger.info("Jarvis stopped cleanly.")
        sys.exit(0)


if __name__ == "__main__":
    main()
