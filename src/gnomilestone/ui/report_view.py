from __future__ import annotations

import math

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk

from gnomilestone.i18n import _
from gnomilestone.models import EstadoTablero, Tarea


class ReportView(Gtk.Box):
    """Resumen visual del avance del proyecto, sin dependencias de gráficos externas."""

    def __init__(self) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.set_margin_top(18)
        self.set_margin_start(18)
        self.set_margin_end(18)
        self.set_margin_bottom(18)
        self._summary = Gtk.Label(xalign=0)
        self._summary.add_css_class("title-3")
        self.append(self._summary)
        self._drawing = Gtk.DrawingArea(content_width=720, content_height=420)
        self._drawing.set_hexpand(True)
        self._drawing.set_vexpand(True)
        self._drawing.set_draw_func(self._draw)
        self.append(self._drawing)
        self._tareas: list[Tarea] = []
        self._estados: list[EstadoTablero] = []

    def set_data(self, tareas: list[Tarea], estados: list[EstadoTablero]) -> None:
        self._tareas = tareas
        self._estados = estados
        total = len(tareas)
        completadas = sum(t.porcentaje_completado >= 100 for t in tareas)
        progreso = sum(t.porcentaje_completado for t in tareas) / total if total else 0
        self._summary.set_text(
            _("{total} tareas · {completadas} completadas · Progreso medio: {progreso:.0f}%").format(
                total=total, completadas=completadas, progreso=progreso
            )
        )
        self._drawing.queue_draw()

    def _draw(self, _area: Gtk.DrawingArea, cr, width: int, height: int) -> None:
        cr.set_line_width(1)
        cr.set_source_rgb(0.55, 0.55, 0.55)
        cr.move_to(48, 25)
        cr.line_to(48, height - 50)
        cr.line_to(width - 20, height - 50)
        cr.stroke()
        self._draw_progress(cr, width, height)
        self._draw_status(cr, width, height)
        self._draw_buckets(cr, width, height)

    def _draw_progress(self, cr, width: int, height: int) -> None:
        tasks = self._tareas
        avg = sum(t.porcentaje_completado for t in tasks) / len(tasks) if tasks else 0
        x, y, w, h = 70, 55, max(160, width - 110), 28
        cr.set_source_rgb(0.82, 0.84, 0.87)
        cr.rectangle(x, y, w, h)
        cr.fill()
        cr.set_source_rgb(0.20, 0.55, 0.38)
        cr.rectangle(x, y, w * min(100, max(0, avg)) / 100, h)
        cr.fill()
        cr.set_source_rgb(0.2, 0.2, 0.2)
        cr.select_font_face("Sans", 0, 1)
        cr.set_font_size(14)
        cr.move_to(x, y - 12)
        cr.show_text(_("Progreso global: {value:.0f}%").format(value=avg))

    def _draw_status(self, cr, width: int, height: int) -> None:
        counts = []
        for estado in self._estados:
            counts.append((estado.nombre, sum(t.estado_id == estado.id for t in self._tareas)))
        if not counts:
            return
        x0, y0, w, h = 70, 145, max(160, width - 110), 120
        max_count = max(1, max(c for _, c in counts))
        bar_w = max(18, min(70, (w - 20) / len(counts) - 10))
        for i, (name, count) in enumerate(counts):
            x = x0 + i * (w / len(counts)) + 10
            bh = h * count / max_count
            cr.set_source_rgb(0.27, 0.48, 0.72)
            cr.rectangle(x, y0 + h - bh, bar_w, bh)
            cr.fill()
            cr.set_source_rgb(0.2, 0.2, 0.2)
            cr.set_font_size(11)
            cr.move_to(x, y0 + h + 18)
            cr.show_text(name[:12])
            cr.move_to(x + bar_w / 3, y0 + h - bh - 6)
            cr.show_text(str(count))
        cr.set_font_size(14)
        cr.move_to(x0, y0 - 12)
        cr.show_text(_("Tareas por estado"))

    def _draw_buckets(self, cr, width: int, height: int) -> None:
        buckets = [sum(t.porcentaje_completado == 0 for t in self._tareas),
                   sum(0 < t.porcentaje_completado < 100 for t in self._tareas),
                   sum(t.porcentaje_completado >= 100 for t in self._tareas)]
        labels = [_('Sin empezar'), _('En curso'), _('Completadas')]
        total = max(1, sum(buckets))
        cx, cy, radius = width - 145, height - 120, 58
        start = -math.pi / 2
        colors = ((0.62, 0.65, 0.70), (0.95, 0.65, 0.20), (0.20, 0.55, 0.38))
        for count, color in zip(buckets, colors):
            sweep = 2 * math.pi * count / total
            cr.set_source_rgb(*color)
            cr.move_to(cx, cy)
            cr.arc(cx, cy, radius, start, start + sweep)
            cr.close_path()
            cr.fill()
            start += sweep
        cr.set_source_rgb(0.2, 0.2, 0.2)
        cr.set_font_size(14)
        cr.move_to(width - 235, cy - radius - 12)
        cr.show_text(_("Avance"))
        cr.set_font_size(11)
        for i, label in enumerate(labels):
            cr.move_to(width - 235, cy + 75 + i * 16)
            cr.show_text(f"{label}: {buckets[i]}")
