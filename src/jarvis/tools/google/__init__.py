from pathlib import Path

SCOPES = ["https://www.googleapis.com/auth/calendar"]

CREDENTIALS_PATH = Path(__file__).parent / "credentials.json"
TOKEN_PATH = Path(__file__).parent / "token.json"

__all__ = ["CREDENTIALS_PATH", "SCOPES", "TOKEN_PATH"]
