#!/usr/bin/env python3
"""Genera REGISTRO_JORNADA_JUNIO.xlsx a partir de la plantilla de mayo.

- Solo se llenan los días que el técnico trabajó (= días con al menos un alta en
  ALTAS_JUNIO_2026.xlsx). Los demás quedan en blanco.
- Cada hoja conserva encabezado, formato, fórmula de total y firmas.
- Patrón por día:
    FULL (7h): 09:00 / 16:00 · 13;00 / 19:00 · ordinarias 7 · total 7
    PART (2h): 11:00 · 13:00 · ordinarias 2 · total 2      (JOEL, AYMAN)
- JAMES se escribe en la hoja de ALVARO (el usuario ajustará el encabezado luego).
- DIEGO no trabajó en junio → hoja en blanco.
- OJO: las hojas NO están todas alineadas — ALVARO/DIEGO no tienen fila "Periodo de
  liquidación", así que su rejilla arranca una fila más arriba. Por eso la rejilla se
  localiza por contenido ("Día del mes" / "Total horas mes"), no por fila fija.
"""
from datetime import date, time

from openpyxl import load_workbook
from openpyxl.cell.cell import MergedCell

from src.reconciliation.extract import parse_date

ALTAS = ("/Users/samaro/Library/CloudStorage/GoogleDrive-salamanca118@gmail.com/"
         "Mi unidad/SECOMCOL/CONTABILIDAD/ALTAS POR TECNICO/2026/ALTAS_JUNIO_2026.xlsx")
TEMPLATE = ("/Users/samaro/Library/CloudStorage/GoogleDrive-salamanca118@gmail.com/"
            "Mi unidad/SECOMCOL/CONTABILIDAD/registro jornada/2026/REGISTRO_JORNADA_MAYO.xlsx")
OUT = ("/Users/samaro/Library/CloudStorage/GoogleDrive-salamanca118@gmail.com/"
       "Mi unidad/SECOMCOL/CONTABILIDAD/registro jornada/2026/REGISTRO_JORNADA_JUNIO.xlsx")

INICIO = date(2026, 6, 1)
FIN = date(2026, 6, 30)
DIAS_MES = 30

# hoja del registro -> (técnico en ALTAS, patrón)   None = dejar en blanco
MAPEO = {
    "CRISTIAN":   ("CRISTIAN", "FULL"),
    "HANS":       ("HANS",     "FULL"),
    "JEAN MARCO": ("JEAN",     "FULL"),
    "JOEL":       ("JOEL",     "PART"),
    "ALVARO":     ("JAMES",    "FULL"),   # ← JAMES escrito aquí (ajustar encabezado)
    "ERCS":       ("ERCS",     "FULL"),
    "YOHAN":      ("YOHAN",    "FULL"),
    "MARTIN":     ("MARTIN",   "FULL"),
    "DIANA":      ("DIANA",    "FULL"),
    "DIEGO":      (None,       "FULL"),   # sin altas en junio
    "AYMAN":      ("AYMAN",    "PART"),
}


def dias_trabajados(path):
    """Devuelve {tecnico: set(días)} a partir de las altas de junio."""
    wb = load_workbook(path, data_only=True)
    dias = {}
    for ws in wb.worksheets:
        s = set()
        for row in list(ws.iter_rows(values_only=True))[2:]:
            if not row or row[0] is None or row[1] in (None, "", "ORDEN"):
                continue
            fecha = parse_date(row[0])
            if fecha and fecha.month == 6:
                s.add(fecha.day)
        dias[ws.title] = s
    return dias


def _set(ws, fila, col, valor, fmt=None):
    cell = ws.cell(row=fila, column=col)
    if isinstance(cell, MergedCell):
        return
    cell.value = valor
    if fmt:
        cell.number_format = fmt


def _texto(ws, fila):
    v = ws.cell(fila, 1).value
    return str(v).strip() if v is not None else ""


def localizar(ws):
    """Devuelve (fila_dia1, fila_total, fila_periodo|None, fila_recibido|None)."""
    fila_header = fila_total = fila_periodo = fila_recibido = None
    for r in range(1, ws.max_row + 1):
        t = _texto(ws, r).lower()
        if t.startswith("día del mes") or t.startswith("dia del mes"):
            fila_header = r
        elif t.startswith("total horas mes"):
            fila_total = r
        elif t.startswith("periodo de liquidaci"):
            fila_periodo = r
        elif t.startswith("recibido por el trabajador"):
            fila_recibido = r + 1   # la fecha va en la fila siguiente, col A
    return fila_header + 2, fila_total, fila_periodo, fila_recibido


def escribir_full(ws, fila):
    _set(ws, fila, 2, "09:00")
    _set(ws, fila, 3, time(16, 0), "hh:mm")
    _set(ws, fila, 4, "13;00")
    _set(ws, fila, 5, "19:00")
    _set(ws, fila, 6, 7)
    _set(ws, fila, 9, 7)


def escribir_part(ws, fila):
    _set(ws, fila, 2, time(11, 0), "hh:mm")
    _set(ws, fila, 3, None)
    _set(ws, fila, 4, time(13, 0), "hh:mm")
    _set(ws, fila, 5, None)
    _set(ws, fila, 6, 2)
    _set(ws, fila, 9, 2)


def main():
    dias = dias_trabajados(ALTAS)
    wb = load_workbook(TEMPLATE)

    resumen = []
    for hoja, (tecnico, patron) in MAPEO.items():
        ws = wb[hoja]
        fila1, fila_total, fila_periodo, fila_recibido = localizar(ws)

        # mapa día -> fila (primera aparición del número de día en col A)
        dia_a_fila = {}
        for r in range(fila1, fila_total):
            v = ws.cell(r, 1).value
            if isinstance(v, int) and 1 <= v <= 31 and v not in dia_a_fila:
                dia_a_fila[v] = r

        # limpiar toda la rejilla (cols B..I) y borrar días > 30 (junio tiene 30)
        for r in range(fila1, fila_total):
            for c in range(2, 10):
                _set(ws, r, c, None)
            v = ws.cell(r, 1).value
            if isinstance(v, int) and v > DIAS_MES:
                _set(ws, r, 1, None)

        # periodo (si la hoja tiene esa fila) y fecha de recibido
        if fila_periodo:
            _set(ws, fila_periodo, 4, INICIO)
            _set(ws, fila_periodo, 10, FIN)
        if fila_recibido:
            _set(ws, fila_recibido, 1, FIN)

        trabajados = sorted(d for d in dias.get(tecnico, set()) if 1 <= d <= DIAS_MES) if tecnico else []
        for d in trabajados:
            fila = dia_a_fila.get(d)
            if fila:
                (escribir_full if patron == "FULL" else escribir_part)(ws, fila)

        etiqueta = hoja if (tecnico is None or tecnico == hoja) else f"{hoja}→{tecnico}"
        resumen.append((etiqueta, patron, len(trabajados), fila_periodo is not None, trabajados))

    wb.save(OUT)

    print("Hoja             patrón  días  periodo?  (días)")
    for etiqueta, patron, n, tiene_periodo, dd in resumen:
        print(f"  {etiqueta:16} {patron:5} {n:4}   {'sí' if tiene_periodo else 'NO':7} {dd}")
    faltan = set(dias) - {t for t, _ in MAPEO.values() if t}
    print("\nTécnicos con altas SIN hoja en el registro:", sorted(faltan))
    print(f"\n✅ Escrito: {OUT}")


if __name__ == "__main__":
    main()
