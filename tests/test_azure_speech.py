from threading import Event, Thread, current_thread
from time import monotonic
from types import SimpleNamespace
from xml.etree import ElementTree

import httpx
import pytest

from jarvis.speech import azure
from jarvis.speech.types import AudioChunk, SpeechCancelled, SpeechError

VOICES = {"en-US": "en-US-JennyNeural"}
PROVIDERS = [azure.AzureSdkProvider, azure.AzureRestProvider]


def synthesize(provider, *, cancel=None, deadline=None, text="Hello.", locale="en-US"):
    return provider.synthesize(
        text,
        locale,
        cancel=cancel if cancel is not None else Event(),
        deadline=deadline if deadline is not None else monotonic() + 2,
    )


class BytesStream(httpx.SyncByteStream):
    def __init__(self, chunks=(b"\x01\x00",), gate=None):
        self.chunks = chunks
        self.gate = gate
        self.entered = Event()
        self.closed = Event()
        self.finished = Event()

    def __iter__(self):
        self.entered.set()
        yield from self.chunks
        if self.gate is not None:
            assert self.gate.wait(3), "test stream was not released"
        self.finished.set()

    def close(self):
        self.closed.set()
        if self.gate is not None:
            self.gate.set()


def rest(
    monkeypatch,
    *,
    chunks=(b"\x01\x00",),
    status=200,
    headers=None,
    gate=None,
    handler=None,
):
    stream = BytesStream(chunks, gate)
    requests = []
    clients = []
    real_client = httpx.Client

    def handle(request):
        requests.append(request)
        if handler is not None:
            return handler(request)
        return httpx.Response(status, headers=headers, stream=stream)

    def client(**kwargs):
        instance = real_client(transport=httpx.MockTransport(handle), **kwargs)
        clients.append(instance)
        return instance

    monkeypatch.setattr(azure.httpx, "Client", client)
    provider = azure.AzureRestProvider("test-key", "eastus", VOICES)
    return provider, SimpleNamespace(stream=stream, requests=requests, clients=clients)


def sdk(
    monkeypatch,
    *,
    chunks=(b"\x01\x00",),
    gate=None,
    code=None,
    details="",
    failure=None,
):
    state = SimpleNamespace(
        entered=Event(),
        finished=Event(),
        stopped=Event(),
        connection_closed=Event(),
        chunks=chunks,
        ssml=[],
        writes=0,
        get_threads=[],
        configurations=[],
        stop_resolved=Event(),
        gate=gate,
    )

    class Config:
        def __init__(self, **kwargs):
            state.configurations.append(self)

        def set_speech_synthesis_output_format(self, value):
            state.format = value

    class OutputStream:
        def __init__(self, callback):
            self.callback = callback

    class Synthesizer:
        def __init__(self, *, speech_config, audio_config):
            self.callback = audio_config.stream.callback

        def speak_ssml_async(self, ssml):
            state.ssml.append(ssml)
            return SimpleNamespace(get=self.get)

        def get(self):
            state.get_threads.append(current_thread())
            state.entered.set()
            try:
                if failure is not None:
                    raise failure
                for data in chunks:
                    state.writes += 1
                    written = self.callback.write(memoryview(data))
                    if data and not written:
                        break
                if gate is not None:
                    assert gate.wait(3), "SDK was not stopped"
                return SimpleNamespace(
                    reason="completed" if code is None else "canceled",
                    cancellation_details=SimpleNamespace(
                        error_code=code,
                        error_details=details,
                    ),
                )
            finally:
                self.callback.close()
                state.finished.set()

        def stop_speaking_async(self):
            state.stopped.set()
            if gate is not None:
                gate.set()
            return SimpleNamespace(get=state.stop_resolved.set)

    module = SimpleNamespace(
        SpeechConfig=Config,
        SpeechSynthesizer=Synthesizer,
        SpeechSynthesisOutputFormat=SimpleNamespace(Raw24Khz16BitMonoPcm="raw24"),
        ResultReason=SimpleNamespace(SynthesizingAudioCompleted="completed"),
        audio=SimpleNamespace(
            PushAudioOutputStreamCallback=object,
            PushAudioOutputStream=OutputStream,
            AudioOutputConfig=lambda **kwargs: SimpleNamespace(**kwargs),
        ),
        Connection=SimpleNamespace(
            from_speech_synthesizer=lambda synth: SimpleNamespace(
                close=state.connection_closed.set
            )
        ),
    )
    real_import = azure.importlib.import_module

    def import_module(name, *args, **kwargs):
        if name == "azure.cognitiveservices.speech":
            return module
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(azure.importlib, "import_module", import_module)
    return azure.AzureSdkProvider("test-key", "eastus", VOICES), state


def assert_worker_stopped(provider):
    provider._worker.join(1)
    assert not provider._worker.is_alive()


@pytest.mark.parametrize("provider_type", PROVIDERS)
@pytest.mark.parametrize(
    "region",
    [
        "",
        "eastus/path",
        "eastus.example",
        "eastus@evil",
        "eastus?x",
        "eastus\n",
        "éastus",
    ],
)
def test_rejects_region_url_injection(provider_type, region):
    with pytest.raises(SpeechError) as error:
        provider_type("key", region, VOICES)
    assert error.value.scope == "provider"


@pytest.mark.parametrize("provider_type", PROVIDERS)
def test_construction_is_offline_and_sdk_lazy(monkeypatch, provider_type):
    def forbidden(*args, **kwargs):
        raise AssertionError("constructor attempted I/O or SDK import")

    real_import = azure.importlib.import_module

    def no_sdk(name, *args, **kwargs):
        if name == "azure.cognitiveservices.speech":
            forbidden()
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(azure.importlib, "import_module", no_sdk)
    monkeypatch.setattr(httpx.Client, "send", forbidden)
    provider = provider_type("key", "east-us2", VOICES)
    assert provider.group == "azure"
    assert provider.name in ("azure_sdk", "azure_rest")
    provider.close()
    provider.close()


@pytest.mark.parametrize(
    "failure", [ImportError("not installed"), OSError("native missing")]
)
def test_missing_sdk_is_provider_error_and_constructor_succeeds(monkeypatch, failure):
    provider = azure.AzureSdkProvider("secret-key", "eastus", VOICES)

    def unavailable(*args, **kwargs):
        raise failure

    monkeypatch.setattr(azure.importlib, "import_module", unavailable)
    with pytest.raises(SpeechError) as error:
        list(synthesize(provider))
    assert error.value.scope == "provider"
    assert str(failure) not in str(error.value)
    provider.close()


@pytest.mark.parametrize("provider_type", PROVIDERS)
@pytest.mark.parametrize("locale", ["en", "en-us", "fr-FR", ""])
def test_locale_is_exact_and_missing_never_uses_default(provider_type, locale):
    provider = provider_type("key", "eastus", VOICES)
    try:
        with pytest.raises(SpeechError) as error:
            list(synthesize(provider, locale=locale))
        assert error.value.scope == "provider"
        assert provider._worker is None
    finally:
        provider.close()


@pytest.mark.parametrize("factory", [sdk, rest])
def test_audio_arrives_before_finish_and_generator_close_cleans_up(
    monkeypatch, factory
):
    gate = Event()
    provider, state = factory(monkeypatch, gate=gate)
    iterator = synthesize(provider)
    assert next(iterator) == AudioChunk(b"\x01\x00", 24000, 1)
    finished = state.finished if factory is sdk else state.stream.finished
    assert not finished.is_set()
    if factory is sdk:
        assert state.get_threads[0] is not current_thread()
        assert state.format == "raw24"
    iterator.close()
    assert_worker_stopped(provider)
    if factory is sdk:
        assert state.stopped.is_set()
        assert state.stop_resolved.is_set()
        assert state.connection_closed.is_set()
    else:
        assert state.stream.closed.is_set()
    provider.close()


@pytest.mark.parametrize("factory", [sdk, rest])
def test_plain_text_and_voice_are_xml_escaped(monkeypatch, factory):
    provider, state = factory(monkeypatch)
    voice = "voice\" & <tag> 'quoted'"
    provider._voices["en-US"] = voice
    text = '<break time="9s"/> & café > "quoted"'
    list(synthesize(provider, text=text))
    document = state.ssml[0] if factory is sdk else state.requests[0].content
    root = ElementTree.fromstring(document)
    assert root.attrib["{http://www.w3.org/XML/1998/namespace}lang"] == "en-US"
    (child,) = root
    assert child.attrib["name"] == voice
    assert child.text == text
    assert list(child) == []
    provider.close()


@pytest.mark.parametrize("status", [401, 403, 429, 503])
def test_rest_shared_failures_skip_all_azure_and_do_not_expose_response(
    monkeypatch, status
):
    provider, state = rest(
        monkeypatch,
        status=status,
        headers={"Retry-After": "17", "secret": "private"},
        chunks=(b"sensitive response text",),
    )
    with pytest.raises(SpeechError) as error:
        list(synthesize(provider))
    assert error.value.scope == "azure"
    assert error.value.retry_after == (17 if status == 429 else None)
    assert str(error.value) == f"Azure speech HTTP {status}"
    assert not state.stream.entered.is_set()
    assert state.stream.closed.is_set()
    provider.close()


@pytest.mark.parametrize(
    "header, expected",
    [
        ("0", 0),
        ("1.5", 1.5),
        ("-1", None),
        ("nan", None),
        ("inf", None),
        ("not-a-number", None),
        (None, None),
    ],
)
def test_retry_after_metadata_without_sleep(monkeypatch, header, expected):
    provider, _ = rest(
        monkeypatch,
        status=429,
        headers={"Retry-After": header} if header is not None else {},
    )
    with pytest.raises(SpeechError) as error:
        list(synthesize(provider))
    assert error.value.retry_after == expected
    provider.close()


@pytest.mark.parametrize(
    "code",
    [
        "AuthenticationFailure",
        "ConnectionFailure",
        "TooManyRequests",
        "ServiceTimeout",
        "ServiceError",
    ],
)
def test_sdk_shared_error_codes(monkeypatch, code):
    provider, state = sdk(
        monkeypatch, chunks=(), code=code, details="secret key and private request"
    )
    with pytest.raises(SpeechError) as error:
        list(synthesize(provider))
    assert error.value.scope == "azure"
    assert "secret" not in str(error.value)
    assert "private" not in str(error.value)
    assert state.connection_closed.is_set()
    provider.close()


@pytest.mark.parametrize("details", ["HTTP 401", "status 429", "HTTP 503"])
def test_sdk_http_status_in_details_is_shared(monkeypatch, details):
    provider, _ = sdk(monkeypatch, chunks=(), code="Unknown", details=details)
    with pytest.raises(SpeechError) as error:
        list(synthesize(provider))
    assert error.value.scope == "azure"
    provider.close()


def test_sdk_retry_after_is_sanitized_cooldown_metadata(monkeypatch):
    provider, _ = sdk(
        monkeypatch,
        chunks=(),
        code="TooManyRequests",
        details="HTTP 429; Retry-After: 23; SECRET",
    )
    with pytest.raises(SpeechError) as error:
        list(synthesize(provider))
    assert error.value.scope == "azure"
    assert error.value.retry_after == 23
    assert "SECRET" not in str(error.value)
    provider.close()


def test_sdk_specific_failure_permits_rest_fallback(monkeypatch):
    provider, state = sdk(
        monkeypatch, failure=OSError("unsupported native library SECRET")
    )
    with pytest.raises(SpeechError) as error:
        list(synthesize(provider))
    assert error.value.scope == "provider"
    assert "SECRET" not in str(error.value)
    assert state.connection_closed.is_set()
    provider.close()


@pytest.mark.parametrize("factory", [sdk, rest])
@pytest.mark.parametrize("chunks", [(b"a", b"bc", b"d"), (b"", b"ab", b"cd")])
def test_pcm_samples_are_aligned_across_transport_chunks(monkeypatch, factory, chunks):
    provider, _ = factory(monkeypatch, chunks=chunks)
    audio = list(synthesize(provider))
    assert b"".join(chunk.data for chunk in audio) == b"abcd"
    assert all(len(chunk.data) % 2 == 0 and chunk.data for chunk in audio)
    assert all(chunk.sample_rate == 24000 and chunk.channels == 1 for chunk in audio)
    provider.close()


@pytest.mark.parametrize("factory", [sdk, rest])
def test_final_incomplete_pcm_sample_is_error(monkeypatch, factory):
    provider, _ = factory(monkeypatch, chunks=(b"abc",))
    iterator = synthesize(provider)
    assert next(iterator).data == b"ab"
    with pytest.raises(SpeechError, match="incomplete PCM"):
        next(iterator)
    assert_worker_stopped(provider)
    provider.close()


@pytest.mark.parametrize("factory", [sdk, rest])
def test_empty_audio_is_error(monkeypatch, factory):
    provider, _ = factory(monkeypatch, chunks=())
    with pytest.raises(SpeechError, match="no PCM"):
        list(synthesize(provider))
    provider.close()


@pytest.mark.parametrize("factory", [sdk, rest])
@pytest.mark.parametrize("action", ["cancel", "close", "deadline"])
def test_interrupts_blocked_first_audio_promptly(monkeypatch, factory, action):
    provider, state = factory(monkeypatch, chunks=(), gate=Event())
    cancel = Event()
    errors = []
    iterator = synthesize(
        provider,
        cancel=cancel,
        deadline=monotonic() + (0.15 if action == "deadline" else 2),
    )

    def consume():
        try:
            list(iterator)
        except Exception as exc:
            errors.append(exc)

    thread = Thread(target=consume)
    thread.start()
    entered = state.entered if factory is sdk else state.stream.entered
    assert entered.wait(1)
    start = monotonic()
    if action == "cancel":
        cancel.set()
    elif action == "close":
        provider.close()
    thread.join(1)
    assert not thread.is_alive()
    assert monotonic() - start < 1
    assert len(errors) == 1
    if action == "deadline":
        assert isinstance(errors[0], SpeechError)
        assert errors[0].scope == "azure"
    else:
        assert isinstance(errors[0], SpeechCancelled)
    assert_worker_stopped(provider)
    provider.close()


@pytest.mark.parametrize("factory", [sdk, rest])
def test_deadline_is_only_for_first_audio(monkeypatch, factory):
    provider, state = factory(monkeypatch, gate=Event())
    iterator = synthesize(provider, deadline=monotonic() + 1)
    next(iterator)
    # Advance the adapter's clock without slowing the test or altering threading.
    clock = monotonic() + 30
    monkeypatch.setattr(azure, "monotonic", lambda: clock)
    if factory is sdk:
        state.gate.set()
    else:
        state.stream.gate.set()
    assert list(iterator) == []
    provider.close()


@pytest.mark.parametrize("factory", [sdk, rest])
def test_pre_cancelled_wins_over_expired_deadline(monkeypatch, factory):
    provider, _ = factory(monkeypatch)
    cancel = Event()
    cancel.set()
    with pytest.raises(SpeechCancelled):
        list(synthesize(provider, cancel=cancel, deadline=monotonic() - 1))
    assert provider._worker is None
    provider.close()


@pytest.mark.parametrize("factory", [sdk, rest])
def test_full_queue_does_not_deadlock_on_close(monkeypatch, factory):
    provider, _ = factory(monkeypatch, chunks=(b"ab",) * 1000)
    iterator = synthesize(provider)
    next(iterator)
    limit = monotonic() + 1
    while provider._active.queue.qsize() < azure._QUEUE_SIZE and monotonic() < limit:
        Event().wait(0.005)
    assert provider._active.queue.full()
    iterator.close()
    assert_worker_stopped(provider)
    provider.close()


def test_rest_reuses_client_and_has_explicit_bounded_timeouts(monkeypatch):
    provider, state = rest(monkeypatch)
    list(synthesize(provider))
    list(synthesize(provider))
    assert len(state.clients) == 1
    assert len(state.requests) == 2
    request = state.requests[0]
    assert request.url == "https://eastus.tts.speech.microsoft.com/cognitiveservices/v1"
    assert request.headers["X-Microsoft-OutputFormat"] == "raw-24khz-16bit-mono-pcm"
    assert request.headers["Content-Type"] == "application/ssml+xml"
    assert request.extensions["timeout"] == {
        "connect": 5.0,
        "read": 10.0,
        "write": 5.0,
        "pool": 5.0,
    }
    provider.close()
    assert state.clients[0].is_closed


def test_rest_network_error_is_shared_and_sanitized(monkeypatch):
    def fail(request):
        raise httpx.ReadTimeout("SECRET response/key", request=request)

    provider, _ = rest(monkeypatch, handler=fail)
    with pytest.raises(SpeechError) as error:
        list(synthesize(provider))
    assert error.value.scope == "azure"
    assert "SECRET" not in str(error.value)
    provider.close()


@pytest.mark.parametrize("factory", [sdk, rest])
@pytest.mark.parametrize("action", ["cancel", "close"])
def test_cancel_after_first_audio_never_becomes_fallback(monkeypatch, factory, action):
    provider, _ = factory(monkeypatch, gate=Event())
    cancel = Event()
    iterator = synthesize(provider, cancel=cancel)
    next(iterator)
    if action == "cancel":
        cancel.set()
    else:
        provider.close()
    with pytest.raises(SpeechCancelled):
        next(iterator)
    assert_worker_stopped(provider)
    provider.close()


@pytest.mark.parametrize("factory", [sdk, rest])
def test_audio_read_stall_is_bounded_after_first_chunk(monkeypatch, factory):
    provider, _ = factory(monkeypatch, gate=Event())
    iterator = synthesize(provider)
    next(iterator)
    monkeypatch.setattr(azure, "_READ_TIMEOUT", 0.05)
    with pytest.raises(SpeechError, match="read timed out") as error:
        next(iterator)
    assert error.value.scope == "azure"
    assert_worker_stopped(provider)
    provider.close()


@pytest.mark.parametrize("factory", [sdk, rest])
def test_waiting_for_serial_call_obeys_deadline(monkeypatch, factory):
    provider, _ = factory(monkeypatch, gate=Event())
    iterator = synthesize(provider)
    next(iterator)
    worker = provider._worker
    with pytest.raises(SpeechError, match="deadline"):
        list(synthesize(provider, deadline=monotonic() + 0.05))
    assert provider._worker is worker
    iterator.close()
    assert_worker_stopped(provider)
    provider.close()


@pytest.mark.parametrize("factory", [sdk, rest])
def test_expired_deadline_does_not_start_request(monkeypatch, factory):
    provider, _ = factory(monkeypatch)
    with pytest.raises(SpeechError, match="deadline"):
        list(synthesize(provider, deadline=monotonic() - 1))
    assert provider._worker is None
    provider.close()


def test_rest_inflight_headers_cannot_accumulate_abandoned_workers(monkeypatch):
    entered, release = Event(), Event()

    def pending_headers(request):
        entered.set()
        assert release.wait(3)
        return httpx.Response(200, content=b"ab")

    provider, state = rest(monkeypatch, handler=pending_headers)
    try:
        with pytest.raises(SpeechError, match="deadline"):
            list(synthesize(provider, deadline=monotonic() + 0.1))
        assert entered.is_set()
        worker = provider._worker
        assert worker.is_alive()
        for _ in range(3):
            with pytest.raises(SpeechError, match="still stopping") as error:
                list(synthesize(provider))
            assert error.value.scope == "provider"
        assert provider._worker is worker
        assert len(state.requests) == 1
    finally:
        release.set()
        assert_worker_stopped(provider)
        provider.close()
