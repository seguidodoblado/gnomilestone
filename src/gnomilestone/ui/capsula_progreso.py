"""Cápsula de progreso: barra redondeada que se rellena según el avance, con el texto encima.

El texto cambia de color justo donde cruza el borde del relleno, para leerse bien sobre
cada fondo (el del relleno y el de la parte vacía), sea cual sea el tema o el color de acento.
"""

from __future__ import annotations

import math

import gi

gi.require_version("Gdk", "4.0")
gi.require_version("Gtk", "4.0")
gi.require_version("Pango", "1.0")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Gdk, Gtk, Pango, PangoCairo

ALTURA = 22
_MARGEN_TEXTO = 8
_CONTRASTE_MINIMO_BLANCO = 3.5


def _lineal(canal: float) -> float:
    return canal / 12.92 if canal <= 0.03928 else ((canal + 0.055) / 1.055) ** 2.4


def luminancia(r: float, g: float, b: float) -> float:
    """Luminancia relativa (WCAG) de un color con canales 0-1."""
    return 0.2126 * _lineal(r) + 0.7152 * _lineal(g) + 0.0722 * _lineal(b)


def texto_sobre(r: float, g: float, b: float) -> tuple[float, float, float]:
    """Blanco o negro según el fondo. Se prefiere el blanco (como hace GNOME sobre el color de
    acento) mientras su contraste WCAG sea al menos 3,5; si no, negro."""
    contraste_blanco = 1.05 / (luminancia(r, g, b) + 0.05)
    return (1.0, 1.0, 1.0) if contraste_blanco >= _CONTRASTE_MINIMO_BLANCO else (0.0, 0.0, 0.0)


class CapsulaProgreso(Gtk.DrawingArea):
    def __init__(self, texto: str, fraccion: float) -> None:
        super().__init__()
        self._texto = texto
        self._fraccion = max(0.0, min(1.0, fraccion))
        self.add_css_class("gnomilestone-capsula")
        self.set_content_height(ALTURA)
        self.set_hexpand(True)
        self.set_draw_func(self._dibujar)

    def _color(
        self, nombre: str, por_defecto: tuple[float, float, float]
    ) -> tuple[float, float, float]:
        encontrado, rgba = self.get_style_context().lookup_color(nombre)
        if not encontrado:
            return por_defecto
        return (rgba.red, rgba.green, rgba.blue)

    def _color_texto(self) -> tuple[float, float, float]:
        rgba = self.get_color() if hasattr(self, "get_color") else Gdk.RGBA()
        return (rgba.red, rgba.green, rgba.blue)

    def _dibujar(self, _area: Gtk.DrawingArea, cr, ancho: int, alto: int) -> None:
        radio = alto / 2

        def contorno() -> None:
            cr.new_sub_path()
            cr.arc(ancho - radio, radio, radio, -math.pi / 2, math.pi / 2)
            cr.arc(radio, radio, radio, math.pi / 2, 3 * math.pi / 2)
            cr.close_path()

        texto_normal = self._color_texto()
        acento = self._color("accent_bg_color", (0.21, 0.52, 0.89))
        cr.save()
        contorno()
        cr.clip()
        # Parte vacía: el color de texto del tema muy atenuado sobre la tarjeta.
        cr.set_source_rgba(*texto_normal, 0.18)
        cr.paint()
        corte = ancho * self._fraccion
        cr.set_source_rgb(*acento)
        cr.rectangle(0, 0, corte, alto)
        cr.fill()
        cr.restore()

        layout = self.create_pango_layout(self._texto)
        layout.set_width(int((ancho - 2 * _MARGEN_TEXTO) * Pango.SCALE))
        layout.set_ellipsize(Pango.EllipsizeMode.END)
        _w, alto_texto = layout.get_pixel_size()
        y = (alto - alto_texto) / 2

        # Parte vacía: el color de texto del tema. Parte rellena: el de mayor contraste
        # con el color de acento.
        for desde, hasta, color in (
            (corte, ancho, texto_normal),
            (0, corte, texto_sobre(*acento)),
        ):
            if hasta <= desde:
                continue
            cr.save()
            cr.rectangle(desde, 0, hasta - desde, alto)
            cr.clip()
            cr.set_source_rgb(*color)
            cr.move_to(_MARGEN_TEXTO, y)
            PangoCairo.show_layout(cr, layout)
            cr.restore()
