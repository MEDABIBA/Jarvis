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
    Call this FIRST whenever the user mentions a file but does not give a full path.
    Never guess a file extension — search by the name the user gave
    Args:
        file_name: Any part of the file name WITHOUT guessing an extension 
            Example: user says "the jarvis file" -> pass "jarvis"
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
    print("🎏find_file func: ", "\n".join(matches))
    return "\n".join(matches)

def read_file(path):
    """Allows you to read a file content. 
    Only call this, when you already have a full path - normally one returned by find_file.
    If you only know part of the name, call find_file first
    Resolve a model-supplied path and keep it inside SANDBOX
    Args:
        path: Path to the file relative to the project root, e.g. 'Jarvis/tools.py'
    """
    try:
        target = Path(path).resolve()
        root = Path(SANDBOX).resolve()
        try:
            target.relative_to(root)
        except ValueError:
            raise ValueError(...)
        if not target.exists():
            return (f"File {target} not found"
                    f"call find_file with a partial name")
        if not target.is_file():
            return f"Not a file {target}"
        read = target.read_text("utf-8", errors="replace")
        print("🎏read_file func", "arguments:", path, "result: ", read)
        return read
    except Exception as e:
        return f"Exception error {e}"
    
available_tools: list[Callable] = [get_time, find_file, read_file] # Add available functions here
REGISTRY: dict[str, Callable] = {f.__name__: f for f in available_tools}