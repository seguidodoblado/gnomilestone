"""Icono de prioridad (alta, media, baja): forma y color propios para leerse de un vistazo."""

from __future__ import annotations

import gi

gi.require_version("Gdk", "4.0")
gi.require_version("Gtk", "4.0")
from gi.repository import Gdk, Gtk

from gnomilestone.i18n import _
from gnomilestone.prioridad import ALTA, BAJA, MEDIA, URGENTE

# nivel -> (icono, clase CSS con el color, texto del tooltip). Los iconos viven en
# assets/icons (ver app.py); el color de un icono simbólico es la propiedad CSS `color`.
_ICONOS = {
    URGENTE: (
        "prioridad-urgente-symbolic",
        "gnomilestone-prioridad-urgente",
        _("Prioridad urgente"),
    ),
    ALTA: ("prioridad-alta-symbolic", "gnomilestone-prioridad-alta", _("Prioridad alta")),
    MEDIA: ("prioridad-media-symbolic", "gnomilestone-prioridad-media", _("Prioridad media")),
    BAJA: ("prioridad-baja-symbolic", "gnomilestone-prioridad-baja", _("Prioridad baja")),
}
_CSS = """
.gnomilestone-prioridad-urgente { color: #a51d2d; }
.gnomilestone-prioridad-alta { color: #e01b24; }
.gnomilestone-prioridad-media { color: #e66100; }
.gnomilestone-prioridad-baja { color: #3584e4; }
"""
_css_aplicado = False


def _asegurar_css() -> None:
    global _css_aplicado
    if _css_aplicado:
        return
    display = Gdk.Display.get_default()
    if display is None:
        return
    proveedor = Gtk.CssProvider()
    proveedor.load_from_string(_CSS)
    Gtk.StyleContext.add_provider_for_display(
        display, proveedor, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
    )
    _css_aplicado = True


def crear_icono_prioridad(nivel: int, pixel_size: int = 16) -> Gtk.Image | None:
    """Icono de la prioridad, o None si la tarea no tiene."""
    if nivel not in _ICONOS:
        return None
    _asegurar_css()
    nombre, clase, tooltip = _ICONOS[nivel]
    imagen = Gtk.Image.new_from_icon_name(nombre)
    imagen.set_pixel_size(pixel_size)
    imagen.add_css_class(clase)
    imagen.set_tooltip_text(tooltip)
    return imagen
