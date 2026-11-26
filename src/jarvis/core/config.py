from functools import cache, cached_property
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, SecretStr, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict

from jarvis.llm.schemas import Provider


class SpeechSettings(BaseModel):
    provider: Literal["piper", "azure_sdk", "azure_rest", "text"] = "piper"
    locale: str = "en-GB"
    azure_key: SecretStr | None = None
    azure_region: str | None = Field(default=None, pattern=r"^[A-Za-z0-9-]+$")
    azure_voices: dict[str, str] = Field(
        default_factory=lambda: {
            "en-GB": "en-GB-RyanNeural",
            "pl-PL": "pl-PL-MarekNeural",
            "ru-RU": "ru-RU-DmitryNeural",
        }
    )
    piper_voices: dict[str, str] = Field(
        default_factory=lambda: {
            "en-GB": "EN/en_GB-northern_english_male-medium.onnx",
            "pl-PL": "PL/pl_PL-mc_speech-medium.onnx",
            "ru-RU": "RU/ru_RU-ruslan-medium.onnx",
        }
    )
    first_audio_timeout: float = Field(default=5, gt=0, le=30, allow_inf_nan=False)
    cooldown: float = Field(default=30, ge=0, allow_inf_nan=False)
    queue_size: int = Field(default=8, ge=1, le=64)
    max_segment_length: int = Field(default=300, ge=16, le=2000)


class AppSettings(BaseSettings):
    """Core application configuration settings.

    Loads environment variables prefixed with `JARVIS_` and handles credential
    management as well as dynamic discovery of available LLM backends.

    Attributes:
        debug: Toggles debug-level logging and detailed exception diagnostics.
        local_model: Model identifier or local path for the default offline LLM.
        sandbox: Working directory for sandboxed file and execution operations.
        anthropic_api_key: Optional API key for Anthropic Claude models.
        gemini_api_key: Optional API key for Google Gemini models.
        gpt_api_key: Optional API key for OpenAI GPT models.
        skip_dirs: Set of directory names to ignore during scanning and indexing.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="JARVIS_",
        env_nested_delimiter="__",
        case_sensitive=False,
        extra="ignore",
    )

    debug: bool = True
    sandbox: Path = Path("./sandbox")
    voices_dir: Path = Path("./voices")
    speech: SpeechSettings = Field(default_factory=SpeechSettings)

    anthropic_api_key: SecretStr | None = None
    gemini_api_key: SecretStr | None = None
    gpt_api_key: SecretStr | None = None
    cerebras_api_key: SecretStr | None = None

    local_model: SecretStr | None = None
    anthropic_model: SecretStr | None = None
    gemini_model: SecretStr | None = None
    gpt_model: SecretStr | None = None
    cerebras_model: SecretStr | None = None

    @cached_property
    def providers(self) -> dict[str, Provider]:
        return {
            "claude": Provider(
                model=self.anthropic_model.get_secret_value()
                if self.anthropic_model
                else "",
                protocol="anthropic",
                api_key=self.anthropic_api_key,
            ),
            "gemini": Provider(
                model=self.gemini_model.get_secret_value() if self.gemini_model else "",
                protocol="openai",
                api_key=self.gemini_api_key,
                gateway_url="https://generativelanguage.googleapis.com/v1beta/openai/",
            ),
            "gpt": Provider(
                model=self.gpt_model.get_secret_value() if self.gpt_model else "",
                protocol="openai",
                api_key=self.gpt_api_key,
                gateway_url="https://api.openai.com/v1",
            ),
            "cerebras": Provider(
                model=self.cerebras_model.get_secret_value()
                if self.cerebras_model
                else "",
                protocol="openai",
                api_key=self.cerebras_api_key,
                gateway_url="https://api.cerebras.ai/v1",
            ),
            "local": Provider(
                model=self.local_model.get_secret_value() if self.local_model else "",
                protocol="local",
            ),
        }

    skip_dirs: set[str] = {".venv", "__pycache__", ".git", "node_modules", ".vscode"}

    @computed_field
    @property
    def available_models(self) -> list[str]:
        """Dynamically determine accessible LLM providers based on active API keys.

        Always includes `'local'`. For cloud providers (`claude`, `gemini`, `gpt`),
        it verifies that the secret exists, is non-empty, and does not contain
        generic placeholder text.

        Returns:
            list[str]: Identifier list of all active model providers (e.g. `["local", "claude"]`).
        """
        models: list[str] = ["local"]

        for model_name, data in self.providers.items():
            if data.api_key is None or not data.model:
                continue

            raw_val = data.api_key.get_secret_value()

            if not raw_val or "api-key" in raw_val.lower():
                continue

            models.append(model_name)

        return models


@cache
def get_settings() -> AppSettings:
    """Retrieve and cache the singleton instance of application settings.

    Subsequent invocations return the cached `AppSettings` instance to avoid
    re-reading environment variables or `.env` files on disk.

    Returns:
        AppSettings: The initialized and cached application configuration.
    """
    return AppSettings()  # pyright: ignore
