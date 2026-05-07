#!/usr/bin/env python3
"""Corre solo Orange para una fecha y escribe al Sheet."""
import sys
import logging
from datetime import datetime, date
from pathlib import Path
from src.scrapers import orange
from src.parsers.pdf_parser import parse_pdf
from src.sheets.writer import write_results

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)

if len(sys.argv) < 2:
    print("Uso: venv/bin/python3 run_orange.py DD/MM/YYYY")
    sys.exit(1)

target_date = datetime.strptime(sys.argv[1], "%d/%m/%Y").date()
downloads_dir = Path("downloads")

print(f"=== Orange: {target_date.strftime('%d/%m/%Y')} ===")
pdfs, incidencias = orange.run(target_date=target_date, downloads_dir=downloads_dir)

results = []
for pdf in pdfs:
    r = parse_pdf(pdf)
    if r:
        results.append(r)
        print(f"  Parseado: {pdf.name} → {r}")

results.extend(incidencias)

if results:
    write_results(results)
    print(f"=== {len(results)} registros escritos al Sheet ===")
else:
    print("=== Sin resultados para escribir ===")
