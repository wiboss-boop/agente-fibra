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
import shutil
import sys
from datetime import date, datetime
from zoneinfo import ZoneInfo
from pathlib import Path
from typing import List

import yaml

from src.parsers.pdf_parser import parse_pdf
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
    logger = logging.getLogger("main")
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

    if not args.no_scrape:
        from src.scrapers import kairos, orange

        logger.info("Iniciando scraper Kairos…")
        try:
            _, kairos_sin_parte = kairos.run(target_date=target_date, downloads_dir=downloads_dir, headless=headless)
        except Exception as exc:
            logger.error("Scraper Kairos falló: %s", exc, exc_info=True)

        logger.info("Iniciando scraper Orange…")
        try:
            _, orange_incidencias = orange.run(
                target_date=target_date, downloads_dir=downloads_dir, headless=headless
            )
        except Exception as exc:
            logger.error("Scraper Orange falló: %s", exc, exc_info=True)
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
    from src.parsers.pdf_parser import TECHNICIAN_MAP
    tecnicos_con_altas = {r.get("tecnico") for r in records if r.get("tecnico")}
    todos_tecnicos = set(TECHNICIAN_MAP.values())
    for tecnico in todos_tecnicos - tecnicos_con_altas:
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
    # 4. Escribir en Google Sheets
    # -----------------------------------------------------------------------
    counters = {"escritos": 0, "duplicados": 0, "omitidos": 0}
    if records:
        try:
            counters = write_results(records)
        except Exception as exc:
            logger.error("Error al escribir en Google Sheets: %s", exc)

    # -----------------------------------------------------------------------
    # 5. Mover PDFs procesados
    # -----------------------------------------------------------------------
    moved = 0
    for pdf in pdfs:
        if pdf.name not in parse_errors:
            move_to_processed(pdf, processed_dir)
            moved += 1
            logger.info("Movido a procesados/: %s", pdf.name)

    # -----------------------------------------------------------------------
    # 6. Resumen
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
    print(f"  Movidos a proc.  : {moved}")
    print("=" * 50)

    if parse_errors:
        print("\nPDFs con error de parseo (no movidos):")
        for name in parse_errors:
            print(f"  · {name}")

    incidencias = [r for r in records if r.get("incidencia")]
    if incidencias:
        print("\nRegistros con incidencia (código no determinado):")
        for r in incidencias:
            print(f"  · {r['_source']}  orden={r.get('orden')}  técnico={r.get('tecnico')}")


if __name__ == "__main__":
    main()
