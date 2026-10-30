from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from loguru import logger

from jarvis.core.state import state
from jarvis.tools.google import CREDENTIALS_PATH, SCOPES, TOKEN_PATH


def google_auth():
    creds = state.google_creds
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            try:
                flow = InstalledAppFlow.from_client_secrets_file(
                    CREDENTIALS_PATH, SCOPES
                )
                creds = flow.run_local_server(port=0, timeout_seconds=120)
            except Exception:
                logger.warning("Google OAuth failed or was cancelled by user")
                return
        with open(TOKEN_PATH, "w") as token:
            token.write(creds.to_json())
