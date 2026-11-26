import os
import secrets
from datetime import datetime
from pathlib import Path

import requests
from ddgs import DDGS
from loguru import logger
from trafilatura import extract

from jarvis.core.config import get_settings
from jarvis.sql.history import get_database
from jarvis.tools.path import safe_path

MAX_TOOL_OUTPUT = 2000


def get_time() -> str:
    """Get the current local date and time with timezone. Call when the user asks the time or date."""
    return str(datetime.now().isoformat())


def find_file(file_name: str) -> str:
    """Find sandbox files by partial name.

    Call FIRST whenever the user mentions a file without a full path. Never guess the extension.

    Args:
        file_name: Part of the name as the user said it, no extension, e.g. "jarvis".
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
    """Read a sandbox file. If you only know part of the name, call find_file first.

    Long files are cut off with a notice naming a line; call again with that from_line only if you need the rest.

    Args:
        path: Sandbox-relative path from find_file, e.g. "notes/todo.txt".
        from_line: 0-based line to start from. Defaults to 0.
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
    """List a sandbox directory. Use to explore; prefer find_file when you know part of the name.

    Args:
        path: Sandbox-relative directory, e.g. "notes". Defaults to the sandbox root.
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
    """Replace one exact occurrence of text in an existing sandbox file.

    Use for any change inside a file. Never ask the user for the exact text; call read_file first and copy it verbatim.

    Args:
        path: Sandbox path from find_file.
        old_text: Exact text to replace; must occur exactly once.
        new_text: Replacement text; an empty string deletes old_text.
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
    """Create a new sandbox file. Fails if it exists; use edit_file for existing files.

    Args:
        path: Sandbox-relative path with file name and extension, never a bare directory, e.g. "notes/example.py".
        content: The complete file text in this one call; never create an empty file and grow it with edit_file.
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
    """Permanently delete a sandbox file; cannot be undone.

    Call ONLY when the user explicitly asks to delete a file. ALWAYS get the path from find_file first; never guess it or ask the user for it.

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
    """Create a sandbox directory. Fails if the path exists; call list_dir first if unsure.

    Args:
        path: Sandbox-relative path including the new directory name, e.g. "example/Jarvis".
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
    """Save facts to memory. Call when the user asks you to remember something or shares important info about themselves.

    Args:
        chat_memory: One or two sentences on what matters from the conversation; empty string if nothing or it belongs in user_profile.
        user_profile: One or two sentences about the user (name, preferences, habits, long-lived facts); empty string if nothing or it belongs in chat_memory."""

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
    """Remove memory entries by id. Call when a stored fact is outdated, the user asks you to forget it, or it is a duplicate.

    Read the ids from the <chat_memory> and <user_profile> blocks of your system prompt.

    Args:
        entry_ids: One or more comma-separated ids, e.g. "a3f1, 7b02"."""

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
    """Search past conversations with the user by keywords.

    Call when the user refers to an earlier conversation no longer in your context. Do NOT use it to save facts; use remember.

    Args:
        keywords: Two or three distinctive words, not a sentence; all must appear in the same past turn.
        limit: How many past turns to return; keep it small, 2 is usually enough.
    """
    turns = get_database().read(keywords, limit)
    return "\n\n".join(
        f"{turn['created_at']}\nQuestion: {turn['question']}\nAnswer: {turn['answer']}"
        for turn in turns
    )


def web_search(query: str) -> str:
    """Search the internet for current information. Start here, not with fetch_page.

    Call when the user asks about recent events, news, weather, prices, or anything you don't know.

    Args:
        query: A short search query; for news or recent events include the date, e.g. "Metro 2039 November 19 2039".
    """
    try:
        with DDGS() as ddgs:
            results = [
                f"Title: {r['title']}\nBody: {r['body']}\nURL: {r['href']}"
                for r in ddgs.text(query, max_results=3)
            ]
            return "\n".join(results) if results else "No results found."
    except Exception:
        return "Search failed. Try rephrasing the query."


def fetch_page(url: str) -> str:
    """Fetch a web page and extract its main text.

    Call ONLY when you already have a URL from web_search or from the user; otherwise call web_search first.

    Args:
        url: Full http or https URL.
    """

    HEADERS = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:131.0) Gecko/20100101 Firefox/131.0",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    }
    try:
        resp = requests.get(url, headers=HEADERS, timeout=5)
    except Exception as e:
        return f"HTTP error occurred: {e}"
    if not resp.text:
        return "Could not download page"
    result = extract(
        resp.text,
        include_links=False,
        favor_recall=False,
    )
    if not result:
        return "Error: no  extractable format"
    if len(result) > 6000:
        return result[:6000] + " \n truncated"
    return result
