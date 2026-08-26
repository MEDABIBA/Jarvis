from pathlib import Path

from jarvis.core.config import get_settings


def safe_path(user_supplied_path: str | Path) -> Path:
    """Resolve and validate a path strictly inside the configured sandbox root.

    Raises:
        ValueError: If the target path escapes the sandbox boundary.
    """
    settings = get_settings()
    sandbox_root = settings.sandbox.resolve()

    target = (
        (sandbox_root / user_supplied_path).resolve()
        if not Path(user_supplied_path).is_absolute()
        else Path(user_supplied_path).resolve()
    )

    if not target.is_relative_to(sandbox_root):
        raise ValueError(
            f"Security violation: path '{user_supplied_path}' is outside sandbox '{sandbox_root}'"
        )

    return target
