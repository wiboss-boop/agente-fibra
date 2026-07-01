#!/usr/bin/env python3
"""Crea el spreadsheet fibra de JULIO_2026 duplicando la estructura del sheet actual (JUNIO).

- Técnicos: solo encabezado (filas 1-2: nombre + FECHA/ORDEN/CODIGO/PRECIO/TECNICO), SIN datos.
- Base / Hoja6: contenido íntegro.
- Descuentos: solo encabezado (fila 1).
- Se omiten Hoja1 y las pestañas 'Discrepancias …' viejas.
- Se crea con el SERVICE ACCOUNT (misma identidad que escribe el agente en prod) y se
  comparte con el humano (salamanca118) para que pueda verlo/editarlo.

Uso:  ... crear_sheet_julio.py [--write]   (sin --write = dry-run, no crea nada)
"""
import json
import os
import sys
from pathlib import Path

from googleapiclient.discovery import build

SA_FILE = "/Users/samaro/Documents/secomcol-bot/secomcol-bot-54966487a09b.json"
SOURCE_ID = "1JjUY08AJmICiPmc9xXDJEdqKFIv2rIln6AYYWUxzMwI"   # sheet actual (JUNIO)
NUEVO_TITULO = "JULIO_2026"
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


def _creds():
    """OAuth de la cuenta humana (salamanca118) con scope de Drive."""
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from google_auth_oauthlib.flow import InstalledAppFlow

    creds = None
    if Path(OAUTH_TOKEN).exists():
        creds = Credentials.from_authorized_user_file(OAUTH_TOKEN, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(OAUTH_CLIENT, SCOPES)
            creds = flow.run_local_server(port=0, prompt="consent")
        Path(OAUTH_TOKEN).write_text(creds.to_json())
    return creds


def main():
    write = "--write" in sys.argv
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
    print("Plan de pestañas para JULIO_2026:")
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
    print("\n⚠ Falta apuntar el agente: ACTIVE_SHEET_ID =", nuevo_id)


if __name__ == "__main__":
    main()
