"""Utilidades de mes para el cierre mensual.

Reúne lo que los cuatro scripts del cierre repetían por su cuenta:

- nombres/números de mes y aritmética con salto de año (DICIEMBRE -> ENERO),
- el registro de spreadsheets mensuales (`config/sheets_mensuales.json`), que sustituye
  al dict SHEETS que había que editar a mano cada mes en gen_altas_mensual.py,
- las rutas de Drive de los .xlsx del cierre, para que cierre_mensual.py sepa si un paso
  ya está hecho mirando la misma ruta en la que escribe el generador.

El registro lo escribe `crear_sheet_mensual.py --write` al crear el mes, y lo leen los
generadores; así el ID del Sheet nunca se teclea dos veces.
"""

import json
import os
from pathlib import Path
from typing import Dict, Optional, Tuple

MESES = ("ENERO", "FEBRERO", "MARZO", "ABRIL", "MAYO", "JUNIO",
         "JULIO", "AGOSTO", "SEPTIEMBRE", "OCTUBRE", "NOVIEMBRE", "DICIEMBRE")

RAIZ = Path(__file__).resolve().parents[1]
REGISTRO = RAIZ / "config" / "sheets_mensuales.json"

# Carpeta SECOMCOL del Drive de la cuenta humana, sincronizada en el Mac. Con
# SECOMCOL_BASE se apunta a otra (p.ej. una copia para probar sin tocar el Drive).
BASE_DRIVE = Path(os.environ.get(
    "SECOMCOL_BASE",
    "/Users/samaro/Library/CloudStorage/GoogleDrive-salamanca118@gmail.com/"
    "Mi unidad/SECOMCOL",
))


def numero(mes: str) -> int:
    """'AGOSTO' -> 8. Lanza ValueError si el mes no existe."""
    nombre_mes = mes.strip().upper()
    if nombre_mes not in MESES:
        raise ValueError(f"mes desconocido: {mes}")
    return MESES.index(nombre_mes) + 1


def nombre(mes_num: int) -> str:
    """8 -> 'AGOSTO'."""
    if not 1 <= mes_num <= 12:
        raise ValueError(f"mes fuera de rango: {mes_num}")
    return MESES[mes_num - 1]


def anterior(mes_num: int, anio: int) -> Tuple[int, int]:
    """Mes anterior con salto de año: (1, 2027) -> (12, 2026)."""
    return (12, anio - 1) if mes_num == 1 else (mes_num - 1, anio)


def siguiente(mes_num: int, anio: int) -> Tuple[int, int]:
    """Mes siguiente con salto de año: (12, 2026) -> (1, 2027)."""
    return (1, anio + 1) if mes_num == 12 else (mes_num + 1, anio)


def parse_titulo(titulo: str) -> Optional[Tuple[str, int]]:
    """'AGOSTO_2026' -> ('AGOSTO', 2026). None si el título no tiene ese formato."""
    partes = titulo.strip().upper().replace("-", "_").replace(" ", "_").split("_")
    if len(partes) == 2 and partes[0] in MESES and partes[1].isdigit():
        return partes[0], int(partes[1])
    return None


# ---------------------------------------------------------------------------
# Registro de spreadsheets mensuales
# ---------------------------------------------------------------------------

def cargar_registro() -> Dict[str, Dict[str, str]]:
    """{'2026': {'AGOSTO': '<id>'}}; dict vacío si el archivo no existe."""
    if not REGISTRO.exists():
        return {}
    return json.loads(REGISTRO.read_text())


def sheet_id(mes: str, anio: int) -> Optional[str]:
    """ID del Sheet del mes, o None si no está registrado."""
    return cargar_registro().get(str(anio), {}).get(mes.strip().upper())


def registrar_sheet(mes: str, anio: int, spreadsheet_id: str) -> None:
    """Anota el Sheet del mes en el registro (idempotente; sobrescribe si cambió)."""
    mes = mes.strip().upper()
    if mes not in MESES:
        raise ValueError(f"mes desconocido: {mes}")
    registro = cargar_registro()
    registro.setdefault(str(anio), {})[mes] = spreadsheet_id
    ordenado = {
        anio_k: {m: registro[anio_k][m] for m in MESES if m in registro[anio_k]}
        for anio_k in sorted(registro)
    }
    REGISTRO.parent.mkdir(parents=True, exist_ok=True)
    REGISTRO.write_text(json.dumps(ordenado, indent=2, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------------------
# Rutas de los .xlsx del cierre en Drive
# ---------------------------------------------------------------------------

def ruta_altas(mes: str, anio: int) -> Path:
    """CONTABILIDAD/ALTAS POR TECNICO/<año>/ALTAS_<MES>_<AÑO>.xlsx"""
    carpeta = BASE_DRIVE / "CONTABILIDAD" / "ALTAS POR TECNICO" / str(anio)
    return carpeta / f"ALTAS_{mes.strip().upper()}_{anio}.xlsx"


def ruta_jornada(mes: str, anio: int) -> Path:
    """CONTABILIDAD/registro jornada/<año>/REGISTRO_JORNADA_<MES>.xlsx

    Se archivan por año aunque el nombre no lo lleve: el de DICIEMBRE, que es la plantilla
    del de ENERO, está en la carpeta del año anterior.
    """
    carpeta = BASE_DRIVE / "CONTABILIDAD" / "registro jornada" / str(anio)
    return carpeta / f"REGISTRO_JORNADA_{mes.strip().upper()}.xlsx"
