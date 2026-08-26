import os
from datetime import datetime
from pathlib import Path

from loguru import logger

from jarvis.core.config import get_settings
from jarvis.tools.path import safe_path


def get_time() -> str:
    """Get the current local date and time with timezone information."""
    return str(datetime.now().astimezone())


def find_file(file_name: str) -> str:
    """Recursively search for files in the sandbox matching a query string."""
    settings = get_settings()
    sandbox_root = settings.sandbox.resolve()

    if not sandbox_root.is_dir():
        return f"Configuration error: sandbox directory '{sandbox_root}' does not exist"

    matches: list[str] = []
    for root, _, files in os.walk(sandbox_root):
        rel_root = Path(root).relative_to(sandbox_root)
        if any(part in settings.skip_dirs for part in rel_root.parts):
            continue

        for file in files:
            if file_name.lower() in file.lower():
                full_path = Path(root, file)
                matches.append(str(full_path.relative_to(sandbox_root)))

    if not matches:
        return f"No files matching '{file_name}' found in sandbox."

    logger.debug("find_file('{}') returned {} results", file_name, len(matches))
    return "\n".join(matches)


def read_file(path: str) -> str:
    """Read full text content of a file within the sandbox."""
    try:
        target = safe_path(path)
        if not target.exists():
            return f"Error: File '{path}' does not exist. Use find_file to search."
        if not target.is_file():
            return f"Error: '{path}' is a directory, not a file."

        return target.read_text(encoding="utf-8", errors="replace")
    except ValueError as err:
        return str(err)
    except OSError as err:
        logger.error("Failed to read file '{}': {}", path, err)
        return f"OS error reading file: {err}"


def list_dir(path: str = ".") -> str:
    """List directory contents within the sandbox."""
    try:
        target = safe_path(path)
        if not target.exists():
            return f"Error: Directory '{path}' does not exist."
        if not target.is_dir():
            return f"Error: '{path}' is not a directory."

        entries = os.listdir(target)
        return (
            f"Contents of '{path}':\n" + "\n".join(entries)
            if entries
            else f"Directory '{path}' is empty."
        )
    except ValueError as err:
        return str(err)
    except OSError as err:
        return f"OS error listing directory: {err}"


def edit_file(path: str, old_text: str, new_text: str) -> str:
    """Replace an exact single occurrence of text inside a sandbox file."""
    try:
        target = safe_path(path)
        if not target.is_file():
            return f"Error: '{path}' is not an existing file."

        content = target.read_text(encoding="utf-8", errors="replace")
        count = content.count(old_text)

        if count == 0:
            return "Error: 'old_text' was not found in the file. Read the file to get exact verbatim text."
        if count > 1:
            return f"Error: 'old_text' appears {count} times. Provide more surrounding context to make it unique."

        updated_content = content.replace(old_text, new_text, 1)
        target.write_text(updated_content, encoding="utf-8")
        logger.info("Edited file: {}", path)
        return f"File '{path}' successfully updated."
    except ValueError as err:
        return str(err)
    except OSError as err:
        return f"OS error modifying file: {err}"


def create_file(path: str, content: str = "") -> str:
    """Create a new file in the sandbox with specified initial content."""
    try:
        target = safe_path(path)
        target.parent.mkdir(parents=True, exist_ok=True)

        if target.exists():
            return f"Error: File '{path}' already exists. Use edit_file to modify existing files."

        target.write_text(content, encoding="utf-8")
        logger.info("Created file: {}", path)
        return f"File '{path}' created successfully."
    except ValueError as err:
        return str(err)
    except OSError as err:
        return f"OS error creating file: {err}"


def delete_file(path: str) -> str:
    """Delete a file permanently inside the sandbox."""
    try:
        target = safe_path(path)
        if not target.exists():
            return f"Error: File '{path}' does not exist."
        if not target.is_file():
            return (
                f"Error: '{path}' is a directory. Use directory deletion tools instead."
            )

        target.unlink()
        logger.info("Deleted file: {}", path)
        return f"File '{path}' deleted successfully."
    except ValueError as err:
        return str(err)
    except OSError as err:
        return f"OS error deleting file: {err}"


def create_directory(path: str) -> str:
    """Create a new directory hierarchy in the sandbox."""
    try:
        target = safe_path(path)
        if target.exists():
            return f"Error: Path '{path}' already exists."

        target.mkdir(parents=True, exist_ok=True)
        logger.info("Created directory: {}", path)
        return f"Directory '{path}' created successfully."
    except ValueError as err:
        return str(err)
    except OSError as err:
        return f"OS error creating directory: {err}"
