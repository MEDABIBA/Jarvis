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
