#!/usr/bin/env python3
import os

# Escribir credentials.yaml desde variable de entorno
credentials_yaml = os.getenv("CREDENTIALS_YAML")
if credentials_yaml:
    os.makedirs("config", exist_ok=True)
    with open("config/credentials.yaml", "w") as f:
        f.write(credentials_yaml)

# Instalar playwright browsers
os.system("playwright install chromium --with-deps || playwright install chromium")

# Arrancar scheduler
os.execlp("python", "python", "scheduler.py")
