from __future__ import annotations

import math
from datetime import datetime

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, Pango, PangoCairo

from gnomilestone.documentacion import EventoRoadmap, eventos_pasados
from gnomilestone.i18n import _
from gnomilestone.ui.zoom import Centrador, Zoom, factor_de_ajuste

_COLOR_HOY = (0.86, 0.2, 0.2)  # el rojo de la línea de «hoy» del Gantt
_PASO = 170  # separación horizontal entre eventos
_CAJA_W, _CAJA_H = 140, 48
_ALTO = 380
_INICIO_EVENTOS = 200  # x del primer evento: deja sitio a la cabeza (proyecto) a la izquierda


def _tema_oscuro() -> bool:
    ajustes = Gtk.Settings.get_default()
    return bool(ajustes and "dark" in (ajustes.get_property("gtk-theme-name") or "").lower())


def _caja(cr, x, y, w, h, radio) -> None:
    radio = min(radio, w / 2, h / 2)
    cr.new_sub_path()
    cr.arc(x + w - radio, y + radio, radio, -math.pi / 2, 0)
    cr.arc(x + w - radio, y + h - radio, radio, 0, math.pi / 2)
    cr.arc(x + radio, y + h - radio, radio, math.pi / 2, math.pi)
    cr.arc(x + radio, y + radio, radio, math.pi, 3 * math.pi / 2)
    cr.close_path()


class RoadmapView(Gtk.Box):
    """Línea de tiempo en espina de pescado: una espina horizontal con los eventos del
    proyecto (hitos y tareas de primer nivel) como cajas alternadas arriba y abajo, y el
    proyecto como cabeza al inicio (a la izquierda). Ámbar = hito, lavanda = tarea; completados, atenuados.
    Una marca «Hoy» separa el pasado (zona más tenue) del futuro.
    Zoom con botones o Ctrl+rueda; al abrirse queda centrada."""

    def __init__(self) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6, hexpand=True, vexpand=True)
        self._eventos: list[EventoRoadmap] = []
        self._nombre = ""
        self._zoom = Zoom(self._on_zoom, self._ajustar)
        self.append(self._zoom.botones())
        self._area = Gtk.DrawingArea()
        self._area.set_hexpand(True)
        self._area.set_vexpand(True)
        self._area.set_draw_func(self._dibujar)
        self._scroller = Gtk.ScrolledWindow(hexpand=True, vexpand=True)
        self._scroller.set_child(self._area)
        self.append(self._scroller)
        self._zoom.conectar_rueda(self._scroller)
        self._centrador = Centrador(self._scroller)
        self._ajustar_tamano()

    def _ancho_base(self) -> int:
        return max(520, _INICIO_EVENTOS + len(self._eventos) * _PASO + 40)

    def _ajustar_tamano(self) -> None:
        """En modo ajuste el dibujo ocupa justo la vista (sin scroll) y se escala al pintar;
        con zoom manual tiene el tamaño del contenido escalado y la vista hace scroll."""
        if self._zoom.auto:
            self._area.set_content_width(0)
            self._area.set_content_height(0)
        else:
            z = self._zoom.factor
            self._area.set_content_width(int(self._ancho_base() * z))
            self._area.set_content_height(int(_ALTO * z))
        self._area.queue_draw()

    def set_datos(self, nombre_proyecto: str, eventos: list[EventoRoadmap]) -> None:
        self._nombre = nombre_proyecto
        self._eventos = eventos
        self._ajustar()

    def _ajustar(self) -> None:
        """Vuelve al ajuste automático: se ve todo el Roadmap, centrado."""
        self._zoom.auto = True
        self._ajustar_tamano()

    def _on_zoom(self, ancla) -> None:
        fx, fy, ox, oy = self._centrador.capturar(ancla)
        self._ajustar_tamano()
        self._centrador.pedir(fx, fy, ox, oy)

    def _texto(
        self, cr, texto: str, centro_x: float, y: float, px: float, ancho_max: float,
        negrita: bool = False,
    ) -> None:
        """Texto centrado en `centro_x` con la tipografía del sistema (la del widget), con
        puntos suspensivos si no cabe en `ancho_max`. `y` es el borde superior del texto."""
        layout = self._area.create_pango_layout(texto)
        descripcion = self._area.get_pango_context().get_font_description().copy()
        descripcion.set_absolute_size(px * Pango.SCALE)
        if negrita:
            descripcion.set_weight(Pango.Weight.BOLD)
        layout.set_font_description(descripcion)
        layout.set_width(int(ancho_max * Pango.SCALE))
        layout.set_ellipsize(Pango.EllipsizeMode.END)
        layout.set_alignment(Pango.Alignment.CENTER)
        cr.move_to(centro_x - ancho_max / 2, y)
        PangoCairo.show_layout(cr, layout)

    def _dibujar(self, _area, cr, ancho_real: int, alto_real: int) -> None:
        ancho = self._ancho_base()
        if self._zoom.auto:
            # El factor se recalcula con el tamaño real de la vista (sin carreras con el
            # layout) y se guarda para que el zoom manual parta de lo que se ve.
            self._zoom.factor = factor_de_ajuste(ancho_real, alto_real, ancho, _ALTO)
        z = self._zoom.factor
        cr.scale(z, z)
        ancho_vista, alto = ancho_real / z, alto_real / z
        # El dibujo mide `_ancho_base()`; si la vista es más ancha, se centra.
        cr.translate(max(0.0, (ancho_vista - ancho) / 2), 0)
        oscuro = _tema_oscuro()
        texto = (0.92, 0.92, 0.95) if oscuro else (0.16, 0.16, 0.22)
        linea = (0.55, 0.55, 0.95) if oscuro else (0.30, 0.30, 0.78)
        cabeza = (0.53, 0.53, 1.0)
        tarea_c = (0.30, 0.30, 0.50) if oscuro else (0.85, 0.85, 1.0)
        hito_c = (0.95, 0.76, 0.22)
        eje = alto / 2

        if not self._eventos:
            cr.set_source_rgb(*texto)
            self._texto(cr, _("No hay hitos ni tareas con fecha para el Roadmap."),
                        ancho / 2, eje - 9, 14, ancho - 32)
            return

        cabeza_w, cabeza_h = 170, 64
        cabeza_x = 16
        cr.set_source_rgb(*linea)
        cr.set_line_width(3)
        cr.move_to(cabeza_x + cabeza_w, eje)
        cr.line_to(ancho - 16, eje)
        cr.stroke()
        _caja(cr, cabeza_x, eje - cabeza_h / 2, cabeza_w, cabeza_h, 12)
        cr.set_source_rgb(*cabeza)
        cr.fill()
        cr.set_source_rgb(0.08, 0.08, 0.2)
        self._texto(cr, self._nombre, cabeza_x + cabeza_w / 2, eje - 10, 14,
                    cabeza_w - 16, negrita=True)

        # «Dónde estás»: todo lo anterior a hoy es pasado (zona más tenue) y la marca «Hoy»
        # se coloca entre el último evento pasado y el primero de hoy o futuro.
        pasados = eventos_pasados(self._eventos, datetime.now().astimezone().date())
        if pasados == 0:
            x_hoy = (cabeza_x + cabeza_w + _INICIO_EVENTOS) / 2
        else:
            x_hoy = _INICIO_EVENTOS + (pasados - 0.5) * _PASO
        cr.set_source_rgba(*texto, 0.07)
        cr.rectangle(0, 0, x_hoy, alto)
        cr.fill()
        cr.set_source_rgba(*_COLOR_HOY, 0.85)
        cr.set_line_width(2)
        cr.set_dash([6.0, 4.0])
        cr.move_to(x_hoy, 30)
        cr.line_to(x_hoy, alto - 10)
        cr.stroke()
        cr.set_dash([])
        _caja(cr, x_hoy - 26, 6, 52, 22, 11)
        cr.set_source_rgb(*_COLOR_HOY)
        cr.fill()
        cr.set_source_rgb(1, 1, 1)
        self._texto(cr, _("HOY"), x_hoy, 10, 11, 52, negrita=True)
        if pasados:
            cr.set_source_rgba(*texto, 0.55)
            self._texto(cr, _("◀ Pasado"), x_hoy - 50, 34, 10, 90)
        if pasados < len(self._eventos):
            cr.set_source_rgba(*texto, 0.55)
            self._texto(cr, _("Futuro ▶"), x_hoy + 50, 34, 10, 90)

        for i, evento in enumerate(self._eventos):
            x = _INICIO_EVENTOS + i * _PASO  # punto de la espina
            arriba = i % 2 == 0
            caja_x = x - _CAJA_W / 2 - 30
            caja_y = eje - 110 - _CAJA_H / 2 if arriba else eje + 110 - _CAJA_H / 2
            borde_y = caja_y + _CAJA_H if arriba else caja_y
            alfa = 0.55 if evento.completado else (0.8 if i < pasados else 1.0)
            # Rama diagonal de la espina a la caja.
            cr.set_source_rgba(*linea, alfa)
            cr.set_line_width(2)
            cr.move_to(x, eje)
            cr.line_to(caja_x + _CAJA_W / 2 + 10, borde_y)
            cr.stroke()
            cr.arc(x, eje, 4, 0, 2 * math.pi)
            cr.fill()
            _caja(cr, caja_x, caja_y, _CAJA_W, _CAJA_H, 8)
            cr.set_source_rgba(*(hito_c if evento.es_hito else tarea_c), alfa)
            cr.fill()
            cr.set_source_rgba(*((0.16, 0.12, 0.04) if evento.es_hito else texto), alfa)
            centro = caja_x + _CAJA_W / 2
            self._texto(cr, evento.titulo, centro, caja_y + 6, 12, _CAJA_W - 12)
            self._texto(cr, evento.fecha, centro, caja_y + 27, 10, _CAJA_W - 12)
