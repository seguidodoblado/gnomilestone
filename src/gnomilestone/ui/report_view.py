from __future__ import annotations

import math
from datetime import datetime, timedelta

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk

from gnomilestone import settings
from gnomilestone.ganttcalc import (
    PLANIFICADA_PASADA,
    VENCIDA,
    estado_vencimiento,
    parse_fecha,
)
from gnomilestone.i18n import _
from gnomilestone.models import Asignacion, EstadoTablero, Recurso, Tarea
from gnomilestone.ui.kanban_view import _PALETA_COLUMNAS


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
        self._font_family = "Sans"
        self._font_size = 11.0
        self._recursos: list[Recurso] = []
        self._asignaciones: list[Asignacion] = []
        self._alertas = (0, 0, 0)

    def set_data(
        self,
        tareas: list[Tarea],
        estados: list[EstadoTablero],
        recursos: list[Recurso] | None = None,
        asignaciones: list[Asignacion] | None = None,
    ) -> None:
        self._tareas = tareas
        self._estados = estados
        self._recursos = recursos or []
        self._asignaciones = asignaciones or []
        hoy = datetime.now().astimezone().date()
        dias_alerta = settings.read_settings().get("dias_alerta_vencimiento", 1)
        try:
            dias_alerta = max(0, int(dias_alerta))
        except (TypeError, ValueError):
            dias_alerta = 1
        vencidas = sum(estado_vencimiento(t, hoy, dias_alerta) == VENCIDA for t in tareas)
        planificadas = sum(estado_vencimiento(t, hoy, dias_alerta) == PLANIFICADA_PASADA for t in tareas)
        proximas = sum(
            bool(t.fecha_limite)
            and hoy < parse_fecha(t.fecha_limite) <= hoy + timedelta(days=7)
            and t.porcentaje_completado < 100
            for t in tareas
        )
        self._alertas = (vencidas, planificadas, proximas)
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
        settings = Gtk.Settings.get_default()
        dark = bool(settings and "dark" in (settings.get_property("gtk-theme-name") or "").lower())
        self._text_color = (0.90, 0.90, 0.92) if dark else (0.20, 0.20, 0.20)
        if settings:
            font_name = settings.get_property("gtk-font-name") or "Sans 11"
            family, _, size = font_name.rpartition(" ")
            self._font_family = family or "Sans"
            try:
                self._font_size = float(size)
            except ValueError:
                self._font_size = 11.0
        cr.set_line_width(1)
        cr.select_font_face(self._font_family, 0, 0)
        margin = 18
        gap = 18
        top_h = max(130, int(height * 0.24))
        bottom_y = margin + top_h + gap
        left_w = int((width - margin * 2 - gap) * 0.58)
        right_x = margin + left_w + gap
        right_w = width - right_x - margin
        self._draw_panel(cr, margin, margin, width - margin * 2, top_h)
        self._draw_panel(cr, margin, bottom_y, left_w, height - bottom_y - margin)
        self._draw_panel(cr, right_x, bottom_y, right_w, height - bottom_y - margin)
        self._draw_progress(cr, width, height)
        self._draw_status(cr, width, height, margin, bottom_y, left_w)
        self._draw_buckets(cr, right_x, right_w, bottom_y, height - bottom_y - margin)

    def _draw_panel(self, cr, x: int, y: int, width: int, height: int) -> None:
        cr.set_source_rgba(0.12, 0.13, 0.15, 0.36)
        cr.rectangle(x, y, width, height)
        cr.fill()
        cr.set_source_rgba(0.45, 0.47, 0.52, 0.45)
        cr.rectangle(x, y, width, height)
        cr.stroke()

    def _draw_progress(self, cr, width: int, height: int) -> None:
        tasks = self._tareas
        avg = sum(t.porcentaje_completado for t in tasks) / len(tasks) if tasks else 0
        x, y, w, h = 42, 72, max(160, width - 84), 58
        cr.set_source_rgb(0.82, 0.84, 0.87)
        cr.rectangle(x, y, w, h)
        cr.fill()
        cr.set_source_rgb(0.20, 0.55, 0.38)
        cr.rectangle(x, y, w * min(100, max(0, avg)) / 100, h)
        cr.fill()
        cr.set_source_rgb(*self._text_color)
        cr.select_font_face(self._font_family, 0, 1)
        cr.set_font_size(max(13, self._font_size + 1))
        cr.move_to(x, y - 12)
        cr.show_text(_("Progreso global: {value:.0f}%").format(value=avg))

    def _draw_status(self, cr, width: int, height: int, panel_x: int, panel_y: int, panel_w: int) -> None:
        counts = []
        for indice, estado in enumerate(self._estados):
            counts.append(
                (
                    estado.nombre,
                    sum(t.estado_id == estado.id for t in self._tareas),
                    self._hex_color(_PALETA_COLUMNAS[indice % len(_PALETA_COLUMNAS)]),
                )
            )
        if not counts:
            return
        x0, y0, w, h = panel_x + 28, panel_y + 68, panel_w - 56, max(100, height - panel_y - 115)
        max_count = max(1, max(c for _, c, _ in counts))
        bar_w = max(18, min(70, (w - 20) / len(counts) - 10))
        for i, (name, count, color) in enumerate(counts):
            x = x0 + i * (w / len(counts)) + 10
            bh = h * count / max_count
            cr.set_source_rgb(*color)
            cr.rectangle(x, y0 + h - bh, bar_w, bh)
            cr.fill()
            cr.set_source_rgb(*self._text_color)
            cr.set_font_size(max(12, self._font_size + 1))
            cr.move_to(x, y0 + h + 18)
            cr.show_text(name[:12])
            # Mantener el valor dentro del panel incluso cuando la barra llega al techo.
            label_x = x + max(0, (bar_w - cr.text_extents(str(count)).width) / 2)
            label_y = max(y0 + self._font_size + 4, y0 + h - bh - 8)
            cr.move_to(label_x, label_y)
            cr.show_text(str(count))
        cr.set_font_size(max(14, self._font_size + 2))
        cr.move_to(x0, y0 - 12)
        cr.show_text(_("Tareas por estado"))

    @staticmethod
    def _hex_color(value: str | None) -> tuple[float, float, float]:
        if value:
            raw = value.removeprefix("#")
            if len(raw) == 6:
                try:
                    return tuple(int(raw[i : i + 2], 16) / 255 for i in (0, 2, 4))
                except ValueError:
                    pass
        return (0.27, 0.48, 0.72)

    def _draw_buckets(self, cr, panel_x: int, panel_w: int, panel_y: int, panel_h: int) -> None:
        buckets = [sum(t.porcentaje_completado == 0 for t in self._tareas),
                   sum(0 < t.porcentaje_completado < 100 for t in self._tareas),
                   sum(t.porcentaje_completado >= 100 for t in self._tareas)]
        labels = [_('Sin empezar'), _('En curso'), _('Completadas')]
        total = max(1, sum(buckets))
        cx, cy, radius = panel_x + panel_w // 2, panel_y + panel_h // 2, min(100, max(62, panel_w // 4))
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
        cr.set_source_rgb(*self._text_color)
        cr.set_font_size(max(14, self._font_size + 2))
        cr.move_to(panel_x + 28, panel_y + 42)
        cr.show_text(_("Avance"))
        cr.set_font_size(max(12, self._font_size + 1))
        for i, label in enumerate(labels):
            cr.move_to(panel_x + 28, panel_y + panel_h - 62 + i * 18)
            cr.show_text(f"{label}: {buckets[i]}")
        self._draw_alerts(cr, panel_x, panel_y, panel_w, panel_h)

    def _draw_alerts(self, cr, panel_x: int, panel_y: int, panel_w: int, panel_h: int) -> None:
        """Muestra un resumen de fechas para detectar desviaciones rápidamente."""
        vencidas, planificadas, proximas = self._alertas
        x = panel_x + panel_w * 0.55
        y = panel_y + panel_h - 80
        cr.set_font_size(max(12, self._font_size + 1))
        cr.set_source_rgb(*self._text_color)
        cr.move_to(x, y - 18)
        cr.show_text(_("Fechas"))
        cr.set_source_rgb(0.88, 0.20, 0.14)
        cr.move_to(x, y)
        cr.show_text(_("Alerta roja (≤ 1 día): {count}").format(count=vencidas))
        cr.set_source_rgb(0.95, 0.55, 0.08)
        cr.move_to(x, y + 18)
        cr.show_text(_("Planificadas pasadas: {count}").format(count=planificadas))
        cr.set_source_rgb(*self._text_color)
        cr.move_to(x, y + 36)
        cr.show_text(_("Próximas 7 días: {count}").format(count=proximas))
        recursos_activos = len({a.recurso_id for a in self._asignaciones})
        cr.move_to(x, y + 54)
        cr.show_text(_("Recursos activos: {count}").format(count=recursos_activos))
