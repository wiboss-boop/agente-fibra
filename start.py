#!/usr/bin/env python3
import os

credentials_yaml = os.getenv("CREDENTIALS_YAML")
if credentials_yaml:
    os.makedirs("config", exist_ok=True)
    with open("config/credentials.yaml", "w") as f:
        f.write(credentials_yaml)

args = ["main.py"]
if os.getenv("AGENTE_FECHA"):
    args += ["--fecha", os.getenv("AGENTE_FECHA")]
if os.getenv("AGENTE_NO_SCRAPE"):
    args += ["--no-scrape"]
if os.getenv("AGENTE_VISIBLE"):
    args += ["--visible"]

os.execlp("python", "python", *args)
