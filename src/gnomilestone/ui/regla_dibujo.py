"""Dibujo común de la regla de fechas (Gantt y Uso): dos niveles, bandas alternas y «Hoy»."""

from __future__ import annotations

from datetime import date

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk

from gnomilestone import ganttcalc, theme
from gnomilestone.i18n import _

ALTURA_REGLA = 28
_ALTURA_NIVEL_SUPERIOR = 14
_COLOR_HOY = (0.86, 0.2, 0.2)  # rojo fijo, el mismo de la línea del día actual


def color_fondo() -> tuple[float, float, float]:
    """Fondo para las etiquetas que se dibujan sobre el lienzo, según el tema."""
    nombre_tema = Gtk.Settings.get_default().get_property("gtk-theme-name")
    return (0.18, 0.18, 0.18) if theme.is_dark_theme(nombre_tema) else (1.0, 1.0, 1.0)


def dibujar_bandas(cr, ancho: float, alto: float, fecha_origen: date, px_por_dia: float, color):
    """Tinte suave en los meses (o años) alternos, para localizarse de un vistazo."""
    niveles = ganttcalc.niveles_regla(fecha_origen, px_por_dia, ancho)
    inicios = [fecha for fecha, _etiqueta in niveles.superior]
    for indice, inicio in enumerate(inicios):
        if indice % 2 == 0:
            continue
        x0 = ganttcalc.fecha_a_x(inicio, fecha_origen, px_por_dia)
        x1 = (
            ganttcalc.fecha_a_x(inicios[indice + 1], fecha_origen, px_por_dia)
            if indice + 1 < len(inicios)
            else ancho
        )
        cr.set_source_rgba(*color, 0.05)
        cr.rectangle(x0, 0, x1 - x0, alto)
        cr.fill()


def dibujar_regla(
    cr,
    ancho: float,
    fecha_origen: date,
    px_por_dia: float,
    color_marca,
    color_texto,
    hoy: date | None = None,
    x_visible: float = 0.0,
) -> None:
    """`x_visible` es el desplazamiento horizontal actual: la etiqueta del nivel superior
    (mes o año) se mantiene visible en el borde izquierdo mientras dura ese periodo."""
    niveles = ganttcalc.niveles_regla(fecha_origen, px_por_dia, ancho)
    dibujar_bandas(cr, ancho, ALTURA_REGLA, fecha_origen, px_por_dia, color_marca)

    cr.select_font_face("sans-serif", 0, 1)  # 1 = cairo.FONT_WEIGHT_BOLD
    cr.set_font_size(10.5)
    cr.set_line_width(1)
    inicios = [fecha for fecha, _etiqueta in niveles.superior]
    for indice, (fecha, etiqueta) in enumerate(niveles.superior):
        x = ganttcalc.fecha_a_x(fecha, fecha_origen, px_por_dia)
        x_fin = (
            ganttcalc.fecha_a_x(inicios[indice + 1], fecha_origen, px_por_dia)
            if indice + 1 < len(inicios)
            else ancho
        )
        cr.set_source_rgba(*color_marca, 0.4)
        cr.move_to(x, 0)
        cr.line_to(x, ALTURA_REGLA)
        cr.stroke()
        # Pegajosa: sigue al borde izquierdo visible sin salirse de su propio periodo.
        ancho_texto = cr.text_extents(etiqueta).x_advance
        x_texto = max(x + 4, min(x_visible + 4, x_fin - ancho_texto - 4))
        cr.set_source_rgba(*color_texto, 0.95)
        cr.move_to(x_texto, _ALTURA_NIVEL_SUPERIOR - 3)
        cr.show_text(etiqueta)

    cr.select_font_face("sans-serif", 0, 0)
    cr.set_font_size(10)
    for fecha, etiqueta in niveles.inferior:
        x = ganttcalc.fecha_a_x(fecha, fecha_origen, px_por_dia)
        cr.set_source_rgba(*color_marca, 0.3)
        cr.move_to(x, _ALTURA_NIVEL_SUPERIOR)
        cr.line_to(x, ALTURA_REGLA)
        cr.stroke()
        cr.set_source_rgba(*color_texto, 0.85)
        cr.move_to(x + 3, ALTURA_REGLA - 4)
        cr.show_text(etiqueta)

    cr.set_source_rgba(*color_marca, 0.35)
    cr.move_to(0, _ALTURA_NIVEL_SUPERIOR)
    cr.line_to(ancho, _ALTURA_NIVEL_SUPERIOR)
    cr.stroke()

    x_hoy = ganttcalc.fecha_a_x(hoy or date.today(), fecha_origen, px_por_dia)
    if 0 <= x_hoy <= ancho:
        cr.set_source_rgba(*_COLOR_HOY, 0.9)
        cr.set_line_width(2)
        cr.move_to(x_hoy, 0)
        cr.line_to(x_hoy, ALTURA_REGLA)
        cr.stroke()
        # Etiqueta «Hoy» sobre la línea, para localizarlo aunque la escala sea muy ancha.
        cr.select_font_face("sans-serif", 0, 1)
        cr.set_font_size(9.5)
        texto = _("Hoy")
        extents = cr.text_extents(texto)
        ancho_pastilla = extents.width + 8
        cr.set_source_rgba(*_COLOR_HOY, 0.95)
        cr.rectangle(x_hoy - ancho_pastilla / 2, 0, ancho_pastilla, _ALTURA_NIVEL_SUPERIOR - 1)
        cr.fill()
        cr.set_source_rgba(1, 1, 1, 1)
        cr.move_to(x_hoy - extents.width / 2 - extents.x_bearing, _ALTURA_NIVEL_SUPERIOR - 4)
        cr.show_text(texto)
