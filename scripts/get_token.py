"""Flujo OAuth con puerto fijo: imprime la URL y espera la autorización para guardar token.json."""
from pathlib import Path
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
CREDS = Path("config/google_oauth_credentials.json")
TOKEN = Path("config/token.json")

flow = InstalledAppFlow.from_client_secrets_file(str(CREDS), SCOPES)
creds = flow.run_local_server(
    port=8765,
    open_browser=False,
    prompt="consent",
    authorization_prompt_message="AUTH_URL>>> {url}",
    success_message="Autorización completada. Puedes cerrar esta pestaña.",
)
TOKEN.write_text(creds.to_json())
print("TOKEN_OK")
