"""
Código de doble factor (2FA) de Polar, leído del buzón común de Gmail.

Desde noviembre de 2026 Polar pide un código al entrar. Llega desde orange@orange.es a
`<buzón>+<técnico>@gmail.com`. Todas esas direcciones van al mismo buzón, y lo que va
después del «+» dice de qué técnico es el código. El agente lee el buzón por IMAP con una
contraseña de aplicación de Google.

Los técnicos no se ven afectados: en su móvil eligen SMS, y esa elección se guarda en su
navegador.

Variables de entorno (en Railway, servicio agente-fibra):
  POLAR_2FA_GMAIL               dirección base del buzón de Gmail, sin «+»
  POLAR_2FA_GMAIL_APP_PASSWORD  contraseña de aplicación (16 letras; los espacios no cuentan)

El correo trae algo así: «este es tu código de seguridad 12abc para el acceso a Web de Polar».
"""

import email
import html
import imaplib
import logging
import os
import re
import time
import unicodedata
from contextlib import contextmanager
from email.message import Message
from email.utils import getaddresses
from typing import Callable, Dict, Iterator, Optional

logger = logging.getLogger(__name__)

REMITENTE = "orange.es"
CARPETAS = ("INBOX", "[Gmail]/Spam")
_RE_CODIGO = re.compile(r"c[oó]digo de seguridad\s+([A-Za-z0-9]{3,12})\s+para", re.IGNORECASE)


class Codigo2FAError(RuntimeError):
    """No se pudo conseguir el código: faltan las variables, falla el buzón o no llegó."""


def _sin_tildes(txt: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", txt) if unicodedata.category(c) != "Mn")


def direccion_tecnico(base: str, nombre: str) -> str:
    """buzon@example.com + «LUIS E» → buzon+luise@example.com"""
    usuario, dominio = base.strip().lower().split("@", 1)
    etiqueta = re.sub(r"[^a-z0-9]", "", _sin_tildes(nombre).lower())
    if not etiqueta:
        raise ValueError(f"Nombre de técnico sin letras: {nombre!r}")
    return f"{usuario.split('+', 1)[0]}+{etiqueta}@{dominio}"


def extraer_codigo(texto: str) -> Optional[str]:
    plano = html.unescape(re.sub(r"<[^>]+>", " ", texto))
    plano = re.sub(r"\s+", " ", plano)
    m = _RE_CODIGO.search(plano)
    return m.group(1) if m else None


def _cuerpo(msg: Message) -> str:
    partes = []
    for parte in msg.walk():
        if parte.get_content_type() in ("text/plain", "text/html"):
            datos = parte.get_payload(decode=True) or b""
            partes.append(datos.decode(parte.get_content_charset() or "utf-8", "replace"))
    return "\n".join(partes)


def _destinatarios(msg: Message) -> set:
    cabeceras = msg.get_all("To", []) + msg.get_all("Delivered-To", []) + msg.get_all("Cc", [])
    return {dir_.strip().lower() for _, dir_ in getaddresses(cabeceras) if dir_}


def codigo_del_mensaje(crudo: bytes, direccion: str) -> Optional[str]:
    """El código, si el correo es de Orange y va a esa dirección; None en otro caso."""
    msg = email.message_from_bytes(crudo)
    remitente = " ".join(dir_ for _, dir_ in getaddresses(msg.get_all("From", []))).lower()
    if REMITENTE not in remitente or direccion.lower() not in _destinatarios(msg):
        return None
    return extraer_codigo(_cuerpo(msg))


class BuzonCodigos:
    """Buzón de Gmail con los códigos. Solo lee: no borra ni marca nada."""

    def __init__(self, usuario: Optional[str] = None, password: Optional[str] = None,
                 conectar: Optional[Callable[[], imaplib.IMAP4]] = None):
        self.usuario = (usuario or os.environ.get("POLAR_2FA_GMAIL", "")).strip()
        self._password = re.sub(r"\s+", "", password or os.environ.get("POLAR_2FA_GMAIL_APP_PASSWORD", ""))
        if not self.usuario or not self._password:
            raise Codigo2FAError("Falta POLAR_2FA_GMAIL o POLAR_2FA_GMAIL_APP_PASSWORD")
        self._conectar = conectar or (lambda: imaplib.IMAP4_SSL("imap.gmail.com", timeout=30))

    def direccion(self, nombre: str) -> str:
        return direccion_tecnico(self.usuario, nombre)

    @contextmanager
    def _sesion(self) -> Iterator[imaplib.IMAP4]:
        try:
            imap = self._conectar()
            imap.login(self.usuario, self._password)
        except (imaplib.IMAP4.error, OSError) as exc:
            raise Codigo2FAError(f"No se pudo entrar al buzón {self.usuario}: {exc}") from None
        try:
            yield imap
        finally:
            try:
                imap.logout()
            except Exception:
                pass

    @staticmethod
    def _uids(imap: imaplib.IMAP4, carpeta: str, desde: int = 1) -> Optional[list]:
        """UIDs ≥ `desde` de la carpeta, o None si la carpeta no existe."""
        typ, _ = imap.select(f'"{carpeta}"', readonly=True)
        if typ != "OK":
            return None
        typ, datos = imap.uid("SEARCH", None, "UID", f"{desde}:*")
        if typ != "OK" or not datos or not datos[0]:
            return []
        # «n:*» devuelve siempre el último aunque sea menor que n
        return sorted(u for u in map(int, datos[0].split()) if u >= desde)

    def marca(self) -> Dict[str, int]:
        """El UID más alto de cada carpeta ahora mismo: lo que llegue después es nuevo."""
        with self._sesion() as imap:
            marca = {}
            for carpeta in CARPETAS:
                uids = self._uids(imap, carpeta)
                if uids is not None:
                    marca[carpeta] = uids[-1] if uids else 0
            return marca

    def _buscar(self, imap: imaplib.IMAP4, direccion: str, marca: Dict[str, int]) -> Optional[str]:
        for carpeta, ultimo in marca.items():
            uids = self._uids(imap, carpeta, ultimo + 1) or []
            for uid in reversed(uids):  # el más reciente primero
                typ, datos = imap.uid("FETCH", str(uid), "(BODY.PEEK[])")
                if typ != "OK":
                    continue
                for item in datos:
                    if isinstance(item, tuple):
                        codigo = codigo_del_mensaje(item[1], direccion)
                        if codigo:
                            if carpeta != "INBOX":
                                logger.warning("Código 2FA de %s encontrado en %s", direccion, carpeta)
                            return codigo
        return None

    def esperar_codigo(self, direccion: str, marca: Dict[str, int], timeout: float = 180,
                       cada: float = 5, dormir: Callable[[float], None] = time.sleep,
                       reloj: Callable[[], float] = time.monotonic) -> str:
        """Espera a que llegue un código nuevo (posterior a `marca`) para esa dirección."""
        fin = reloj() + timeout
        with self._sesion() as imap:
            while True:
                codigo = self._buscar(imap, direccion, marca)
                if codigo:
                    return codigo
                if reloj() >= fin:
                    raise Codigo2FAError(f"No llegó el código de Polar a {direccion} en {int(timeout)} s")
                dormir(cada)
