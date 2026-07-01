#!/usr/bin/env python3
"""Genera ALTAS_JUNIO_2026.xlsx desde el Sheet 'JUNIO' del agente.

Reglas acordadas con el usuario:
- Todo es junio 2026. El DÍA de la fecha es correcto; mes/año se fuerzan a 06/2026.
- Precio al técnico: se toma de la columna TECNICO; si está vacío se rellena por código.
- Se excluyen filas que no son órdenes (SIN ALTAS, pies de nómina, festivos, etc.).
- Formato de salida = igual que ALTAS_MAYO_2026.xlsx: una hoja por técnico,
  fila 1 título 'NOMBRE — JUNIO 2026', fila 2 cabecera FECHA|ORDEN|CODIGO|TECNICO.
"""
import re
import sys
from collections import defaultdict

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill

from src.sheets.auth import get_sheets_service

SID = "1JjUY08AJmICiPmc9xXDJEdqKFIv2rIln6AYYWUxzMwI"
TECS = ["CRISTIAN", "MARTIN", "JAMES", "JEAN", "YOHAN", "ERCS",
        "HANS", "JOEL", "DIANA", "AYMAN", "LUIS E"]
OUT = ("/Users/samaro/Library/CloudStorage/GoogleDrive-salamanca118@gmail.com/"
       "Mi unidad/SECOMCOL/CONTABILIDAD/ALTAS POR TECNICO/2026/ALTAS_JUNIO_2026.xlsx")

STOP = {"FESTIVOS", "DESCUENTOS", "TOTAL", "TOTALES", "SUBTOTAL", "IRPF",
        "SECOMCOL", "SEG SOCIAL", "G BRUTA", "SIN ALTAS", "SIN PARTE",
        "RESUMEN", "OBSERVACIONES", "EMBARGO", "MULTA", "GASOLINA"}

# Precio al técnico por código (derivado de junio; consistente con mayo)
PRECIO_TECNICO = {
    "AVERIA OK": 10, "MM01": 27, "MM02": 27, "MM03": 27, "MM04": 27,
    "MM05": 27, "MM06": 27, "MM12": 27, "MM17": 17, "ZA_DESMONTAJE": 10,
    "ZA_INC/MTO/AMP": 14, "ZA_INCIDENCIAS": 14, "ZA_INSTALACION": 30,
    "ZA_TRASLADO": 40,
}


def is_order(orden) -> bool:
    text = str(orden).strip()
    return bool(text) and text != "-" and text.upper() not in STOP \
        and bool(re.search(r"\d", text)) and len(text) >= 5


def day_of(fecha):
    match = re.match(r"(\d{1,2})", str(fecha).strip())
    return int(match.group(1)) if match else None


def money(value):
    text = str(value).replace("€", "").replace(",", "").strip()
    try:
        return float(text)
    except ValueError:
        return None


def main() -> None:
    write = "--write" in sys.argv
    service = get_sheets_service()

    workbook = Workbook()
    workbook.remove(workbook.active)

    title_font = Font(bold=True, size=12)
    header_font = Font(bold=True)
    header_fill = PatternFill("solid", fgColor="D9D9D9")

    total_rows = 0
    total_fixed_date = 0
    total_filled_price = 0
    total_no_price = 0
    summary = []

    for tab in TECS:
        rows = service.spreadsheets().values().get(
            spreadsheetId=SID, range=f"'{tab}'!A3:E"
        ).execute().get("values", [])

        altas = []
        fixed_date = filled_price = no_price = 0
        for row in rows:
            row = row + [""] * (5 - len(row))
            fecha, orden, codigo, _precio_contratista, tecnico = row
            if not is_order(orden):
                continue
            day = day_of(fecha)
            if day is None or not (1 <= day <= 30):
                print(f"  ⚠ {tab}: fecha ilegible {fecha!r} orden={orden} — omitida")
                continue

            fecha_ok = f"{day:02d}/06/2026"
            if str(fecha).strip().replace(" ", "") != fecha_ok:
                fixed_date += 1

            codigo = str(codigo).strip().upper()
            precio = money(tecnico)
            if precio is None:
                precio = PRECIO_TECNICO.get(codigo)
                if precio is not None:
                    filled_price += 1
                else:
                    no_price += 1
            altas.append([fecha_ok, str(orden).strip(), codigo, precio])

        altas.sort(key=lambda a: (day_of(a[0]), a[1]))

        sheet = workbook.create_sheet(tab)
        sheet["A1"] = f"{tab} — JUNIO 2026"
        sheet["A1"].font = title_font
        for col, name in zip("ABCD", ["FECHA", "ORDEN", "CODIGO", "TECNICO"]):
            cell = sheet[f"{col}2"]
            cell.value = name
            cell.font = header_font
            cell.fill = header_fill
        for i, alta in enumerate(altas, start=3):
            for j, val in enumerate(alta):
                sheet.cell(row=i, column=j + 1, value=val)
        for col, width in zip("ABCD", (12, 22, 16, 10)):
            sheet.column_dimensions[col].width = width

        summary.append((tab, len(altas), fixed_date, filled_price, no_price))
        total_rows += len(altas)
        total_fixed_date += fixed_date
        total_filled_price += filled_price
        total_no_price += no_price

    print("\nTécnico    altas  fecha_corr  precio_relleno  sin_precio")
    for tab, n, fd, fp, np in summary:
        print(f"  {tab:8} {n:5}   {fd:8}   {fp:12}   {np}")
    print(f"  {'TOTAL':8} {total_rows:5}   {total_fixed_date:8}   "
          f"{total_filled_price:12}   {total_no_price}")

    if write:
        workbook.save(OUT)
        print(f"\n✅ Escrito: {OUT}")
    else:
        print("\n(dry-run — usa --write para guardar el .xlsx)")


if __name__ == "__main__":
    main()
