import os
import secrets
from datetime import datetime
from pathlib import Path

from loguru import logger

from jarvis.core.config import get_settings
from jarvis.sql.history import get_database
from jarvis.tools.path import safe_path

MAX_TOOL_OUTPUT = 2000


def get_time() -> str:
    """Get the current local date and time with timezone information.

    Call this when the user asks what time or what date it is.
    """
    return str(datetime.now().isoformat())


def find_file(file_name: str) -> str:
    """Find files inside the sandbox by a partial name.

    Call this FIRST whenever the user mentions a file but does not give a full
    path. Never guess a file extension — search by the name the user gave.

    Args:
        file_name: Any part of the file name, without guessing an extension.
            Example: user says "the jarvis file" -> pass "jarvis".
    """
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


def read_file(path: str, from_line: int = 0) -> str:
    """Read the content of a file inside the sandbox.

    Call this only when you already have a path — normally one returned by
    find_file. If you only know part of the name, call find_file first.

    Long files are cut off. When the result ends with a truncation notice,
    call this again with `from_line` set to the line it names - but only
    if you actually need the rest.


    Args:
        path: Path relative to the sandbox root, as returned by find_file.
            Example: "notes/todo.txt".
        from_line: Line to start reading from, counting from 0. Defaults to
            the start of the file. Example: 120.
    """
    res = []
    size = 0
    try:
        target = safe_path(path)
        if not target.exists():
            return f"Error: File '{path}' does not exist. Use find_file to search."
        if not target.is_file():
            return f"Error: '{path}' is a directory, not a file."

        list_lines = target.open(encoding="utf-8", errors="replace").readlines()
        if from_line >= len(list_lines):
            return f"Error: from_line {from_line} is past the end of '{path}' ({len(list_lines)} lines)."
        for i, line in enumerate(list_lines[from_line:], start=from_line):
            if size >= MAX_TOOL_OUTPUT:
                res.append(
                    f"[truncated at line {i} of {len(list_lines)}; "
                    f"call read_file again with from_line={i}]"
                )
                break
            res.append(line)
            size += len(line)
        return "".join(res)
    except ValueError as err:
        return str(err)
    except OSError as err:
        logger.error("Failed to read file '{}': {}", path, err)
        return f"OS error reading file: {err}"


def list_dir(path: str = ".") -> str:
    """List the contents of a directory inside the sandbox.

    Use this to explore the structure when you do not know where a file lives.
    Prefer find_file when you already know part of the file name.

    Args:
        path: Directory path relative to the sandbox root. Defaults to the
            sandbox root itself. Example: "notes".
    """
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
    """Replace an exact single occurrence of text inside a sandbox file.

    Call this whenever the user asks to change, fix, rename or remove something
    inside an existing file. Never ask the user for the exact text — call
    read_file first and copy it verbatim.

    Args:
        path: Path inside the sandbox, as returned by find_file.
        old_text: Exact text to replace. Must occur exactly once in the file.
        new_text: Replacement text. An empty string deletes old_text.
    """
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
    """Create a new file inside the sandbox with optional initial content.

    Call this when the user asks to create a new file, empty or with content.
    Fails if the file already exists — use edit_file to change an existing one.

    Args:
        path: Full path of the new file relative to the sandbox root, including
            the file name and extension. Never pass a directory on its own.
            Example: user says "create example.py in the notes folder" ->
            pass "notes/example.py".
        content: The complete text of the file. Write the whole script in this
            single call — never create an empty file and grow it with edit_file.
    """
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
    """Permanently delete a file inside the sandbox.

    Call this ONLY when the user explicitly asks to delete or remove a file.
    ALWAYS call find_file first to get the real path — never guess it and never
    ask the user for it. The deletion cannot be undone.

    Args:
        path: Exact path returned by find_file.
    """
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
    """Create a new directory inside the sandbox.

    Call this when the user asks to create a directory. Fails if the path
    already exists — call list_dir first if you are unsure.

    Args:
        path: Full path of the new directory relative to the sandbox root,
            including the directory name.
            Example: user says "create Jarvis in the example directory" ->
            pass "example/Jarvis".
    """
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


# memory

MEMORY_DIR = Path(__file__).parents[3] / "memory"


def remember(chat_memory: str = "", user_profile: str = "") -> str:
    """Save a fact to your memory.

    Call whis when user ask to remember something, or tell you important info about him to write a brief history of the chat

    Args:
        chat_memory: One or two sentances on what matters from conversation so far. Empty string, if there is nothing worth storing, or this info will be stored in user_profile arguments.
        user_profile: One or two sentances about the user themselves - their name, preferences, habits, long-lived facts. Empty string, if there is nothing worth storing, or this info will be stored in chat_memory arguments."""

    if not chat_memory.strip() and not user_profile.strip():
        return "Nothing saved: both arguments were empty"

    MEMORY_FILES = ((chat_memory, "MEMORY.md"), (user_profile, "USER.md"))

    data = str(datetime.now())[0:-7]
    written: list[str] = []
    failed: list[str] = []
    for text, filename in MEMORY_FILES:
        if not text.strip():
            continue
        try:
            with open(f"{MEMORY_DIR}/{filename}", "a", encoding="utf-8") as f:
                entry_id = secrets.token_hex(2)
                f.write(f"- [{entry_id}] {data} {text.strip()}\n")
            written.append(filename)
        except OSError as err:
            logger.error("Could not write memory file {}: {}", filename, err)
            failed.append(filename)

    if not written:
        return f"Failed to save files: {', '.join(failed)}"
    result = f"Saved to {', '.join(written)}."
    if failed:
        result += f" Failed to save: {', '.join(failed)}."
    return result


def forget(entry_ids: str):
    """Remove deprecated information from the memory files by their id

    Call this when a stored fact is no longer true, when user asks you to forget something, or when you notice a duplicate.
    The entries and their ids are already shown to you in the <chat_memory> and
    <user_profile> blocks of your system prompt. Read the ids from there

    Args:
        entry_ids: One or more ids, comma separated
        Example: "a3f1, 7b02"."""

    id_list = [i.strip() for i in entry_ids.split(",")]
    removed = []
    if not id_list:
        return "There's nothing to delete, entry_ids argument was empty"
    for filename in ("MEMORY.md", "USER.md"):
        try:
            with open(f"{MEMORY_DIR}/{filename}", encoding="utf-8") as f:
                lines = f.readlines()
            kept = []
            for line in lines:
                hax = line[3:7].strip()
                if hax in id_list:
                    removed.append(hax)
                else:
                    kept.append(line)
            if len(kept) == len(lines):
                continue
            with open(f"{MEMORY_DIR}/{filename}", "w", encoding="utf-8") as f:
                f.writelines(kept)
        except OSError as err:
            logger.error("Could not edit memory file {}: {}", filename, err)

    missing = [i for i in id_list if i not in removed]
    if not removed:
        return f"No entry matched ids {', '.join(missing)}"
    result = f"Lines with ids {', '.join(removed)} were successfully removed"
    if missing:
        result += f". Not found: {', '.join(missing)}"
    return result


def read_from_database(keywords: str, limit: int = 2) -> str:
    """Search your past conversation with the user by keywords
    Call it when the user refers to something from an earlier conversation that is no longer in your context.
    Do NOT call this to save a new fact that is what `remember` is for
    Args:
    keywords: Two or three distinctive words, not a sentence or a question.
        All of them must appear in the same turn, according to his value system will be search a conversation in the database
    limit: A integer value, how many past turns to return from the database. Keep it small' 2 is usially enough
    """
    turns = get_database().read(keywords, limit)
    return "\n\n".join(
        f"{turn['created_at']}\nQuestion: {turn['question']}\nAnswer: {turn['answer']}"
        for turn in turns
    )
