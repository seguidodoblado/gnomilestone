from __future__ import annotations

import gettext
import locale
import os
from datetime import date
from pathlib import Path

DOMAIN = "gnomilestone"
LOCALE_DIR = Path(__file__).parent


def install() -> None:
    try:
        locale.setlocale(locale.LC_ALL, "")
    except locale.Error:
        pass  # locale del sistema no instalado: seguimos con el idioma por defecto (es)
    gettext.bindtextdomain(DOMAIN, str(LOCALE_DIR))
    gettext.textdomain(DOMAIN)


def _(message: str) -> str:
    return gettext.dgettext(DOMAIN, message)


def codigo_idioma() -> str:
    """Código de idioma de la interfaz (p. ej. ``es``, ``en_us``). Fuente: ajustes
    (``LANGUAGE``), luego variables/locale del sistema; por defecto ``es`` (idioma fuente)."""
    for candidato in (
        os.environ.get("LANGUAGE", "").split(":")[0],
        os.environ.get("LC_MESSAGES", "").split(".")[0],
        os.environ.get("LANG", "").split(".")[0],
        locale.getlocale(locale.LC_MESSAGES)[0] or "",
    ):
        if candidato:
            return candidato.replace("-", "_").lower()
    return "es"


def formatear_fecha_local(fecha_iso: str) -> str:
    """``YYYY-MM-DD`` o ``YYYY-MM-DDTHH:MM`` → texto de UI según el idioma (solo la fecha,
    la hora no se muestra aquí). En español: ``dd/mm/aaaa``."""
    anio, mes, dia = (int(parte) for parte in fecha_iso.split("T")[0].split("-"))
    fecha = date(anio, mes, dia)
    if codigo_idioma().startswith("es"):
        return fecha.strftime("%d/%m/%Y")
    try:
        return fecha.strftime("%x")
    except ValueError:
        return fecha_iso
