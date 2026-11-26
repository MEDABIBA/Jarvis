from threading import Event
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from jarvis.core.config import AppSettings, SpeechSettings
from jarvis.speech.factory import build_speech_service
from jarvis.speech.types import SpeechError, SpeechTurn


def test_nested_environment(monkeypatch):
    monkeypatch.setenv("JARVIS_SPEECH__PROVIDER", "azure_rest")
    monkeypatch.setenv("JARVIS_SPEECH__LOCALE", "pl-PL")
    monkeypatch.setenv("JARVIS_SPEECH__AZURE_KEY", "test-key")
    monkeypatch.setenv("JARVIS_SPEECH__AZURE_REGION", "westeurope")
    monkeypatch.setenv("JARVIS_SPEECH__AZURE_VOICES", '{"de-DE":"test-voice"}')
    speech = AppSettings(_env_file=None).speech
    assert speech.provider == "azure_rest"
    assert speech.locale == "pl-PL"
    assert speech.azure_voices == {"de-DE": "test-voice"}
    assert "test-key" not in repr(speech)


@pytest.mark.parametrize("provider", ["piper", "text"])
def test_offline_modes_never_construct_azure(provider):
    settings = AppSettings(_env_file=None, speech=SpeechSettings(provider=provider))
    with patch("jarvis.speech.azure.AzureRestProvider") as rest:
        with patch("jarvis.speech.azure.AzureSdkProvider") as sdk:
            service = build_speech_service(settings)
            service.close()
    rest.assert_not_called()
    sdk.assert_not_called()


def test_missing_azure_configuration_uses_local_only():
    settings = AppSettings(_env_file=None, speech={"provider": "azure_sdk"})
    with patch("jarvis.speech.factory.PiperProvider") as piper:
        service = build_speech_service(settings)
        service.close()
    piper.assert_called_once_with(settings.voices_dir, settings.speech.piper_voices)


def test_azure_order_and_close():
    settings = AppSettings(
        _env_file=None,
        speech={"provider": "azure_sdk", "azure_key": "test", "azure_region": "eastus"},
    )
    with (
        patch("jarvis.speech.azure.AzureSdkProvider") as sdk,
        patch("jarvis.speech.azure.AzureRestProvider") as rest,
        patch("jarvis.speech.factory.PiperProvider") as piper,
    ):
        service = build_speech_service(settings)
        assert service._providers == (
            sdk.return_value,
            rest.return_value,
            piper.return_value,
        )
        service.close()
        for provider in (sdk, rest, piper):
            provider.return_value.close.assert_called_once()


def test_text_mode_reports_no_audio_without_loading_models():
    service = build_speech_service(
        AppSettings(_env_file=None, speech={"provider": "text"})
    )
    with pytest.raises(SpeechError):
        list(
            service.synthesize("Text only", "en-GB", cancel=Event(), turn=SpeechTurn())
        )
    service.close()


@pytest.mark.parametrize(
    "values",
    [
        {"provider": "unknown"},
        {"first_audio_timeout": 0},
        {"first_audio_timeout": float("inf")},
        {"cooldown": -1},
        {"queue_size": 0},
        {"max_segment_length": 10},
        {"azure_region": "host.example/path"},
    ],
)
def test_invalid_settings(values):
    with pytest.raises(ValidationError):
        SpeechSettings(**values)
