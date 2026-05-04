#!/usr/bin/env python3
"""
Corre el agente-fibra automáticamente a las 18:00 hora de Bogotá (UTC-5)
equivalente a las 21:00 UTC.
"""
import schedule
import time
import subprocess
import logging
import os
from datetime import datetime

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

def enviar_telegram(mensaje):
    import urllib.request
    token = os.getenv("TELEGRAM_TOKEN")
    chat_id = "7610971004"
    if not token:
        logger.warning("TELEGRAM_TOKEN no configurado, no se puede enviar informe")
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = {"chat_id": chat_id, "text": mensaje, "parse_mode": "HTML"}
    import json
    req = urllib.request.Request(url, json.dumps(data).encode(), {"Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=10)

def run_agente():
    logger.info("Iniciando agente-fibra...")
    try:
        result = subprocess.run(
            ["python", "main.py"],
            capture_output=True,
            text=True,
            timeout=3600
        )
        logger.info("Agente terminado:\n%s", result.stdout)
        if result.stderr:
            logger.error("Errores:\n%s", result.stderr)
        # Extraer resumen del output
        output = result.stdout
        lineas = [l for l in output.split("\n") if any(k in l for k in ["RESUMEN", "PDFs", "Escritos", "Duplicados", "Incidencias", "Errores", "==="])]
        resumen = "\n".join(lineas).strip() or output[-500:].strip()
        enviar_telegram(f"<b>Agente Fibra</b> — informe\n\n<pre>{resumen}</pre>")
    except subprocess.TimeoutExpired:
        logger.error("Agente timeout después de 1 hora")
        enviar_telegram("⚠️ Agente fibra: timeout después de 1 hora")
    except Exception as e:
        logger.error("Error: %s", e)
        enviar_telegram(f"❌ Agente fibra error: {e}")

# 21:00 UTC = 18:00 Bogotá
schedule.every().day.at("21:00").do(run_agente)

logger.info("Scheduler iniciado. Agente correrá a las 18:00 Bogotá (21:00 UTC)")

while True:
    schedule.run_pending()
    time.sleep(60)
