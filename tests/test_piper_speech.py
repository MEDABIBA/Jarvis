import subprocess
import sys
from pathlib import Path
from threading import Event
from types import SimpleNamespace

import pytest

from jarvis.speech import piper
from jarvis.speech.types import AudioChunk, SpeechCancelled, SpeechError


@pytest.fixture
def fake_piper(tmp_path, monkeypatch):
    (tmp_path / "en.onnx").touch()
    (tmp_path / "pl.onnx").touch()
    state = SimpleNamespace(loads=[], chunks=0, closed=0, on_load=None, on_chunk=None)

    class Voice:
        @staticmethod
        def load(path):
            state.loads.append(path)
            if state.on_load:
                state.on_load()
            return Voice()

        def synthesize(self, text):
            state.text = text
            try:
                for data in [b"\x01\x00", b"\x02\x00", b"\x03\x00"]:
                    state.chunks += 1
                    if state.on_chunk:
                        state.on_chunk()
                    yield SimpleNamespace(
                        audio_int16_bytes=data, sample_rate=22050, sample_channels=1,
                    )
            finally:
                state.closed += 1

    monkeypatch.setitem(sys.modules, "piper", SimpleNamespace(PiperVoice=Voice))
    state.voice_type = Voice
    return state


@pytest.fixture
def clock(monkeypatch):
    now = [100.0]
    monkeypatch.setattr(piper, "monotonic", lambda: now[0])
    return now


def stream(provider, *, locale="en-GB", cancel=None, deadline=105):
    return provider.synthesize(
        "Hello.", locale, cancel=cancel if cancel is not None else Event(),
        deadline=deadline,
    )


def test_import_and_construction_need_no_optional_dependencies_or_cloud(tmp_path):
    # Fresh interpreter, not sys.modules polluted by fakes or other tests.
    script = '''
import importlib.abc
import sys
from pathlib import Path
class Guard(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, *args):
        if fullname.split('.')[0] in {'piper', 'numpy', 'sounddevice', 'azure', 'httpx'}:
            raise AssertionError('forbidden dependency: ' + fullname)
        if fullname in {'jarvis.core.config', 'jarvis.speech.azure', 'jarvis.speech.tts'}:
            raise AssertionError('forbidden integration: ' + fullname)
sys.meta_path.insert(0, Guard())
from jarvis.speech.piper import PiperProvider
from jarvis.speech.service import SpeechService
from jarvis.speech.text import SentenceBuffer, to_speech
provider = PiperProvider(Path(sys.argv[1]), {'en-GB': 'en.onnx'})
SpeechService([provider]).close()
'''
    result = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path)], capture_output=True,
        text=True, timeout=10,
    )
    assert result.returncode == 0, result.stderr


def test_exact_locale_loading_is_lazy_cached_and_incremental(tmp_path, fake_piper, clock):
    provider = piper.PiperProvider(tmp_path, {"en-GB": "en.onnx", "pl-PL": "pl.onnx"})
    assert fake_piper.loads == []
    iterator = stream(provider)
    assert fake_piper.loads == []
    assert next(iterator) == AudioChunk(b"\x01\x00", 22050)
    assert fake_piper.chunks == 1  # No list(voice.synthesize(...)).
    iterator.close()
    assert fake_piper.closed == 1
    assert len(list(stream(provider))) == 3
    assert fake_piper.loads == [tmp_path / "en.onnx"]
    assert len(list(stream(provider, locale="pl-PL"))) == 3
    assert fake_piper.loads == [tmp_path / "en.onnx", tmp_path / "pl.onnx"]


@pytest.mark.parametrize("locale", ["en-US", "en", "pl-PL", "EN-gb"])
def test_missing_exact_locale_never_chooses_another_voice(tmp_path, fake_piper, clock, locale):
    provider = piper.PiperProvider(tmp_path, {"en-GB": "en.onnx"})
    with pytest.raises(SpeechError, match="requested locale"):
        list(stream(provider, locale=locale))
    assert fake_piper.loads == []


def test_missing_model_is_speech_error_without_dependency_load(tmp_path, fake_piper, clock):
    provider = piper.PiperProvider(tmp_path, {"en-GB": "missing.onnx"})
    with pytest.raises(SpeechError, match="model is missing"):
        list(stream(provider))
    assert fake_piper.loads == []


def test_missing_dependency_is_speech_error(tmp_path, monkeypatch, clock):
    (tmp_path / "en.onnx").touch()
    monkeypatch.setitem(sys.modules, "piper", None)
    provider = piper.PiperProvider(tmp_path, {"en-GB": "en.onnx"})
    with pytest.raises(SpeechError, match="dependency is unavailable"):
        list(stream(provider))


@pytest.mark.parametrize("relative", ["../outside.onnx", "/tmp/outside.onnx", "nested/../../outside.onnx"])
def test_configured_model_cannot_escape_voices_directory(tmp_path, fake_piper, clock, relative):
    provider = piper.PiperProvider(tmp_path, {"en-GB": relative})
    with pytest.raises(SpeechError, match="inside voices directory"):
        list(stream(provider))
    assert fake_piper.loads == []


def test_symlink_cannot_escape_voices_directory(tmp_path, fake_piper, clock):
    (tmp_path / "voices").mkdir()
    (tmp_path / "voices" / "link.onnx").symlink_to(tmp_path / "en.onnx")
    provider = piper.PiperProvider(tmp_path / "voices", {"en-GB": "link.onnx"})
    with pytest.raises(SpeechError, match="inside voices directory"):
        list(stream(provider))
    assert fake_piper.loads == []


def test_pre_cancelled_wins_over_expired_deadline(tmp_path, fake_piper, clock):
    provider = piper.PiperProvider(tmp_path, {"en-GB": "en.onnx"})
    cancel = Event()
    cancel.set()
    with pytest.raises(SpeechCancelled):
        list(stream(provider, cancel=cancel, deadline=99))
    assert fake_piper.loads == []


def test_expired_deadline_does_not_load_model(tmp_path, fake_piper, clock):
    provider = piper.PiperProvider(tmp_path, {"en-GB": "en.onnx"})
    with pytest.raises(SpeechError, match="deadline"):
        list(stream(provider, deadline=99))
    assert fake_piper.loads == []


@pytest.mark.parametrize("cancelled", [True, False])
def test_checks_cancellation_and_deadline_after_model_load(tmp_path, fake_piper, clock, cancelled):
    cancel = Event()
    fake_piper.on_load = cancel.set if cancelled else lambda: clock.__setitem__(0, 106)
    provider = piper.PiperProvider(tmp_path, {"en-GB": "en.onnx"})
    with pytest.raises(SpeechCancelled if cancelled else SpeechError):
        list(stream(provider, cancel=cancel))
    assert fake_piper.chunks == 0


@pytest.mark.parametrize("cancelled", [True, False])
def test_checks_cancellation_and_deadline_after_first_chunk_inference(tmp_path, fake_piper, clock, cancelled):
    cancel = Event()
    fake_piper.on_chunk = cancel.set if cancelled else lambda: clock.__setitem__(0, 106)
    provider = piper.PiperProvider(tmp_path, {"en-GB": "en.onnx"})
    with pytest.raises(SpeechCancelled if cancelled else SpeechError):
        list(stream(provider, cancel=cancel))
    assert fake_piper.chunks == fake_piper.closed == 1


def test_cancel_between_chunks_stops_without_computing_next_chunk(tmp_path, fake_piper, clock):
    cancel = Event()
    provider = piper.PiperProvider(tmp_path, {"en-GB": "en.onnx"})
    iterator = stream(provider, cancel=cancel)
    next(iterator)
    cancel.set()
    with pytest.raises(SpeechCancelled):
        next(iterator)
    assert fake_piper.chunks == fake_piper.closed == 1


def test_first_audio_deadline_does_not_limit_full_sentence(tmp_path, fake_piper, clock):
    provider = piper.PiperProvider(tmp_path, {"en-GB": "en.onnx"})
    iterator = stream(provider)
    next(iterator)
    clock[0] = 1000
    assert len(list(iterator)) == 2


def test_empty_synthesis_is_failure(tmp_path, fake_piper, clock, monkeypatch):
    monkeypatch.setattr(fake_piper.voice_type, "synthesize", lambda *a: iter(()))
    provider = piper.PiperProvider(tmp_path, {"en-GB": "en.onnx"})
    with pytest.raises(SpeechError, match="no audio"):
        list(stream(provider))


def test_model_loading_and_synthesis_failures_are_sanitized(tmp_path, fake_piper, clock, monkeypatch):
    def fail(*args):
        raise RuntimeError("secret model path and raw input")

    monkeypatch.setattr(fake_piper.voice_type, "synthesize", fail)
    provider = piper.PiperProvider(tmp_path, {"en-GB": "en.onnx"})
    with pytest.raises(SpeechError, match="^Piper synthesis failed$"):
        list(stream(provider))
    monkeypatch.setattr(fake_piper.voice_type, "load", fail)
    provider = piper.PiperProvider(tmp_path, {"en-GB": "en.onnx"})
    with pytest.raises(SpeechError, match="could not be loaded"):
        list(stream(provider))


def test_provider_close_is_idempotent_clears_cache_and_stops_active_stream(tmp_path, fake_piper, clock):
    provider = piper.PiperProvider(tmp_path, {"en-GB": "en.onnx"})
    iterator = stream(provider)
    next(iterator)
    provider.close()
    provider.close()
    assert provider._cache == {}
    with pytest.raises(SpeechCancelled):
        next(iterator)
    assert fake_piper.closed == 1
    with pytest.raises(SpeechCancelled):
        list(stream(provider))


def test_source_generator_close_failure_does_not_mask_cancellation(tmp_path, fake_piper, clock, monkeypatch):
    class Source:
        def __iter__(self):
            return self

        def __next__(self):
            return SimpleNamespace(audio_int16_bytes=b"\0\0", sample_rate=22050)

        def close(self):
            raise RuntimeError("close failed")

    monkeypatch.setattr(fake_piper.voice_type, "synthesize", lambda *a: Source())
    provider = piper.PiperProvider(tmp_path, {"en-GB": "en.onnx"})
    cancel = Event()
    iterator = stream(provider, cancel=cancel)
    assert next(iterator) == AudioChunk(b"\0\0", 22050)
    cancel.set()
    with pytest.raises(SpeechCancelled):
        next(iterator)
