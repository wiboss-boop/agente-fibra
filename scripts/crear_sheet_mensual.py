#!/usr/bin/env python3
"""Crea el spreadsheet fibra del mes duplicando la estructura del sheet del mes anterior.

- Técnicos: solo encabezado (filas 1-2: nombre + FECHA/ORDEN/CODIGO/PRECIO/TECNICO), SIN datos,
  y fórmulas VLOOKUP contra Base sembradas en D3:E500 (el agente de fibra solo escribe A-C;
  sin las fórmulas, PRECIO/TECNICO quedan vacíos — pasó todo agosto-2026).
- Base / Hoja6: contenido íntegro.
- Descuentos: solo encabezado (fila 1).
- Se omiten Hoja1 y las pestañas 'Discrepancias …' viejas.
- Se crea con la cuenta humana (salamanca118) y se da acceso de editor al SERVICE ACCOUNT
  (misma identidad con la que el agente escribe en prod).

Uso:
    crear_sheet_mensual.py --mes AGOSTO_2026 --source <id-o-url-del-mes-anterior> [--write]

Sin --write es dry-run: no crea nada, solo imprime el plan de pestañas.
"""
import argparse
import json
import os
import re
import sys
from pathlib import Path

from googleapiclient.discovery import build

SA_FILE = "/Users/samaro/Documents/secomcol-bot/secomcol-bot-54966487a09b.json"
# El agente en prod escribe con el service account -> hay que darle acceso de editor.
SA_EMAIL = json.load(open(SA_FILE))["client_email"]
SCOPES = ["https://www.googleapis.com/auth/spreadsheets",
          "https://www.googleapis.com/auth/drive"]
OAUTH_CLIENT = "config/google_oauth_credentials.json"
OAUTH_TOKEN = "config/token_drive.json"   # token aparte (con scope drive), no toca el del agente

TECNICOS = ["CRISTIAN", "MARTIN", "JAMES", "JEAN", "YOHAN", "ERCS",
            "HANS", "JOEL", "DIANA", "AYMAN", "LUIS E"]
INTEGRAS = ["Base", "Hoja6"]        # copiar íntegras
SOLO_HEADER_1 = ["Descuentos"]      # solo fila 1
OMITIR_PREFIJOS = ("Hoja1", "Discrepancias")

# Orden de las pestañas en el sheet nuevo
ORDEN = ["Base"] + TECNICOS + ["Hoja6", "Descuentos"]

# Las fórmulas de tarifado se siembran hasta esta fila (igual que hacía nuevo_mes.py).
# En las hojas que escribe el bot de alarmas (JEAN/JOEL/DIANA/MARTIN) el bot pisa la
# fórmula con el valor resuelto al escribir cada fila — mismo comportamiento que julio.
FORMULA_LAST_ROW = 500


def _creds():
    """OAuth de la cuenta humana (salamanca118) con scope de Drive."""
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from google_auth_oauthlib.flow import InstalledAppFlow

    from google.auth.exceptions import RefreshError

    creds = None
    if Path(OAUTH_TOKEN).exists():
        creds = Credentials.from_authorized_user_file(OAUTH_TOKEN, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except RefreshError:
                # el refresh token caduca (app en modo testing) -> volver a consentir
                print("⚠ token de Drive caducado, abriendo consentimiento en el navegador…")
                creds = None
        if not creds or not creds.valid:
            flow = InstalledAppFlow.from_client_secrets_file(OAUTH_CLIENT, SCOPES)
            creds = flow.run_local_server(port=0, prompt="consent")
        Path(OAUTH_TOKEN).write_text(creds.to_json())
    return creds


def _sheet_id(valor):
    """Acepta el ID pelado o la URL completa del spreadsheet."""
    m = re.search(r"/spreadsheets/d/([A-Za-z0-9_-]+)", valor)
    return m.group(1) if m else valor


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--mes", required=True,
                    help="título del sheet nuevo, p.ej. AGOSTO_2026")
    ap.add_argument("--source", required=True,
                    help="ID o URL del sheet del mes anterior (origen de la estructura)")
    ap.add_argument("--write", action="store_true",
                    help="crea el sheet de verdad (sin este flag es dry-run)")
    args = ap.parse_args()

    write = args.write
    NUEVO_TITULO = args.mes
    SOURCE_ID = _sheet_id(args.source)
    creds = _creds()
    sheets = build("sheets", "v4", credentials=creds)
    drive = build("drive", "v3", credentials=creds)

    src_meta = sheets.spreadsheets().get(spreadsheetId=SOURCE_ID).execute()
    src_tabs = [s["properties"]["title"] for s in src_meta["sheets"]]

    # decidir qué copiar de cada pestaña del origen
    plan = []  # (tab, modo)  modo: 'full' | 'header2' | 'header1'
    for tab in ORDEN:
        if tab not in src_tabs:
            print(f"  ⚠ {tab} no existe en el origen — se omite")
            continue
        if tab in INTEGRAS:
            modo = "full"
        elif tab in SOLO_HEADER_1:
            modo = "header1"
        else:
            modo = "header2"
        plan.append((tab, modo))

    print(f"Origen: {src_meta['properties']['title']} ({SOURCE_ID})")
    print(f"Plan de pestañas para {NUEVO_TITULO}:")
    for tab, modo in plan:
        print(f"  {tab:12} -> {modo}")
    omitidas = [t for t in src_tabs if t not in [p[0] for p in plan]]
    print("Omitidas:", omitidas)

    if not write:
        print("\n(dry-run — usa --write para crear el sheet)")
        return

    # leer valores del origen según el modo
    def leer(tab, modo):
        if modo == "full":
            rng = f"'{tab}'"
        elif modo == "header2":
            rng = f"'{tab}'!A1:Z2"
        else:  # header1
            rng = f"'{tab}'!A1:Z1"
        return sheets.spreadsheets().values().get(
            spreadsheetId=SOURCE_ID, range=rng).execute().get("values", [])

    # crear el spreadsheet nuevo con todas las pestañas
    body = {"properties": {"title": NUEVO_TITULO},
            "sheets": [{"properties": {"title": tab}} for tab, _ in plan]}
    nuevo = sheets.spreadsheets().create(body=body).execute()
    nuevo_id = nuevo["spreadsheetId"]

    # escribir los valores de cada pestaña
    data = []
    for tab, modo in plan:
        valores = leer(tab, modo)
        if valores:
            data.append({"range": f"'{tab}'!A1", "values": valores})
    if data:
        sheets.spreadsheets().values().batchUpdate(
            spreadsheetId=nuevo_id,
            body={"valueInputOption": "USER_ENTERED", "data": data},
        ).execute()

    # sembrar fórmulas de tarifado en D/E de las hojas de técnico + formato €
    def formulas(row):
        return [f'=IF($C{row}="","",IFERROR(VLOOKUP($C{row},Base!$A:$C,{i},FALSE),""))'
                for i in (2, 3)]

    tabs_tecnico = [tab for tab, modo in plan if modo == "header2"]
    sheets.spreadsheets().values().batchUpdate(
        spreadsheetId=nuevo_id,
        body={"valueInputOption": "USER_ENTERED", "data": [
            {"range": f"'{tab}'!D3:E{FORMULA_LAST_ROW}",
             "values": [formulas(r) for r in range(3, FORMULA_LAST_ROW + 1)]}
            for tab in tabs_tecnico
        ]},
    ).execute()

    ids_nuevo = {s["properties"]["title"]: s["properties"]["sheetId"]
                 for s in nuevo["sheets"]}
    sheets.spreadsheets().batchUpdate(spreadsheetId=nuevo_id, body={"requests": [
        {"repeatCell": {
            "range": {"sheetId": ids_nuevo[tab], "startRowIndex": 2,
                      "endRowIndex": FORMULA_LAST_ROW,
                      "startColumnIndex": 3, "endColumnIndex": 5},
            "cell": {"userEnteredFormat": {"numberFormat":
                     {"type": "CURRENCY", "pattern": '"€"#,##0.00'}}},
            "fields": "userEnteredFormat.numberFormat",
        }} for tab in tabs_tecnico
    ]}).execute()
    print(f"   Fórmulas VLOOKUP sembradas en D3:E{FORMULA_LAST_ROW} "
          f"de {len(tabs_tecnico)} hojas de técnico")

    # dar acceso de editor al service account (el agente en prod escribe con él)
    drive.permissions().create(
        fileId=nuevo_id,
        body={"type": "user", "role": "writer", "emailAddress": SA_EMAIL},
        sendNotificationEmail=False,
    ).execute()

    print(f"\n✅ Creado: {NUEVO_TITULO} (propietario: salamanca118)")
    print(f"   ID:  {nuevo_id}")
    print(f"   URL: https://docs.google.com/spreadsheets/d/{nuevo_id}")
    print(f"   Editor: {SA_EMAIL} (service account del agente)")
    print("\n⚠ Faltan las DOS variables de Railway (en agosto-2026 solo se cambió")
    print("  la primera y las alarmas escribieron todo el mes en el sheet viejo):")
    print(f"    railway variables -s agente-fibra --set \"ACTIVE_SHEET_ID={nuevo_id}\"")
    print(f"    railway variables -s web --set \"GOOGLE_SHEET_ID_ALARMAS={nuevo_id}\"")


if __name__ == "__main__":
    main()
