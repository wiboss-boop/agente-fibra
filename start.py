#!/usr/bin/env python3
import os

credentials_yaml = os.getenv("CREDENTIALS_YAML")
if credentials_yaml:
    os.makedirs("config", exist_ok=True)
    with open("config/credentials.yaml", "w") as f:
        f.write(credentials_yaml)

args = ["main.py"]
fecha = os.getenv("AGENTE_FECHA")
if fecha:
    args += ["--fecha", fecha]

os.execlp("python", "python", *args)
