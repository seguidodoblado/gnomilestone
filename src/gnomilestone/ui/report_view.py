from __future__ import annotations

import math
from calendar import monthrange
from datetime import date, datetime, timedelta

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
from gnomilestone.models import (
    Asignacion,
    Dependencia,
    EstadoTablero,
    HistorialTarea,
    Recurso,
    Tarea,
)
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
        self._estado_circular = False
        self._avance_burndown = False
        self._ritmo_semanal = False
        self._ritmo_anual = True
        gesto_estado = Gtk.GestureClick()
        gesto_estado.connect("pressed", self._on_estado_card_pressed)
        self._drawing.add_controller(gesto_estado)
        grafica = Gtk.Overlay()
        grafica.set_hexpand(True)
        grafica.set_vexpand(True)
        grafica.set_child(self._drawing)
        self.append(grafica)
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
        self._tareas_expandidas = set()
        self._criticos_colapsados = set()
        self._timeline_hitboxes = []
        self._dependencias = []
        self._historial: list[HistorialTarea] = []
        gesto = Gtk.GestureClick()
        gesto.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        gesto.connect("pressed", self._on_insights_pressed)
        self._insights.add_controller(gesto)
        gesto_modos = Gtk.GestureClick()
        gesto_modos.connect("pressed", self._on_modo_informe_pressed)
        self._drawing.add_controller(gesto_modos)

    def set_data(
        self,
        tareas: list[Tarea],
        estados: list[EstadoTablero],
        recursos: list[Recurso] | None = None,
        asignaciones: list[Asignacion] | None = None,
        dependencias: list[Dependencia] | None = None,
        historial: list[HistorialTarea] | None = None,
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
        self._historial = historial or []
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

    def _on_estado_card_pressed(self, _gesture, _n_press, x, y) -> None:
        width, height = self._drawing.get_width(), self._drawing.get_height()
        if width <= 0 or height <= 0:
            return
        margin, gap = 18, 18
        top_h = max(130, int(height * 0.24))
        panel_y = margin + top_h + gap
        left_w = int((width - margin * 2 - gap * 2) * 0.42)
        selector_x = margin + left_w - 154
        # El selector segmentado es parte de la cabecera y conserva su posición.
        if selector_x <= x <= selector_x + 146 and panel_y + 17 <= y <= panel_y + 47:
            self._estado_circular = not self._estado_circular
            self._drawing.queue_draw()

    def _on_modo_informe_pressed(self, _gesture, _n_press, x, y) -> None:
        width = self._drawing.get_width()
        height = self._drawing.get_height()
        margin, gap = 18, 18
        top_h = max(130, int(height * 0.24))
        panel_y = margin + top_h + gap
        disponible = width - margin * 2 - gap * 2
        left_w = int(disponible * 0.42)
        middle_x = margin + left_w + gap
        middle_w = int(disponible * 0.31)
        if middle_x <= x <= middle_x + middle_w and panel_y <= y <= panel_y + 58:
            self._avance_burndown = not self._avance_burndown
            self._drawing.queue_draw()
        self._drawing.queue_draw()

    def _draw_insights(self, _area: Gtk.DrawingArea, cr, width: int, height: int) -> None:
        """Gráficos adicionales: reparto por persona y ruta crítica."""
        cr.set_source_rgb(*getattr(self, "_text_color", (0.2, 0.2, 0.2)))
        cr.select_font_face(self._font_family, 0, 0)
        cr.set_font_size(max(11, self._font_size))
        gap = 22
        left_w = max(230, int(width * 0.23))
        mid_w = max(360, int(width * 0.45))
        right_x = left_w + mid_w + gap * 2
        right_w = max(230, width - right_x)
        self._draw_insight_panel(cr, 0, 0, left_w, height, _("Reparto por persona"))
        self._draw_insight_panel(cr, left_w + gap, 0, mid_w, height, _("Ruta crítica"))
        self._draw_insight_panel(cr, right_x, 0, right_w, height, _("Ritmo de trabajo"))
        self._draw_resource_bars(cr, 18, 70, left_w - 36)
        self._draw_critical_path(cr, left_w + gap + 18, 48, mid_w - 36)
        self._draw_heatmap(cr, right_x + 18, 64, right_w - 36, height - 64)
        self._draw_mode_selector(cr, right_x + 18, 14, right_w - 36,
                                 (_("Anual"), _("Mensual")), self._ritmo_anual)

    def _draw_mode_selector(self, cr, x, y, width, opciones, segundo_activo, selector_w=None):
        selector_w = min(selector_w or 150, width)
        selector_x = x + width - selector_w
        self._rounded_rectangle(cr, selector_x, y, selector_w, 26, 6)
        cr.set_source_rgb(0.10, 0.11, 0.14)
        cr.fill()
        cr.set_font_size(max(10, self._font_size - 1))
        for indice, texto in enumerate(opciones):
            activo = (indice == 0) == segundo_activo
            ox, ow = selector_x + indice * selector_w / 2, selector_w / 2
            if activo:
                self._rounded_rectangle(cr, ox + 2, y + 2, ow - 4, 22, 4)
                cr.set_source_rgb(0.98, 0.32, 0.16)
                cr.fill()
            cr.set_source_rgb(1, 1, 1) if activo else cr.set_source_rgb(*self._text_color)
            ext = cr.text_extents(texto)
            cr.move_to(ox + (ow - ext.width) / 2, y + 17)
            cr.show_text(texto)

    def _draw_heatmap(self, cr, x, y, width, height):
        """Actividad diaria registrada en el historial de las tareas."""
        columnas, filas = (24, 16) if self._ritmo_anual else (7, 5)
        hoy = datetime.now().astimezone().date()
        dias_mes = monthrange(hoy.year, hoy.month)[1]
        if self._ritmo_anual:
            dias_mes = 366 if monthrange(hoy.year, 2)[1] == 29 else 365
        elif self._ritmo_semanal:
            primer_dia = hoy.replace(day=1)
            columnas = (primer_dia.weekday() + dias_mes + 6) // 7
        gap = 3 if self._ritmo_anual else 5
        limite_celda = 8 if self._ritmo_anual else 24
        celda = min(
            (width - gap * (columnas - 1)) / columnas,
            (height - 86 - gap * (filas - 1)) / filas,
            limite_celda,
        )
        inicio_x = x + max(0, (width - (celda * columnas + gap * (columnas - 1))) / 2)
        alto_grilla = celda * filas + gap * (filas - 1)
        inicio_y = y + max(28, (height - alto_grilla - 80) / 2)
        actividad: dict[str, int] = {}
        pesos = {"creacion": 1, "estado": 3, "progreso": 2, "planificacion": 2,
                 "planificacion_base": 2, "fin_real": 3, "fecha_inicio": 1, "limite": 1}
        for evento in self._historial:
            fecha = evento.creado[:10]
            try:
                date.fromisoformat(fecha)
            except ValueError:
                continue
            actividad[fecha] = actividad.get(fecha, 0) + pesos.get(evento.tipo, 1)
        max_actividad = max(actividad.values(), default=0)
        for fila in range(filas):
            for columna in range(columnas):
                dia = fila * columnas + columna
                if not self._ritmo_anual and dia >= dias_mes:
                    continue
                if self._ritmo_anual:
                    dia_anual = fila * columnas + columna
                    fecha = date(hoy.year, 1, 1) + timedelta(days=dia_anual)
                    valor = actividad.get(fecha.isoformat(), 0) if dia_anual < dias_mes else 0
                elif self._ritmo_semanal:
                    inicio_semana = hoy - timedelta(days=hoy.weekday())
                    fecha = inicio_semana - timedelta(weeks=columnas - columna - 1)
                    valor = sum(
                        cantidad for fecha_texto, cantidad in actividad.items()
                        if date.fromisoformat(fecha_texto).isocalendar()[:2]
                        == fecha.isocalendar()[:2]
                    )
                else:
                    fecha = hoy.replace(day=1) + timedelta(days=dia)
                    valor = actividad.get(fecha.isoformat(), 0)
                intensidad = valor / max_actividad if max_actividad else 0
                color = self._heatmap_color(intensidad) if valor else (0.23, 0.25, 0.30)
                xx = inicio_x + columna * (celda + gap)
                yy = inicio_y + fila * (celda + gap)
                self._rounded_rectangle(cr, xx, yy, celda, celda, 4)
                gradiente = cairo.LinearGradient(xx, yy, xx + celda, yy + celda)
                gradiente.add_color_stop_rgb(0, *(min(1, componente * 1.18) for componente in color))
                gradiente.add_color_stop_rgb(1, *(componente * 0.72 for componente in color))
                cr.set_source(gradiente)
                cr.fill()
                if not valor:
                    cr.set_source_rgba(0.48, 0.51, 0.57, 0.35)
                    cr.set_line_width(0.7)
                    self._rounded_rectangle(cr, xx, yy, celda, celda, 4)
                    cr.stroke()
        cr.set_font_size(max(9, self._font_size - 2))
        leyenda_y = inicio_y + filas * (celda + gap) + 14
        leyenda_ancho = celda * 5 + gap * 4
        leyenda_x = x + (width - leyenda_ancho) / 2
        for i in range(5):
            xx = leyenda_x + i * (celda + gap)
            intensidad = i / 4
            color = self._heatmap_color(intensidad)
            self._rounded_rectangle(cr, xx, leyenda_y, celda, 8, 3)
            gradiente = cairo.LinearGradient(xx, leyenda_y, xx + celda, leyenda_y + 8)
            gradiente.add_color_stop_rgb(0, *(min(1, componente * 1.18) for componente in color))
            gradiente.add_color_stop_rgb(1, *(componente * 0.72 for componente in color))
            cr.set_source(gradiente)
            cr.fill()
        cr.set_source_rgb(*self._text_color)
        etiqueta = _("Menos actividad → Más actividad")
        ext = cr.text_extents(etiqueta)
        cr.move_to(leyenda_x + (leyenda_ancho - ext.width) / 2, leyenda_y + 26)
        cr.show_text(etiqueta)
        cr.set_source_rgb(*self._text_color)
        cr.set_font_size(max(10, self._font_size - 1))
        texto = _("Actividad registrada · {eventos} eventos").format(eventos=sum(actividad.values()))
        ext = cr.text_extents(texto)
        cr.move_to(x + (width - ext.width) / 2, y + height - 8)
        cr.show_text(texto)

    @staticmethod
    def _heatmap_color(intensidad: float) -> tuple[float, float, float]:
        """Escala compartida con la barra global: verde, azul, amarillo, naranja, rojo."""
        colores = (
            (0.20, 0.65, 0.42),
            (0.22, 0.47, 0.84),
            (0.95, 0.78, 0.12),
            (0.95, 0.45, 0.08),
            (0.86, 0.12, 0.14),
        )
        posicion = min(1, max(0, intensidad)) * (len(colores) - 1)
        indice = min(len(colores) - 2, int(posicion))
        fraccion = posicion - indice
        primero, segundo = colores[indice], colores[indice + 1]
        return tuple(a + (b - a) * fraccion for a, b in zip(primero, segundo))

    def _draw_insight_panel(self, cr, x, y, width, height, title):
        cr.set_source_rgba(0.12, 0.13, 0.15, 0.24)
        cr.rectangle(x, y, width, height)
        cr.fill()
        cr.set_source_rgb(*getattr(self, "_text_color", (0.2, 0.2, 0.2)))
        cr.set_font_size(max(16, self._font_size + 3))
        cr.move_to(x + 18, y + 30)
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
        self._rounded_rectangle(cr, x, eje_y - 5, width, 10, 5)
        carril = cairo.LinearGradient(x, eje_y - 5, x + width, eje_y + 5)
        carril.add_color_stop_rgb(0, 0.12, 0.24, 0.42)
        carril.add_color_stop_rgb(0.5, 0.22, 0.47, 0.84)
        carril.add_color_stop_rgb(1, 0.12, 0.24, 0.42)
        cr.set_source(carril)
        cr.fill()
        cr.set_line_width(1.5)
        cr.set_source_rgba(*getattr(self, "_text_color", (0.2, 0.2, 0.2)), 0.65)
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
            expandido = (critico and tarea.id not in self._criticos_colapsados) or tarea.id in self._tareas_expandidas
            es_hito = tarea.es_hito
            color = (0.95, 0.65, 0.12) if es_hito else ((0.88, 0.20, 0.14) if critico else (0.22, 0.47, 0.84))
            if not expandido:
                cr.set_source_rgb(*color)
                cr.arc(xx, eje_y, 7, 0, 2 * math.pi)
                cr.fill()
                self._timeline_hitboxes.append((xx - 12, eje_y - 12, xx + 12, eje_y + 12, tarea.id))
                continue
            popup_w = min(190, max(150, width / 2.25))
            popup_h = 46 if critico else 38
            banda = indice % 4
            encima = banda in (0, 2)
            popup_y = eje_y - (68 if banda == 0 else 112) if encima else eje_y + (18 if banda == 1 else 62)
            popup_x = max(x, min(x + width - popup_w, xx - popup_w / 2))
            self._rounded_rectangle(cr, popup_x, popup_y, popup_w, popup_h, 7)
            if es_hito:
                oscuro, claro = (0.78, 0.38, 0.04), (1.0, 0.78, 0.24)
            elif critico:
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
            cr.set_font_size(max(11, self._font_size - 1))
            titulo = tarea.titulo[:24]
            ext = cr.text_extents(titulo)
            cr.move_to(popup_x + (popup_w - ext.width) / 2, popup_y + 18)
            cr.show_text(titulo)
            if critico:
                cr.set_font_size(max(10, self._font_size - 2))
                detalle = f"{tarea.porcentaje_completado}% · {tarea.duracion_dias} d"
                ext = cr.text_extents(detalle)
                cr.move_to(popup_x + (popup_w - ext.width) / 2, popup_y + 35)
                cr.show_text(detalle)
            self._timeline_hitboxes.append((xx - 14, eje_y - 14, xx + 14, eje_y + 14, tarea.id))
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
        width = self._insights.get_width()
        gap = 22
        left_w = max(230, int(width * 0.23))
        mid_w = max(360, int(width * 0.45))
        right_x = left_w + mid_w + gap * 2
        if right_x <= x and y <= 48:
            self._ritmo_anual = not self._ritmo_anual
            self._insights.queue_draw()
            return
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
                    if tarea_id in self._tareas_expandidas:
                        self._tareas_expandidas.remove(tarea_id)
                    else:
                        self._tareas_expandidas.add(tarea_id)
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
        disponible = width - margin * 2 - gap * 2
        left_w = int(disponible * 0.42)
        middle_x = margin + left_w + gap
        middle_w = int(disponible * 0.31)
        right_x = middle_x + middle_w + gap
        right_w = width - right_x - margin
        self._draw_panel(cr, margin, margin, width - margin * 2, top_h)
        self._draw_panel(cr, margin, bottom_y, left_w, height - bottom_y - margin)
        self._draw_panel(cr, middle_x, bottom_y, middle_w, height - bottom_y - margin)
        self._draw_panel(cr, right_x, bottom_y, right_w, height - bottom_y - margin)
        self._draw_progress(cr, width, height)
        self._draw_status(cr, width, height, margin, bottom_y, left_w)
        self._draw_burnup(cr, middle_x, middle_w, bottom_y, height - bottom_y - margin)
        self._draw_alerts(cr, right_x, bottom_y, right_w, height - bottom_y - margin)

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
        x, y, w, h = 42, 78, max(160, width - 84), 58
        cr.set_source_rgb(0.82, 0.84, 0.87)
        self._rounded_rectangle(cr, x, y, w, h, h / 2)
        cr.fill()
        gradiente = cairo.LinearGradient(x, y, x + w, y + h)
        gradiente.add_color_stop_rgb(0.00, 0.86, 0.12, 0.14)
        gradiente.add_color_stop_rgb(0.25, 0.95, 0.45, 0.08)
        gradiente.add_color_stop_rgb(0.50, 0.95, 0.78, 0.12)
        gradiente.add_color_stop_rgb(0.75, 0.22, 0.47, 0.84)
        gradiente.add_color_stop_rgb(1.00, 0.20, 0.65, 0.42)
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
        cr.set_font_size(max(18, self._font_size + 6))
        titulo = _("Progreso global: {value:.0f}%").format(value=avg)
        ext = cr.text_extents(titulo)
        cr.move_to((width - ext.width) / 2, y - 22)
        cr.show_text(titulo)

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
        cr.set_source_rgb(*self._text_color)
        cr.set_font_size(max(18, self._font_size + 5))
        titulo = _("Tareas por estado")
        cr.move_to(panel_x + 18, panel_y + 42)
        cr.show_text(titulo)
        selector_x = panel_x + panel_w - 154
        selector_y, selector_w, selector_h = panel_y + 17, 146, 30
        self._rounded_rectangle(cr, selector_x, selector_y, selector_w, selector_h, 7)
        cr.set_source_rgb(0.10, 0.11, 0.14)
        cr.fill()
        opciones = ((_("Barras"), not self._estado_circular), (_("Circular"), self._estado_circular))
        cr.set_font_size(max(11, self._font_size))
        for indice, (texto, activo) in enumerate(opciones):
            ox = selector_x + indice * selector_w / 2
            ow = selector_w / 2
            if activo:
                self._rounded_rectangle(cr, ox + 2, selector_y + 2, ow - 4, selector_h - 4, 5)
                cr.set_source_rgb(0.98, 0.32, 0.16)
                cr.fill()
            cr.set_source_rgb(1.0, 1.0, 1.0) if activo else cr.set_source_rgb(*self._text_color)
            ext_opcion = cr.text_extents(texto)
            cr.move_to(ox + (ow - ext_opcion.width) / 2, selector_y + 20)
            cr.show_text(texto)
        if self._estado_circular:
            self._draw_status_circular(cr, counts, panel_x, panel_y, panel_w, height)
            return
        x0, y0, w, h = panel_x + 28, panel_y + 68, panel_w - 56, max(100, height - panel_y - 115)
        max_count = max(1, max(c for _, c, _ in counts))
        bar_w = max(18, min(70, (w - 20) / len(counts) - 10))
        for i, (name, count, color) in enumerate(counts):
            x = x0 + (i + 0.5) * (w / len(counts)) - bar_w / 2
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

    def _draw_status_circular(self, cr, counts, panel_x, panel_y, panel_w, height) -> None:
        total = max(1, sum(count for _, count, _ in counts))
        panel_height = height - panel_y - 18
        cx = panel_x + panel_w * 0.45
        cy = panel_y + panel_height * 0.56
        radius = min(105, max(70, panel_w * 0.18))
        start = -math.pi / 2
        for nombre, count, color in counts:
            sweep = 2 * math.pi * count / total
            gradiente = cairo.RadialGradient(cx - radius * 0.3, cy - radius * 0.4, radius * 0.1, cx, cy, radius)
            gradiente.add_color_stop_rgb(0, *(min(1, c * 1.2) for c in color))
            gradiente.add_color_stop_rgb(1, *color)
            cr.set_source(gradiente)
            cr.move_to(cx, cy)
            cr.arc(cx, cy, radius, start, start + sweep)
            cr.close_path()
            cr.fill()
            if count:
                etiqueta = f"{count / total:.0%}"
                medio = start + sweep / 2
                luminosidad = 0.299 * color[0] + 0.587 * color[1] + 0.114 * color[2]
                if luminosidad > 0.62:
                    cr.set_source_rgb(0.12, 0.13, 0.15)
                else:
                    cr.set_source_rgb(1, 1, 1)
                cr.set_font_size(max(13, self._font_size))
                ext = cr.text_extents(etiqueta)
                cr.move_to(cx + math.cos(medio) * radius * 0.62 - ext.width / 2, cy + math.sin(medio) * radius * 0.62 + ext.height / 2)
                cr.show_text(etiqueta)
            start += sweep
        cr.set_font_size(max(11, self._font_size))
        for i, (nombre, count, color) in enumerate(counts):
            yy = panel_y + panel_height - 70 + i * 19
            cr.set_source_rgb(*color)
            self._rounded_rectangle(cr, panel_x + 28, yy - 9, 10, 10, 3)
            cr.fill()
            cr.set_source_rgb(*self._text_color)
            cr.move_to(panel_x + 46, yy)
            cr.show_text(f"{nombre}: {count}")

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

    def _draw_burnup(self, cr, panel_x: int, panel_w: int, panel_y: int, panel_h: int) -> None:
        """Curva burnup basada en las finalizaciones registradas en el historial."""
        total = len(self._tareas)
        progreso = sum(t.porcentaje_completado for t in self._tareas) / total if total else 0
        x0, y0 = panel_x + 42, panel_y + 70
        ancho, alto = panel_w - 70, max(110, panel_h - 125)
        titulo = _("Ritmo de avance")
        cr.set_source_rgb(*self._text_color)
        cr.set_font_size(max(16, self._font_size + 3))
        # Esta card comparte cabecera con el selector; dejamos el título a la izquierda
        # para que ambos respiren incluso en ventanas estrechas.
        cr.move_to(panel_x + 18, panel_y + 42)
        cr.show_text(titulo)
        self._draw_mode_selector(
            cr, panel_x + 18, panel_y + 14, panel_w - 36,
            (_("Burndown"), _("Burnup")), self._avance_burndown,
        )
        cr.set_line_width(1)
        cr.set_source_rgba(*self._text_color, 0.28)
        cr.move_to(x0, y0)
        cr.line_to(x0, y0 + alto)
        cr.line_to(x0 + ancho, y0 + alto)
        cr.stroke()
        if not total:
            return
        completadas_por_dia: dict[str, int] = {}
        for evento in self._historial:
            if evento.tipo == "progreso" and evento.valor_nuevo == "100":
                fecha = evento.creado[:10]
                completadas_por_dia[fecha] = completadas_por_dia.get(fecha, 0) + 1
        if not completadas_por_dia:
            cr.set_source_rgb(*self._text_color)
            cr.set_font_size(max(10, self._font_size - 1))
            cr.move_to(x0 + 8, y0 + alto / 2)
            cr.show_text(_("Sin datos históricos todavía"))
            return
        puntos_ideal = []
        puntos_real = []
        dias = sorted(completadas_por_dia)
        for i in range(7):
            xx = x0 + ancho * i / 6
            ideal = total * (1 - i / 6) if self._avance_burndown else total * i / 6
            indice = min(len(dias) - 1, round((len(dias) - 1) * i / 6))
            acumuladas = sum(completadas_por_dia[dia] for dia in dias[: indice + 1]) if i else 0
            real = total - min(total, acumuladas) if self._avance_burndown else min(total, acumuladas)
            puntos_ideal.append((xx, y0 + alto - alto * ideal / total))
            puntos_real.append((xx, y0 + alto - alto * real / total))
        # Área entre la trayectoria ideal y la real: permite leer la desviación
        # de un vistazo sin alterar las dos líneas principales.
        cr.new_path()
        cr.move_to(*puntos_ideal[0])
        for punto in puntos_ideal[1:]:
            cr.line_to(*punto)
        for punto in reversed(puntos_real):
            cr.line_to(*punto)
        cr.close_path()
        if progreso < 100:
            desviacion_gradiente = cairo.LinearGradient(x0, y0, x0, y0 + alto)
            desviacion_gradiente.add_color_stop_rgba(0, 0.88, 0.20, 0.14, 0.28)
            desviacion_gradiente.add_color_stop_rgba(1, 0.88, 0.20, 0.14, 0.04)
        else:
            desviacion_gradiente = cairo.LinearGradient(x0, y0, x0, y0 + alto)
            desviacion_gradiente.add_color_stop_rgba(0, 0.20, 0.65, 0.42, 0.28)
            desviacion_gradiente.add_color_stop_rgba(1, 0.20, 0.65, 0.42, 0.04)
        cr.set_source(desviacion_gradiente)
        cr.fill()
        for puntos, color, grosor in (
            (puntos_ideal, (0.55, 0.58, 0.64), 2),
            (puntos_real, (0.22, 0.65, 0.42), 3),
        ):
            cr.set_source_rgb(*color)
            cr.set_line_width(grosor)
            cr.move_to(*puntos[0])
            for punto in puntos[1:]:
                cr.line_to(*punto)
            cr.stroke()
        cr.set_font_size(max(9, self._font_size - 2))
        leyenda_y = y0 + alto + 36
        cr.set_source_rgb(0.55, 0.58, 0.64)
        leyenda_x = x0 + 8
        ideal = _("Ideal")
        cr.move_to(leyenda_x, leyenda_y)
        cr.show_text(ideal)
        leyenda_x += cr.text_extents(ideal).width + 18
        cr.set_source_rgb(0.22, 0.65, 0.42)
        avance = _("Pendientes" if self._avance_burndown else "Completadas")
        cr.move_to(leyenda_x, leyenda_y)
        cr.show_text(avance)
        leyenda_x += cr.text_extents(avance).width + 18
        desviacion = progreso - 100
        cr.set_source_rgb(0.88, 0.20, 0.14) if desviacion < 0 else cr.set_source_rgb(0.20, 0.65, 0.42)
        cr.move_to(leyenda_x, leyenda_y)
        cr.show_text(_("Desviación: {valor:+.0f}%").format(valor=desviacion))
        cr.set_source_rgb(*self._text_color)
        cr.move_to(x0 + ancho - 70, y0 + alto + 18)
        cr.show_text(_("Días"))

    def _draw_buckets(self, cr, panel_x: int, panel_w: int, panel_y: int, panel_h: int) -> None:
        buckets = [sum(t.porcentaje_completado == 0 for t in self._tareas),
                   sum(0 < t.porcentaje_completado < 100 for t in self._tareas),
                   sum(t.porcentaje_completado >= 100 for t in self._tareas)]
        labels = [_('Sin empezar'), _('En curso'), _('Completadas')]
        total = max(1, sum(buckets))
        # El circular ocupa la mitad superior; la leyenda queda siempre debajo.
        cx, cy, radius = panel_x + panel_w // 2, panel_y + panel_h * 0.43, min(88, max(58, panel_w // 4))
        start = -math.pi / 2
        # Paleta semántica compartida: azul = pendiente, verde = activo/completado,
        # gris = estado neutro sin trabajo iniciado.
        colors = ((0.22, 0.47, 0.84), (0.20, 0.65, 0.42), (0.52, 0.56, 0.63))
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
            if count:
                medio = start + sweep / 2
                etiqueta = f"{count / total:.0%}"
                # En colores claros (p. ej. amarillo) el blanco pierde contraste.
                luminosidad = 0.299 * color[0] + 0.587 * color[1] + 0.114 * color[2]
                cr.set_source_rgb(0.12, 0.13, 0.15) if luminosidad > 0.62 else cr.set_source_rgb(1.0, 1.0, 1.0)
                cr.set_font_size(max(13, self._font_size))
                ext = cr.text_extents(etiqueta)
                cr.move_to(
                    cx + math.cos(medio) * radius * 0.62 - ext.width / 2,
                    cy + math.sin(medio) * radius * 0.62 + ext.height / 2,
                )
                cr.show_text(etiqueta)
            start += sweep
        cr.set_source_rgb(*self._text_color)
        cr.set_font_size(max(16, self._font_size + 3))
        titulo = _("Avance")
        ext = cr.text_extents(titulo)
        cr.move_to(panel_x + (panel_w - ext.width) / 2, panel_y + 42)
        cr.show_text(titulo)
        cr.set_font_size(max(12, self._font_size + 1))
        for i, label in enumerate(labels):
            swatch_y = panel_y + panel_h - 84 + i * 18
            cr.set_source_rgb(*colors[i])
            self._rounded_rectangle(cr, panel_x + 28, swatch_y - 9, 10, 10, 3)
            cr.fill()
            cr.set_source_rgb(*self._text_color)
            cr.move_to(panel_x + 46, swatch_y)
            cr.show_text(f"{label}: {buckets[i]}")

    def _draw_alerts(self, cr, panel_x: int, panel_y: int, panel_w: int, panel_h: int) -> None:
        """Muestra el riesgo temporal como barras comparables."""
        vencidas, planificadas, proximas = self._alertas
        x = panel_x + 28
        y = panel_y + panel_h / 2 - 42
        ancho = panel_w - 56
        maximo = max(1, vencidas, planificadas, proximas)
        cr.set_source_rgb(*self._text_color)
        cr.set_font_size(max(16, self._font_size + 3))
        titulo = _("Riesgo temporal")
        ext = cr.text_extents(titulo)
        cr.move_to(panel_x + (panel_w - ext.width) / 2, panel_y + 42)
        cr.show_text(titulo)
        filas = (
            (_("Alertas rojas"), vencidas, (0.88, 0.20, 0.14)),
            (_("Planificación pasada"), planificadas, (0.95, 0.55, 0.08)),
            (_("Próximas 7 días"), proximas, (0.22, 0.47, 0.84)),
        )
        for i, (etiqueta, valor, color) in enumerate(filas):
            yy = y + i * 24
            cr.set_source_rgb(*self._text_color)
            cr.set_font_size(max(10, self._font_size - 1))
            cr.move_to(x, yy + 12)
            cr.show_text(etiqueta)
            bx = x + ancho * 0.48
            bw = ancho * 0.52
            self._rounded_rectangle(cr, bx, yy + 1, bw, 14, 7)
            cr.set_source_rgba(0.45, 0.48, 0.54, 0.28)
            cr.fill()
            relleno = bw * valor / maximo
            if relleno:
                gradiente = cairo.LinearGradient(bx, yy, bx + relleno, yy + 14)
                gradiente.add_color_stop_rgb(0, *tuple(min(1, c * 0.72) for c in color))
                gradiente.add_color_stop_rgb(1, *color)
                self._rounded_rectangle(cr, bx, yy + 1, relleno, 14, 7)
                cr.set_source(gradiente)
                cr.fill()
            cr.set_source_rgb(*self._text_color)
            cr.move_to(bx + bw + 8, yy + 12)
            cr.show_text(str(valor))
        recursos_activos = len({a.recurso_id for a in self._asignaciones})
        cr.set_font_size(max(11, self._font_size))
        cr.move_to(x, y + 92)
        cr.show_text(_("Recursos activos: {count}").format(count=recursos_activos))
