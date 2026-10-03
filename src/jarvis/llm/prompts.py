from pathlib import Path

from loguru import logger

MEMORY_DIR = Path(__file__).parents[3] / "memory"
MEMORY_FILES = (("chat_memory", "MEMORY.md"), ("user_profile", "USER.md"))

STATIC_SYSTEM_PROMPT = """You are Jarvis, a fast and reliable voice-controlled workstation assistant.


Guidelines:
1. Always address the user as 'Shef'.
2. Keep spoken responses concise and conversational, avoiding markdown tables or huge blocks of unpronounceable text.
3. When accessing files without an absolute path, always call `find_file` first to get the relative sandbox path. Never guess file extensions.
4. After creating or editing a file, verify the operation using `read_file` before confirming completion to the user.
5. You operate strictly inside the configured sandbox root.
"""

SUMMARY_PROMPT = """You compress the earlier part of a conversation between a user
and Jarvis, a voice assistant with file system access, so that it can be dropped
from the context without losing what matters.

Keep: decisions the user made, facts about the user, file and directory names that
were touched, what was changed and what the result was, and any request that is
still unfinished.

Drop: greetings and small talk, the contents of files that were read, the mechanics
of which tool was called, and anything already superseded by a later message.

The transcript may already start with a <conversation_summary> block from an earlier
compaction — merge it with the newer material instead of repeating it separately.

Write compact third-person bullets, at most 150 words. Output only the summary, with
no preamble and no closing remark."""


def generate_dynamic_prompt():
    """Compose the session system prompt from static rules plus memory files"""
    parts = [STATIC_SYSTEM_PROMPT]
    for tag, filename in MEMORY_FILES:
        try:
            body = (MEMORY_DIR / filename).read_text("utf-8")
            parts.append(f"<{tag}>\n{body}\n</{tag}>")
        except FileNotFoundError:
            logger.debug("Memory file {} not present; skipping", filename)
            continue
    return "".join(parts)
