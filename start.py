#!/usr/bin/env python3
import os

# Escribir credentials.yaml desde variable de entorno
credentials_yaml = os.getenv("CREDENTIALS_YAML")
if credentials_yaml:
    os.makedirs("config", exist_ok=True)
    with open("config/credentials.yaml", "w") as f:
        f.write(credentials_yaml)

# Instalar dependencias del sistema para Playwright en Ubuntu 24
os.system("apt-get install -y libasound2t64 libglib2.0-0 libnss3 libnspr4 libdbus-1-3 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 libatspi2.0-0 libx11-6 libxcomposite1 libxdamage1 libxext6 libxfixes3 libxrandr2 libgbm1 libxcb1 libxkbcommon0 libpango-1.0-0 libcairo2 2>/dev/null || true")
os.system("playwright install chromium")

# Arrancar scheduler
os.execlp("python", "python", "scheduler.py")
