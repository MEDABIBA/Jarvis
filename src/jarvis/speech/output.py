"""Bounded, best-effort speech output; cancellation never interrupts LLM text."""

from collections.abc import Callable
from contextlib import suppress
from queue import Empty, Full, Queue
from threading import Event, Lock, Thread
from typing import Protocol

from loguru import logger

from jarvis.speech.service import SpeechService
from jarvis.speech.text import SentenceBuffer, to_speech
from jarvis.speech.types import AudioChunk, SpeechCancelled, SpeechError, SpeechTurn

_POLL = 0.05


class Player(Protocol):
    """One owner calls write/finish; abort requests cancellation without waiting.

    The owner must finish after abort to release resources, without draining.
    """

    def write(self, chunk: AudioChunk, cancel: Event) -> None: ...
    def finish(self) -> None: ...
    def abort(self) -> None: ...


class SoundDevicePlayer:
    """Lazy PCM playback with owner-only native I/O and destruction.

    abort() only signals: even Pa_AbortStream may block or race other native calls.
    The owner closes on return from write(), or via finish() if it was idle.
    """

    def __init__(self) -> None:
        self._io_lock = Lock()
        self._stream = None
        self._format: tuple[int, int] | None = None
        self._aborted = Event()

    def _check(self, cancel: Event) -> None:
        if cancel.is_set():
            self.abort()
        if self._aborted.is_set():
            raise SpeechCancelled()

    def write(self, chunk: AudioChunk, cancel: Event) -> None:
        with self._io_lock:
            try:
                self._write(chunk, cancel)
            finally:
                if self._aborted.is_set():
                    with suppress(Exception):
                        self._finish()

    def _write(self, chunk: AudioChunk, cancel: Event) -> None:
        self._check(cancel)
        if not chunk.data:
            return
        frame_size = 2 * chunk.channels
        if chunk.sample_rate <= 0 or frame_size <= 0 or len(chunk.data) % frame_size:
            raise ValueError("Invalid playback PCM format")
        audio_format = (chunk.sample_rate, chunk.channels)
        if self._format != audio_format:
            self._finish()
        self._check(cancel)
        stream = self._stream
        if stream is None:
            import sounddevice

            stream = self._stream = sounddevice.RawOutputStream(
                samplerate=chunk.sample_rate, channels=chunk.channels, dtype="int16"
            )
            self._format = audio_format
            self._check(cancel)  # Cancellation may have happened during open.
            stream.start()
        # At most 20 ms of PCM per native write, without copying the whole chunk.
        size = max(1, chunk.sample_rate // 50) * frame_size
        data = memoryview(chunk.data)
        for offset in range(0, len(data), size):
            self._check(cancel)
            stream.write(data[offset : offset + size])
        self._check(cancel)

    def finish(self) -> None:
        with self._io_lock:
            self._finish()

    def _finish(self) -> None:
        stream, self._stream = self._stream, None
        if stream is None:
            return
        try:
            if self._aborted.is_set():
                stream.abort()
            else:
                stream.stop()
        finally:
            # Only the owner can reach this, after all native operations returned.
            stream.close()

    def abort(self) -> None:
        self._aborted.set()


class SpeechSession:
    """A fixed-locale turn. Feed/boundary/finish serialize; cancel is independent.

    done also means disabled/cancelled, not necessarily that native synthesis has
    returned. SpeechOutput separately tracks worker liveness before reusing service.
    """

    def __init__(self, output: "SpeechOutput", locale: str) -> None:
        self.done = Event()
        self.turn = SpeechTurn()
        self._output, self._locale = output, locale
        self._buffer = SentenceBuffer(output._max_length)
        self._queue: Queue[str] = Queue(output._queue_size)
        self._input_lock, self._player_lock = Lock(), Lock()
        self._cancelled, self._ending = Event(), Event()
        self._player: Player | None = None
        self._speaking = False
        self._thread: Thread | None = None

    def _enqueue(self, sentences: list[str], *, wait: bool = False) -> None:
        for sentence in sentences:
            while not self.done.is_set():
                try:
                    self._queue.put(
                        sentence, block=wait, timeout=_POLL if wait else None
                    )
                    break
                except Full:
                    if wait:
                        continue
                    self.cancel()
                    logger.warning(
                        "Speech queue full; continuing this turn as text only"
                    )
                    return

    def feed(self, delta: str) -> None:
        with self._input_lock:
            if not self.done.is_set() and not self._ending.is_set():
                self._enqueue(self._buffer.feed(delta))

    def boundary(self) -> None:
        with self._input_lock:
            if not self.done.is_set() and not self._ending.is_set():
                self._enqueue(self._buffer.flush())
                self._buffer = SentenceBuffer(self._output._max_length)

    def finish(self) -> None:
        with self._input_lock:
            if not self.done.is_set() and not self._ending.is_set():
                self._enqueue(self._buffer.flush(), wait=True)
                self._ending.set()
        if self._thread is not None:
            while self._thread.is_alive():
                self._thread.join(_POLL)
                if self._cancelled.is_set():
                    break

    def cancel(self) -> None:
        if self.done.is_set() and not self._cancelled.is_set():
            return
        self._cancelled.set()
        self.turn.failed = True
        self.done.set()
        with self._player_lock:
            if self._speaking:
                self._output._speaking.clear()
                self._speaking = False
            player, self._player = self._player, None
        if player is not None:
            with suppress(Exception):
                player.abort()

    def _clear_speaking(self) -> None:
        with self._player_lock:
            if self._speaking:
                self._output._speaking.clear()
                self._speaking = False

    def _run(self) -> None:
        player = None
        announced = False
        try:
            while not self._cancelled.is_set():
                try:
                    sentence = self._queue.get(timeout=_POLL)
                except Empty:
                    if self._ending.is_set() and self._queue.empty():
                        break
                    continue
                text = to_speech(sentence, self._locale)
                if not text:
                    continue
                if self._cancelled.is_set():
                    break
                stream = iter(
                    self._output._service.synthesize(
                        text, self._locale, cancel=self._cancelled, turn=self.turn
                    )
                )
                try:
                    for chunk in stream:
                        if self._cancelled.is_set():
                            raise SpeechCancelled()
                        if not chunk.data:
                            continue
                        if player is None:
                            player = self._output._player_factory()
                            with self._player_lock:
                                cancelled = self._cancelled.is_set()
                                if not cancelled:
                                    self._player = player
                            if cancelled:
                                with suppress(Exception):
                                    player.abort()
                                raise SpeechCancelled()
                        with self._player_lock:
                            if self._cancelled.is_set():
                                raise SpeechCancelled()
                            self._output._speaking.set()
                            self._speaking = True
                        if not announced:
                            logger.info("Speech provider: {}", self.turn.provider)
                            announced = True
                        player.write(chunk, self._cancelled)
                finally:
                    with suppress(Exception):
                        close = getattr(stream, "close", None)
                        if close is not None:
                            close()
                if player is not None and not self._cancelled.is_set():
                    player.finish()
                    self._clear_speaking()
        except SpeechCancelled:
            self.cancel()
        except SpeechError:
            logger.warning("Speech unavailable; continuing this turn as text only")
            self.cancel()
        except Exception:
            # Neither device errors nor cleanup errors may restart synthesis.
            # Exception messages can contain credentials or private response text.
            logger.warning("Speech output failed; continuing this turn as text only")
            self.cancel()
        finally:
            # cancel() relinquishes the UI reference, not this owner's reference.
            if player is not None and self._cancelled.is_set():
                with suppress(Exception):
                    player.finish()
            self._clear_speaking()
            self.done.set()


class SpeechOutput:
    def __init__(
        self,
        service: SpeechService,
        *,
        queue_size: int = 8,
        max_segment_length: int = 300,
        speaking: Event | None = None,
        player_factory: Callable[[], Player] = SoundDevicePlayer,
    ) -> None:
        if queue_size < 1:
            raise ValueError("queue_size must be positive")
        if max_segment_length < 16:
            raise ValueError("max_segment_length must be at least 16")
        self._service, self._player_factory = service, player_factory
        self._queue_size, self._max_length = queue_size, max_segment_length
        self._speaking = speaking if speaking is not None else Event()
        self._lock = Lock()
        self._current: SpeechSession | None = None
        self._worker: Thread | None = None
        self._closed = False

    def start(self, locale: str) -> SpeechSession:
        with self._lock:
            if self._current is not None:
                self._current.cancel()
            if self._worker is not None and self._worker.is_alive():
                self._worker.join(_POLL)
            session = SpeechSession(self, locale)
            self._current = session
            if self._closed or (self._worker is not None and self._worker.is_alive()):
                session.cancel()
                logger.warning("Speech worker unavailable; continuing as text only")
            else:
                worker = Thread(target=session._run, name="jarvis-speech", daemon=True)
                session._thread = self._worker = worker
                worker.start()
            return session

    def cancel(self) -> None:
        with self._lock:
            session = self._current
        if session is not None:
            session.cancel()

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            session, worker = self._current, self._worker
        if session is not None:
            session.cancel()
        if worker is not None:
            worker.join(_POLL)
        self._service.close()
