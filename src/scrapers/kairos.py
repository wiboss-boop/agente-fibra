"""
Scraper para la plataforma Kairos / MásMóvil / Yoigo.
URL: https://instaladores.kairos365.com

Flujo por técnico:
  1. Login con #usuario / #password / #bt_login
  2. El dashboard muestra directamente las órdenes del día
  3. Los IDs de orden están en hrefs con formato /Dashboard/Detalle?codigoOt=XXXX
  4. Por cada orden: abrir /Dashboard/Detalle, descargar PDF del boletín
  5. Logout vía /Dashboard/Logout
"""

import logging
import re
from datetime import date
from pathlib import Path
from typing import List, Optional

import yaml
from playwright.sync_api import sync_playwright, Page, BrowserContext, TimeoutError as PWTimeout

logger = logging.getLogger(__name__)

_CONFIG_PATH = Path("config/credentials.yaml")
_BASE_URL = "https://instaladores.kairos365.com"
_TIMEOUT = 30_000


def load_technicians(config_path: Path = _CONFIG_PATH) -> List[dict]:
    with open(config_path) as f:
        cfg = yaml.safe_load(f)
    return [t for t in cfg["technicians"] if t.get("kairos")]


def run(
    target_date: Optional[date] = None,
    downloads_dir: Path = Path("downloads"),
    headless: bool = True,
) -> List[Path]:
    """
    Descarga los PDFs de Kairos para todos los técnicos en la fecha indicada.
    Retorna lista de rutas de PDFs descargados.
    """
    if target_date is None:
        target_date = date.today()

    downloads_dir.mkdir(parents=True, exist_ok=True)
    technicians = load_technicians()
    logger.info("Kairos: %d técnicos para %s", len(technicians), target_date.strftime("%d/%m/%Y"))

    all_downloaded: List[Path] = []
    all_sin_parte: List[dict] = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=headless)
        for tech in technicians:
            downloaded, sin_parte = _process_technician(browser, tech, target_date, downloads_dir)
            all_downloaded.extend(downloaded)
            all_sin_parte.extend(sin_parte)
        browser.close()

    logger.info("Kairos: %d PDFs descargados, %d sin parte", len(all_downloaded), len(all_sin_parte))
    return all_downloaded, all_sin_parte


# ---------------------------------------------------------------------------
# Procesamiento por técnico
# ---------------------------------------------------------------------------

def _process_technician(browser, tech: dict, target_date: date, downloads_dir: Path) -> List[Path]:
    name = tech["name"]
    logger.info("Kairos → %s (%s)", name, tech["kairos_user"])

    context = browser.new_context(accept_downloads=True)
    page = context.new_page()
    downloaded: List[Path] = []
    sin_parte: List[dict] = []

    try:
        _login(page, tech["kairos_user"], tech["kairos_pass"])
        order_ids = _get_order_ids(page, target_date)

        if not order_ids and _no_work_today(page):
            logger.info("Técnico %s: sin órdenes hoy — no laboró", name)
            return downloaded, sin_parte

        logger.info("Kairos / %s: %d órdenes encontradas", name, len(order_ids))

        for order_id in order_ids:
            pdf_path = downloads_dir / f"{order_id}.pdf"
            if pdf_path.exists():
                logger.info("Ya existe, omitido: %s", pdf_path.name)
                continue
            path = _download_order_pdf(page, order_id, pdf_path)
            if path == "SIN_PARTE":
                logger.info("Kairos: orden %s sin parte — registrar sin_parte", order_id)
                sin_parte.append({
                    "orden": order_id,
                    "fecha": target_date.strftime("%d/%m/%Y"),
                    "tecnico": name,
                    "codigo": "sin parte",
                    "incidencia": False,
                    "_source": f"{order_id}_sin_parte",
                })
            elif path:
                downloaded.append(path)

    except PWTimeout as exc:
        logger.error("Kairos / %s: timeout — %s", name, exc)
    except Exception as exc:
        logger.error("Kairos / %s: error — %s", name, exc, exc_info=True)
    finally:
        try:
            _logout(page)
        except Exception:
            pass
        context.close()

    return downloaded, sin_parte


# ---------------------------------------------------------------------------
# Login / logout
# ---------------------------------------------------------------------------

def _login(page: Page, username: str, password: str) -> None:
    logger.debug("Kairos: login como %s", username)
    page.goto(_BASE_URL, timeout=_TIMEOUT)
    page.wait_for_load_state("networkidle", timeout=_TIMEOUT)

    page.fill("#usuario", username)
    page.fill("#password", password)
    page.click("#bt_login")

    # Esperar a que el formulario desaparezca (login OK) o aparezca un error
    try:
        page.locator("#usuario").wait_for(state="hidden", timeout=10_000)
        logger.debug("Kairos: login OK")
    except PWTimeout:
        # El formulario sigue visible → login rechazado
        error_msg = ""
        err = page.locator(".alert-danger, .alert.alert-danger, [class*='error']")
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

_NO_WORK_PATTERNS = (
    "no tienes ningún código",
    "no tiene ningún código",
    "sin órdenes",
    "no hay órdenes",
    "no tienes órdenes",
    "no existen órdenes",
)


def _no_work_today(page: Page) -> bool:
    """Detecta el mensaje de la plataforma indicando que el técnico no tiene trabajo hoy."""
    html = page.content().lower()
    return any(p in html for p in _NO_WORK_PATTERNS)


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
            # El botón puede estar hidden; forzar click via JS
            page.evaluate("document.getElementById('previous-day-button').click()")
            page.wait_for_timeout(1_500)
        except Exception as e:
            logger.warning("Kairos: no se pudo navegar al día anterior: %s", e)
            break

    # Esperar a que carguen las órdenes
    try:
        page.wait_for_selector("a[href*='codigoOt']", state="attached", timeout=15_000)
    except PWTimeout:
        pass  # Sin órdenes o página vacía

    # Verificar la fecha mostrada
    try:
        shown = page.locator("#current-day-title").inner_text(timeout=3_000).strip()
        date_str = target_date.strftime("%d/%m/%Y")
        if shown and date_str not in shown:
            logger.warning("Kairos: fecha mostrada '%s' no coincide con objetivo '%s'", shown, date_str)
    except Exception:
        pass

    ids = _extract_order_ids_from_page(page)
    if not ids:
        logger.warning("Kairos: no se encontraron órdenes para %s.", target_date.strftime("%d/%m/%Y"))
    return ids



def _extract_order_ids_from_page(page: Page) -> List[str]:
    """Extrae IDs de orden de los href /Dashboard/Detalle?codigoOt=XXXX, aplicando filtros."""
    html = page.content()
    ids = re.findall(r'/Dashboard/Detalle\?codigoOt=([^"\'&\s]+)', html)
    unique = list(dict.fromkeys(ids))

    filtered = []
    for oid in unique:
        reason = _skip_reason(oid, html)
        if reason:
            logger.info("Orden omitida: %s — %s", oid, reason)
        else:
            filtered.append(oid)

    logger.debug("Kairos: IDs extraídos del HTML: %s", filtered)
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

def _last_available_index(page: Page, order_id: str) -> "tuple[Optional[int], int]":
    """
    Busca el ultimo parte disponible entre los intentos de una orden.
    Devuelve (indice, n_total). Si no hay partes, devuelve (None, 0).
    """
    containers = page.locator("[id^='instalacion_']").all()
    n_total = len(containers)

    if n_total == 0:
        logger.warning("Kairos: orden %s sin partes disponibles", order_id)
        return None, 0

    last_index = None
    for container in containers:
        btn = container.locator("button")
        if btn.count() == 0:
            continue
        div_id = container.get_attribute("id") or ""
        m = re.search(r'instalacion_(\d+)', div_id)
        if m:
            last_index = int(m.group(1))

    if last_index is None:
        logger.warning("Kairos: orden %s sin indices de parte", order_id)
        return None, n_total

    if n_total > 1:
        logger.info("Orden %s: %d intentos, descargando el ultimo", order_id, n_total)

    return last_index, n_total


def _download_order_pdf(page: Page, order_id: str, dest_path: Path) -> Optional[Path]:
    """
    Descarga el PDF del parte de instalación de una orden.

    El botón "Parte de Instalación" dispara una petición a:
      GET /Dashboard/DescargarParte?codigoOt=<ID>&tipo=instalacion&indice=<N>
    Se descarga directamente vía API request (sin popup) para mayor robustez.
    Si hay varios partes (indice=0,1,2...) descarga el primero.
    """
    logger.info("Kairos: descargando PDF de %s", order_id)
    try:
        # Primero cargar el detalle para verificar cuántos partes hay
        page.goto(f"{_BASE_URL}/Dashboard/Detalle?codigoOt={order_id}", timeout=_TIMEOUT)
        page.wait_for_load_state("networkidle", timeout=_TIMEOUT)

        indice, n_partes = _last_available_index(page, order_id)
        if indice is None:
            return "SIN_PARTE"
        url = f"{_BASE_URL}/Dashboard/DescargarParte?codigoOt={order_id}&tipo=instalacion&indice={indice}"

        response = page.request.get(url)
        if response.status != 200:
            logger.warning("Kairos: HTTP %d al descargar %s", response.status, order_id)
            return None

        content_type = response.headers.get("content-type", "")
        if "pdf" not in content_type and len(response.body()) < 100:
            logger.warning("Kairos: respuesta inesperada para %s (content-type=%s)", order_id, content_type)
            return None

        dest_path.write_bytes(response.body())
        logger.info("Kairos: guardado %s (%d bytes)", dest_path.name, len(response.body()))
        return dest_path

    except PWTimeout:
        logger.error("Kairos: timeout en orden %s", order_id)
        return None
    except Exception as exc:
        logger.error("Kairos: error en orden %s — %s", order_id, exc)
        return None
