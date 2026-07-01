#!/usr/bin/env python3
"""Conciliación mensual: ¿las altas que pagamos a los técnicos nos las certificó el contratista?

Uso:
  venv/bin/python3 conciliar.py MAYO                 # dry-run: imprime el resumen
  venv/bin/python3 conciliar.py MAYO --write         # además escribe la pestaña en el Sheet
  venv/bin/python3 conciliar.py MAYO --anio 2026 --corte 2026-05-20
  venv/bin/python3 conciliar.py MAYO \
      --altas "/ruta/ALTAS_MAYO.xlsx" \
      --anexos "/ruta/anexo1.xlsx" "/ruta/anexo2.xlsx"   # rutas explícitas

Sin --altas/--anexos descubre los archivos automáticamente en la estructura de Google Drive:
  ALTAS:  SECOMCOL/CONTABILIDAD/ALTAS POR TECNICO/<anio>/ALTAS*<MES>*.xlsx
  ANEXOS: SECOMCOL/FACTURACION/<anio>/<MES+1>/ y <MES+2>/  (la carpeta del mes contiene
          los anexos del mes de trabajo anterior; el de <MES+2> cubre el desfase 21→20).
"""
import argparse
import sys
from datetime import datetime
from pathlib import Path

import yaml

from src.reconciliation import extract_altas, extract_anexo, reconcile, linea_of
from src.reconciliation.sheet_writer import write_discrepancias

BASE = Path("/Users/samaro/Library/CloudStorage/GoogleDrive-salamanca118@gmail.com/Mi unidad/SECOMCOL")
MESES = ["ENERO", "FEBRERO", "MARZO", "ABRIL", "MAYO", "JUNIO",
         "JULIO", "AGOSTO", "SEPTIEMBRE", "OCTUBRE", "NOVIEMBRE", "DICIEMBRE"]


def _spreadsheet_id() -> str:
    with open("config/credentials.yaml") as f:
        return yaml.safe_load(f)["google_sheets"]["spreadsheet_id"]


def _is_excel(path: Path) -> bool:
    return path.suffix.lower() == ".xlsx" and not path.name.startswith("~$")


def _is_anexo(path: Path) -> bool:
    """Excluye facturas emitidas y otros .xlsx que no son anexos de certificación."""
    return _is_excel(path) and "FACTURA" not in path.name.upper()


def discover_altas(mes: str, anio: int) -> list[Path]:
    folder = BASE / "CONTABILIDAD" / "ALTAS POR TECNICO" / str(anio)
    return [p for p in folder.glob(f"ALTAS*{mes}*.xlsx") if _is_excel(p)]


def discover_anexos(mes_idx: int, anio: int) -> list[Path]:
    """Anexos del mes de trabajo `mes_idx` (0-based): carpetas de mes+1 y mes+2."""
    found = []
    for offset in (1, 2):
        idx = mes_idx + offset
        if idx >= len(MESES):
            continue
        folder = BASE / "FACTURACION" / str(anio) / MESES[idx]
        if folder.is_dir():
            found += [p for p in folder.glob("*.xlsx") if _is_anexo(p)]
    return found


def main() -> None:
    parser = argparse.ArgumentParser(description="Conciliación altas técnicos vs anexos contratista")
    parser.add_argument("mes", help="Mes de trabajo a conciliar (nombre o número 1-12)")
    parser.add_argument("--anio", type=int, default=datetime.now().year)
    parser.add_argument("--corte", default=None, help="Fecha de corte YYYY-MM-DD (default: última fecha certificada)")
    parser.add_argument("--altas", nargs="+", default=None, help="Rutas explícitas de Excel de ALTAS")
    parser.add_argument("--anexos", nargs="+", default=None, help="Rutas explícitas de anexos")
    parser.add_argument("--write", action="store_true", help="Escribir la pestaña en Google Sheets")
    parser.add_argument("--tab", default=None, help="Nombre de la pestaña destino (default: 'Discrepancias <MES> <AÑO>')")
    args = parser.parse_args()

    mes = MESES[int(args.mes) - 1] if args.mes.isdigit() else args.mes.strip().upper()
    if mes not in MESES:
        sys.exit(f"Mes no reconocido: {args.mes}")
    mes_idx = MESES.index(mes)

    altas_paths = [Path(p) for p in args.altas] if args.altas else discover_altas(mes, args.anio)
    anexo_paths = [Path(p) for p in args.anexos] if args.anexos else discover_anexos(mes_idx, args.anio)

    if not altas_paths:
        sys.exit(f"No se encontró archivo de ALTAS para {mes} {args.anio}")
    if not anexo_paths:
        sys.exit(f"No se encontraron anexos para {mes} {args.anio} (carpetas {MESES[mes_idx+1:mes_idx+3]})")

    print(f"Conciliando {mes} {args.anio}")
    print("ALTAS:")
    for p in altas_paths:
        print(f"  · {p.name}")
    print("ANEXOS:")
    for p in anexo_paths:
        print(f"  · {p.parent.name}/{p.name}")

    altas = [a for p in altas_paths for a in extract_altas(str(p))]
    anexo = [l for p in anexo_paths for l in extract_anexo(str(p))]

    corte = datetime.strptime(args.corte, "%Y-%m-%d").date() if args.corte else None
    result = reconcile(altas, anexo, corte=corte)

    print("\n" + "=" * 60)
    print(f"  Órdenes únicas en ALTAS:  {result.total_altas}")
    print(f"  Órdenes únicas en ANEXOS: {result.total_anexo}")
    print(f"  Coinciden:                {result.coincidentes}")
    cortes = result.corte_por_linea or ({"(global)": result.corte} if result.corte else {})
    print(f"  Corte certificación:      " + ", ".join(f"{k}={v}" for k, v in cortes.items()))
    print(f"  🔴 RECLAMABLES:           {len(result.reclamables)}  ({result.total_reclamable_eur:.2f} EUR)")
    print(f"  🟡 Pendientes (post-corte): {len(result.pendientes)}")
    print(f"  ⚪ Sin fecha legible:      {len(result.sin_fecha)}")
    print(f"  ℹ Certificado sin alta:   {len(result.certificado_sin_alta)}")
    print("=" * 60)
    for a in result.reclamables:
        f = a["fecha"].strftime("%d/%m/%Y") if a.get("fecha") else "—"
        print(f"  {f}  {a['orden']:22} {linea_of(a['orden']):8} {a['tecnico']:9} "
              f"{a['codigo'][:16]:16} {a.get('precio') or '':>5}")

    if args.write:
        tab = args.tab or f"Discrepancias {mes} {args.anio}"
        url = write_discrepancias(_spreadsheet_id(), result, f"{mes} {args.anio}", tab=tab)
        print(f"\n✅ Pestaña '{tab}' escrita. {url}")
    else:
        print("\n(dry-run — usa --write para escribir la pestaña en el Sheet)")


if __name__ == "__main__":
    main()
