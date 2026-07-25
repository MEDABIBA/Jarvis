import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

LLM_MODEL = os.environ.get("LLM_MODEL")
if not LLM_MODEL:
    raise RuntimeError("LLM_MODEL is not set — add it to .env")

SANDBOX = os.environ