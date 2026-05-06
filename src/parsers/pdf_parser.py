"""
Parser de boletines PDF de instalaciones de fibra óptica.

Soporta los siguientes tipos de documentos:
- "PARTE DE INSTALACIÓN"   (Kairos / MásMóvil / Yoigo)
- "Boletín digital"        (Orange)
- "CIERRE PETICIÓN"        (avería clásica, campo Código de OT)
- "CIERRE DE INCIDENCIA"   (ATC nuevo, campo Código de Petición)
"""

import re
import logging
from pathlib import Path
from typing import Optional, Tuple

import pdfplumber

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Mapeo de códigos de técnico a nombre de hoja
# ---------------------------------------------------------------------------

TECHNICIAN_MAP: dict[str, str] = {
    "Z2168": "DIEGO",
    "Z2220": "ERCS",
    "Z2174": "CRISTIAN",
    "Z2252": "MARTIN",
    "Z2170": "ALVARO",
    "Z2169": "YOHAN",
    "Z2604": "HANS",
    "Z2494": "LUIS E",
}

# ---------------------------------------------------------------------------
# Tabla de metros → código
# ---------------------------------------------------------------------------

def _meters_to_code(meters: float) -> str:
    if meters <= 20:
        return "MM01"
    if meters <= 30:
        return "MM02"
    if meters <= 50:
        return "MM04"
    if meters <= 60:
        return "MM05"
    return "MM06"


# ---------------------------------------------------------------------------
# Extracción de texto del PDF
# ---------------------------------------------------------------------------

def _extract_text(filepath: Path) -> str:
    """Concatena el texto de todas las páginas del PDF."""
    pages = []
    with pdfplumber.open(filepath) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                pages.append(text)
    return "\n".join(pages)


# ---------------------------------------------------------------------------
# Detección del tipo de documento
# ---------------------------------------------------------------------------

def _detect_pdf_type(text: str) -> str:
    """Devuelve 'atc', 'kairos', 'orange', 'averia' o 'unknown'."""
    # ATC: campo "Código de Petición" (formato nuevo) O título "CIERRE DE INCIDENCIA" (cualquier variante)
    if re.search(r'c[oó]digo\s+de\s+petici[oó]n', text, re.IGNORECASE):
        return "atc"
    first_line = text.split('\n')[0].strip().upper()
    if "CIERRE DE INCIDENCIA" in first_line:
        return "atc"
    normalized = text.upper()
    if "CIERRE PETICI" in normalized:
        return "averia"
    if "PARTE DE INSTALACI" in normalized:
        return "kairos"
    if "BOLET" in normalized and "DIGITAL" in normalized:
        return "orange"
    if "DATOS ACOMETIDA" in normalized:
        return "orange"
    return "unknown"


# ---------------------------------------------------------------------------
# Extracción de campos individuales
# ---------------------------------------------------------------------------

def _find_field(text: str, *labels: str) -> Optional[str]:
    """
    Busca el primer label que aparezca en el texto y devuelve su valor.
    Soporta formatos:
      - "Label: valor"  (mismo línea)
      - "Label:\n• valor"  (valor en línea siguiente con bullet)
    """
    for label in labels:
        pattern = rf'{re.escape(label)}\s*:?\s*([^\n]+)'
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            value = match.group(1).strip()
            if value:
                return value
        # Valor en línea siguiente con bullet (• o -)
        pattern2 = rf'{re.escape(label)}\s*:?\s*\n\s*[•\-]\s*([^\n]+)'
        match2 = re.search(pattern2, text, re.IGNORECASE)
        if match2:
            value = match2.group(1).strip().lstrip('•\-– ').strip()
            if value:
                return value
    return None


def _extract_orden(text: str, pdf_type: str) -> Optional[str]:
    if pdf_type == "kairos":
        raw = _find_field(text, "Código de instalación", "Código instalación", "Nº de instalación")
    elif pdf_type == "atc":
        raw = _find_field(text, "Código de Petición", "Código de petición", "Código de OT", "Código OT")
    elif pdf_type == "averia":
        raw = _find_field(text, "Código de OT", "Código OT", "Código de instalación")
    else:
        raw = _find_field(text, "Identificador OT", "Código", "Cód.", "Referencia")
    if raw:
        return raw.split()[0]
    return None


def _extract_fecha(text: str) -> Optional[str]:
    raw = _find_field(text, "Fecha")
    if raw:
        date_match = re.search(r'\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4}', raw)
        if date_match:
            return date_match.group(0)
        # Si el campo contiene solo la fecha sin separadores claros
        return raw.split()[0]
    # Fallback: buscar cualquier fecha en el documento
    date_match = re.search(r'\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4}', text)
    return date_match.group(0) if date_match else None


def _extract_tecnico(text: str) -> Optional[str]:
    # Primero intentar con el campo explícito "Código de técnico:" para mayor precisión
    field = _find_field(text, "Código de técnico", "Técnico")
    if field:
        token = field.split()[0]
        if token in TECHNICIAN_MAP:
            return TECHNICIAN_MAP[token]
    # Fallback: buscar cualquier código Z en el texto
    for code, name in TECHNICIAN_MAP.items():
        if code in text:
            return name
    return None


# ---------------------------------------------------------------------------
# Extracción de metros desde un fragmento de texto
# ---------------------------------------------------------------------------

def _extract_meters(text: str) -> Optional[float]:
    """
    Detecta patrones como: "20m", "20 m", "20 metros", "20mt", "20,5 m".
    Excluye velocidades de red (Mb, MB, Mbps, M/M) mediante lookahead negativo.
    Devuelve None si no encuentra ninguno.
    """
    # "metros"/"mt" son inequívocos.
    # "m" sola: se acepta solo si NO va seguida de b/B/p/P/s/S (Mb, MB, Mbps) ni de "/"
    pattern = r'(\d+(?:[.,]\d+)?)\s*(?:metros?|mt\b|m(?![bBpPsS/])\b)'
    for match in re.finditer(pattern, text, re.IGNORECASE):
        value = float(match.group(1).replace(',', '.'))
        # Longitudes de acometida plausibles: 1–500 m
        if 1 <= value <= 500:
            return value
    return None


# ---------------------------------------------------------------------------
# Determinación del código según tipo de PDF
# ---------------------------------------------------------------------------

def _codigo_kairos(text: str) -> Tuple[Optional[str], bool]:
    """
    Devuelve (codigo, incidencia).
    Busca el campo "Tipo acometida:" y aplica la tabla de clasificación.
    """
    tipo_raw = _find_field(text, "Tipo acometida", "Tipo de acometida")
    if not tipo_raw:
        logger.debug("Campo 'Tipo acometida' no encontrado en PDF Kairos")
        return None, True

    tipo_lower = tipo_raw.lower()

    if "reutilizada" in tipo_lower:
        return "MM17", False

    # Intentar extraer metros del propio campo
    meters = _extract_meters(tipo_raw)

    # Si no hay metros en el campo tipo, buscar en "Longitud exterior"
    if meters is None and ("nueva" in tipo_lower or "exterior" in tipo_lower):
        longitud_raw = _find_field(text, "Longitud exterior", "Longitud acometida", "Longitud")
        if longitud_raw:
            meters = _extract_meters(longitud_raw)
            if meters is None:
                import re as _re
                longitud_clean = longitud_raw.strip().lstrip("•\-– ").strip()
                m = _re.match(r"(\d+(?:[.,]\d+)?)", longitud_clean)
                if m:
                    meters = float(m.group(1).replace(",", "."))
        # Sin longitud especificada: asumir MM01 (<=20m)
        return _meters_to_code(meters if meters is not None else 20), False

    if meters is not None:
        return _meters_to_code(meters), False

    logger.debug("No se pudo determinar código desde 'Tipo acometida': %s", tipo_raw)
    return None, True


def _codigo_averia(text: str) -> Tuple[Optional[str], bool]:
    """
    Devuelve (codigo, incidencia) para documentos "CIERRE PETICIÓN".
    Busca indicadores de resolución en la sección de verificación.
    """
    resuelta = bool(re.search(
        r'reparada\s+la\s+av[eé]r[ií]a|av[eé]r[ií]a\s+resuelta|cliente\s+conforme',
        text,
        re.IGNORECASE,
    ))
    no_resuelta = bool(re.search(
        r'no\s+resuelta|no\s+reparada|pendiente\s+de\s+resoluci[oó]n',
        text,
        re.IGNORECASE,
    ))

    if resuelta and not no_resuelta:
        return "AVERIA OK", False
    if no_resuelta:
        return "AVERIA KO", False

    logger.debug("No se pudo determinar resolución de avería")
    return None, True


def _codigo_atc(text: str) -> Tuple[Optional[str], bool, bool]:
    """
    Devuelve (codigo, incidencia, skip) para ATCs nuevos (campo 'Código de Petición').

    Reglas según primera línea (título):
      - contiene "KO"                → skip=True (no registrar en Sheets)
      - contiene "CIERRE DE INCIDENCIA" + "OK" → incidencia=True, codigo=None
      - contiene "OK" (cualquier otro) → incidencia=False, codigo="AVERIA OK"
    """
    first_line = text.split('\n')[0].strip().upper()

    if "KO" in first_line and "OK" not in first_line:
        return None, False, True

    return "AVERIA OK", False, False


def _codigo_orange(text: str) -> Tuple[Optional[str], bool]:
    """
    Devuelve (codigo, incidencia).
    Posventa OK → AVERIA OK. Sin metros → MM17. Con metros → MM0x.
    """
    # Boletín Posventa = avería resuelta
    if re.search(r'bolet[ií]n\s+digital\s+posventa', text, re.IGNORECASE):
        return "AVERIA OK", False
    meters = _extract_meters(text)
    if meters is not None:
        return _meters_to_code(meters), False
    return "MM17", False


# ---------------------------------------------------------------------------
# Función pública principal
# ---------------------------------------------------------------------------

def parse_pdf(filepath) -> dict:
    """
    Extrae los campos relevantes de un boletín PDF de instalación de fibra.

    Returns
    -------
    dict con claves:
        orden      : Optional[str]  — número/código de orden
        fecha      : Optional[str]  — fecha en formato dd/mm/aaaa (o como aparezca)
        tecnico    : Optional[str]  — nombre del técnico (DIEGO, CRISTIAN, …)
        codigo     : Optional[str]  — MM01…MM06 / MM17 / None si incidencia
        incidencia : bool        — True si no se pudo determinar el código
    """
    path = Path(filepath)
    logger.info("Procesando PDF: %s", path.name)

    text = _extract_text(path)
    if not text.strip():
        logger.warning("PDF sin texto extraíble: %s", path.name)
        return {
            "orden": None,
            "fecha": None,
            "tecnico": None,
            "codigo": None,
            "incidencia": True,
        }

    pdf_type = _detect_pdf_type(text)
    logger.debug("Tipo de PDF detectado: %s", pdf_type)

    orden = _extract_orden(text, pdf_type)
    fecha = _extract_fecha(text)
    tecnico = _extract_tecnico(text)
    # Fallback: extraer técnico del nombre del archivo (ej. 8603203_HANS.pdf)
    if not tecnico:
        import re as _re
        m = _re.search(r'_([A-Z][A-Z ]+[A-Z])(?:_dup)?\.pdf$', path.name)
        if m:
            candidate = m.group(1).strip()
            if candidate in set(TECHNICIAN_MAP.values()):
                tecnico = candidate

    if pdf_type == "atc":
        codigo, incidencia, skip = _codigo_atc(text)
        if skip:
            logger.info("ATC omitido (KO): %s", path.name)
            return {"skip": True, "orden": orden, "fecha": fecha,
                    "tecnico": tecnico, "codigo": None, "incidencia": False}
    elif pdf_type == "kairos":
        codigo, incidencia = _codigo_kairos(text)
    elif pdf_type == "orange":
        codigo, incidencia = _codigo_orange(text)
    elif pdf_type == "averia":
        codigo, incidencia = _codigo_averia(text)
    else:
        logger.warning("Tipo de PDF desconocido en %s", path.name)
        codigo, incidencia = None, True

    result = {
        "orden": orden,
        "fecha": fecha,
        "tecnico": tecnico,
        "codigo": codigo,
        "incidencia": incidencia,
    }
    logger.info("Resultado: %s", result)
    return result


# ---------------------------------------------------------------------------
# Tests con texto simulado (sin necesidad de PDFs reales)
# ---------------------------------------------------------------------------

def _run_tests():
    """
    Ejercita la lógica del parser con textos de ejemplo.
    Llama directamente a las funciones internas para no depender de archivos.
    """
    import textwrap

    PASS = "\033[92mOK\033[0m"
    FAIL = "\033[91mFAIL\033[0m"
    results = []

    def check(name: str, got, expected):
        ok = got == expected
        icon = PASS if ok else FAIL
        print(f"  [{icon}] {name}")
        if not ok:
            print(f"        esperado: {expected!r}")
            print(f"        obtenido: {got!r}")
        results.append(ok)

    # ------------------------------------------------------------------
    # 1. Detección de tipo de PDF
    # ------------------------------------------------------------------
    print("\n=== Detección tipo PDF ===")
    check("Kairos",   _detect_pdf_type("PARTE DE INSTALACIÓN\nFecha: 25/04/2026"), "kairos")
    check("Orange",   _detect_pdf_type("Boletín digital Instalación\nFecha: 25/04/2026"), "orange")
    check("Unknown",  _detect_pdf_type("Documento genérico"), "unknown")

    # ------------------------------------------------------------------
    # 2. Extracción de técnico
    # ------------------------------------------------------------------
    print("\n=== Extracción técnico ===")
    check("DIEGO",    _extract_tecnico("Técnico: Z2168 - García"), "DIEGO")
    check("CRISTIAN", _extract_tecnico("Instalador Z2174"), "CRISTIAN")
    check("LUIS E",   _extract_tecnico("Z2494 realizó la instalación"), "LUIS E")
    check("None",     _extract_tecnico("Sin código de técnico"), None)

    # ------------------------------------------------------------------
    # 3. Extracción de metros
    # ------------------------------------------------------------------
    print("\n=== Extracción de metros ===")
    check("20m",          _extract_meters("Nueva 20m"), 20.0)
    check("30 metros",    _extract_meters("Acometida de 30 metros"), 30.0)
    check("50 m",         _extract_meters("longitud 50 m nueva"), 50.0)
    check("60mt",         _extract_meters("60mt acometida"), 60.0)
    check("75,5 metros",  _extract_meters("acometida 75,5 metros"), 75.5)
    check("sin metros",   _extract_meters("sin longitud especificada"), None)

    # ------------------------------------------------------------------
    # 4. Tabla metros → código
    # ------------------------------------------------------------------
    print("\n=== Tabla metros → código ===")
    check("20m → MM01", _meters_to_code(20),  "MM01")
    check("21m → MM02", _meters_to_code(21),  "MM02")
    check("30m → MM02", _meters_to_code(30),  "MM02")
    check("50m → MM04", _meters_to_code(50),  "MM04")
    check("60m → MM05", _meters_to_code(60),  "MM05")
    check("61m → MM06", _meters_to_code(61),  "MM06")

    # ------------------------------------------------------------------
    # 5. Código Kairos
    # ------------------------------------------------------------------
    print("\n=== Código Kairos ===")

    texto_kairos_mm17 = textwrap.dedent("""\
        PARTE DE INSTALACIÓN
        Código de instalación: MYSIM_12345678
        Fecha: 25/04/2026
        Técnico: Z2168
        Tipo acometida: Reutilizada
    """)
    check("Reutilizada → MM17", _codigo_kairos(texto_kairos_mm17), ("MM17", False))

    texto_kairos_mm01 = textwrap.dedent("""\
        PARTE DE INSTALACIÓN
        Código de instalación: MYSIM_99999999
        Fecha: 25/04/2026
        Técnico: Z2174
        Tipo acometida: Nueva 20m
    """)
    check("Nueva 20m → MM01", _codigo_kairos(texto_kairos_mm01), ("MM01", False))

    texto_kairos_mm06 = textwrap.dedent("""\
        PARTE DE INSTALACIÓN
        Tipo acometida: Nueva 80 metros
    """)
    check("80 metros → MM06", _codigo_kairos(texto_kairos_mm06), ("MM06", False))

    texto_kairos_incidencia = textwrap.dedent("""\
        PARTE DE INSTALACIÓN
        Sin campo de tipo acometida
    """)
    check("Sin campo → incidencia", _codigo_kairos(texto_kairos_incidencia), (None, True))

    # ------------------------------------------------------------------
    # 6. Código ATC (nuevo formato con "Código de Petición")
    # ------------------------------------------------------------------
    print("\n=== Código ATC ===")

    check("Detección ATC",
          _detect_pdf_type("CIERRE DE INCIDENCIA OK\nCódigo de Petición: ATC-8230262"),
          "atc")

    check("CIERRE DE INCIDENCIA OK → incidencia",
          _codigo_atc("CIERRE DE INCIDENCIA OK\nFecha: 30/04/2026"),
          (None, True, False))

    check("CIERRE OK → AVERIA OK",
          _codigo_atc("CIERRE OK\nFecha: 30/04/2026"),
          ("AVERIA OK", False, False))

    check("KO → skip",
          _codigo_atc("CIERRE KO\nFecha: 30/04/2026"),
          (None, False, True))

    check("orden ATC (Código de Petición)",
          _extract_orden(
              "CIERRE DE INCIDENCIA OK\nFecha: 30/04/2026\nCódigo de Petición: ATC-8230262\n",
              "atc"),
          "ATC-8230262")

    check("técnico ATC (Código de técnico)",
          _extract_tecnico("Código de técnico: Z2174\nMarca: yoigo"),
          "CRISTIAN")

    # ------------------------------------------------------------------
    # 7. Código Orange
    # ------------------------------------------------------------------
    print("\n=== Código Orange ===")

    texto_orange_mm17 = textwrap.dedent("""\
        Boletín digital Instalación
        Código: OB-20260425-001
        Fecha: 25/04/2026
        Técnico: Z2252
        Instalación completada sin acometida nueva.
    """)
    check("Sin acometida/metros → MM17", _codigo_orange(texto_orange_mm17), ("MM17", False))

    texto_orange_mm02 = textwrap.dedent("""\
        Boletín digital Instalación
        Código: OB-20260425-002
        acometida nueva de 30 metros instalada correctamente
    """)
    check("acometida 30m → MM02", _codigo_orange(texto_orange_mm02), ("MM02", False))

    texto_orange_mm04 = textwrap.dedent("""\
        Boletín digital Instalación
        longitud acometida 45m
    """)
    check("acometida 45m → MM04", _codigo_orange(texto_orange_mm04), ("MM04", False))

    texto_orange_acometida_sin_metros = textwrap.dedent("""\
        Boletín digital Instalación
        Se realizó acometida pero no se especifica longitud.
    """)
    check("acometida sin metros → MM17", _codigo_orange(texto_orange_acometida_sin_metros), ("MM17", False))

    # ------------------------------------------------------------------
    # 7. Extracción de fecha y orden
    # ------------------------------------------------------------------
    print("\n=== Fecha y orden ===")
    texto_campos = textwrap.dedent("""\
        PARTE DE INSTALACIÓN
        Código de instalación: MYSIM_12732415 extra texto
        Fecha: 25/04/2026 otros datos
    """)
    check("orden (primer token)",  _extract_orden(texto_campos, "kairos"), "MYSIM_12732415")
    check("fecha (dd/mm/aaaa)",    _extract_fecha(texto_campos), "25/04/2026")

    # ------------------------------------------------------------------
    # Resumen
    # ------------------------------------------------------------------
    passed = sum(results)
    total = len(results)
    print(f"\n{'='*40}")
    print(f"Resultado: {passed}/{total} tests pasados")
    if passed < total:
        print("ATENCIÓN: hay tests fallidos — revisar la lógica")
    else:
        print("Todos los tests han pasado ✓")


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.DEBUG, format="%(levelname)s: %(message)s")

    if len(sys.argv) > 1:
        # Modo PDF real: python pdf_parser.py ruta/al/archivo.pdf
        for pdf_path in sys.argv[1:]:
            result = parse_pdf(pdf_path)
            print(f"\nArchivo: {pdf_path}")
            for key, val in result.items():
                print(f"  {key:12}: {val}")
    else:
        # Sin argumentos: ejecutar tests internos
        _run_tests()
