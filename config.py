import os
from dotenv import load_dotenv

load_dotenv()

LLM_MODEL = os.environ["LLM_MODEL"]
if not LLM_MODEL:
    raise RuntimeError("LLM_MODEL is not set — add it to .env")

SANDBOX= os.environ["SANDBOX"]
SKIP: set[str] = {".venv", "__pycache__", ".git", "node_modules", ".vscode"}