from pathlib import Path

from config import SANDBOX

ROOT = Path(SANDBOX).resolve()


def safe_path(path: str) -> Path:
    """Resolve a model-supplied path and keep it inside SANDBOX.

    Raises:
        ValueError: if the resolved path escapes the sandbox.
    """
    target = Path(path).resolve()
    if not target.is_relative_to(ROOT):
        raise ValueError(f"Path outside allowed directory: {path}")
    return target
