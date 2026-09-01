#!/usr/bin/env python3
"""Cambio de mes del agente de fibra: ejecuta los pasos del cierre en el orden correcto.

Los cuatro scripts del cierre ya existían sueltos; lo que fallaba era la coreografía.
En agosto-2026 se creó el Sheet nuevo pero solo se cambió UNA de las dos variables de
Railway, así que el bot de alarmas escribió todo el mes en el Sheet viejo. Este script
encadena los pasos, resuelve los meses solo y VERIFICA que las dos variables quedaron
apuntando al Sheet nuevo.

Pasos (en este orden, y por este motivo):
  1. Crear el Sheet del mes NUEVO.        Lo primero: el agente corre hoy a las 18:00.
  2. Apuntar Railway al Sheet nuevo.      LAS DOS variables, y se comprueba.
  3. ALTAS del mes CERRADO.               El mes ya está completo; se puede cerrar.
  4. REGISTRO DE JORNADA del mes CERRADO. Se alimenta del .xlsx del paso 3.
  5. Conciliación.                        Manual: los anexos del contratista llegan tarde.

Uso:
    cierre_mensual.py                       # plan del cierre de hoy, no toca nada
    cierre_mensual.py --write               # ejecuta los pasos 1-4
    cierre_mensual.py --paso 2 --write      # repite un paso suelto
    cierre_mensual.py --mes-nuevo SEPTIEMBRE --anio 2026

Requisitos (todos locales, no corre en Railway): venv con las dependencias, el token de
Drive de la cuenta humana, el JSON del service account y la CLI de railway logueada.
"""
import argparse
import subprocess
import sys
from datetime import date
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from src import meses

# servicio de Railway -> variable que guarda el Sheet activo.
# Son DOS: el agente de fibra y el bot de alarmas escriben en el mismo spreadsheet.
VARIABLES_RAILWAY = {
    "agente-fibra": "ACTIVE_SHEET_ID",
    "web": "GOOGLE_SHEET_ID_ALARMAS",
}


def _run(cmd, check=True, capture=False):
    """Lanza un comando mostrando la línea exacta. Devuelve el CompletedProcess."""
    print(f"\n$ {' '.join(cmd)}")
    proc = subprocess.run(cmd, cwd=RAIZ, text=True,
                          capture_output=capture)
    if capture and proc.stdout:
        print(proc.stdout, end="")
    if check and proc.returncode != 0:
        sys.exit(f"\n✗ Falló: {' '.join(cmd)} (código {proc.returncode})")
    return proc


def _script(nombre, *args):
    return [sys.executable, str(RAIZ / "scripts" / nombre), *args]


# ---------------------------------------------------------------------------
# Pasos
# ---------------------------------------------------------------------------

def paso_1_crear_sheet(ctx, write):
    """Crea el spreadsheet del mes nuevo y anota su ID en el registro."""
    if meses.sheet_id(ctx["mes_nuevo"], ctx["anio_nuevo"]):
        print(f"  ✓ {ctx['titulo_nuevo']} ya está en el registro — nada que crear")
        return
    cmd = _script("crear_sheet_mensual.py", "--mes", ctx["titulo_nuevo"],
                  "--source", ctx["sid_cerrado"])
    if write:
        _run(cmd + ["--write"])
    else:
        print(f"  $ {' '.join(cmd)} --write")


def paso_2_railway(ctx, write):
    """Apunta LAS DOS variables de Railway al Sheet nuevo y lo verifica."""
    sid = meses.sheet_id(ctx["mes_nuevo"], ctx["anio_nuevo"])
    if not sid:
        if not write:
            print("  (el ID del Sheet nuevo saldrá del paso 1)")
            for servicio, var in VARIABLES_RAILWAY.items():
                print(f"  $ railway variables -s {servicio} --set \"{var}=<id-nuevo>\"")
            return
        sys.exit(f"✗ No hay Sheet registrado para {ctx['titulo_nuevo']}: corre antes el paso 1")

    for servicio, var in VARIABLES_RAILWAY.items():
        cmd = ["railway", "variables", "-s", servicio, "--set", f"{var}={sid}"]
        if write:
            _run(cmd)
        else:
            print(f"  $ {' '.join(cmd)}")

    if not write:
        return

    # Verificación: en agosto-2026 una de las dos se quedó sin cambiar y no se notó
    # hasta fin de mes. Aquí se relee cada servicio y se exige ver el ID nuevo.
    print("\n  Verificando que las dos variables quedaron en el Sheet nuevo…")
    fallos = []
    for servicio, var in VARIABLES_RAILWAY.items():
        proc = _run(["railway", "variables", "-s", servicio], check=False, capture=True)
        if proc.returncode != 0 or sid not in (proc.stdout or ""):
            fallos.append(f"{servicio}/{var}")
    if fallos:
        sys.exit(f"\n✗ Estas variables NO apuntan a {sid}: {', '.join(fallos)}\n"
                 "  Revísalas a mano antes de seguir: si el bot de alarmas escribe en el "
                 "Sheet viejo, las altas del mes se pierden del cierre.")
    print(f"  ✓ {' y '.join(VARIABLES_RAILWAY.values())} apuntan a {sid}")


def paso_3_altas(ctx, write):
    """Genera ALTAS_<MES_CERRADO>_<AÑO>.xlsx, parando si hay duplicados ambiguos."""
    base = _script("gen_altas_mensual.py", "--mes", ctx["mes_cerrado"],
                   "--anio", str(ctx["anio_cerrado"]))
    if not write:
        print(f"  $ {' '.join(base)} --strict      # revisión")
        print(f"  $ {' '.join(base)} --write       # genera el .xlsx")
        return

    # Primero en seco y en modo estricto: los duplicados ambiguos (misma orden en dos
    # días o en dos técnicos) los decide el usuario mes a mes, nunca el script.
    proc = _run(base + ["--strict"], check=False)
    if proc.returncode == 2:
        sys.exit(
            f"\n✗ Hay duplicados ambiguos en {ctx['mes_cerrado']}: una orden no puede "
            "pagarse dos veces.\n"
            "  Decide cada caso y añádelo a RESOLUCIONES en scripts/gen_altas_mensual.py\n"
            f"  con la clave (\"{ctx['mes_cerrado']}\", {ctx['anio_cerrado']}); luego repite:\n"
            f"      {Path(__file__).name} --paso 3 --write")
    if proc.returncode != 0:
        sys.exit(f"\n✗ Falló la revisión de altas (código {proc.returncode})")
    _run(base + ["--write"])


def paso_4_jornada(ctx, write):
    """Genera REGISTRO_JORNADA_<MES_CERRADO>.xlsx a partir de las altas del paso 3."""
    cmd = _script("gen_jornada_mensual.py", "--mes", ctx["mes_cerrado"],
                  "--anio", str(ctx["anio_cerrado"]))
    if write:
        _run(cmd)
    else:
        print(f"  $ {' '.join(cmd)}")


def paso_5_conciliacion(ctx, write):
    """Recordatorio: la conciliación va aparte, cuando el contratista emite los anexos."""
    mes_c, anio_c = meses.anterior(meses.numero(ctx["mes_cerrado"]), ctx["anio_cerrado"])
    print(f"  Manual. Los anexos de {meses.nombre(mes_c)} {anio_c} están en las carpetas de "
          f"FACTURACION de los dos meses siguientes (ciclo MASMOVIL 21→20):")
    print(f"      python conciliar.py {meses.nombre(mes_c)} --anio {anio_c}")
    print(f"      python conciliar.py {meses.nombre(mes_c)} --anio {anio_c} --write")


PASOS = [
    ("Crear el Sheet del mes nuevo", paso_1_crear_sheet),
    ("Apuntar Railway al Sheet nuevo (las DOS variables)", paso_2_railway),
    ("ALTAS del mes cerrado", paso_3_altas),
    ("REGISTRO DE JORNADA del mes cerrado", paso_4_jornada),
    ("Conciliación (manual)", paso_5_conciliacion),
]


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mes-nuevo", help="mes que empieza, p.ej. SEPTIEMBRE (default: el de hoy)")
    ap.add_argument("--anio", type=int, help="año del mes que empieza (default: el de hoy)")
    ap.add_argument("--paso", type=int, choices=range(1, len(PASOS) + 1),
                    help="ejecutar solo este paso")
    ap.add_argument("--write", action="store_true",
                    help="ejecuta de verdad (sin este flag solo imprime el plan)")
    args = ap.parse_args()

    hoy = date.today()
    anio_nuevo = args.anio or hoy.year
    mes_nuevo_num = meses.numero(args.mes_nuevo) if args.mes_nuevo else hoy.month
    mes_nuevo = meses.nombre(mes_nuevo_num)
    mes_cerrado_num, anio_cerrado = meses.anterior(mes_nuevo_num, anio_nuevo)
    mes_cerrado = meses.nombre(mes_cerrado_num)

    sid_cerrado = meses.sheet_id(mes_cerrado, anio_cerrado)
    if not sid_cerrado:
        sys.exit(f"✗ No hay Sheet registrado para {mes_cerrado} {anio_cerrado} en "
                 f"{meses.REGISTRO}.\n  Es el origen del mes nuevo y la fuente de las "
                 "altas: anótalo antes de cerrar.")

    ctx = {
        "mes_nuevo": mes_nuevo, "anio_nuevo": anio_nuevo,
        "titulo_nuevo": f"{mes_nuevo}_{anio_nuevo}",
        "mes_cerrado": mes_cerrado, "anio_cerrado": anio_cerrado,
        "sid_cerrado": sid_cerrado,
    }

    print("=" * 70)
    print(f"  CAMBIO DE MES — cierra {mes_cerrado} {anio_cerrado}, "
          f"empieza {mes_nuevo} {anio_nuevo}")
    print("=" * 70)
    print(f"  Sheet de {mes_cerrado}: {sid_cerrado}")
    sid_nuevo = meses.sheet_id(mes_nuevo, anio_nuevo)
    print(f"  Sheet de {mes_nuevo}:  {sid_nuevo or '(aún no creado)'}")
    if not args.write:
        print("  Modo plan: no se toca nada. Añade --write para ejecutar.")

    seleccion = [args.paso] if args.paso else range(1, len(PASOS) + 1)
    for n in seleccion:
        titulo, funcion = PASOS[n - 1]
        print(f"\n--- Paso {n}. {titulo} " + "-" * max(0, 50 - len(titulo)))
        funcion(ctx, args.write)

    print("\n" + "=" * 70)
    if args.write:
        print(f"  ✅ Cierre de {mes_cerrado} {anio_cerrado} ejecutado")
        print("  Comprueba mañana que el agente escribió en el Sheet nuevo.")
    else:
        print("  (plan — usa --write para ejecutarlo)")
    print("=" * 70)


if __name__ == "__main__":
    main()
