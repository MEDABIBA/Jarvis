from threading import Event

import pytest

from jarvis.speech import service
from jarvis.speech.types import AudioChunk, SpeechCancelled, SpeechError, SpeechTurn

PCM = AudioChunk(b"\x01\x00", 22050)


class Provider:
    def __init__(self, name="sdk", group="azure", items=(PCM,), action=None):
        self.name = name
        self.group = group
        self.items = items
        self.action = action
        self.calls = []
        self.stream_closed = 0
        self.closed = 0
        self.close_error = False

    def synthesize(self, text, locale, *, cancel, deadline):
        self.calls.append((text, locale, deadline))
        try:
            if self.action:
                self.action()
            for item in self.items:
                if isinstance(item, Exception):
                    raise item
                yield item
        finally:
            self.stream_closed += 1
            if self.close_error:
                raise RuntimeError("private cleanup detail")

    def close(self):
        self.closed += 1
        if self.close_error:
            raise RuntimeError("private close detail")


def speak(svc, turn=None, cancel=None, locale="en-GB", text="Hello."):
    return list(svc.synthesize(
        text, locale, cancel=cancel if cancel is not None else Event(),
        turn=turn if turn is not None else SpeechTurn(),
    ))


@pytest.fixture
def clock(monkeypatch):
    now = [100.0]
    monkeypatch.setattr(service, "monotonic", lambda: now[0])
    return now


def test_provider_error_falls_back_to_rest_and_pins_turn(clock):
    sdk = Provider(items=(SpeechError("SDK unavailable"),))
    rest = Provider("rest")
    local = Provider("piper", "local")
    svc = service.SpeechService([sdk, rest, local])
    turn = SpeechTurn()
    assert speak(svc, turn) == [PCM]
    assert turn == SpeechTurn(started=True, provider="rest")
    clock[0] += 100
    assert speak(svc, turn, text="Next sentence.") == [PCM]
    assert len(sdk.calls) == 1
    assert len(rest.calls) == 2
    assert not local.calls
    assert sdk.stream_closed == 1


@pytest.mark.parametrize("scope", ["provider", "azure"])
def test_azure_group_scope_and_locale_cooldowns(clock, scope):
    sdk = Provider(items=(SpeechError("unavailable", scope=scope),))
    rest = Provider("rest")
    local = Provider("piper", "local")
    svc = service.SpeechService([sdk, rest, local])
    speak(svc, locale="pl-PL")
    assert len(rest.calls) == (1 if scope == "provider" else 0)
    speak(svc, locale="pl-PL")
    assert len(sdk.calls) == 1
    speak(svc, locale="en-GB")
    assert len(sdk.calls) == (2 if scope == "provider" else 1)
    clock[0] = 131
    speak(svc, locale="pl-PL")
    assert len(sdk.calls) == (3 if scope == "provider" else 2)


@pytest.mark.parametrize("scope", ["provider", "azure"])
def test_retry_after_extends_cooldown_without_sleep(clock, scope):
    sdk = Provider(items=(SpeechError("limited", scope=scope, retry_after=90),))
    local = Provider("piper", "local")
    svc = service.SpeechService([sdk, local], cooldown=30)
    speak(svc)
    clock[0] = 140
    speak(svc)
    assert len(sdk.calls) == 1
    clock[0] = 191
    speak(svc)
    assert len(sdk.calls) == 2


@pytest.mark.parametrize("retry", [None, -1, float("nan"), float("inf"), 2])
def test_bad_or_short_retry_metadata_does_not_shorten_cooldown(clock, retry):
    sdk = Provider(items=(SpeechError("bad", retry_after=retry),))
    local = Provider("piper", "local")
    svc = service.SpeechService([sdk, local])
    speak(svc)
    clock[0] = 129
    speak(svc)
    assert len(sdk.calls) == 1
    clock[0] = 131
    speak(svc)
    assert len(sdk.calls) == 2


def test_cloud_deadline_is_shared(clock):
    sdk = Provider(items=(SpeechError("SDK"),), action=lambda: clock.__setitem__(0, 103))
    rest = Provider("rest")
    svc = service.SpeechService([sdk, rest], first_audio_timeout=5)
    assert speak(svc) == [PCM]
    assert sdk.calls[0][2] == rest.calls[0][2] == 105


def test_expired_cloud_budget_still_allows_fresh_local_deadline(clock):
    sdk = Provider(items=(SpeechError("SDK"),), action=lambda: clock.__setitem__(0, 106))
    rest = Provider("rest")
    local = Provider("piper", "local")
    svc = service.SpeechService([sdk, rest, local], first_audio_timeout=5)
    assert speak(svc) == [PCM]
    assert sdk.calls[0][2] == 105
    assert not rest.calls
    assert local.calls[0][2] == 111


def test_late_first_audio_is_rejected_but_later_audio_is_not_timed_out(clock):
    late = Provider(action=lambda: clock.__setitem__(0, 106))
    local = Provider("piper", "local", items=(PCM, PCM))
    turn = SpeechTurn()
    stream = service.SpeechService([late, local]).synthesize(
        "Hello.", "en-GB", cancel=Event(), turn=turn,
    )
    assert next(stream) == PCM
    assert turn.provider == "piper"
    clock[0] = 1000
    assert list(stream) == [PCM]


@pytest.mark.parametrize("failure", [SpeechError("failed"), RuntimeError("secret")])
def test_error_after_any_audio_never_replays_and_disables_turn(failure):
    sdk = Provider(items=(PCM, failure))
    rest = Provider("rest")
    svc = service.SpeechService([sdk, rest])
    turn = SpeechTurn()
    stream = svc.synthesize("First.", "en-GB", cancel=Event(), turn=turn)
    assert next(stream) == PCM
    with pytest.raises(SpeechError):
        next(stream)
    assert turn.started and turn.failed
    assert not rest.calls
    assert speak(svc, turn, text="Second.") == []
    assert len(sdk.calls) == 1
    assert sdk.stream_closed == 1


def test_second_sentence_failure_does_not_switch_provider_or_replay():
    sdk = Provider()
    rest = Provider("rest")
    svc = service.SpeechService([sdk, rest])
    turn = SpeechTurn()
    assert speak(svc, turn) == [PCM]
    sdk.items = (SpeechError("second sentence failed"),)
    with pytest.raises(SpeechError):
        speak(svc, turn, text="Second.")
    assert turn.failed
    assert not rest.calls


def test_pinned_provider_on_cooldown_never_switches(clock):
    sdk = Provider()
    rest = Provider("rest")
    svc = service.SpeechService([sdk, rest])
    old = SpeechTurn()
    speak(svc, old)
    sdk.items = (SpeechError("bad locale"),)
    speak(svc)  # An independent turn puts SDK on cooldown.
    with pytest.raises(SpeechError):
        speak(svc, old, text="Next.")
    assert old.failed
    assert len(rest.calls) == 1


@pytest.mark.parametrize("items", [(), (AudioChunk(b"", 22050),)])
def test_empty_audio_falls_back(items):
    sdk = Provider(items=items)
    local = Provider("piper", "local")
    turn = SpeechTurn()
    assert speak(service.SpeechService([sdk, local]), turn) == [PCM]
    assert turn.provider == "piper"


@pytest.mark.parametrize("chunk", [
    b"not an audio chunk", AudioChunk(b"x", 22050), AudioChunk(b"xx", 0),
    AudioChunk(b"xx", 22050, 0), AudioChunk(b"xx", 22050, 2),
])
def test_invalid_first_pcm_does_not_start_turn(chunk):
    sdk = Provider(items=(chunk,))
    local = Provider("piper", "local")
    turn = SpeechTurn()
    assert speak(service.SpeechService([sdk, local]), turn) == [PCM]
    assert turn.provider == "piper"


def test_unexpected_exception_is_sanitized_and_provider_scoped(caplog):
    sdk = Provider(items=(RuntimeError("secret-key private-text"),))
    rest = Provider("rest")
    assert speak(service.SpeechService([sdk, rest])) == [PCM]
    assert "secret-key" not in caplog.text and "private-text" not in caplog.text
    sdk = Provider(items=(PCM, RuntimeError("secret-key private-text")))
    with pytest.raises(SpeechError, match="^Speech provider failed$") as exc:
        speak(service.SpeechService([sdk]))
    assert exc.value.__suppress_context__


def test_pre_cancelled_makes_no_calls_and_never_falls_back():
    cancel = Event()
    cancel.set()
    sdk = Provider()
    local = Provider("piper", "local")
    with pytest.raises(SpeechCancelled):
        speak(service.SpeechService([sdk, local]), cancel=cancel)
    assert not sdk.calls and not local.calls


@pytest.mark.parametrize("items", [(SpeechCancelled(),), (PCM, SpeechCancelled())])
def test_provider_cancellation_closes_stream_no_fallback_or_cooldown(items):
    sdk = Provider(items=items)
    local = Provider("piper", "local")
    svc = service.SpeechService([sdk, local])
    with pytest.raises(SpeechCancelled):
        speak(svc)
    assert sdk.stream_closed == 1
    assert not local.calls
    sdk.items = (PCM,)
    assert speak(svc) == [PCM]
    assert len(sdk.calls) == 2


def test_cancel_set_during_provider_failure_wins_without_fallback():
    cancel = Event()
    sdk = Provider(items=(SpeechError("failure"),), action=cancel.set)
    local = Provider("piper", "local")
    with pytest.raises(SpeechCancelled):
        speak(service.SpeechService([sdk, local]), cancel=cancel)
    assert not local.calls
    assert sdk.stream_closed == 1


def test_cancel_between_chunks_does_not_advance_provider():
    cancel = Event()
    advanced = []
    sdk = Provider()

    def source(*args, **kwargs):
        try:
            yield PCM
            advanced.append(True)
            yield PCM
        finally:
            sdk.stream_closed += 1

    sdk.synthesize = source
    local = Provider("piper", "local")
    turn = SpeechTurn()
    iterator = service.SpeechService([sdk, local]).synthesize(
        "Hello.", "en-GB", cancel=cancel, turn=turn,
    )
    assert next(iterator) == PCM
    cancel.set()
    with pytest.raises(SpeechCancelled):
        next(iterator)
    assert not advanced and not local.calls
    assert sdk.stream_closed == 1 and turn.failed


def test_empty_chunks_cannot_extend_first_audio_budget(clock):
    sdk = Provider()

    def source(*args, **kwargs):
        while True:
            clock[0] += 1
            yield AudioChunk(b"", 22050)

    sdk.synthesize = source
    local = Provider("piper", "local")
    turn = SpeechTurn()
    assert speak(service.SpeechService([sdk, local]), turn) == [PCM]
    assert clock[0] == 105
    assert turn.provider == "piper"


def test_explicit_generator_close_closes_provider_stream():
    sdk = Provider(items=(PCM, PCM))
    stream = service.SpeechService([sdk]).synthesize(
        "Hello.", "en-GB", cancel=Event(), turn=SpeechTurn(),
    )
    assert next(stream) == PCM
    stream.close()
    assert sdk.stream_closed == 1


def test_close_errors_never_mask_cancellation_or_stop_cleanup():
    sdk = Provider(items=(SpeechCancelled(),))
    sdk.close_error = True
    local = Provider("piper", "local")
    svc = service.SpeechService([sdk, sdk, local])
    # Provider's finally replaces cancellation with a cleanup error, but the
    # cancellation signal still takes precedence in the orchestrator.
    cancel = Event()
    sdk.action = cancel.set
    with pytest.raises(SpeechCancelled):
        speak(svc, cancel=cancel)
    svc.close()
    svc.close()
    assert sdk.closed == local.closed == 1
    with pytest.raises(SpeechCancelled):
        speak(svc)


def test_iterator_close_error_does_not_mask_success_or_original_failure():
    class Stream:
        def __init__(self, failure):
            self.failure = failure
            self.done = False

        def __iter__(self):
            return self

        def __next__(self):
            if self.failure:
                raise SpeechCancelled()
            if self.done:
                raise StopIteration
            self.done = True
            return PCM

        def close(self):
            raise RuntimeError("cleanup detail")

    sdk = Provider()
    sdk.synthesize = lambda *a, **kw: Stream(False)
    assert speak(service.SpeechService([sdk])) == [PCM]
    sdk.synthesize = lambda *a, **kw: Stream(True)
    with pytest.raises(SpeechCancelled):
        speak(service.SpeechService([sdk]))


def test_no_implicit_cloud_and_empty_configuration_is_text_only():
    local = Provider("piper", "local")
    svc = service.SpeechService([local])
    assert speak(svc) == [PCM]
    turn = SpeechTurn()
    with pytest.raises(SpeechError, match="No speech provider available"):
        speak(service.SpeechService([]), turn)
    assert turn.failed and not turn.started


def test_empty_text_does_not_fail_or_start_turn():
    sdk = Provider()
    turn = SpeechTurn()
    assert speak(service.SpeechService([sdk]), turn, text=" \n") == []
    assert turn == SpeechTurn()
    assert not sdk.calls


@pytest.mark.parametrize("kwargs", [
    {"first_audio_timeout": 0}, {"first_audio_timeout": -1},
    {"first_audio_timeout": float("inf")}, {"cooldown": -1},
    {"cooldown": float("nan")},
])
def test_invalid_budgets_are_rejected(kwargs):
    with pytest.raises(ValueError):
        service.SpeechService([], **kwargs)
