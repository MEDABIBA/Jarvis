from path import safe_path
from config import SANDBOX, SKIP
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
import os


def get_time() -> str:
    """Get the current local time. Call this when the user asks what time it is."""
    return str(datetime.now().astimezone())


def find_file(file_name: str) -> str:
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


def read_file(path: str) -> str:
    """Allows you to read a file content.
    Only call this, when you already have a full path - normally one returned by find_file.
    If you only know part of the name, call find_file first
    Resolve a model-supplied path and keep it inside SANDBOX
    Args:
        path: Path to the file relative to the project root, e.g. "D:/Jarvis/tools.py"
    """
    try:
        try:
            target = safe_path(path)
        except ValueError as e:
            return str(e)
        if not target.exists():
            return f"File {target} not foundcall find_file with a partial name"
        if not target.is_file():
            return f"Not a file {target}"
        read = target.read_text("utf-8", errors="replace")
        print("🎏read_file func", "arguments:", path, "result: ", read)
        return read
    except Exception as e:
        return f"Exception error {e}"


def list_dir(path: str) -> str | list[str]:
    """Allows you to check the structure of the directory
    Use it when the file name is unknown to you, or to find a specific file
    Args:
        path: Path to the directory relative to the project root, e.g. 'Jarvis'
    """
    try:
        target = safe_path(path)
    except ValueError as e:
        return str(e)
    print("list_dir func", "arguments:", path, "result: ", os.listdir(path))
    return f"Contents of {path}:\n" + "\n".join(os.listdir(path))


def edit_file(path: str, old_text: str, new_text: str) -> str:
    """Change the context of a file by replacing an exact piece of text
    Call this whenever the user asks to change, edit, fix, rename or remove
    something inside a file
    Args:
        path: Path to the file as returned by find_file
        old_text: Exact text that you want to replace. Must appear exactly once in the file
        new_text: Replacement text. Empty string deletes old_text
    """
    try:
        target = safe_path(path)
    except ValueError as e:
        return str(e)
    if not target.is_file():
        return f"Not a file {target}"

    with open(file=target, mode="r", encoding="utf-8", newline="") as f:
        text = f.read()
        count = text.count(old_text)
        if count == 0:
            return (
                "old_text not found in the file. Call read_file to see the exact content, "
                "then call edit_file again with old_text copied verbatim from what you read. "
                "Do not ask the user — the correct text is in the file."
            )
        if count > 1:
            return f"old_text appears {count} times, please, specify which one to make it unique. Do not ask the user — the correct text is in the file"
        if new_text and new_text in text:
            return (
                "The file already contains new_text — this edit was already applied. "
                "Call read_file to check the current content before editing again."
            )
    with open(file=target, mode="w", encoding="utf-8", newline="") as f:
        f.write(text.replace(old_text, new_text, 1))
    print("edit_file func", "arguments:", path, old_text, new_text, "Successfully")
    return f"Edited successfully"


def create_file(path: str, content: str = "") -> str:
    """Created a new file in allowed directory with optional content
    Call this whenewer user asks to create a new empty, or with some text / lines of code file
    Before calling this, check that the directory exists with list_dir
    Fails if the file already exists — use edit_file to change an existing file
    Args:
    path: Full path of the new file, INCLUDING
        the file name and extension. Never pass a directory on its own.
        Example: user says "create example.py in the Jarvis folder" -> pass "Jarvis/example.py"
    file_content: The COMPLETE text of the file. Write the whole script here in
        one call. Never create a file and then grow it with edit_file"""
    print("create_file func", "arguments:", path, content)
    try:
        target = safe_path(path)
    except ValueError as e:
        return str(e)
    try:
        with open(target, "x", encoding="utf-8", newline="") as f:
            f.write(content)
    except OSError as e:
        return f"Could not create file: {type(e).__name__}: {e}"
    return f"File {path} created successfully"


# def write_file():
#     pass


def delete_file(path: str) -> str:
    """Permanently delete a file inside the allowed directory.
    Call this ONLY when the user explicitly asks to delete or remove a file.
    ALWAYS call find_file first to get the real path — never guess it, don`t ask the user, use find_file to find the directory.
    The deletion is permanent.
    Args:
        path: Exact path returned by find_file
    """
    try:
        target = safe_path(path)
    except ValueError as e:
        return str(e)
    if not os.path.exists(target):
        return (
            f"File not found {path}. Call find_file tool with a paralel name to get the correct path,"
            f"then retry — do not ask the user"
        )
    if not target.is_file():
        return f"Not a file: {path}. This tool deletes files, not directories"
    try:
        answer = input(f"Delete {target}[y/N]? \n").strip().lower()
        if answer != "y":
            return f"Deletion cancalled by user: {path}"
        os.remove(target)
    except OSError as e:
        return f"Could not delete: {e}"
    print("delete_file func", "arguments:", path, f"File deleted {path}")
    return f"File deleted successfully {target}"


def create_directory(path: str) -> str:
    """Created a new directory in allowed directories
    Call this whenewer user asks to create a directory
    Before calling this, check that the path is exists with list_dir
    Fails if the dicrectory already exists
    Args:
    path: Full path of the new directory, INCLUDING
        the directory name
        Example: user says "create Jarvis in the example directory-> pass "example/Jarvis"
    """
    try:
        target = safe_path(path)
    except ValueError as e:
        return str(e)
    if target.exists():
        return f"Directory already exists: {path}"
    try:
        target.mkdir()
    except OSError as e:
        return f"Could not create directory: {type(e).__name__}: {e}"
    print("create_directory func", "arguments:", target, f"Directory created {target}")
    return f"Directory {target} created successfully"


available_tools: list[Callable] = [
    get_time,
    find_file,
    read_file,
    list_dir,
    edit_file,
    create_file,
    delete_file,
    create_directory,
]  # Add available functions here
REGISTRY: dict[str, Callable] = {f.__name__: f for f in available_tools}
