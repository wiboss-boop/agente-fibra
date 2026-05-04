#!/usr/bin/env python3
"""
Corre el agente-fibra automáticamente a las 18:00 hora de Bogotá (UTC-5)
equivalente a las 21:00 UTC.
"""
import schedule
import time
import subprocess
import logging
from datetime import datetime

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

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
    except subprocess.TimeoutExpired:
        logger.error("Agente timeout después de 1 hora")
    except Exception as e:
        logger.error("Error: %s", e)

# 21:00 UTC = 18:00 Bogotá
schedule.every().day.at("21:00").do(run_agente)

logger.info("Scheduler iniciado. Agente correrá a las 18:00 Bogotá (21:00 UTC)")

while True:
    schedule.run_pending()
    time.sleep(60)
