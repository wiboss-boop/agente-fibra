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

- Al crear el mes, el ID queda anotado en config/sheets_mensuales.json (lo leen los
  generadores del cierre; antes había que copiarlo a mano al dict SHEETS).

Sin OAuth (--id). Crear el archivo necesita el token de Drive de la cuenta humana, y ese
token caduca: el 01-oct-2026 daba invalid_grant, y renovarlo pide aceptar un consentimiento
en el navegador. Si no hay nadie para aceptarlo, la cuenta humana crea un Google Sheet VACÍO
con el título del mes (en drive.google.com o con el conector de Drive), lo comparte como
Editor con el service account, y este script lo monta con el service account: mismas
pestañas, valores, fórmulas y registro que al crearlo.

Uso:
    crear_sheet_mensual.py --mes SEPTIEMBRE_2026 [--source <id-o-url-del-mes-anterior>] [--write]
    crear_sheet_mensual.py --mes OCTUBRE_2026 --id <id-o-url-del-sheet-vacío> [--write]
    crear_sheet_mensual.py --mes OCTUBRE_2026 --reautorizar --write   # renueva el token

Sin --source se toma el Sheet del mes anterior del registro.
Sin --write es dry-run: no crea nada, solo imprime el plan de pestañas (con --id, además
comprueba el Sheet vacío).
"""
import argparse
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from src import meses

# El agente en prod escribe con el service account -> hay que darle acceso de editor.
SA_FILE = os.environ.get(
    "SECOMCOL_SA_FILE",
    "/Users/samaro/Documents/secomcol-bot/secomcol-bot-54966487a09b.json",
)
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


def _sa_email():
    """Email del service account del agente. Se lee tarde: sin el JSON el script
    seguía sirviendo para el dry-run, pero antes reventaba al importarlo."""
    try:
        return json.loads(Path(SA_FILE).read_text())["client_email"]
    except (OSError, KeyError, json.JSONDecodeError) as exc:
        sys.exit(f"No se pudo leer el service account en {SA_FILE}: {exc}\n"
                 "Ajusta la ruta con SECOMCOL_SA_FILE=/ruta/al/service_account.json")


def _sa_creds():
    """Credenciales del service account: todo lo que necesita el montaje con --id."""
    from google.oauth2 import service_account

    _sa_email()   # si falta el JSON, el mismo error claro de siempre
    return service_account.Credentials.from_service_account_file(SA_FILE, scopes=SCOPES)


def _sin_token(mes, motivo):
    """Qué hacer cuando el token de Drive no sirve y nadie ha pedido --reautorizar."""
    try:
        sa = json.loads(Path(SA_FILE).read_text())["client_email"]
    except (OSError, KeyError, json.JSONDecodeError):
        sa = f"el service account (client_email de {SA_FILE})"
    return (
        f"\n✗ El token de Drive de la cuenta humana ({OAUTH_TOKEN}) {motivo}.\n"
        "  Renovarlo pide aceptar un consentimiento de Google en el navegador. Dos salidas:\n\n"
        "  · Sin OAuth, sin nadie delante:\n"
        f"      1. Con la cuenta humana, crea un Google Sheet VACÍO titulado {mes}, en la raíz\n"
        "         de Mi unidad como los otros meses (drive.google.com o el conector de Drive).\n"
        f"      2. Compártelo como Editor con {sa}\n"
        f"      3. crear_sheet_mensual.py --mes {mes} --id <id-del-sheet> --write\n"
        "         (o, desde el cierre: cierre_mensual.py --paso 1 --write --id <id-del-sheet>)\n\n"
        "  · Renovar el token, con alguien delante del navegador:\n"
        f"      crear_sheet_mensual.py --mes {mes} --reautorizar --write"
    )


def _creds(mes, reautorizar):
    """OAuth de la cuenta humana (salamanca118) con scope de Drive.

    El refresh token caduca (el 01-oct-2026, tras un mes sin usarse, daba invalid_grant).
    Antes el script abría entonces el navegador y se quedaba esperando a que alguien
    aceptara; ahora solo lo abre con --reautorizar, y si no explica la vía sin OAuth (--id).
    """
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from google_auth_oauthlib.flow import InstalledAppFlow

    from google.auth.exceptions import RefreshError

    creds = None
    if Path(OAUTH_TOKEN).exists():
        creds = Credentials.from_authorized_user_file(OAUTH_TOKEN, SCOPES)
    if not creds or not creds.valid:
        motivo = "no existe" if creds is None else "no es válido"
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except RefreshError as exc:
                # el refresh token caduca (app en modo testing) -> volver a consentir
                creds = None
                motivo = f"está caducado o revocado ({exc.args[0] if exc.args else exc})"
        if not creds or not creds.valid:
            if not reautorizar:
                sys.exit(_sin_token(mes, motivo))
            print(f"⚠ el token de Drive {motivo}: abriendo el consentimiento en el navegador…")
            flow = InstalledAppFlow.from_client_secrets_file(OAUTH_CLIENT, SCOPES)
            creds = flow.run_local_server(port=0, prompt="consent")
        Path(OAUTH_TOKEN).write_text(creds.to_json())
    return creds


def _sheet_id(valor):
    """Acepta el ID pelado o la URL completa del spreadsheet."""
    m = re.search(r"/spreadsheets/d/([A-Za-z0-9_-]+)", valor)
    return m.group(1) if m else valor


def _plan(src_tabs):
    """Qué copiar de cada pestaña del origen: [(tab, modo)] en ORDEN.

    modo: 'full' (íntegra) | 'header2' (filas 1-2) | 'header1' (fila 1).
    """
    plan = []
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
    return plan


def _comprobar_destino(sheets, drive, nuevo_id, titulo, plan, destino):
    """El Sheet de --id: que el service account pueda editarlo y que sea el vacío del mes.

    Devuelve sus metadatos. Si algo no cuadra aborta sin escribir nada: borrar la pestaña
    que trae el archivo vacío en el Sheet equivocado sería perder datos.
    """
    try:
        meta = sheets.spreadsheets().get(spreadsheetId=nuevo_id).execute()
        archivo = drive.files().get(
            fileId=nuevo_id, fields="owners(emailAddress),capabilities(canEdit)",
            supportsAllDrives=True).execute()
    except HttpError as exc:
        sys.exit(f"✗ El service account no puede abrir {nuevo_id} (HTTP {exc.resp.status}).\n"
                 f"  Revisa el ID y compártelo como Editor con {_sa_email()}")
    pestanas = [s["properties"]["title"] for s in meta["sheets"]]
    duenos = ", ".join(o["emailAddress"] for o in archivo.get("owners", [])) or "?"
    print(f"Destino: {meta['properties']['title']} ({nuevo_id}), de {duenos}; "
          f"pestañas: {pestanas}")

    problemas = []
    if not archivo.get("capabilities", {}).get("canEdit"):
        problemas.append("el service account solo puede verlo: compártelo como Editor")
    if meta["properties"]["title"] != titulo:
        problemas.append(f"se llama {meta['properties']['title']!r}, no {titulo!r}: "
                         "¿es el Sheet que toca?")
    ya = [tab for tab, _ in plan if tab in pestanas]
    if ya:
        problemas.append(f"ya tiene pestañas del mes ({', '.join(ya)}): ¿ya está montado?")
    valores = sheets.spreadsheets().values().batchGet(
        spreadsheetId=nuevo_id, ranges=[f"'{tab}'" for tab in pestanas]).execute()["valueRanges"]
    con_datos = [tab for tab, vr in zip(pestanas, valores) if vr.get("values") and tab not in ya]
    if con_datos:
        problemas.append(f"no está vacío: hay datos en {', '.join(con_datos)}")
    if destino:
        registrado = meses.sheet_id(*destino)
        if registrado and registrado != nuevo_id:
            problemas.append(f"el registro ya tiene otro Sheet para {destino[0]} {destino[1]}: "
                             f"{registrado}")
    if problemas:
        sys.exit("✗ No se monta nada:\n  · " + "\n  · ".join(problemas))
    return meta


def _preparar_destino(sheets, nuevo_id, src_meta, meta, plan):
    """Crea las pestañas del plan en ORDEN en el Sheet de --id y quita las que traía.

    Locale y zona horaria se igualan a los del origen: el archivo vacío puede venir de la UI
    o del conector, y USER_ENTERED interpreta los precios de Base según el locale.
    Devuelve {tab: sheetId}.
    """
    origen, actual = src_meta["properties"], meta["properties"]
    props = {k: origen[k] for k in ("locale", "timeZone")
             if origen.get(k) and origen[k] != actual.get(k)}
    requests = []
    if props:
        requests.append({"updateSpreadsheetProperties": {
            "properties": props, "fields": ",".join(props)}})
    requests += [{"addSheet": {"properties": {"title": tab, "index": i}}}
                 for i, (tab, _) in enumerate(plan)]
    requests += [{"deleteSheet": {"sheetId": s["properties"]["sheetId"]}} for s in meta["sheets"]]
    resp = sheets.spreadsheets().batchUpdate(
        spreadsheetId=nuevo_id, body={"requests": requests}).execute()
    if props:
        print(f"   Locale/zona horaria igualados al origen: {props}")
    return {r["addSheet"]["properties"]["title"]: r["addSheet"]["properties"]["sheetId"]
            for r in resp["replies"] if "addSheet" in r}


def _poblar(sheets, source_id, nuevo_id, plan, ids_nuevo):
    """Valores del origen según el plan + fórmulas de tarifado y formato € en los técnicos."""
    # leer valores del origen según el modo
    def leer(tab, modo):
        if modo == "full":
            rng = f"'{tab}'"
        elif modo == "header2":
            rng = f"'{tab}'!A1:Z2"
        else:  # header1
            rng = f"'{tab}'!A1:Z1"
        return sheets.spreadsheets().values().get(
            spreadsheetId=source_id, range=rng).execute().get("values", [])

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


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--mes", required=True,
                    help="título del sheet nuevo, p.ej. SEPTIEMBRE_2026")
    ap.add_argument("--source",
                    help="ID o URL del sheet del mes anterior (origen de la estructura); "
                         "por defecto, el del mes anterior en config/sheets_mensuales.json")
    ap.add_argument("--id",
                    help="ID o URL de un Google Sheet VACÍO con el título del mes, creado por "
                         "la cuenta humana y compartido como Editor con el service account: "
                         "se monta con el service account, sin el token de Drive")
    ap.add_argument("--reautorizar", action="store_true",
                    help="si el token de Drive no sirve, abrir el consentimiento de Google en "
                         "el navegador (hace falta alguien delante para aceptarlo)")
    ap.add_argument("--write", action="store_true",
                    help="crea el sheet de verdad (sin este flag es dry-run)")
    args = ap.parse_args()
    if args.id and args.reautorizar:
        ap.error("--id no usa el token de Drive: sobra --reautorizar")

    write = args.write
    NUEVO_TITULO = args.mes
    # El título manda: de él salen el mes y el año con los que se anota el ID en el
    # registro y con los que se busca el origen. Si no es MES_AÑO, se exige --source.
    destino = meses.parse_titulo(NUEVO_TITULO)

    if args.source:
        SOURCE_ID = _sheet_id(args.source)
    else:
        if not destino:
            ap.error(f"--mes '{NUEVO_TITULO}' no es MES_AÑO: pasa el origen con --source")
        mes_prev, anio_prev = meses.anterior(meses.numero(destino[0]), destino[1])
        SOURCE_ID = meses.sheet_id(meses.nombre(mes_prev), anio_prev)
        if not SOURCE_ID:
            ap.error(f"no hay Sheet registrado para {meses.nombre(mes_prev)} {anio_prev} "
                     f"en {meses.REGISTRO}; pásalo con --source")
        print(f"Origen tomado del registro: {meses.nombre(mes_prev)} {anio_prev}")

    # Con --id todo va con el service account; si no, con el OAuth de la cuenta humana,
    # que es quien crea el archivo (y por eso queda como propietaria).
    creds = _sa_creds() if args.id else _creds(NUEVO_TITULO, args.reautorizar)
    sheets = build("sheets", "v4", credentials=creds)
    drive = build("drive", "v3", credentials=creds)

    src_meta = sheets.spreadsheets().get(spreadsheetId=SOURCE_ID).execute()
    src_tabs = [s["properties"]["title"] for s in src_meta["sheets"]]
    plan = _plan(src_tabs)

    print(f"Origen: {src_meta['properties']['title']} ({SOURCE_ID})")
    print(f"Plan de pestañas para {NUEVO_TITULO}:")
    for tab, modo in plan:
        print(f"  {tab:12} -> {modo}")
    omitidas = [t for t in src_tabs if t not in [p[0] for p in plan]]
    print("Omitidas:", omitidas)

    if args.id:
        nuevo_id = _sheet_id(args.id)
        dest_meta = _comprobar_destino(sheets, drive, nuevo_id, NUEVO_TITULO, plan, destino)

    if not write:
        print(f"\n(dry-run — usa --write para {'montar' if args.id else 'crear'} el sheet)")
        return

    # Antes de crear nada: si falta el JSON del service account, el sheet nuevo se
    # quedaría creado y sin acceso para el agente. Mejor reventar aquí.
    sa_email = _sa_email()

    if args.id:
        ids_nuevo = _preparar_destino(sheets, nuevo_id, src_meta, dest_meta, plan)
    else:
        # crear el spreadsheet nuevo con todas las pestañas
        body = {"properties": {"title": NUEVO_TITULO},
                "sheets": [{"properties": {"title": tab}} for tab, _ in plan]}
        nuevo = sheets.spreadsheets().create(body=body).execute()
        nuevo_id = nuevo["spreadsheetId"]
        ids_nuevo = {s["properties"]["title"]: s["properties"]["sheetId"]
                     for s in nuevo["sheets"]}

    _poblar(sheets, SOURCE_ID, nuevo_id, plan, ids_nuevo)

    if not args.id:
        # dar acceso de editor al service account (el agente en prod escribe con él);
        # con --id ya lo tiene: _comprobar_destino lo exige
        drive.permissions().create(
            fileId=nuevo_id,
            body={"type": "user", "role": "writer", "emailAddress": sa_email},
            sendNotificationEmail=False,
        ).execute()

    # anotar el ID en el registro que leen los generadores del cierre
    if destino:
        meses.registrar_sheet(destino[0], destino[1], nuevo_id)
        print(f"   Registrado en {meses.REGISTRO} como {destino[0]} {destino[1]}")
    else:
        print(f"   ⚠ '{NUEVO_TITULO}' no es MES_AÑO: anota el ID a mano en {meses.REGISTRO}")

    if args.id:
        print(f"\n✅ Montado: {NUEVO_TITULO}")
    else:
        print(f"\n✅ Creado: {NUEVO_TITULO} (propietario: salamanca118)")
    print(f"   ID:  {nuevo_id}")
    print(f"   URL: https://docs.google.com/spreadsheets/d/{nuevo_id}")
    print(f"   Editor: {sa_email} (service account del agente)")
    print("\n⚠ Faltan las DOS variables de Railway (en agosto-2026 solo se cambió")
    print("  la primera y las alarmas escribieron todo el mes en el sheet viejo):")
    print(f"    railway variables -s agente-fibra --set \"ACTIVE_SHEET_ID={nuevo_id}\"")
    print(f"    railway variables -s web --set \"GOOGLE_SHEET_ID_ALARMAS={nuevo_id}\"")


if __name__ == "__main__":
    main()
