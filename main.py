#!/usr/bin/env python3
"""
Agente de fibra óptica.
Uso: venv/bin/python3 main.py [--fecha DD/MM/YYYY] [--no-scrape] [--visible]

Flags opcionales:
  --fecha DD/MM/YYYY   fecha a procesar (default: hoy)
  --no-scrape          saltar descarga y procesar solo los PDFs ya en downloads/
  --visible            abrir el navegador en modo visible (útil para depurar scrapers)
"""

import argparse
import logging
import os
import shutil
import sys
from datetime import date, datetime
from zoneinfo import ZoneInfo
from pathlib import Path
from typing import List

import yaml

from src.parsers.pdf_parser import parse_pdf

logger = logging.getLogger("main")
from src.sheets.writer import write_results


def setup_logging() -> None:
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(f"logs/agente_{date.today()}.log"),
            logging.StreamHandler(sys.stdout),
        ],
    )
    for noisy in ("googleapiclient", "google", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.ERROR)


def load_config(path: str = "config/credentials.yaml") -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Agente de fibra óptica")
    parser.add_argument(
        "--fecha",
        default=None,
        help="Fecha a procesar en formato DD/MM/YYYY (default: hoy)",
    )
    parser.add_argument(
        "--no-scrape",
        action="store_true",
        help="Omitir descarga de PDFs y procesar solo los que ya están en downloads/",
    )
    parser.add_argument(
        "--visible",
        action="store_true",
        help="Abrir el navegador en modo visible (headless=False)",
    )
    return parser.parse_args()


def collect_pdfs(downloads_dir: Path) -> List[Path]:
    return sorted(p for p in downloads_dir.glob("*.pdf") if p.is_file())


def move_to_processed(pdf: Path, processed_dir: Path) -> None:
    processed_dir.mkdir(parents=True, exist_ok=True)
    dest = processed_dir / pdf.name
    if dest.exists():
        dest = processed_dir / f"{pdf.stem}_dup{pdf.suffix}"
    shutil.move(str(pdf), dest)


def main() -> None:
    setup_logging()
    args = parse_args()

    # Fecha objetivo
    if args.fecha:
        target_date = datetime.strptime(args.fecha, "%d/%m/%Y").date()
    else:
        target_date = datetime.now(ZoneInfo("America/Bogota")).date()

    config = load_config()
    downloads_dir = Path(config.get("downloads_dir", "downloads"))
    processed_dir = downloads_dir / "procesados"
    headless = not args.visible

    if target_date.weekday() == 6:
        print("Hoy es domingo — no hay trabajo programado")
        return

    logger.info("Fecha objetivo: %s", target_date.strftime("%d/%m/%Y"))

    # -----------------------------------------------------------------------
    # 1. Descarga de PDFs (scrapers)
    # -----------------------------------------------------------------------
    orange_incidencias: List[dict] = []
    kairos_sin_parte: List[dict] = []
    scraper_errors: List[str] = []
    # Fallos de un técnico concreto (login rechazado, timeout…): el scraper sigue con el
    # siguiente y antes solo quedaban en el log.
    fallos_tecnico: List[dict] = []

    if not args.no_scrape:
        from src.scrapers import kairos, orange

        logger.info("Iniciando scraper Kairos…")
        try:
            _, kairos_sin_parte = kairos.run(target_date=target_date, downloads_dir=downloads_dir,
                                             headless=headless, errores=fallos_tecnico)
        except Exception as exc:
            logger.error("Scraper Kairos falló: %s", exc, exc_info=True)
            scraper_errors.append(f"Kairos: {exc}")

        logger.info("Iniciando scraper Orange…")
        try:
            _, orange_incidencias = orange.run(
                target_date=target_date, downloads_dir=downloads_dir, headless=headless,
                errores=fallos_tecnico,
            )
        except Exception as exc:
            logger.error("Scraper Orange falló: %s", exc, exc_info=True)
            scraper_errors.append(f"Orange: {exc}")
    else:
        logger.info("Modo --no-scrape: omitiendo descarga automática")

    # -----------------------------------------------------------------------
    # 2. Recoger PDFs disponibles en downloads/
    # -----------------------------------------------------------------------
    pdfs = collect_pdfs(downloads_dir)
    if not pdfs and not orange_incidencias:
        logger.info("No hay PDFs ni incidencias Orange que procesar.")

    logger.info("PDFs a procesar: %d", len(pdfs))

    # -----------------------------------------------------------------------
    # 3. Parsear PDFs + añadir incidencias Orange sin boletín
    # -----------------------------------------------------------------------
    records = []
    parse_errors = []

    for pdf in pdfs:
        try:
            result = parse_pdf(pdf)
            if result.get("skip"):
                logger.info("PDF omitido (KO): %s", pdf.name)
                continue
            # La fecha interna del PDF es poco fiable (fechas sueltas del documento,
            # plantillas con años viejos). El alta pertenece al día de proceso, igual
            # que las incidencias Orange/Kairos y las SIN ALTAS.
            fecha_pdf = result.get("fecha")
            fecha_proceso = target_date.strftime("%d/%m/%Y")
            if fecha_pdf and fecha_pdf != fecha_proceso:
                logger.warning(
                    "Fecha del PDF %s ('%s') difiere del día de proceso ('%s'); se usa el día de proceso",
                    pdf.name, fecha_pdf, fecha_proceso,
                )
            result["fecha"] = fecha_proceso
            result["_source"] = pdf.name
            records.append(result)
        except Exception as exc:
            logger.error("Error al parsear %s: %s", pdf.name, exc)
            parse_errors.append(pdf.name)

    if orange_incidencias:
        logger.info("Añadiendo %d incidencias Orange sin boletín OK", len(orange_incidencias))
        records.extend(orange_incidencias)

    if kairos_sin_parte:
        logger.info("Añadiendo %d órdenes Kairos sin parte", len(kairos_sin_parte))
        records.extend(kairos_sin_parte)

    # -----------------------------------------------------------------------
    # 4. Añadir SIN ALTAS para técnicos sin registros
    # -----------------------------------------------------------------------
    # Un técnico cuyo portal falló no es «sin altas»: no se sabe. Se deja sin fila para
    # recuperar el día cuando se arregle, y el Telegram lo avisa.
    tecnicos_con_altas = {r.get("tecnico") for r in records if r.get("tecnico")}
    tecnicos_con_fallo = {f["tecnico"] for f in fallos_tecnico}
    todos_tecnicos = {t["name"] for t in config.get("technicians", [])}
    for tecnico in sorted(tecnicos_con_fallo - tecnicos_con_altas):
        logger.warning("Sin dato hoy (falló el portal, no se apunta SIN ALTAS): %s", tecnico)
    for tecnico in sorted(todos_tecnicos - tecnicos_con_altas - tecnicos_con_fallo):
        records.append({
            "orden": "-",
            "fecha": target_date.strftime("%d/%m/%Y"),
            "tecnico": tecnico,
            "codigo": "SIN ALTAS",
            "incidencia": False,
            "_source": f"{tecnico}_sin_altas",
        })
        logger.info("Sin altas hoy: %s", tecnico)

    # -----------------------------------------------------------------------
    # 5. Escribir en Google Sheets
    # -----------------------------------------------------------------------
    counters = {"escritos": 0, "duplicados": 0, "omitidos": 0}
    if records:
        try:
            counters = write_results(records)
        except Exception as exc:
            logger.error("Error al escribir en Google Sheets: %s", exc)

    # -----------------------------------------------------------------------
    # 6. Mover PDFs procesados
    # -----------------------------------------------------------------------
    moved = 0
    for pdf in pdfs:
        if pdf.name not in parse_errors:
            move_to_processed(pdf, processed_dir)
            moved += 1
            logger.info("Movido a procesados/: %s", pdf.name)

    # -----------------------------------------------------------------------
    # 7. Resumen
    # -----------------------------------------------------------------------
    n_incidencias = sum(1 for r in records if r.get("incidencia"))
    n_sin_tecnico = sum(1 for r in records if not r.get("tecnico"))

    print("\n" + "=" * 50)
    print(f"  RESUMEN — {target_date.strftime('%d/%m/%Y')}")
    print("=" * 50)
    print(f"  PDFs procesados  : {len(pdfs)}")
    print(f"  Escritos en Sheet: {counters['escritos']}")
    print(f"  Duplicados       : {counters['duplicados']}")
    print(f"  Incidencias      : {n_incidencias}")
    print(f"  Sin técnico      : {n_sin_tecnico}")
    print(f"  Errores parseo   : {len(parse_errors)}")
    print(f"  Errores scraper  : {len(scraper_errors) + len(fallos_tecnico)}")
    print(f"  Movidos a proc.  : {moved}")
    print("=" * 50)

    if scraper_errors or fallos_tecnico:
        print("\nErrores en scrapers:")
        for err in scraper_errors:
            print(f"  · {err}")
        for f in fallos_tecnico:
            print(f"  · {f['plataforma']} / {f['tecnico']} ({f['usuario']}): {f['error']}")

    if parse_errors:
        print("\nPDFs con error de parseo (no movidos):")
        for name in parse_errors:
            print(f"  · {name}")

    incidencias = [r for r in records if r.get("incidencia")]
    if incidencias:
        print("\nRegistros con incidencia (código no determinado):")
        for r in incidencias:
            print(f"  · {r['_source']}  orden={r.get('orden')}  técnico={r.get('tecnico')}")

    # -----------------------------------------------------------------------
    # 8. Notificación Telegram
    # -----------------------------------------------------------------------
    _send_telegram_summary(target_date, len(pdfs), counters, n_incidencias,
                           len(parse_errors), len(scraper_errors) + len(fallos_tecnico), moved,
                           fallos_tecnico)


def _md(texto: str) -> str:
    """Escapa lo que el Markdown de Telegram interpretaría (un «_» suelto tumba el envío)."""
    for c in ("_", "*", "`", "["):
        texto = texto.replace(c, "\\" + c)
    return texto


def _lineas_fallos(fallos_tecnico):
    """Bloque del Telegram con los técnicos cuyo portal falló, separando los logins."""
    if not fallos_tecnico:
        return []
    lines = []
    logins = [f for f in fallos_tecnico if f["login"]]
    otros = [f for f in fallos_tecnico if not f["login"]]
    if logins:
        lines += ["", "🔑 *No deja entrar en el portal* (¿contraseña caducada o cambiada?):"]
        lines += [f"  · {f['plataforma']} / {_md(f['tecnico'])} ({_md(f['usuario'])})" for f in logins]
        lines.append(_md("Cambiarla en el portal, en config/credentials.yaml y en "
                         "CREDENTIALS_YAML de Railway."))
    if otros:
        lines += ["", "⚠️ *Fallos del portal:*"]
        lines += [f"  · {f['plataforma']} / {_md(f['tecnico'])}: {_md(f['error'])}" for f in otros]
    nombres = sorted({f["tecnico"] for f in fallos_tecnico})
    lines.append(_md(f"No se apunta SIN ALTAS a {', '.join(nombres)}: "
                     "hay que recuperar el día cuando funcione."))
    return lines


def _send_telegram_summary(target_date, n_pdfs, counters, n_incidencias,
                            n_parse_errors, n_scraper_errors, moved, fallos_tecnico=()):
    import urllib.request
    import json
    token = os.environ.get("TELEGRAM_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "7610971004")
    if not token:
        logger.warning("TELEGRAM_TOKEN no configurado — resumen no enviado")
        return
    icono = "⚠️" if (fallos_tecnico or n_scraper_errors or n_parse_errors) else "✅"
    lines = [
        f"{icono} *Agente fibra — {target_date.strftime('%d/%m/%Y')}*",
        f"PDFs procesados: {n_pdfs}",
        f"Escritos en Sheet: {counters['escritos']}",
        f"Duplicados: {counters['duplicados']}",
        f"Incidencias: {n_incidencias}",
        f"Errores parseo: {n_parse_errors}",
        f"Errores scraper: {n_scraper_errors}",
        f"Movidos a procesados: {moved}",
    ]
    if n_parse_errors > 0:
        lines.append("⚠️ Hay PDFs con error de parseo")
    if n_scraper_errors > 0:
        lines.append("⚠️ Hay errores en scrapers")
    lines += _lineas_fallos(fallos_tecnico)
    text = "\n".join(lines)
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = json.dumps({"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}).encode()
    try:
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=10)
        logger.info("Resumen enviado por Telegram")
    except Exception as exc:
        logger.error("Error enviando Telegram: %s", exc)


if __name__ == "__main__":
    main()
