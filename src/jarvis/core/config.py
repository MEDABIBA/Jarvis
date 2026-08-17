from functools import cache
from pathlib import Path

from pydantic import SecretStr, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="JARVIS_",
        env_nested_delimiter="__",
        case_sensitive=False,
        extra="ignore",
    )

    debug: bool = True
    local_llm: str
    sandbox: Path = Path("./sandbox")

    anthropic_api_key: SecretStr | None = None
    gemini_api_key: SecretStr | None = None
    gpt_api_key: SecretStr | None = None

    skip_dirs: set[str] = {".venv", "__pycache__", ".git", "node_modules", ".vscode"}

    @computed_field
    @property
    def available_models(self) -> list[str]:
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
    return AppSettings()
