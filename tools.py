from config import SANDBOX, SKIP
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
import os

def get_time() -> list[str] | str:
    """Get the current local time. Call this when the user asks what time it is."""
    return str(datetime.now().astimezone())

def find_file(file_name: str) -> str | list[str]:
    """Find the full path of a file by its name.
    Call this when the user asks where a file is, or what path leads to it.
    Args:
        file_name: Exact file name with extension, e.g. 'jarvis.py'
    """
    matches: list[str] = []
    path = Path(SANDBOX).resolve()
    if not path.is_dir():
        return f"Configuration error: search root {path} does not exist"
    for root, _, files in os.walk(path):
        if any(part in SKIP for part in Path(root).parts):
            continue
        for f in files:
            if file_name.lower() in f.lower():
                matches.append(str(Path(root, f)))
    if not matches:
        return f"No files matching '{file_name}' found"
        
    return "\n".join(matches)

def read_file(file_name):
    pass

available_tools: list[Callable] = [get_time, find_file]
REGISTRY: dict[str, Callable] = {f.__name__: f for f in available_tools}