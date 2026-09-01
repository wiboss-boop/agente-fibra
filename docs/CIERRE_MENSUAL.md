# Cambio de mes

Todo el cierre se lanza desde `scripts/cierre_mensual.py`, que encadena los pasos en
orden y verifica los dos puntos donde el cierre se ha roto antes.

```bash
# 1. Ver el plan (no toca nada). Los meses se deducen de la fecha de hoy.
PYTHONPATH=. venv/bin/python scripts/cierre_mensual.py

# 2. Ejecutarlo
PYTHONPATH=. venv/bin/python scripts/cierre_mensual.py --write

# Repetir un paso suelto, o cerrar un mes que no es el de hoy
PYTHONPATH=. venv/bin/python scripts/cierre_mensual.py --paso 2 --write
PYTHONPATH=. venv/bin/python scripts/cierre_mensual.py --mes-nuevo SEPTIEMBRE --anio 2026
```

Corre **en el Mac**, no en Railway: necesita el token de Drive de la cuenta humana, el
JSON del service account y la CLI de `railway` logueada.

## Los pasos, y por qué en este orden

| # | Paso | Script | Por qué aquí |
|---|------|--------|--------------|
| 1 | Crear el Sheet del mes nuevo | `crear_sheet_mensual.py` | Lo primero: el agente corre hoy a las 18:00 Bogotá y necesita dónde escribir. |
| 2 | Apuntar Railway al Sheet nuevo | `railway variables` | Hasta que no cambian **las dos** variables, el mes nuevo se escribe en el Sheet viejo. |
| 3 | ALTAS del mes cerrado | `gen_altas_mensual.py` | El mes ya está completo; de aquí sale la nómina. |
| 4 | Registro de jornada del mes cerrado | `gen_jornada_mensual.py` | Se alimenta del `.xlsx` del paso 3. |
| 5 | Conciliación | `conciliar.py` | Manual y más tarde: los anexos del contratista llegan con uno o dos meses de retraso. |

## Las dos variables de Railway

El agente de fibra y el bot de alarmas escriben en el **mismo** spreadsheet, pero cada uno
lo lee de su propia variable:

| Servicio | Variable |
|----------|----------|
| `agente-fibra` | `ACTIVE_SHEET_ID` |
| `web` | `GOOGLE_SHEET_ID_ALARMAS` |

En agosto-2026 solo se cambió la primera y las alarmas escribieron todo el mes en el Sheet
de julio. Por eso el paso 2 vuelve a leer las variables después de escribirlas y aborta si
alguna no apunta al Sheet nuevo.

## Duplicados ambiguos

Una orden no puede pagarse dos veces. Los duplicados del mismo día se colapsan solos, pero
la misma orden en **dos días** o en **dos técnicos** la decide el usuario mes a mes.

El paso 3 corre primero `gen_altas_mensual.py --strict` (código de salida 2 si quedan
ambiguos) y para el cierre. Cuando eso pasa:

1. Mirar el listado que imprime bajo `⚠ REVISAR`.
2. Añadir la decisión a `RESOLUCIONES` en `scripts/gen_altas_mensual.py`, con la clave
   `("MES", AÑO)` — **nunca** heredar las de otro mes: descuadraría la nómina.
3. Repetir: `scripts/cierre_mensual.py --paso 3 --write`.

## Registro de Sheets

`config/sheets_mensuales.json` guarda el ID del spreadsheet de cada mes:

```json
{ "2026": { "AGOSTO": "1-GRoSJ…" } }
```

Lo escribe `crear_sheet_mensual.py --write` al crear el mes y lo leen `cierre_mensual.py`
y `gen_altas_mensual.py`. Antes había que copiar el ID a mano a un dict en el código.
Si un mes se crea a mano, hay que anotarlo aquí.

## Rutas de Google Drive

Los generadores escriben en `Mi unidad/SECOMCOL`. La raíz sale de `SECOMCOL_BASE`, con la
ruta del Mac como valor por defecto; el JSON del service account sale de `SECOMCOL_SA_FILE`.

- `CONTABILIDAD/ALTAS POR TECNICO/<año>/ALTAS_<MES>_<AÑO>.xlsx`
- `CONTABILIDAD/registro jornada/<año>/REGISTRO_JORNADA_<MES>.xlsx`
- `FACTURACION/<año>/<MES>/` — anexos del contratista (ver `src/reconciliation/README.md`)
