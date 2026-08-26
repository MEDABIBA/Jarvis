from functools import cache
from pathlib import Path

from pydantic import SecretStr, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppSettings(BaseSettings):
    """Core application configuration settings.

    Loads environment variables prefixed with `JARVIS_` and handles credential
    management as well as dynamic discovery of available LLM backends.

    Attributes:
        debug: Toggles debug-level logging and detailed exception diagnostics.
        local_llm: Model identifier or local path for the default offline LLM.
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
    local_llm: str = "mistral"
    sandbox: Path = Path("./sandbox")
    voices_dir: Path = Path("./voices")

    anthropic_api_key: SecretStr | None = None
    gemini_api_key: SecretStr | None = None
    gpt_api_key: SecretStr | None = None

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

        key_mappings: dict[str, SecretStr | None] = {
            "claude": self.anthropic_api_key,
            "gemini": self.gemini_api_key,
            "gpt": self.gpt_api_key,
        }

        for model_name, secret in key_mappings.items():
            if secret is None:
                continue

            raw_val = secret.get_secret_value().strip()

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
    return AppSettings()
