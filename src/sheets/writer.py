"""
Escritura de resultados del parser en Google Sheets.

Estructura esperada por hoja (una por técnico):
  Fila 1 : nombre del técnico
  Fila 2 : cabeceras  →  A=FECHA  B=ORDEN  C=CODIGO  G=NOTAS
  Fila 3+ : datos
"""

import logging
import yaml
from pathlib import Path
from typing import List, Dict, Any, Optional

from src.sheets.auth import get_sheets_service

logger = logging.getLogger(__name__)

_CONFIG_PATH = Path("config/credentials.yaml")

# Columnas de escritura
COL_FECHA   = "A"
COL_ORDEN   = "B"
COL_CODIGO  = "C"
COL_NOTAS   = "G"
FIRST_DATA_ROW = 3  # las filas 1 y 2 son cabecera


# ---------------------------------------------------------------------------
# Configuración
# ---------------------------------------------------------------------------

def _load_spreadsheet_id(config_path: Path = _CONFIG_PATH) -> str:
    with open(config_path) as f:
        cfg = yaml.safe_load(f)
    sid = cfg.get("google_sheets", {}).get("spreadsheet_id", "")
    if not sid:
        raise ValueError(
            "El campo 'google_sheets.spreadsheet_id' está vacío en credentials.yaml.\n"
            "Copia el ID del documento desde la URL: docs.google.com/spreadsheets/d/<ID>/edit"
        )
    return sid


# ---------------------------------------------------------------------------
# Operaciones sobre la hoja
# ---------------------------------------------------------------------------

def _get_sheet_names(service, spreadsheet_id: str) -> List[str]:
    """Devuelve los nombres de todas las hojas del spreadsheet."""
    meta = service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    return [s["properties"]["title"] for s in meta["sheets"]]


def _read_column(
    service,
    spreadsheet_id: str,
    sheet_name: str,
    col: str,
    from_row: int = FIRST_DATA_ROW,
) -> List[str]:
    """Lee una columna completa desde from_row hasta el final de los datos."""
    range_ = f"'{sheet_name}'!{col}{from_row}:{col}"
    result = (
        service.spreadsheets()
        .values()
        .get(spreadsheetId=spreadsheet_id, range=range_)
        .execute()
    )
    rows = result.get("values", [])
    # Cada elemento es una lista de un valor; aplanamos
    return [r[0] if r else "" for r in rows]



def _write_range(
    service,
    spreadsheet_id: str,
    range_: str,
    values: List[List[Any]],
) -> None:
    """Escribe values en range_ usando valueInputOption=USER_ENTERED."""
    body = {"values": values}
    service.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range=range_,
        valueInputOption="USER_ENTERED",
        body=body,
    ).execute()


# ---------------------------------------------------------------------------
# Lógica principal de escritura
# ---------------------------------------------------------------------------

def write_results(records: List[Dict[str, Any]]) -> Dict[str, int]:
    """
    Escribe una lista de registros del parser en las hojas correspondientes.

    Parámetros
    ----------
    records : lista de dicts con claves:
        orden, fecha, tecnico, codigo, incidencia

    Devuelve
    --------
    Dict con contadores: {"escritos": n, "duplicados": n, "omitidos": n}
    """
    service = get_sheets_service()
    spreadsheet_id = _load_spreadsheet_id()

    sheet_names = _get_sheet_names(service, spreadsheet_id)
    logger.info("Hojas disponibles: %s", sheet_names)

    counters = {"escritos": 0, "duplicados": 0, "omitidos": 0}

    # Caché por hoja: set de (fecha, orden) ya existentes + siguiente fila libre
    cache: Dict[str, Dict] = {}

    for rec in records:
        tecnico = rec.get("tecnico")
        orden   = rec.get("orden")
        fecha   = rec.get("fecha") or ""
        codigo  = rec.get("codigo") or ""
        incidencia = rec.get("incidencia", False)

        # Omitir si no hay técnico asignado
        if not tecnico:
            logger.debug("Omitido (sin técnico): orden=%s", orden)
            counters["omitidos"] += 1
            continue

        # Omitir si la hoja del técnico no existe en el spreadsheet
        if tecnico not in sheet_names:
            logger.warning("Hoja '%s' no encontrada en el spreadsheet — omitido", tecnico)
            counters["omitidos"] += 1
            continue

        # Cargar caché de la hoja (una sola lectura por hoja)
        if tecnico not in cache:
            fechas  = _read_column(service, spreadsheet_id, tecnico, COL_FECHA)
            ordenes = _read_column(service, spreadsheet_id, tecnico, COL_ORDEN)
            n = max(len(fechas), len(ordenes))
            fechas  += [""] * (n - len(fechas))
            ordenes += [""] * (n - len(ordenes))
            cache[tecnico] = {
                "keys": set(zip(fechas, ordenes)),   # (fecha, orden) únicos
                "next_row": FIRST_DATA_ROW + n,
            }

        # Verificar duplicado por (fecha, orden) — evita bloquear "-" entre días
        cache_key = (fecha, orden)
        if orden and cache_key in cache[tecnico]["keys"]:
            logger.info("Duplicado omitido: orden=%s fecha=%s en hoja '%s'", orden, fecha, tecnico)
            counters["duplicados"] += 1
            continue

        target_row = cache[tecnico]["next_row"]

        if incidencia:
            _write_incidencia(service, spreadsheet_id, tecnico, target_row, fecha, orden)
        else:
            _write_normal(service, spreadsheet_id, tecnico, target_row, fecha, orden, codigo)

        # Actualizar caché
        cache[tecnico]["keys"].add(cache_key)
        cache[tecnico]["next_row"] += 1

        logger.info(
            "Escrito en '%s' fila %d: orden=%s codigo=%s incidencia=%s",
            tecnico, target_row, orden, codigo, incidencia,
        )
        counters["escritos"] += 1

    return counters


def _write_normal(
    service,
    spreadsheet_id: str,
    sheet: str,
    row: int,
    fecha: str,
    orden: str,
    codigo: str,
) -> None:
    """Escribe una fila normal: FECHA | ORDEN | CODIGO en cols A-C."""
    range_ = f"'{sheet}'!{COL_FECHA}{row}:{COL_CODIGO}{row}"
    _write_range(service, spreadsheet_id, range_, [[fecha, orden, codigo]])


def _write_incidencia(
    service,
    spreadsheet_id: str,
    sheet: str,
    row: int,
    fecha: str,
    orden: str,
) -> None:
    """Escribe FECHA y ORDEN, y marca col G como 'incidencia'."""
    # A y B
    range_ab = f"'{sheet}'!{COL_FECHA}{row}:{COL_ORDEN}{row}"
    _write_range(service, spreadsheet_id, range_ab, [[fecha, orden]])
    # G
    range_g = f"'{sheet}'!{COL_NOTAS}{row}"
    _write_range(service, spreadsheet_id, range_g, [["incidencia"]])


# ---------------------------------------------------------------------------
# Bloque de prueba manual
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    service = get_sheets_service()
    spreadsheet_id = _load_spreadsheet_id()

    # 1. Listar hojas
    sheet_names = _get_sheet_names(service, spreadsheet_id)
    print("\nHojas disponibles en el spreadsheet:")
    for name in sheet_names:
        print(f"  · {name}")

    # 2. Registro de prueba en hoja ERCS
    test_record = {
        "orden":      "TEST_00000000",
        "fecha":      "28/04/2026",
        "tecnico":    "ERCS",
        "codigo":     "MM01",
        "incidencia": False,
    }

    if "ERCS" not in sheet_names:
        print("\nATENCIÓN: la hoja 'ERCS' no existe en el spreadsheet.")
        print("Crea la hoja manualmente y vuelve a ejecutar este script.")
        sys.exit(1)

    print(f"\nEscribiendo registro de prueba en hoja 'ERCS':")
    print(f"  {test_record}")

    counters = write_results([test_record])
    print(f"\nResultado: {counters}")

    if counters["escritos"] == 1:
        print("Registro escrito correctamente.")
    elif counters["duplicados"] == 1:
        print("El registro ya existía (duplicado), no se escribió de nuevo.")
    else:
        print("No se escribió — revisar logs.")
