#!/usr/bin/env python3
import os
import json

# Escribir credenciales de Google desde variables de entorno
creds_json = os.getenv("GOOGLE_CREDENTIALS_JSON")
if creds_json:
    os.makedirs("config", exist_ok=True)
    with open("config/credentials.yaml", "w") as f:
        f.write(os.getenv("CREDENTIALS_YAML", ""))
    with open("config/google_oauth_credentials.json", "w") as f:
        f.write(creds_json)

# Escribir token de Google
token_json = os.getenv("GOOGLE_TOKEN_JSON")
if token_json:
    with open("config/token.json", "w") as f:
        f.write(token_json)

# Instalar playwright browsers
os.system("playwright install chromium")

# Arrancar scheduler
os.execlp("python", "python", "scheduler.py")
