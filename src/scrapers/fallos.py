"""
Fallos por técnico de los scrapers, para que main.py los avise en vez de tragárselos.

Cada scraper sigue con el siguiente técnico cuando uno falla. Antes, el fallo solo quedaba
en el log: el técnico salía como SIN ALTAS y el Telegram decía «Errores scraper: 0». Así
pasó en octubre de 2026, con las contraseñas de Orange caducadas durante semanas.
"""

from typing import List, Optional


class LoginFallido(RuntimeError):
    """El portal no dejó entrar: contraseña caducada o cambiada, o cuenta bloqueada."""


def registrar(errores: Optional[List[dict]], plataforma: str, tech: dict, usuario: str,
              exc: Exception) -> None:
    if errores is None:
        return
    errores.append({
        "plataforma": plataforma,
        "tecnico": tech["name"],
        "usuario": usuario,
        "login": isinstance(exc, LoginFallido),
        "error": str(exc).splitlines()[0][:200] if str(exc) else type(exc).__name__,
    })
