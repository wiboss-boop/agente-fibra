"""
Scraper para la plataforma Polar / Orange.
URL: https://polar-tecnicos.orange.es

Usa el mismo motor que Kairos (mismos selectores de login y estructura de URLs):
  - Login: #usuario / #password / #bt_login
  - Órdenes del día: href /Dashboard/Detalle?codigoOt=XXXX en el dashboard
  - Logout: /Dashboard/Logout
"""

import logging
import re
from datetime import date
from pathlib import Path
from typing import List, Optional, Tuple

import yaml
from playwright.sync_api import sync_playwright, Page, TimeoutError as PWTimeout

logger = logging.getLogger(__name__)

_CONFIG_PATH = Path("config/credentials.yaml")
_BASE_URL = "https://polar-tecnicos.orange.es"
_TIMEOUT = 20_000


def load_technicians(config_path: Path = _CONFIG_PATH) -> List[dict]:
    with open(config_path) as f:
        cfg = yaml.safe_load(f)
    return [t for t in cfg["technicians"] if t.get("orange")]


def run(
    target_date: Optional[date] = None,
    downloads_dir: Path = Path("downloads"),
    headless: bool = True,
) -> Tuple[List[Path], List[dict]]:
    """
    Descarga los PDFs de Orange/Polar para todos los técnicos en la fecha indicada.
    Retorna (lista de PDFs descargados, lista de registros de incidencia sin PDF).
    """
    if target_date is None:
        target_date = date.today()

    downloads_dir.mkdir(parents=True, exist_ok=True)
    technicians = load_technicians()
    logger.info("Orange: %d técnicos para %s", len(technicians), target_date.strftime("%d/%m/%Y"))

    all_downloaded: List[Path] = []
    all_incidencias: List[dict] = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=headless)
        for tech in technicians:
            downloaded, incidencias = _process_technician(browser, tech, target_date, downloads_dir)
            all_downloaded.extend(downloaded)
            all_incidencias.extend(incidencias)
        browser.close()

    logger.info("Orange: %d PDFs descargados, %d incidencias sin boletín",
                len(all_downloaded), len(all_incidencias))
    return all_downloaded, all_incidencias


# ---------------------------------------------------------------------------
# Procesamiento por técnico
# ---------------------------------------------------------------------------

def _process_technician(
    browser, tech: dict, target_date: date, downloads_dir: Path
) -> Tuple[List[Path], List[dict]]:
    name = tech["name"]
    logger.info("Orange → %s (%s)", name, tech["orange_user"])

    context = browser.new_context(accept_downloads=True)
    page = context.new_page()
    downloaded: List[Path] = []
    incidencias: List[dict] = []

    try:
        _login(page, tech["orange_user"], tech["orange_pass"])
        order_ids = _get_order_ids(page, target_date)
        logger.info("Orange / %s: %d órdenes encontradas", name, len(order_ids))

        for order_id in order_ids:
            pdf_path = downloads_dir / f"{order_id}_{name}.pdf"
            if pdf_path.exists():
                logger.info("Ya existe, omitido: %s", pdf_path.name)
                continue
            path, is_incidencia = _download_order_pdf(page, order_id, pdf_path)
            if path:
                downloaded.append(path)
            elif is_incidencia:
                incidencias.append({
                    "orden": order_id,
                    "fecha": target_date.strftime("%d/%m/%Y"),
                    "tecnico": name,
                    "codigo": None,
                    "incidencia": True,
                    "_source": f"{order_id}_sin_boletin",
                })

    except PWTimeout as exc:
        logger.error("Orange / %s: timeout — %s", name, exc)
    except Exception as exc:
        logger.error("Orange / %s: error — %s", name, exc, exc_info=True)
    finally:
        try:
            _logout(page)
        except Exception:
            pass
        context.close()

    return downloaded, incidencias


# ---------------------------------------------------------------------------
# Login / logout
# ---------------------------------------------------------------------------

def _login(page: Page, username: str, password: str) -> None:
    logger.debug("Orange: login como %s", username)
    page.goto(_BASE_URL, timeout=_TIMEOUT)
    page.wait_for_load_state("networkidle", timeout=_TIMEOUT)

    # Si ya hay sesión activa, redirige directo al Dashboard
    if "/Dashboard" in page.url:
        logger.debug("Orange: sesión ya activa para %s", username)
        return

    page.locator("#usuario").click()
    page.locator("#usuario").clear()
    page.keyboard.type(username)
    page.locator("#password").click()
    page.locator("#password").clear()
    page.keyboard.type(password)
    page.click("#bt_login")

    # Cerrar aviso de cambio de contraseña si aparece
    try:
        btn_omitir = page.locator("button:has-text('Omitir'), button:has-text('Saltar'), button:has-text('Cancelar'), button:has-text('No'), a:has-text('Omitir'), a:has-text('Saltar')")
        btn_omitir.first.click(timeout=5_000)
        logger.debug("Orange: aviso de contraseña cerrado")
    except Exception:
        pass

    # Orange es una SPA: detectar login exitoso por cambio de URL al Dashboard
    try:
        page.wait_for_url("**/Dashboard**", timeout=15_000)
        logger.debug("Orange: login OK")
    except PWTimeout:
        error_msg = ""
        err = page.locator(".alert-danger, [class*='error']")
        if err.count() > 0:
            error_msg = err.first.inner_text().strip()
        raise RuntimeError(f"Login fallido para {username}: {error_msg or 'credenciales incorrectas'}")


def _logout(page: Page) -> None:
    try:
        page.goto(f"{_BASE_URL}/Dashboard/Logout", timeout=10_000)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Listado de órdenes del día
# ---------------------------------------------------------------------------

def _get_order_ids(page: Page, target_date: date) -> List[str]:
    """
    Navega al Dashboard y usa el botón #previous-day-button para llegar
    a la fecha objetivo. Si es hoy, carga directamente.
    """
    today = date.today()
    days_back = (today - target_date).days

    # Esperar a que el dashboard cargue
    try:
        page.wait_for_selector("#header_listado", state="visible", timeout=15_000)
    except PWTimeout:
        pass

    # Navegar hacia atrás los días necesarios
    for _ in range(days_back):
        try:
            page.evaluate("document.getElementById('previous-day-button').click()")
            page.wait_for_timeout(1_500)
        except Exception as e:
            logger.warning("Orange: no se pudo navegar al día anterior: %s", e)
            break

    # Esperar a que carguen las órdenes
    try:
        page.wait_for_selector("a[href*='codigoOt']", state="attached", timeout=20_000)
    except PWTimeout:
        pass

    # Verificar la fecha mostrada
    try:
        shown = page.locator("#current-day-title").inner_text(timeout=3_000).strip()
        date_str = target_date.strftime("%d/%m/%Y")
        if shown and date_str not in shown:
            logger.warning("Orange: fecha mostrada '%s' no coincide con objetivo '%s'", shown, date_str)
    except Exception:
        pass

    ids = _extract_order_ids_from_page(page)
    if not ids:
        logger.warning("Orange: no se encontraron órdenes para %s.", target_date.strftime("%d/%m/%Y"))
    return ids


def _extract_order_ids_from_page(page: Page) -> List[str]:
    """Extrae IDs de orden de los href /Dashboard/Detalle?codigoOt=XXXX, aplicando filtros."""
    html = page.content()
    ids = re.findall(r'/(?:Dashboard/Detalle|DetalleOrden)\?codigoOt=([^"\'&\s]+)', html)
    unique = list(dict.fromkeys(ids))

    filtered = []
    for oid in unique:
        reason = _skip_reason(oid, html)
        if reason:
            logger.info("Orden omitida: %s — %s", oid, reason)
        else:
            filtered.append(oid)

    logger.debug("Orange: IDs extraídos: %s", filtered)
    return filtered


def _skip_reason(order_id: str, html: str) -> Optional[str]:
    """Devuelve el motivo de exclusión o None si la orden debe procesarse."""
    if "AGILETV" in order_id.upper() or "AGILE_TV" in order_id.upper():
        return "servicio AgileTV"

    # Buscar solo el texto del <a> que apunta a esta orden
    m = re.search(
        rf'<a[^>]*codigoOt={re.escape(order_id)}[^>]*>(.*?)</a>',
        html,
        re.DOTALL | re.IGNORECASE,
    )
    if m:
        link_text = m.group(1).lower()
        for status in ("anulada", "anulado", "cancelada", "cancelado"):
            if status in link_text:
                return f"estado {status}"

    return None


# ---------------------------------------------------------------------------
# Descarga de PDF por orden
# ---------------------------------------------------------------------------

_BOLETIN_OK = "boletín digital de instalación ok"


def _find_boletin_ok_index(page: Page, order_id: str) -> "Tuple[Optional[int], int]":
    """
    Busca el botón llamado 'Boletín digital de Instalación OK' entre los documentos.
    Devuelve (indice, n_total).
    - Si no hay documentos: (None, 0)   → sin partes, no es incidencia gestionable
    - Si hay documentos pero ninguno es el boletín OK: (None, n>0) → registrar como incidencia
    - Si se encuentra: (indice, n_total)
    """
    # Buscar por data-orden (nuevo formato Orange) o por id^=instalacion_ (formato antiguo)
    containers = page.locator("[data-orden]").all()
    if not containers:
        containers = page.locator("[id^='instalacion_']").all()
        use_data_orden = False
    else:
        use_data_orden = True
    n_total = len(containers)

    if n_total == 0:
        logger.warning("Orange: orden %s sin partes disponibles", order_id)
        return None, 0

    boletin_idx = None
    for container in containers:
        btn = container.locator("button")
        if btn.count() == 0:
            continue
        txt = btn.first.inner_text().strip().lower()
        if _BOLETIN_OK in txt:
            if use_data_orden:
                data_orden = container.get_attribute("data-orden") or ""
                m = re.search(r'_(\d+)$', data_orden)
            else:
                div_id = container.get_attribute("id") or ""
                m = re.search(r'instalacion_(\d+)', div_id)
            if m:
                boletin_idx = int(m.group(1))

    if boletin_idx is None:
        logger.info("Orden %s: sin boletín OK — marcando como incidencia", order_id)
        return None, n_total

    if n_total > 1:
        logger.info("Orden %s: %d intentos, descargando solo el último (verde)", order_id, n_total)

    return boletin_idx, n_total


def _download_order_pdf(page: Page, order_id: str, dest_path: Path) -> "Tuple[Optional[Path], bool]":
    """
    Descarga el 'Boletín digital de Instalación OK' de una orden Orange.
    Retorna (path, is_incidencia):
      - (Path, False)  → descarga exitosa
      - (None, True)   → documentos presentes pero sin boletín OK → registrar incidencia
      - (None, False)  → sin documentos o error técnico
    """
    logger.info("Orange: descargando PDF de %s", order_id)
    try:
        page.goto(f"{_BASE_URL}/DetalleOrden?codigoOt={order_id}", timeout=_TIMEOUT)
        page.wait_for_load_state("networkidle", timeout=_TIMEOUT)

        indice, n_total = _find_boletin_ok_index(page, order_id)
        if indice is None:
            is_incidencia = n_total > 0
            return None, is_incidencia

        url = f"{_BASE_URL}/DetalleOrden/DescargarParte?codigoOt={order_id}&tipo=1&indice={indice}"
        response = page.request.get(url)
        if response.status != 200:
            logger.warning("Orange: HTTP %d al descargar %s", response.status, order_id)
            return None, False

        content_type = response.headers.get("content-type", "")
        if "pdf" not in content_type and len(response.body()) < 100:
            logger.warning("Orange: respuesta inesperada para %s (content-type=%s)", order_id, content_type)
            return None, False

        dest_path.write_bytes(response.body())
        logger.info("Orange: guardado %s (%d bytes)", dest_path.name, len(response.body()))
        return dest_path, False

    except PWTimeout:
        logger.error("Orange: timeout en orden %s", order_id)
        return None, False
    except Exception as exc:
        logger.error("Orange: error en orden %s — %s", order_id, exc)
        return None, False
