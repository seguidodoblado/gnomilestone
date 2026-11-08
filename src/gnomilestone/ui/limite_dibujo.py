"""Dibujo de la fecha límite (línea de holgura y bandera) con las reglas de color de
vencimiento. Lo comparten el Gantt y la vista de Uso, para que se lean igual."""

from __future__ import annotations

from datetime import timedelta

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk

from gnomilestone import ganttcalc, settings, theme
from gnomilestone.i18n import _, formatear_fecha_local
from gnomilestone.models import Tarea

Color = tuple[float, float, float, float]

COLOR_LIMITE = (0.85, 0.11, 0.14)  # rojo de la fecha límite y su línea de holgura
COLOR_LIMITE_PLANIFICADA = (0.93, 0.53, 0.0)  # naranja: plan ya pasado, límite aún no
TOLERANCIA_PX = 6  # distancia horizontal a la bandera para mostrar su tooltip


def x_limite(fecha_limite: str, fecha_origen, px_por_dia: float) -> float:
    # La fecha límite es inclusiva: se marca al final de ese día, que es el mismo
    # borde que usa la barra para su último día planificado.
    return ganttcalc.fecha_a_x(
        ganttcalc.parse_fecha(fecha_limite) + timedelta(days=1), fecha_origen, px_por_dia
    )


def color_limite(tarea: Tarea) -> Color:
    dias_alerta = settings.read_settings().get("dias_alerta_vencimiento", 1)
    try:
        dias_alerta = max(0, int(dias_alerta))
    except (TypeError, ValueError):
        dias_alerta = 1
    estado = ganttcalc.estado_vencimiento(tarea, dias_alerta=dias_alerta)
    if estado == ganttcalc.VENCIDA:
        return (*COLOR_LIMITE, 1.0)
    if estado == ganttcalc.PLANIFICADA_PASADA:
        return (*COLOR_LIMITE_PLANIFICADA, 1.0)
    # Una fecha límite futura y alejada es informativa, no una alerta: blanco puro
    # sobre tema oscuro y negro puro sobre tema claro, con baja opacidad.
    tema_oscuro = theme.is_dark_theme(Gtk.Settings.get_default().get_property("gtk-theme-name"))
    color_neutro = (1.0, 1.0, 1.0) if tema_oscuro else (0.0, 0.0, 0.0)
    return (*color_neutro, 0.55)


def texto_limite(tarea: Tarea) -> str:
    if not tarea.fecha_limite:
        return ""
    texto = _("Fecha límite: {fecha}").format(fecha=formatear_fecha_local(tarea.fecha_limite))
    fin = ganttcalc.fecha_fin_planificada(tarea)
    if fin is None:
        return texto
    margen = (ganttcalc.parse_fecha(tarea.fecha_limite) - fin).days
    if margen < 0:
        sufijo = _("planificada después del límite")
    elif margen == 0:
        sufijo = _("sin margen")
    elif margen == 1:
        sufijo = _("margen de 1 día")
    else:
        sufijo = _("margen de {dias} días").format(dias=margen)
    return f"{texto} · {sufijo}"


def dibujar_limite(cr, x_barra_fin: float, x_limite_px: float, y_linea: float, color: Color) -> None:
    """Línea discontinua de holgura desde el final de la barra y bandera en la fecha límite."""
    if x_limite_px > x_barra_fin + 0.5:
        cr.set_source_rgba(color[0], color[1], color[2], min(color[3], 0.6))
        cr.set_line_width(1.5)
        cr.set_dash([3.0, 3.0])
        cr.move_to(x_barra_fin, y_linea)
        cr.line_to(x_limite_px, y_linea)
        cr.stroke()
        cr.set_dash([])
    dibujar_bandera(cr, x_limite_px, y_linea, color)


def dibujar_bandera(cr, x: float, y: float, color: Color) -> None:
    alto = 9.0
    ancho = 7.0
    cr.set_source_rgba(*color)
    cr.set_line_width(1.5)
    cr.move_to(x, y - alto)
    cr.line_to(x, y + alto)
    cr.stroke()
    cr.move_to(x, y - alto)
    cr.line_to(x + ancho, y - alto + 3.5)
    cr.line_to(x, y - alto + 7)
    cr.close_path()
    cr.fill()
