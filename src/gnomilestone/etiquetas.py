"""Utilidades de color de las etiquetas (hex sin «#», como en GitHub)."""

from __future__ import annotations

import html
import zlib

# Colores por defecto de las etiquetas de GitHub: una etiqueta nueva coge uno estable
# según su nombre, para que siempre salga igual.
_PALETA = ("d73a4a", "0075ca", "cfd3d7", "a2eeef", "7057ff", "008672", "e4e669", "d876e3", "fbca04")


def color_automatico(nombre: str) -> str:
    return _PALETA[zlib.crc32(nombre.strip().casefold().encode()) % len(_PALETA)]


def color_de_texto(color_hex: str) -> str:
    """Blanco o negro, el que mejor se lea sobre `color_hex`."""
    color_hex = color_hex.lstrip("#")
    try:
        r, g, b = (int(color_hex[i : i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return "000000"
    luminancia = 0.299 * r + 0.587 * g + 0.114 * b
    return "000000" if luminancia > 150 else "ffffff"


def marcado_chip(nombre: str, color: str) -> str:
    """Marcado Pango de una etiqueta como «chip»: fondo de su color y texto legible."""
    color = color.lstrip("#")
    return (
        f'<span size="small" background="#{color}" foreground="#{color_de_texto(color)}"> '
        f"{html.escape(nombre, quote=False)} </span>"
    )
