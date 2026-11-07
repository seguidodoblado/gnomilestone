from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, Gtk

from gnomilestone.ganttcalc import PLANIFICADA_PASADA, VENCIDA, estado_vencimiento
from gnomilestone.i18n import _
from gnomilestone.models import Tarea

CLASE_PLANIFICADA_PASADA = "gnomilestone-planificada-pasada"
CLASE_VENCIDA = "gnomilestone-vencida"

# Naranja/rojo fijos (no dependen del tema): el color es la propia señal de aviso.
_CSS = (
    f".{CLASE_PLANIFICADA_PASADA} {{ color: #e66100; }}\n"
    f".{CLASE_VENCIDA} {{ color: #e01b24; }}\n"
)
_css_aplicado = False


def asegurar_css_vencimientos() -> None:
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


def aplicar_estilo_vencimiento(widget: Gtk.Widget, tarea: Tarea | None) -> str | None:
    """Pinta el nombre de la tarea en naranja/rojo según su estado de vencimiento y
    devuelve ese estado (o None). Quita siempre las dos clases antes de añadir la que
    toque: las celdas de ColumnView y las tarjetas se reciclan al refrescar."""
    widget.remove_css_class(CLASE_PLANIFICADA_PASADA)
    widget.remove_css_class(CLASE_VENCIDA)
    widget.remove_css_class("error")
    if tarea is None:
        return None
    estado = estado_vencimiento(tarea)
    if estado == VENCIDA:
        widget.add_css_class(CLASE_VENCIDA)
    elif estado == PLANIFICADA_PASADA:
        widget.add_css_class(CLASE_PLANIFICADA_PASADA)
    return estado


def texto_vencimiento(estado: str | None) -> str | None:
    """Texto del tooltip que explica el aviso, o None si la tarea no tiene ninguno."""
    if estado == VENCIDA:
        return _("Vencida: ya pasó su fecha límite")
    if estado == PLANIFICADA_PASADA:
        return _("Pasada su fecha planificada")
    return None
