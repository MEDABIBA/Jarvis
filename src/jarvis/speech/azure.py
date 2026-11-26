"""Sentence-in/audio-stream-out Azure adapters; neither opens a speaker device.

Calls on one provider are serialized. Close a partially consumed iterator explicitly.
REST reuses a bounded connection pool. SDK synthesizers/connections are per sentence
so late native callbacks cannot reach the next sentence's queue. Native TextStream
input and speculative preconnection are deliberately not used.
"""

from __future__ import annotations

import importlib
import math
import re
from collections.abc import Callable, Iterator
from contextlib import suppress
from queue import Empty, Full, Queue
from threading import Event, Lock, Thread, current_thread
from time import monotonic
from xml.sax.saxutils import escape, quoteattr

import httpx

from jarvis.speech.types import AudioChunk, SpeechCancelled, SpeechError

_POLL = 0.05
_READ_TIMEOUT = 10.0
_JOIN_TIMEOUT = 0.25
_QUEUE_SIZE = 8
_BLOCK_SIZE = 4096


def _ssml(text: str, locale: str, voice: str) -> str:
    return (
        '<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" '
        f"xml:lang={quoteattr(locale)}><voice name={quoteattr(voice)}>"
        f"{escape(text)}</voice></speak>"
    )


def _retry_after(value: str | None) -> float | None:
    try:
        seconds = float(value) if value is not None else -1.0
    except ValueError:
        return None
    return seconds if math.isfinite(seconds) and seconds >= 0 else None


def _sdk_error(code: object = "", details: str = "") -> SpeechError:
    # Inspect only for classification. Never expose native error_details: they can
    # include subscription information, request text, URLs, or service headers.
    description = f"{code} {details}".lower()
    shared = (
        "authentication",
        "unauthorized",
        "forbidden",
        "connection",
        "toomanyrequests",
        "too many requests",
        "quota",
        "throttl",
        "serviceerror",
        "service error",
        "servicetimeout",
        "serviceunavailable",
        "service unavailable",
        "websocket",
        "timeout",
        "timed out",
    )
    if any(word in description for word in shared) or re.search(
        r"\b(?:401|403|408|429|5\d\d)\b", description
    ):
        retry = re.search(r"\bretry-after\s*[:=]\s*([0-9]+(?:\.[0-9]+)?)", description)
        return SpeechError(
            "Azure speech service failed",
            scope="azure",
            retry_after=_retry_after(retry.group(1)) if retry else None,
        )
    return SpeechError("Azure SDK synthesis failed", scope="provider")


class _Run:
    def __init__(self, cancel: Event) -> None:
        self.cancel = cancel
        self.stop = Event()
        self.finished = Event()
        self.queue: Queue[bytes] = Queue(maxsize=_QUEUE_SIZE)
        self.error: SpeechError | None = None
        self._lock = Lock()
        self._interrupt: Callable[[], object] | None = None

    def put(self, data: bytes) -> bool:
        # Bound bytes as well as queue length; callback buffers need not be small.
        for offset in range(0, len(data), _BLOCK_SIZE):
            while not self.stop.is_set() and not self.cancel.is_set():
                try:
                    self.queue.put(data[offset : offset + _BLOCK_SIZE], timeout=_POLL)
                    break
                except Full:
                    continue
            else:
                return False
        return True

    def interrupt_with(self, callback: Callable[[], object]) -> None:
        with self._lock:
            stopped = self.stop.is_set()
            if not stopped:
                self._interrupt = callback
        if stopped:
            with suppress(Exception):
                callback()

    def abort(self) -> None:
        with self._lock:
            self.stop.set()
            callback, self._interrupt = self._interrupt, None
            # Serialize interruption with worker cleanup: in particular, the SDK
            # worker must not miss a stop future still being created by close().
            if callback is not None:
                with suppress(Exception):
                    callback()


class _AzureProvider:
    group = "azure"
    name: str

    def __init__(self, key: str, region: str, voices: dict[str, str]) -> None:
        if not re.fullmatch(r"[A-Za-z0-9-]+", region):
            raise SpeechError("Invalid Azure speech region", scope="provider")
        self._key = key
        self._region = region
        self._voices = dict(voices)
        self._closed = Event()
        self._serial = Lock()
        self._state = Lock()
        self._active: _Run | None = None
        self._worker: Thread | None = None

    def _check(self, cancel: Event, deadline: float | None) -> None:
        if cancel.is_set() or self._closed.is_set():
            raise SpeechCancelled()
        if deadline is not None and monotonic() >= deadline:
            raise SpeechError(
                "Azure speech first-audio deadline exceeded", scope="azure"
            )

    def synthesize(
        self, text: str, locale: str, *, cancel: Event, deadline: float
    ) -> Iterator[AudioChunk]:
        self._check(cancel, deadline)
        voice = self._voices.get(locale)
        if not voice:
            raise SpeechError("No Azure voice for exact locale", scope="provider")
        while not self._serial.acquire(timeout=_POLL):
            self._check(cancel, deadline)
        run = _Run(cancel)
        worker = None
        try:
            self._check(cancel, deadline)
            ssml = _ssml(text, locale, voice)
            with self._state:
                self._check(cancel, deadline)
                # Python cannot kill a wedged native call or OS resolver. Never
                # accumulate abandoned workers on repeated fallback attempts.
                if self._worker is not None and self._worker.is_alive():
                    raise SpeechError("Previous Azure worker is still stopping")
                worker = Thread(
                    target=self._produce,
                    args=(run, ssml),
                    name=f"{self.name}-audio",
                    daemon=True,
                )
                self._active = run
                self._worker = worker
                worker.start()
            pending = b""
            started = False
            last_audio = monotonic()
            while True:
                self._check(cancel, None if started else deadline)
                try:
                    data = run.queue.get(timeout=_POLL)
                except Empty:
                    if run.finished.is_set():
                        # Producer can finish between get() and this check.
                        if not run.queue.empty():
                            continue
                        self._check(cancel, None if started else deadline)
                        if run.error is not None:
                            raise run.error from None
                        if pending:
                            raise SpeechError(
                                "Azure returned an incomplete PCM sample"
                            ) from None
                        if not started:
                            raise SpeechError(
                                "Azure returned no PCM audio", scope="azure"
                            ) from None
                        return
                    if started and monotonic() - last_audio >= _READ_TIMEOUT:
                        raise SpeechError(
                            "Azure audio read timed out", scope="azure"
                        ) from None
                    continue
                self._check(cancel, None if started else deadline)
                data = pending + data
                end = len(data) - len(data) % 2
                pending = data[end:]
                if end:
                    started = True
                    last_audio = monotonic()
                    yield AudioChunk(data=data[:end], sample_rate=24000)
                    # Consumer/playback time is not a provider read stall.
                    last_audio = monotonic()
        finally:
            run.abort()
            if worker is not None:
                worker.join(timeout=_JOIN_TIMEOUT)
            with self._state:
                if self._active is run:
                    self._active = None
            self._serial.release()

    def _produce(self, run: _Run, ssml: str) -> None:
        try:
            if not run.stop.is_set():
                self._request(run, ssml)
        except SpeechError as exc:
            run.error = exc
        except Exception:
            # Don't attach raw transport/native exceptions to the public error.
            run.error = SpeechError("Azure adapter failed", scope="provider")
        finally:
            run.finished.set()

    def _request(self, run: _Run, ssml: str) -> None:
        raise NotImplementedError

    def close(self) -> None:
        self._closed.set()
        with self._state:
            run, worker = self._active, self._worker
        if run is not None:
            run.abort()
        if worker is not None and worker is not current_thread():
            worker.join(timeout=_JOIN_TIMEOUT)


class AzureSdkProvider(_AzureProvider):
    """Lazy optional SDK, using a push stream and one bounded worker per call."""

    name = "azure_sdk"

    def _request(self, run: _Run, ssml: str) -> None:
        try:
            sdk = importlib.import_module("azure.cognitiveservices.speech")
        except Exception:
            raise SpeechError("Azure SDK or native dependencies unavailable") from None

        class Output(sdk.audio.PushAudioOutputStreamCallback):
            def write(self, audio_buffer: memoryview) -> int:
                data = bytes(audio_buffer)
                return len(data) if run.put(data) else 0

            def close(self) -> None:
                pass  # Completion belongs to the synthesis result, not stream close.

        synth = connection = future = stop_future = None
        stop_lock = Lock()

        def stop() -> None:
            nonlocal stop_future
            # Called outside a native audio callback; never wait here. The worker
            # resolves both futures to release their native async handles.
            with stop_lock:
                if synth is not None and stop_future is None:
                    try:
                        stop_future = synth.stop_speaking_async()
                    finally:
                        if connection is not None:
                            connection.close()

        try:
            config = sdk.SpeechConfig(subscription=self._key, region=self._region)
            config.set_speech_synthesis_output_format(
                sdk.SpeechSynthesisOutputFormat.Raw24Khz16BitMonoPcm
            )
            callback = Output()
            stream = sdk.audio.PushAudioOutputStream(callback)
            output = sdk.audio.AudioOutputConfig(stream=stream)
            synth = sdk.SpeechSynthesizer(speech_config=config, audio_config=output)
            connection = sdk.Connection.from_speech_synthesizer(synth)
            # Serialize start with stop so cancellation cannot race ahead of start.
            with stop_lock:
                if run.stop.is_set() or run.cancel.is_set():
                    return
                future = synth.speak_ssml_async(ssml)
            run.interrupt_with(stop)
            result = future.get()  # Only the worker waits; callbacks stream audio now.
            if run.stop.is_set() or run.cancel.is_set():
                return
            if result.reason != sdk.ResultReason.SynthesizingAudioCompleted:
                details = result.cancellation_details
                raise _sdk_error(details.error_code, details.error_details)
        except SpeechError:
            raise
        except Exception as exc:
            raise _sdk_error(details=str(exc)) from None
        finally:
            # abort() first releases a callback blocked on a full queue.
            run.abort()
            with stop_lock:
                stopping = stop_future
            if connection is not None:
                with suppress(Exception):
                    connection.close()
            if stopping is not None:
                with suppress(Exception):
                    stopping.get()


class AzureRestProvider(_AzureProvider):
    """Reusable HTTP client; cancellation closes the active streamed response."""

    name = "azure_rest"

    def __init__(self, key: str, region: str, voices: dict[str, str]) -> None:
        super().__init__(key, region, voices)
        self._client = httpx.Client(
            timeout=httpx.Timeout(_READ_TIMEOUT, connect=5.0, write=5.0, pool=5.0),
            limits=httpx.Limits(max_connections=1, max_keepalive_connections=1),
            follow_redirects=False,
        )
        self._url = f"https://{region}.tts.speech.microsoft.com/cognitiveservices/v1"

    def _request(self, run: _Run, ssml: str) -> None:
        try:
            with self._client.stream(
                "POST",
                self._url,
                headers={
                    "Ocp-Apim-Subscription-Key": self._key,
                    "Content-Type": "application/ssml+xml",
                    "X-Microsoft-OutputFormat": "raw-24khz-16bit-mono-pcm",
                    "User-Agent": "jarvis-speech",
                },
                content=ssml.encode("utf-8"),
            ) as response:
                run.interrupt_with(response.close)
                if run.stop.is_set() or run.cancel.is_set():
                    return
                if response.status_code != 200:
                    status = response.status_code
                    shared = status in (401, 403, 408, 429) or status >= 500
                    raise SpeechError(
                        f"Azure speech HTTP {status}",
                        scope="azure" if shared else "provider",
                        retry_after=_retry_after(response.headers.get("Retry-After"))
                        if status == 429
                        else None,
                    )
                for data in response.iter_bytes():
                    if not run.put(data):
                        return
        except httpx.RequestError:
            raise SpeechError("Azure speech network failure", scope="azure") from None
        finally:
            run.abort()

    def close(self) -> None:
        super().close()
        with suppress(Exception):
            self._client.close()
