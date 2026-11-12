"""Icono del tipo de una tarea (trabajo, error, funcionalidad): forma y color propios."""

from __future__ import annotations

import gi

gi.require_version("Gdk", "4.0")
gi.require_version("Gtk", "4.0")
from gi.repository import Gdk, Gtk

from gnomilestone.tipos import ERROR, FUNCIONALIDAD, TRABAJO, nombre_tipo

# tipo -> (icono, clase CSS con el color). Los iconos viven en assets/icons (ver app.py); el
# color de un icono simbólico es la propiedad CSS `color`. Los colores siguen a los de GitHub.
_ICONOS = {
    TRABAJO: ("tipo-trabajo-symbolic", "gnomilestone-tipo-trabajo"),
    ERROR: ("tipo-error-symbolic", "gnomilestone-tipo-error"),
    FUNCIONALIDAD: ("tipo-funcionalidad-symbolic", "gnomilestone-tipo-funcionalidad"),
}
_CSS = """
.gnomilestone-tipo-trabajo { color: #e5a50a; }
.gnomilestone-tipo-error { color: #e01b24; }
.gnomilestone-tipo-funcionalidad { color: #3584e4; }
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


def crear_icono_tipo(tipo: str, pixel_size: int = 16) -> Gtk.Image | None:
    """Icono del tipo, o None si la tarea no tiene."""
    if tipo not in _ICONOS:
        return None
    _asegurar_css()
    nombre, clase = _ICONOS[tipo]
    imagen = Gtk.Image.new_from_icon_name(nombre)
    imagen.set_pixel_size(pixel_size)
    imagen.add_css_class(clase)
    imagen.set_tooltip_text(nombre_tipo(tipo))
    return imagen
