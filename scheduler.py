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

def enviar_telegram(mensaje: str) -> None:
    import json
    import urllib.request
    token = os.getenv("TELEGRAM_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "7610971004")
    if not token:
        logger.warning("TELEGRAM_TOKEN no configurado, no se puede enviar informe")
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = {"chat_id": chat_id, "text": mensaje, "parse_mode": "HTML"}
    req = urllib.request.Request(url, json.dumps(data).encode(), {"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=10)
    except Exception as exc:
        logger.warning("No se pudo enviar mensaje Telegram: %s", exc)


def run_agente() -> None:
    from datetime import datetime
    from zoneinfo import ZoneInfo
    fecha_hoy = datetime.now(ZoneInfo("America/Bogota")).strftime("%d/%m/%Y")

    logger.info("Iniciando agente-fibra para %s...", fecha_hoy)
    try:
        result = subprocess.run(
            ["python", "main.py"],
            capture_output=True,
            text=True,
            timeout=3600,
        )
        logger.info("Agente terminado:\n%s", result.stdout)
        if result.stderr:
            logger.error("Stderr:\n%s", result.stderr)

        output = result.stdout
        tiene_errores = (
            "Errores scraper  : " in output and
            not "Errores scraper  : 0" in output
        ) or result.returncode != 0

        keywords = ["RESUMEN", "PDFs", "Escritos", "Duplicados", "Incidencias",
                    "Errores", "===", "Kairos:", "Orange:"]
        lineas = [l for l in output.split("\n") if any(k in l for k in keywords)]
        resumen = "\n".join(lineas).strip() or output[-500:].strip()

        icono = "⚠️" if tiene_errores else "✅"
        enviar_telegram(
            f"{icono} <b>Agente Fibra</b> — {fecha_hoy}\n\n<pre>{resumen}</pre>"
        )
    except subprocess.TimeoutExpired:
        logger.error("Agente timeout después de 1 hora")
        enviar_telegram(f"⚠️ <b>Agente Fibra</b> — {fecha_hoy}\n\nTimeout después de 1 hora")
    except Exception as exc:
        logger.error("Error inesperado: %s", exc)
        enviar_telegram(f"❌ <b>Agente Fibra</b> — {fecha_hoy}\n\nError: {exc}")

# 21:00 UTC = 18:00 Bogotá
schedule.every().day.at("21:00").do(run_agente)

logger.info("Scheduler iniciado. Agente correrá a las 18:00 Bogotá (21:00 UTC)")

while True:
    schedule.run_pending()
    time.sleep(60)
