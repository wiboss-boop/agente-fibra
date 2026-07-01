"""Escribe las discrepancias reclamables en una pestaña del Sheet del agente."""
from datetime import date

from src.reconciliation.core import ReconResult
from src.reconciliation.extract import linea_of
from src.sheets.auth import get_sheets_service

_HEADER = ["FECHA ALTA", "ORDEN", "LINEA", "TECNICO", "CODIGO",
           "IMPORTE PAGADO TECNICO (EUR)", "ESTADO", "NOTA"]


def write_discrepancias(spreadsheet_id: str, result: ReconResult, periodo: str,
                        tab: str = "Discrepancias") -> str:
    """Crea (o reemplaza) la pestaña `tab` con las altas reclamables. Devuelve la URL."""
    service = get_sheets_service()
    meta = service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    existing = {s["properties"]["title"]: s["properties"]["sheetId"] for s in meta["sheets"]}

    if tab in existing:
        service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"requests": [{"deleteSheet": {"sheetId": existing[tab]}}]},
        ).execute()
    added = service.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={"requests": [{"addSheet": {"properties": {"title": tab}}}]},
    ).execute()
    tab_id = added["replies"][0]["addSheet"]["properties"]["sheetId"]

    hoy = date.today().strftime("%d/%m/%Y")
    if result.corte:
        corte = result.corte.strftime("%d/%m/%Y")
    elif result.corte_por_linea:
        corte = ", ".join(f"{k} {v.strftime('%d/%m/%Y')}" for k, v in result.corte_por_linea.items())
    else:
        corte = "—"
    rows = [
        [f"DISCREPANCIAS {periodo} — altas pagadas al técnico NO certificadas por el contratista (generado {hoy})"],
        [],
        _HEADER,
    ]
    for alta in result.reclamables:
        rows.append([
            alta["fecha"].strftime("%d/%m/%Y") if alta.get("fecha") else "",
            alta["orden"], linea_of(alta["orden"]), alta["tecnico"], alta["codigo"],
            alta["precio"] if alta.get("precio") is not None else "",
            "RECLAMABLE",
            f"Pagada al técnico, sin certificar (fecha ≤ corte {corte})",
        ])
    rows += [
        [],
        ["", "", "", "", "TOTAL RECLAMABLE", round(result.total_reclamable_eur, 2), "", ""],
        [],
        [f"Cruce por nº de orden (absorbe ciclo 21→20 de MASMOVIL). Corte certificación: {corte}."],
        [f"{len(result.pendientes)} altas posteriores al corte quedan pendientes de un anexo futuro (no incluidas)."],
    ]

    service.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id, range=f"'{tab}'!A1",
        valueInputOption="USER_ENTERED", body={"values": rows},
    ).execute()

    service.spreadsheets().batchUpdate(spreadsheetId=spreadsheet_id, body={"requests": [
        {"repeatCell": {"range": {"sheetId": tab_id, "startRowIndex": 2, "endRowIndex": 3},
            "cell": {"userEnteredFormat": {"textFormat": {"bold": True},
                "backgroundColor": {"red": 0.85, "green": 0.85, "blue": 0.85}}},
            "fields": "userEnteredFormat(textFormat,backgroundColor)"}},
        {"repeatCell": {"range": {"sheetId": tab_id, "startRowIndex": 0, "endRowIndex": 1},
            "cell": {"userEnteredFormat": {"textFormat": {"bold": True, "fontSize": 11}}},
            "fields": "userEnteredFormat.textFormat"}},
        {"updateDimensionProperties": {"range": {"sheetId": tab_id, "dimension": "COLUMNS",
            "startIndex": 0, "endIndex": 8}, "properties": {"pixelSize": 160}, "fields": "pixelSize"}},
    ]}).execute()

    return f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit#gid={tab_id}"
