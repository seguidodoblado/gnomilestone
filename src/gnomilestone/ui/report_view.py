from __future__ import annotations

import math
from datetime import datetime, timedelta

import cairo
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
from gnomilestone.models import Asignacion, Dependencia, EstadoTablero, Recurso, Tarea
from gnomilestone.report_metrics import (
    estado_github,
    reparto_por_recurso,
    ruta_critica,
)
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
        self._details = Gtk.Label(xalign=0, wrap=True)
        self._details.add_css_class("dim-label")
        self.append(self._details)
        self._drawing = Gtk.DrawingArea(content_width=720, content_height=420)
        self._drawing.set_hexpand(True)
        self._drawing.set_vexpand(True)
        self._drawing.set_draw_func(self._draw)
        self.append(self._drawing)
        self._insights = Gtk.DrawingArea(content_width=720, content_height=330)
        self._insights.set_hexpand(True)
        self._insights.set_content_height(330)
        self._insights.set_vexpand(False)
        self._insights.set_can_target(True)
        self._insights.set_draw_func(self._draw_insights)
        self.append(self._insights)
        self._tareas: list[Tarea] = []
        self._estados: list[EstadoTablero] = []
        self._font_family = "Sans"
        self._font_size = 11.0
        self._recursos: list[Recurso] = []
        self._asignaciones: list[Asignacion] = []
        self._alertas = (0, 0, 0)
        self._reparto = []
        self._critica = []
        self._tareas_semana = []
        self._tarea_expandida = None
        self._criticos_colapsados = set()
        self._timeline_hitboxes = []
        self._dependencias = []
        gesto = Gtk.GestureClick()
        gesto.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        gesto.connect("pressed", self._on_insights_pressed)
        self._insights.add_controller(gesto)

    def set_data(
        self,
        tareas: list[Tarea],
        estados: list[EstadoTablero],
        recursos: list[Recurso] | None = None,
        asignaciones: list[Asignacion] | None = None,
        dependencias: list[Dependencia] | None = None,
    ) -> None:
        self._tareas = tareas
        self._estados = estados
        self._recursos = recursos or []
        self._asignaciones = asignaciones or []
        reparto = sorted(
            reparto_por_recurso(self._recursos, tareas, self._asignaciones),
            key=lambda fila: (-fila.tareas, -fila.progreso_medio, fila.recurso.nombre.casefold()),
        )
        sin_tareas = sum(fila.tareas == 0 for fila in reparto)
        critica = ruta_critica(tareas, dependencias or [])
        self._reparto, self._critica = reparto, critica
        self._dependencias = dependencias or []
        self._tareas_semana = [
            tarea for tarea in tareas
            if tarea.fecha_inicio
        ]
        github = estado_github(tareas)
        self._details.set_text(
            _("Ruta crítica: {critica} · "
              "Recursos sin tareas: {sin_tareas} · GitHub vinculadas: {vinculadas}, locales: {locales}").format(
                critica=" → ".join(t.titulo for t in critica) or _("sin dependencias"),
                sin_tareas=sin_tareas,
                vinculadas=github.vinculadas, locales=github.locales,
            )
        )
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
        self._insights.queue_draw()

    def _draw_insights(self, _area: Gtk.DrawingArea, cr, width: int, height: int) -> None:
        """Gráficos adicionales: reparto por persona y ruta crítica."""
        cr.set_source_rgb(*getattr(self, "_text_color", (0.2, 0.2, 0.2)))
        cr.select_font_face(self._font_family, 0, 0)
        cr.set_font_size(max(11, self._font_size))
        gap = 22
        left_w = max(250, int(width * 0.29))
        mid_w = max(420, width - left_w - gap)
        self._draw_insight_panel(cr, 0, 0, left_w, height, _("Reparto por persona"))
        self._draw_insight_panel(cr, left_w + gap, 0, mid_w, height, _("Ruta crítica"))
        self._draw_resource_bars(cr, 18, 48, left_w - 36)
        self._draw_critical_path(cr, left_w + gap + 18, 48, mid_w - 36)

    def _draw_insight_panel(self, cr, x, y, width, height, title):
        cr.set_source_rgba(0.12, 0.13, 0.15, 0.24)
        cr.rectangle(x, y, width, height)
        cr.fill()
        cr.set_source_rgb(*getattr(self, "_text_color", (0.2, 0.2, 0.2)))
        cr.set_font_size(max(14, self._font_size + 2))
        cr.move_to(x + 12, y + 22)
        cr.show_text(title)

    def _draw_resource_bars(self, cr, x, y, width):
        filas = self._reparto[:7]
        if not filas:
            return
        max_tareas = max(1, max(f.tareas for f in filas))
        cr.set_font_size(max(12, self._font_size))
        for i, fila in enumerate(filas):
            yy = y + i * 31
            cr.set_source_rgb(*getattr(self, "_text_color", (0.2, 0.2, 0.2)))
            cr.move_to(x, yy + 12)
            cr.show_text(fila.recurso.nombre[:14])
            bx = x + min(100, width * 0.42)
            bw = max(20, width - (bx - x) - 8)
            bar_y, bar_h, radius = yy, 20, 10
            self._rounded_rectangle(cr, bx, bar_y, bw, bar_h, radius)
            cr.set_source_rgba(0.12, 0.22, 0.38, 0.75)
            cr.fill()
            progreso_w = bw * fila.tareas / max_tareas
            if progreso_w:
                self._rounded_rectangle(cr, bx, bar_y, progreso_w, bar_h, radius)
                gradiente = cairo.LinearGradient(bx, bar_y, bx + progreso_w, bar_y + bar_h)
                gradiente.add_color_stop_rgb(0, 0.18, 0.42, 0.78)
                gradiente.add_color_stop_rgb(1, 0.30, 0.62, 0.95)
                cr.set_source(gradiente)
                cr.fill()
            cr.set_source_rgb(0.96, 0.98, 1.0)
            cr.set_font_size(max(12, self._font_size))
            etiqueta = _("{tareas} tareas · {progreso:.0f}%").format(
                tareas=fila.tareas, progreso=fila.progreso_medio
            )
            ext = cr.text_extents(etiqueta)
            cr.move_to(bx + (bw - ext.width) / 2, bar_y + 14)
            cr.show_text(etiqueta)

    def _draw_critical_path(self, cr, x, y, width):
        if self._tareas_semana:
            self._draw_week_timeline(cr, x, y, width)
            return
        if not self._critica:
            cr.set_source_rgb(*getattr(self, "_text_color", (0.2, 0.2, 0.2)))
            cr.set_font_size(max(12, self._font_size))
            cr.move_to(x, y + 32)
            cr.show_text(_("No hay dependencias críticas"))
            return
        paso = max(34, min(76, width / len(self._critica)))
        cadena_w = paso * max(0, len(self._critica) - 1)
        x += max(0, (width - cadena_w) / 2)
        cr.set_line_width(3)
        cr.set_source_rgb(0.88, 0.20, 0.14)
        node_w, node_h = min(92, paso * 0.72), 42
        node_y = y + 12
        line_y = node_y + node_h / 2
        cr.move_to(x, line_y)
        cr.line_to(x + paso * max(0, len(self._critica) - 1), line_y)
        cr.stroke()
        cr.set_font_size(max(11, self._font_size - 1))
        for i, tarea in enumerate(self._critica):
            xx = x + i * paso
            cr.set_source_rgb(0.88, 0.20, 0.14)
            self._rounded_rectangle(cr, xx - node_w / 2, node_y, node_w, node_h, 8)
            cr.fill()
            cr.set_source_rgb(*getattr(self, "_text_color", (0.2, 0.2, 0.2)))
            cr.set_font_size(max(11, self._font_size - 1))
            titulo = tarea.titulo[:13]
            ext = cr.text_extents(titulo)
            cr.move_to(xx - ext.width / 2, node_y + 17)
            cr.show_text(titulo)
            cr.set_font_size(max(9, self._font_size - 3))
            detalle = f"{max(tarea.duracion_dias, 1)} d · {tarea.porcentaje_completado}%"
            ext = cr.text_extents(detalle)
            cr.move_to(xx - ext.width / 2, node_y + 33)
            cr.show_text(detalle)
        cr.set_source_rgb(*getattr(self, "_text_color", (0.2, 0.2, 0.2)))
        cr.set_font_size(max(12, self._font_size))
        if len(self._critica) == 1:
            leyenda = _("Única tarea crítica")
        else:
            leyenda = _("Esta cadena puede retrasar el proyecto")
        ext = cr.text_extents(leyenda)
        # x es el centro de la cadena; la leyenda se centra en el ancho disponible
        # de la tarjeta, no en el primer nodo.
        centro = x + cadena_w / 2
        cr.move_to(centro - ext.width / 2, y + 112)
        cr.show_text(leyenda)

    def _draw_week_timeline(self, cr, x, y, width):
        """Línea temporal centrada en el primer evento crítico."""
        criticos = {t.id for t in self._critica}
        criticos_datos = sorted(
            (t for t in self._tareas_semana if t.id in criticos),
            key=lambda t: t.fecha_inicio or "",
        )
        centro = parse_fecha(criticos_datos[0].fecha_inicio) if criticos_datos else parse_fecha(self._tareas_semana[0].fecha_inicio)
        inicio = centro - timedelta(days=3)
        fin = centro + timedelta(days=3)
        tareas = [
            t for t in self._tareas_semana
            if t.fecha_inicio and inicio <= parse_fecha(t.fecha_inicio) <= fin
        ]
        self._timeline_hitboxes = []
        cr.set_font_size(max(9, self._font_size - 2))
        eje_y = y + 118
        cr.set_line_width(2)
        cr.set_source_rgba(*getattr(self, "_text_color", (0.2, 0.2, 0.2)), 0.45)
        cr.move_to(x, eje_y)
        cr.line_to(x + width, eje_y)
        cr.stroke()
        for dia in range(7):
            xx = x + width * dia / 6
            cr.set_source_rgba(*getattr(self, "_text_color", (0.2, 0.2, 0.2)), 0.35)
            cr.move_to(xx, eje_y - 5)
            cr.line_to(xx, eje_y + 5)
            cr.stroke()
            cr.set_source_rgb(*getattr(self, "_text_color", (0.2, 0.2, 0.2)))
            cr.move_to(xx - 8, eje_y + 72)
            cr.show_text((inicio + timedelta(days=dia)).strftime("%a")[:3])
        tareas = sorted(
            tareas,
            key=lambda t: (t.fecha_inicio or "", t.id not in criticos, t.id),
        )[:8]
        por_dia = {}
        for tarea in tareas:
            por_dia.setdefault(parse_fecha(tarea.fecha_inicio), []).append(tarea)
        for indice, tarea in enumerate(tareas):
            fecha = parse_fecha(tarea.fecha_inicio)
            dia = max(0, min(6, (fecha - inicio).days))
            grupo = por_dia[fecha]
            posicion = grupo.index(tarea)
            desplazamiento = (posicion - (len(grupo) - 1) / 2) * min(30, width / 18)
            xx = max(x + 5, min(x + width - 5, x + width * dia / 6 + desplazamiento))
            critico = tarea.id in criticos
            expandido = (critico and tarea.id not in self._criticos_colapsados) or tarea.id == self._tarea_expandida
            color = (0.88, 0.20, 0.14) if critico else (0.22, 0.47, 0.84)
            if not expandido:
                cr.set_source_rgb(*color)
                cr.arc(xx, eje_y, 5, 0, 2 * math.pi)
                cr.fill()
                self._timeline_hitboxes.append((xx - 12, eje_y - 12, xx + 12, eje_y + 12, tarea.id))
                continue
            popup_w = min(112, max(72, width / 2.8))
            popup_h = 34 if critico else 28
            encima = indice % 2 == 0
            popup_y = eje_y - 68 if encima else eje_y + 18
            popup_x = max(x, min(x + width - popup_w, xx - popup_w / 2))
            self._rounded_rectangle(cr, popup_x, popup_y, popup_w, popup_h, 7)
            if critico:
                oscuro, claro = (0.68, 0.08, 0.10), (0.96, 0.25, 0.20)
            else:
                oscuro, claro = (0.12, 0.34, 0.68), (0.28, 0.62, 0.95)
            gradiente = cairo.LinearGradient(popup_x, popup_y, popup_x, popup_y + popup_h)
            gradiente.add_color_stop_rgb(0, *claro)
            gradiente.add_color_stop_rgb(1, *oscuro)
            cr.set_source(gradiente)
            cr.fill()
            cr.set_line_width(1.5)
            cr.move_to(xx, popup_y + popup_h if encima else popup_y)
            cr.line_to(xx, eje_y)
            cr.stroke()
            cr.set_source_rgb(*color)
            cr.arc(xx, eje_y, 6 if critico else 4, 0, 2 * math.pi)
            cr.fill()
            cr.set_source_rgb(*getattr(self, "_text_color", (0.2, 0.2, 0.2)))
            cr.set_font_size(max(9, self._font_size - 3))
            titulo = tarea.titulo[:15]
            ext = cr.text_extents(titulo)
            cr.move_to(popup_x + (popup_w - ext.width) / 2, popup_y + 14)
            cr.show_text(titulo)
            if critico:
                cr.set_font_size(max(8, self._font_size - 4))
                detalle = f"{tarea.porcentaje_completado}% · {tarea.duracion_dias} d"
                ext = cr.text_extents(detalle)
                cr.move_to(popup_x + (popup_w - ext.width) / 2, popup_y + 27)
                cr.show_text(detalle)
            self._timeline_hitboxes.append((popup_x, popup_y, popup_x + popup_w, popup_y + popup_h, tarea.id))
        cr.set_font_size(max(10, self._font_size - 1))
        cr.set_source_rgb(*getattr(self, "_text_color", (0.2, 0.2, 0.2)))
        cr.set_font_size(max(10, self._font_size - 1))
        leyenda = _("Ventana de 7 días centrada en el primer evento crítico · rojo = crítico")
        if not self._critica:
            leyenda = _("Ventana de 7 días centrada en el primer evento relevante")
        ext = cr.text_extents(leyenda)
        cr.move_to(x + (width - ext.width) / 2, y + 250)
        cr.show_text(leyenda)

    def _on_insights_pressed(self, _gesture, _n_press, x, y):
        if not self._timeline_hitboxes:
            return
        for x0, y0, x1, y1, tarea_id in self._timeline_hitboxes:
            if x0 <= x <= x1 and y0 <= y <= y1:
                if tarea_id in {t.id for t in self._critica}:
                    if tarea_id in self._criticos_colapsados:
                        self._criticos_colapsados.remove(tarea_id)
                    else:
                        self._criticos_colapsados.add(tarea_id)
                else:
                    self._tarea_expandida = None if self._tarea_expandida == tarea_id else tarea_id
                self._insights.queue_draw()
                return

    @staticmethod
    def _rounded_rectangle(cr, x, y, width, height, radius):
        """Dibuja un rectángulo redondeado compatible con pycairo."""
        radius = min(radius, width / 2, height / 2)
        cr.new_sub_path()
        cr.arc(x + width - radius, y + radius, radius, -math.pi / 2, 0)
        cr.arc(x + width - radius, y + height - radius, radius, 0, math.pi / 2)
        cr.arc(x + radius, y + height - radius, radius, math.pi / 2, math.pi)
        cr.arc(x + radius, y + radius, radius, math.pi, 3 * math.pi / 2)
        cr.close_path()

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
        self._rounded_rectangle(cr, x, y, w, h, h / 2)
        cr.fill()
        gradiente = cairo.LinearGradient(x, y, x + w, y + h)
        gradiente.add_color_stop_rgb(0, 0.12, 0.42, 0.30)
        gradiente.add_color_stop_rgb(1, 0.30, 0.72, 0.48)
        cr.set_source(gradiente)
        relleno = w * min(100, max(0, avg)) / 100
        if relleno > 0:
            cr.save()
            self._rounded_rectangle(cr, x, y, w, h, h / 2)
            cr.clip()
            cr.rectangle(x, y, relleno, h)
            cr.fill()
            cr.restore()
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
            gradiente = cairo.LinearGradient(x, y0 + h - bh, x + bar_w, y0 + h)
            gradiente.add_color_stop_rgb(0, *tuple(min(1, c * 0.72) for c in color))
            gradiente.add_color_stop_rgb(1, *color)
            cr.set_source(gradiente)
            self._rounded_rectangle(cr, x, y0 + h - bh, bar_w, bh, min(8, bar_w / 2, bh / 2))
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
        # El circular ocupa la mitad superior; la leyenda queda siempre debajo.
        cx, cy, radius = panel_x + panel_w // 2, panel_y + panel_h * 0.36, min(88, max(58, panel_w // 4))
        start = -math.pi / 2
        colors = ((0.62, 0.65, 0.70), (0.95, 0.65, 0.20), (0.20, 0.55, 0.38))
        for count, color in zip(buckets, colors):
            sweep = 2 * math.pi * count / total
            gradiente = cairo.RadialGradient(cx - radius * 0.35, cy - radius * 0.45, radius * 0.1, cx, cy, radius)
            gradiente.add_color_stop_rgb(0, *(min(1, c * 1.18) for c in color))
            gradiente.add_color_stop_rgb(1, *color)
            cr.set_source(gradiente)
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
            cr.move_to(panel_x + 28, panel_y + panel_h - 76 + i * 18)
            cr.show_text(f"{label}: {buckets[i]}")
        self._draw_alerts(cr, panel_x, panel_y, panel_w, panel_h)

    def _draw_alerts(self, cr, panel_x: int, panel_y: int, panel_w: int, panel_h: int) -> None:
        """Muestra un resumen de fechas para detectar desviaciones rápidamente."""
        vencidas, planificadas, proximas = self._alertas
        x = panel_x + panel_w * 0.55
        y = panel_y + panel_h - 76
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
