"""
Autenticación OAuth2 para Google Sheets.

Primera ejecución: abre el navegador para que el usuario autorice.
Ejecuciones siguientes: reutiliza el token guardado en config/token.json,
renovándolo automáticamente si ha expirado.
"""

import logging
from pathlib import Path
from typing import Optional

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

_DEFAULT_CREDENTIALS = Path("config/google_oauth_credentials.json")
_DEFAULT_TOKEN = Path("config/token.json")


def get_sheets_service(
    credentials_file: Path = _DEFAULT_CREDENTIALS,
    token_file: Path = _DEFAULT_TOKEN,
):
    """
    Devuelve un cliente autenticado de la API de Google Sheets.

    - Si token_file existe y es válido (o renovable), lo usa directamente.
    - Si no, lanza el flujo OAuth2 en el navegador, espera la autorización
      del usuario y guarda el token resultante en token_file.
    """
    creds = _load_token(token_file)

    if creds and creds.expired and creds.refresh_token:
        logger.info("Token expirado, renovando automáticamente…")
        creds.refresh(Request())
        _save_token(creds, token_file)

    if not creds or not creds.valid:
        creds = _run_oauth_flow(credentials_file)
        _save_token(creds, token_file)

    return build("sheets", "v4", credentials=creds)


def _load_token(token_file: Path) -> Optional[Credentials]:
    if not token_file.exists():
        return None
    try:
        creds = Credentials.from_authorized_user_file(str(token_file), SCOPES)
        logger.info("Token cargado desde %s", token_file)
        return creds
    except Exception as exc:
        logger.warning("No se pudo leer el token guardado (%s), se solicitará uno nuevo", exc)
        return None


def _run_oauth_flow(credentials_file: Path) -> Credentials:
    if not credentials_file.exists():
        raise FileNotFoundError(
            f"No se encontró el archivo de credenciales OAuth: {credentials_file}\n"
            "Descárgalo desde Google Cloud Console → APIs y servicios → Credenciales "
            "→ tu ID de cliente OAuth 2.0 → Descargar JSON y guárdalo en esa ruta."
        )
    logger.info("Iniciando flujo OAuth2 — se abrirá el navegador…")
    flow = InstalledAppFlow.from_client_secrets_file(str(credentials_file), SCOPES)
    # port=0 deja que el SO elija un puerto libre
    creds = flow.run_local_server(port=0, prompt="consent")
    logger.info("Autorización completada")
    return creds


def _save_token(creds: Credentials, token_file: Path) -> None:
    token_file.parent.mkdir(parents=True, exist_ok=True)
    token_file.write_text(creds.to_json())
    logger.info("Token guardado en %s", token_file)
