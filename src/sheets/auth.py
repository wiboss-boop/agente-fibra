"""
Autenticación para Google Sheets.

Soporta dos modos:
  1. Service Account (Railway/producción): usa GOOGLE_SERVICE_ACCOUNT_JSON env var
     o el archivo config/service_account.json si existe.
  2. OAuth2 (local/desarrollo): usa token.json + google_oauth_credentials.json.
"""

import logging
import os
from pathlib import Path
from typing import Optional

from googleapiclient.discovery import build

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

_DEFAULT_CREDENTIALS = Path("config/google_oauth_credentials.json")
_DEFAULT_TOKEN = Path("config/token.json")
_SERVICE_ACCOUNT_FILE = Path("config/service_account.json")


def get_sheets_service(
    credentials_file: Path = _DEFAULT_CREDENTIALS,
    token_file: Path = _DEFAULT_TOKEN,
):
    sa_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
    if sa_json:
        logger.info("Usando Service Account desde variable de entorno")
        return _build_from_service_account_json(sa_json)

    if _SERVICE_ACCOUNT_FILE.exists():
        logger.info("Usando Service Account desde %s", _SERVICE_ACCOUNT_FILE)
        return _build_from_service_account_file(_SERVICE_ACCOUNT_FILE)

    logger.info("Usando autenticación OAuth2")
    return _build_from_oauth(credentials_file, token_file)


def _build_from_service_account_json(json_str: str):
    import json
    from google.oauth2 import service_account
    info = json.loads(json_str)
    creds = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
    return build("sheets", "v4", credentials=creds)


def _build_from_service_account_file(path: Path):
    from google.oauth2 import service_account
    creds = service_account.Credentials.from_service_account_file(str(path), scopes=SCOPES)
    return build("sheets", "v4", credentials=creds)


def _build_from_oauth(credentials_file: Path, token_file: Path):
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from google_auth_oauthlib.flow import InstalledAppFlow

    creds = _load_token(token_file)

    if creds and creds.expired and creds.refresh_token:
        logger.info("Token expirado, renovando automáticamente…")
        creds.refresh(Request())
        _save_token(creds, token_file)

    if not creds or not creds.valid:
        creds = _run_oauth_flow(credentials_file)
        _save_token(creds, token_file)

    return build("sheets", "v4", credentials=creds)


def _load_token(token_file: Path) -> Optional[object]:
    from google.oauth2.credentials import Credentials
    if not token_file.exists():
        return None
    try:
        creds = Credentials.from_authorized_user_file(str(token_file), SCOPES)
        logger.info("Token cargado desde %s", token_file)
        return creds
    except Exception as exc:
        logger.warning("No se pudo leer el token (%s)", exc)
        return None


def _run_oauth_flow(credentials_file: Path):
    from google_auth_oauthlib.flow import InstalledAppFlow
    if not credentials_file.exists():
        raise FileNotFoundError(f"No se encontró: {credentials_file}")
    logger.info("Iniciando flujo OAuth2…")
    flow = InstalledAppFlow.from_client_secrets_file(str(credentials_file), SCOPES)
    creds = flow.run_local_server(port=0, prompt="consent")
    return creds


def _save_token(creds, token_file: Path) -> None:
    token_file.parent.mkdir(parents=True, exist_ok=True)
    token_file.write_text(creds.to_json())
    logger.info("Token guardado en %s", token_file)
