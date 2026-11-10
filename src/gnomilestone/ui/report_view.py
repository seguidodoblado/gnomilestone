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
    fechas_planificadas_reales,
    flujo_acumulado,
    reparto_por_recurso,
    resumen_desviacion,
    ruta_critica,
    tiempo_medio_por_columna,
)
from gnomilestone.ui.kanban_view import _PALETA_COLUMNAS

# Margen exterior de cada pestaña y separación entre cards, en píxeles.
_MARGEN = 18
_SEPARACION = 18


class ReportView(Gtk.Box):
    """Informes del proyecto en pestañas, sin dependencias de gráficos externas.

    Cada pestaña es un lienzo Cairo propio: Resumen (estado actual), Flujo de
    trabajo (movimiento de tareas), Planificación (previsto frente a real) y
    Equipo (reparto y carga). Ningún informe se repite entre pestañas.
    """

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
        # Selectores de vista de cada card.
        self._estado_circular = False
        self._avance_burndown = False
        self._ritmo_anual = True
        # Datos del proyecto y métricas derivadas en set_data().
        self._tareas: list[Tarea] = []
        self._estados: list[EstadoTablero] = []
        self._recursos: list[Recurso] = []
        self._asignaciones: list[Asignacion] = []
        self._dependencias: list[Dependencia] = []
        self._historial: list[HistorialTarea] = []
        self._alertas = (0, 0, 0)
        self._sin_asignar = 0
        self._reparto = []
        self._critica = []
        self._tareas_semana = []
        self._tareas_expandidas = set()
        self._criticos_colapsados = set()
        # Estilo tomado del tema GTK en cada dibujado.
        self._font_family = "Sans"
        self._font_size = 11.0
        self._text_color = (0.90, 0.90, 0.92)
        # Zonas pulsables (x0, y0, x1, y1, acción) registradas por cada lienzo
        # en su último dibujado, de modo que los clics comparten geometría con
        # lo que se ha pintado realmente.
        self._zonas: dict[Gtk.DrawingArea, list] = {}
        self._lienzo_actual: Gtk.DrawingArea | None = None
        self._lienzos: list[Gtk.DrawingArea] = []
        self._notebook = Gtk.Notebook(vexpand=True, hexpand=True)
        pestanas = (
            (_("Resumen"), self._draw_summary, 560),
            (_("Flujo de trabajo"), self._draw_workflow, 640),
            (_("Planificación"), self._draw_planning, 1000),
            (_("Equipo"), self._draw_team, 600),
        )
        for nombre, dibujar, alto_minimo in pestanas:
            self._notebook.append_page(
                self._nuevo_lienzo(dibujar, alto_minimo), Gtk.Label(label=nombre)
            )
        self.append(self._notebook)

    # ------------------------------------------------------------------
    # Infraestructura de pestañas: lienzos, estilo, clics y rejilla
    # ------------------------------------------------------------------

    def _nuevo_lienzo(self, dibujar, alto_minimo: int) -> Gtk.Widget:
        lienzo = Gtk.DrawingArea(content_width=720, content_height=alto_minimo)
        lienzo.set_hexpand(True)
        lienzo.set_vexpand(True)
        lienzo.set_draw_func(
            lambda area, cr, width, height: self._dibujar_pestana(area, cr, width, height, dibujar)
        )
        gesto = Gtk.GestureClick()
        gesto.connect("pressed", self._on_lienzo_pressed)
        lienzo.add_controller(gesto)
        self._lienzos.append(lienzo)
        # Si la ventana es más baja que el alto mínimo de la pestaña, se
        # desplaza en vertical en vez de aplastar las cards.
        desplazable = Gtk.ScrolledWindow(hexpand=True, vexpand=True)
        desplazable.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        desplazable.set_child(lienzo)
        return desplazable

    def _dibujar_pestana(self, lienzo, cr, width: int, height: int, dibujar) -> None:
        self._preparar_estilo(cr)
        self._lienzo_actual = lienzo
        self._zonas[lienzo] = []
        try:
            dibujar(cr, width, height)
        finally:
            self._lienzo_actual = None

    def _preparar_estilo(self, cr) -> None:
        ajustes = Gtk.Settings.get_default()
        oscuro = bool(ajustes and "dark" in (ajustes.get_property("gtk-theme-name") or "").lower())
        self._text_color = (0.90, 0.90, 0.92) if oscuro else (0.20, 0.20, 0.20)
        if ajustes:
            font_name = ajustes.get_property("gtk-font-name") or "Sans 11"
            family, _sep, size = font_name.rpartition(" ")
            self._font_family = family or "Sans"
            try:
                self._font_size = float(size)
            except ValueError:
                self._font_size = 11.0
        cr.set_line_width(1)
        cr.select_font_face(self._font_family, 0, 0)

    def _registrar_zona(self, x, y, width, height, accion) -> None:
        if self._lienzo_actual is not None:
            self._zonas[self._lienzo_actual].append((x, y, x + width, y + height, accion))

    def _on_lienzo_pressed(self, gesto, _n_press, x, y) -> None:
        lienzo = gesto.get_widget()
        # Lo dibujado más tarde queda encima, así que se comprueba primero.
        for x0, y0, x1, y1, accion in reversed(self._zonas.get(lienzo, [])):
            if x0 <= x <= x1 and y0 <= y <= y1:
                accion()
                lienzo.queue_draw()
                return

    def _alternar(self, atributo: str) -> None:
        setattr(self, atributo, not getattr(self, atributo))

    def _alternar_tarea(self, tarea_id: int) -> None:
        """Pliega o despliega una tarea de la línea temporal de la ruta crítica."""
        if tarea_id in {t.id for t in self._critica}:
            self._criticos_colapsados.symmetric_difference_update({tarea_id})
        else:
            self._tareas_expandidas.symmetric_difference_update({tarea_id})

    def _redibujar(self) -> None:
        for lienzo in self._lienzos:
            lienzo.queue_draw()

    @staticmethod
    def _distribuir(width: int, height: int, filas):
        """Reparte el lienzo en cards según pesos: ((peso_fila, (peso_col, ...)), ...).

        Devuelve, por fila, la lista de rectángulos (x, y, ancho, alto).
        """
        alto_util = height - _MARGEN * 2 - _SEPARACION * (len(filas) - 1)
        total_filas = sum(peso for peso, _columnas in filas)
        rects = []
        y = float(_MARGEN)
        for peso, columnas in filas:
            alto = alto_util * peso / total_filas
            ancho_util = width - _MARGEN * 2 - _SEPARACION * (len(columnas) - 1)
            total_columnas = sum(columnas)
            fila = []
            x = float(_MARGEN)
            for peso_columna in columnas:
                ancho = ancho_util * peso_columna / total_columnas
                fila.append((int(x), int(y), int(ancho), int(alto)))
                x += ancho + _SEPARACION
            rects.append(fila)
            y += alto + _SEPARACION
        return rects

    # ------------------------------------------------------------------
    # Datos
    # ------------------------------------------------------------------

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
        asignadas = {a.tarea_id for a in self._asignaciones}
        self._sin_asignar = sum(t.id not in asignadas for t in tareas)
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
        self._redibujar()

    # ------------------------------------------------------------------
    # Pestañas
    # ------------------------------------------------------------------

    def _draw_summary(self, cr, width: int, height: int) -> None:
        """Resumen: ¿cómo está el proyecto ahora mismo?"""
        (progreso,), (estado, riesgo) = self._distribuir(
            width, height, ((38, (1,)), (62, (55, 45)))
        )
        self._draw_card(cr, *progreso)
        self._draw_progress(cr, *progreso)
        self._draw_card(cr, *estado, _("Estado general"))
        self._draw_kpis(cr, *estado)
        self._draw_card(cr, *riesgo, _("Riesgo temporal"))
        self._draw_alerts(cr, *riesgo)

    def _draw_workflow(self, cr, width: int, height: int) -> None:
        """Flujo de trabajo: ¿dónde se mueven o se atascan las tareas?"""
        (estado, ritmo), (tiempo, cfd) = self._distribuir(
            width, height, ((1, (1, 1)), (1, (2, 3)))
        )
        self._draw_card(cr, *estado, _("Tareas por estado"))
        self._draw_status(cr, *estado)
        self._draw_card(cr, *ritmo, _("Ritmo de trabajo"))
        x, y, w, h = ritmo
        self._draw_mode_selector(
            cr, x + 18, y + 16, w - 36, (_("Anual"), _("Mensual")), self._ritmo_anual,
            lambda: self._alternar("_ritmo_anual"),
        )
        self._draw_heatmap(cr, x + 18, y + 64, w - 36, h - 64)
        self._draw_card(cr, *tiempo, _("Tiempo medio por columna"))
        self._draw_column_time(cr, *tiempo)
        self._draw_card(cr, *cfd, _("Acumulación por columna · CFD"))
        self._draw_cfd(cr, *cfd)

    def _draw_planning(self, cr, width: int, height: int) -> None:
        """Planificación: ¿vamos según lo previsto?"""
        (avance, desviacion), (fechas,), (critica,) = self._distribuir(
            width, height, ((28, (3, 2)), (38, (1,)), (34, (1,)))
        )
        self._draw_card(cr, *avance, _("Ritmo de avance"))
        self._draw_burnup(cr, *avance)
        self._draw_card(cr, *desviacion, _("Desviación de planificación"))
        self._draw_deviation(cr, *desviacion)
        self._draw_card(cr, *fechas, _("Fechas planificadas frente a reales"))
        self._draw_planned_vs_actual(cr, *fechas)
        self._draw_card(cr, *critica, _("Ruta crítica"))
        x, y, w, _h = critica
        self._draw_critical_path(cr, x + 18, y + 48, w - 36)

    def _draw_team(self, cr, width: int, height: int) -> None:
        """Equipo: ¿quién trabaja en qué y con qué carga?"""
        (reparto, actividad), (carga,) = self._distribuir(
            width, height, ((55, (1, 1)), (45, (1,)))
        )
        self._draw_card(cr, *reparto, _("Reparto por persona"))
        x, y, w, h = reparto
        self._draw_resource_bars(cr, x + 18, y + 70, w - 36, h - 90)
        self._draw_card(cr, *actividad, _("Actividad por persona"))
        self._draw_placeholder(cr, *actividad)
        self._draw_card(cr, *carga, _("Carga y progreso por persona"))
        self._draw_placeholder(cr, *carga)

    # ------------------------------------------------------------------
    # Elementos comunes de las cards
    # ------------------------------------------------------------------

    def _draw_panel(self, cr, x: int, y: int, width: int, height: int) -> None:
        cr.set_source_rgba(0.12, 0.13, 0.15, 0.36)
        cr.rectangle(x, y, width, height)
        cr.fill()
        cr.set_source_rgba(0.45, 0.47, 0.52, 0.45)
        cr.rectangle(x, y, width, height)
        cr.stroke()

    def _draw_card(self, cr, x, y, width, height, titulo: str | None = None) -> None:
        """Panel de una card con su título alineado a la izquierda.

        La derecha de la cabecera queda libre para el selector de vista.
        """
        self._draw_panel(cr, x, y, width, height)
        if not titulo:
            return
        cr.set_source_rgb(*self._text_color)
        cr.select_font_face(self._font_family, 0, 1)
        cr.set_font_size(max(16, self._font_size + 3))
        cr.move_to(x + 18, y + 42)
        cr.show_text(titulo)
        cr.select_font_face(self._font_family, 0, 0)

    def _draw_placeholder(self, cr, x, y, width, height) -> None:
        cr.set_source_rgb(0.55, 0.57, 0.62)
        cr.set_font_size(max(11, self._font_size))
        texto = _("Este informe se añadirá en una próxima versión")
        ext = cr.text_extents(texto)
        cr.move_to(x + (width - ext.width) / 2, y + height / 2 + 12)
        cr.show_text(texto)

    def _draw_mode_selector(self, cr, x, y, width, opciones, primero_activo, accion, selector_w=None):
        """Selector segmentado de dos opciones; pulsarlo ejecuta `accion`."""
        selector_w = min(selector_w or 150, width)
        selector_x = x + width - selector_w
        self._rounded_rectangle(cr, selector_x, y, selector_w, 26, 6)
        cr.set_source_rgb(0.10, 0.11, 0.14)
        cr.fill()
        cr.set_font_size(max(10, self._font_size - 1))
        for indice, texto in enumerate(opciones):
            activo = (indice == 0) == primero_activo
            ox, ow = selector_x + indice * selector_w / 2, selector_w / 2
            if activo:
                self._rounded_rectangle(cr, ox + 2, y + 2, ow - 4, 22, 4)
                cr.set_source_rgb(0.98, 0.32, 0.16)
                cr.fill()
            cr.set_source_rgb(1, 1, 1) if activo else cr.set_source_rgb(*self._text_color)
            ext = cr.text_extents(texto)
            cr.move_to(ox + (ow - ext.width) / 2, y + 17)
            cr.show_text(texto)
        self._registrar_zona(selector_x, y, selector_w, 26, accion)

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

    # ------------------------------------------------------------------
    # Resumen
    # ------------------------------------------------------------------

    def _draw_progress(self, cr, x, y, width, height) -> None:
        tasks = self._tareas
        avg = sum(t.porcentaje_completado for t in tasks) / len(tasks) if tasks else 0
        bar_h = max(24, min(58, height - 90))
        bx, bw = x + 24, max(160, width - 48)
        by = y + 56 + max(0, (height - 56 - bar_h - 18) / 2)
        cr.set_source_rgb(0.82, 0.84, 0.87)
        self._rounded_rectangle(cr, bx, by, bw, bar_h, bar_h / 2)
        cr.fill()
        gradiente = cairo.LinearGradient(bx, by, bx + bw, by + bar_h)
        gradiente.add_color_stop_rgb(0.00, 0.86, 0.12, 0.14)
        gradiente.add_color_stop_rgb(0.25, 0.95, 0.45, 0.08)
        gradiente.add_color_stop_rgb(0.50, 0.95, 0.78, 0.12)
        gradiente.add_color_stop_rgb(0.75, 0.22, 0.47, 0.84)
        gradiente.add_color_stop_rgb(1.00, 0.20, 0.65, 0.42)
        cr.set_source(gradiente)
        relleno = bw * min(100, max(0, avg)) / 100
        if relleno > 0:
            cr.save()
            self._rounded_rectangle(cr, bx, by, bw, bar_h, bar_h / 2)
            cr.clip()
            cr.rectangle(bx, by, relleno, bar_h)
            cr.fill()
            cr.restore()
        cr.set_source_rgb(*self._text_color)
        cr.select_font_face(self._font_family, 0, 1)
        cr.set_font_size(max(18, self._font_size + 6))
        titulo = _("Progreso global: {value:.0f}%").format(value=avg)
        ext = cr.text_extents(titulo)
        cr.move_to(x + (width - ext.width) / 2, y + 40)
        cr.show_text(titulo)
        cr.select_font_face(self._font_family, 0, 0)

    def _draw_kpis(self, cr, x, y, width, height) -> None:
        """Fichas con las cifras clave del proyecto."""
        tareas = self._tareas
        total = len(tareas)
        completadas = sum(t.porcentaje_completado >= 100 for t in tareas)
        en_curso = sum(0 < t.porcentaje_completado < 100 for t in tareas)
        sin_empezar = total - completadas - en_curso
        progreso = sum(t.porcentaje_completado for t in tareas) / total if total else 0
        fichas = (
            (_("Total"), str(total), self._text_color),
            (_("Sin empezar"), str(sin_empezar), (0.52, 0.56, 0.63)),
            (_("En curso"), str(en_curso), (0.22, 0.47, 0.84)),
            (_("Completadas"), str(completadas), (0.20, 0.65, 0.42)),
            (_("Vencidas"), str(self._alertas[0]), (0.88, 0.20, 0.14)),
            (_("Progreso medio"), f"{progreso:.0f}%", (0.95, 0.78, 0.12)),
        )
        ax, ay, aw, ah = x + 18, y + 58, width - 36, height - 76
        hueco = 10
        columnas = len(fichas) if (aw - hueco * (len(fichas) - 1)) / len(fichas) >= 100 else 3
        filas = math.ceil(len(fichas) / columnas)
        ficha_w = (aw - hueco * (columnas - 1)) / columnas
        ficha_h = min(96, (ah - hueco * (filas - 1)) / filas)
        ay += max(0, (ah - (ficha_h * filas + hueco * (filas - 1))) / 2)
        for indice, (etiqueta, valor, color) in enumerate(fichas):
            fx = ax + (indice % columnas) * (ficha_w + hueco)
            fy = ay + (indice // columnas) * (ficha_h + hueco)
            self._rounded_rectangle(cr, fx, fy, ficha_w, ficha_h, 8)
            cr.set_source_rgba(0.45, 0.48, 0.54, 0.16)
            cr.fill()
            cr.set_source_rgb(*color)
            cr.select_font_face(self._font_family, 0, 1)
            cr.set_font_size(max(22, min(self._font_size + 14, ficha_h * 0.42)))
            ext = cr.text_extents(valor)
            cr.move_to(fx + (ficha_w - ext.width) / 2, fy + ficha_h * 0.5 + ext.height / 2 - 4)
            cr.show_text(valor)
            cr.select_font_face(self._font_family, 0, 0)
            cr.set_source_rgb(*self._text_color)
            cr.set_font_size(max(10, self._font_size - 1))
            ext = cr.text_extents(etiqueta)
            cr.move_to(fx + (ficha_w - ext.width) / 2, fy + ficha_h - 12)
            cr.show_text(etiqueta)

    def _draw_alerts(self, cr, x, y, width, height) -> None:
        """Muestra el riesgo temporal como barras comparables."""
        vencidas, planificadas, proximas = self._alertas
        ax = x + 28
        ay = y + 58 + max(0, (height - 58 - 120) / 2)
        ancho = width - 56
        maximo = max(1, vencidas, planificadas, proximas)
        filas = (
            (_("Alertas rojas"), vencidas, (0.88, 0.20, 0.14)),
            (_("Planificación pasada"), planificadas, (0.95, 0.55, 0.08)),
            (_("Próximas 7 días"), proximas, (0.22, 0.47, 0.84)),
        )
        for i, (etiqueta, valor, color) in enumerate(filas):
            yy = ay + i * 24
            cr.set_source_rgb(*self._text_color)
            cr.set_font_size(max(10, self._font_size - 1))
            cr.move_to(ax, yy + 12)
            cr.show_text(etiqueta)
            bx = ax + ancho * 0.48
            bw = ancho * 0.52 - 30
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
        cr.move_to(ax, ay + 96)
        cr.show_text(
            _("Recursos activos: {count} · Tareas sin asignar: {sin_asignar}").format(
                count=recursos_activos, sin_asignar=self._sin_asignar
            )
        )

    # ------------------------------------------------------------------
    # Flujo de trabajo
    # ------------------------------------------------------------------

    def _draw_status(self, cr, x, y, width, height) -> None:
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
        selector_w, selector_h = 146, 30
        selector_x, selector_y = x + width - 18 - selector_w, y + 16
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
        self._registrar_zona(selector_x, selector_y, selector_w, selector_h,
                             lambda: self._alternar("_estado_circular"))
        if self._estado_circular:
            self._draw_status_circular(cr, counts, x, y, width, height)
            return
        x0, y0, w, h = x + 28, y + 68, width - 56, max(80, height - 115)
        max_count = max(1, max(c for _, c, _ in counts))
        bar_w = max(18, min(70, (w - 20) / len(counts) - 10))
        for i, (name, count, color) in enumerate(counts):
            bx = x0 + (i + 0.5) * (w / len(counts)) - bar_w / 2
            bh = h * count / max_count
            gradiente = cairo.LinearGradient(bx, y0 + h - bh, bx + bar_w, y0 + h)
            gradiente.add_color_stop_rgb(0, *tuple(min(1, c * 0.72) for c in color))
            gradiente.add_color_stop_rgb(1, *color)
            cr.set_source(gradiente)
            self._rounded_rectangle(cr, bx, y0 + h - bh, bar_w, bh, min(8, bar_w / 2, bh / 2))
            cr.fill()
            cr.set_source_rgb(*self._text_color)
            cr.set_font_size(max(12, self._font_size + 1))
            cr.move_to(bx, y0 + h + 18)
            cr.show_text(name[:12])
            # Mantener el valor dentro del panel incluso cuando la barra llega al techo.
            label_x = bx + max(0, (bar_w - cr.text_extents(str(count)).width) / 2)
            label_y = max(y0 + self._font_size + 4, y0 + h - bh - 8)
            cr.move_to(label_x, label_y)
            cr.show_text(str(count))

    def _draw_status_circular(self, cr, counts, x, y, width, height) -> None:
        total = max(1, sum(count for _, count, _ in counts))
        cx = x + width * 0.45
        cy = y + height * 0.56
        radius = min(105, max(40, min(width * 0.18, height * 0.26)))
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
            yy = y + height - 70 + i * 19
            cr.set_source_rgb(*color)
            self._rounded_rectangle(cr, x + 28, yy - 9, 10, 10, 3)
            cr.fill()
            cr.set_source_rgb(*self._text_color)
            cr.move_to(x + 46, yy)
            cr.show_text(f"{nombre}: {count}")

    def _draw_heatmap(self, cr, x, y, width, height):
        """Actividad diaria registrada en el historial de las tareas."""
        columnas, filas = (24, 16) if self._ritmo_anual else (7, 5)
        hoy = datetime.now().astimezone().date()
        dias_mes = monthrange(hoy.year, hoy.month)[1]
        if self._ritmo_anual:
            dias_mes = 366 if monthrange(hoy.year, 2)[1] == 29 else 365
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
                    fecha = date(hoy.year, 1, 1) + timedelta(days=dia)
                    valor = actividad.get(fecha.isoformat(), 0) if dia < dias_mes else 0
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
        cr.set_line_width(1)
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


    # ------------------------------------------------------------------
    # Flujo de trabajo: tiempo por columna y CFD
    # ------------------------------------------------------------------

    def _draw_nota(self, cr, x, y, width, height, texto: str) -> None:
        cr.set_source_rgb(0.55, 0.57, 0.62)
        cr.set_font_size(max(11, self._font_size))
        ext = cr.text_extents(texto)
        cr.move_to(x + (width - ext.width) / 2, y + height / 2 + 12)
        cr.show_text(texto)

    def _draw_column_time(self, cr, x, y, width, height) -> None:
        """Días medios que una tarea pasa en cada columna del tablero."""
        medios = tiempo_medio_por_columna(self._tareas, self._historial)
        columnas = [(e, medios[e.id]) for e in self._estados if e.id in medios]
        if not columnas:
            self._draw_nota(cr, x, y, width, height, _("Todavía no hay tareas con historial de estados"))
            return
        maximo = max(dias for _e, (dias, _n) in columnas) or 1
        fila_h = max(22, min(40, (height - 90) / len(columnas)))
        etiqueta_w = min(150, width * 0.3)
        bx, bw = x + 18 + etiqueta_w, max(40, width - 36 - etiqueta_w - 90)
        yy = y + 62 + max(0, (height - 62 - 28 - fila_h * len(columnas)) / 2)
        for estado, (dias, tareas_medidas) in columnas:
            indice = self._estados.index(estado)
            color = self._hex_color(_PALETA_COLUMNAS[indice % len(_PALETA_COLUMNAS)])
            cr.set_source_rgb(*self._text_color)
            cr.set_font_size(max(11, self._font_size))
            cr.move_to(x + 18, yy + fila_h / 2 + 4)
            cr.show_text(estado.nombre[:18])
            self._rounded_rectangle(cr, bx, yy + 3, bw, fila_h - 8, 6)
            cr.set_source_rgba(0.45, 0.48, 0.54, 0.22)
            cr.fill()
            relleno = max(4.0, bw * dias / maximo)
            gradiente = cairo.LinearGradient(bx, yy, bx + relleno, yy)
            gradiente.add_color_stop_rgb(0, *(c * 0.72 for c in color))
            gradiente.add_color_stop_rgb(1, *color)
            self._rounded_rectangle(cr, bx, yy + 3, relleno, fila_h - 8, 6)
            cr.set_source(gradiente)
            cr.fill()
            cr.set_source_rgb(*self._text_color)
            cr.move_to(bx + bw + 10, yy + fila_h / 2 + 4)
            cr.show_text(_("{dias:.1f} d").format(dias=dias))
            yy += fila_h
        cr.set_source_rgb(0.55, 0.57, 0.62)
        cr.set_font_size(max(9, self._font_size - 2))
        cr.move_to(x + 18, y + height - 12)
        cr.show_text(_("Media por tarea de los días en cada columna, incluida la estancia actual"))

    def _draw_cfd(self, cr, x, y, width, height) -> None:
        """Diagrama de flujo acumulado: tareas por columna a lo largo del tiempo."""
        dias, conteos = flujo_acumulado(self._tareas, self._historial)
        if len(dias) < 2 or not conteos:
            self._draw_nota(cr, x, y, width, height,
                            _("Se necesitan al menos dos días de historial para dibujarlo"))
            return
        x0, y0 = x + 46, y + 60
        ancho, alto = width - 46 - 24, height - 60 - 62
        total_max = max(1, max(
            sum(conteos.get(e.id, [0] * len(dias))[i] for e in self._estados)
            for i in range(len(dias))
        ))
        cr.set_line_width(1)
        cr.set_font_size(max(9, self._font_size - 2))
        for paso in range(5):
            valor = total_max * paso / 4
            yy = y0 + alto - alto * paso / 4
            cr.set_source_rgba(*self._text_color, 0.12)
            cr.move_to(x0, yy)
            cr.line_to(x0 + ancho, yy)
            cr.stroke()
            cr.set_source_rgb(*self._text_color)
            etiqueta = f"{valor:.0f}"
            cr.move_to(x0 - 8 - cr.text_extents(etiqueta).width, yy + 3)
            cr.show_text(etiqueta)
        n = len(dias) - 1
        acumulado = [0] * len(dias)
        # De abajo arriba: la última columna (completadas) en la base, como en un CFD.
        for estado in reversed(self._estados):
            serie = conteos.get(estado.id, [0] * len(dias))
            indice = self._estados.index(estado)
            color = self._hex_color(_PALETA_COLUMNAS[indice % len(_PALETA_COLUMNAS)])
            inferior = list(acumulado)
            superior = [a + s for a, s in zip(acumulado, serie)]
            cr.new_path()
            for i, valor in enumerate(superior):
                px, py = x0 + ancho * i / n, y0 + alto - alto * valor / total_max
                cr.move_to(px, py) if i == 0 else cr.line_to(px, py)
            for i in range(n, -1, -1):
                cr.line_to(x0 + ancho * i / n, y0 + alto - alto * inferior[i] / total_max)
            cr.close_path()
            cr.set_source_rgba(*color, 0.85)
            cr.fill()
            acumulado = superior
        cr.set_source_rgb(*self._text_color)
        for i in sorted({0, n // 2, n}):
            etiqueta = dias[i].strftime("%d/%m")
            ext = cr.text_extents(etiqueta)
            px = x0 + ancho * i / n
            cr.move_to(min(max(x0, px - ext.width / 2), x0 + ancho - ext.width), y0 + alto + 16)
            cr.show_text(etiqueta)
        lx = x0
        ly = y + height - 16
        cr.set_font_size(max(10, self._font_size - 1))
        for estado in self._estados:
            indice = self._estados.index(estado)
            color = self._hex_color(_PALETA_COLUMNAS[indice % len(_PALETA_COLUMNAS)])
            if lx + 24 + cr.text_extents(estado.nombre).width > x + width - 12:
                break
            cr.set_source_rgb(*color)
            self._rounded_rectangle(cr, lx, ly - 9, 10, 10, 3)
            cr.fill()
            cr.set_source_rgb(*self._text_color)
            cr.move_to(lx + 15, ly)
            cr.show_text(estado.nombre)
            lx += 15 + cr.text_extents(estado.nombre).width + 18

    # ------------------------------------------------------------------
    # Planificación: fechas y desviación
    # ------------------------------------------------------------------

    def _draw_planned_vs_actual(self, cr, x, y, width, height) -> None:
        """Una fila por tarea: barra prevista (contorno) y barra real (rellena)."""
        filas = fechas_planificadas_reales(self._tareas)
        if not filas:
            self._draw_nota(cr, x, y, width, height, _("Todavía no hay tareas con inicio y final planificado"))
            return
        hoy = datetime.now().astimezone().date()
        fila_h = max(26, min(40, (height - 110) / max(1, min(len(filas), 12))))
        visibles = max(1, int((height - 110) // fila_h))
        mostradas = filas[:visibles]
        desde = min(f.inicio for f in mostradas)
        hasta = max([hoy] + [d for f in mostradas for d in (f.fin_inicial, f.fin_actual, f.fin_real) if d])
        # El día final cuenta entero (una tarea de un día ocupa un día) y el eje abarca
        # al menos dos semanas para que las tareas cortas no se aplasten.
        hasta = max(hasta, desde + timedelta(days=13))
        dias_total = (hasta - desde).days + 1
        etiqueta_w = min(190, width * 0.26)
        ax, aw = x + 18 + etiqueta_w, width - 36 - etiqueta_w
        ay = y + 66

        def px(dia: date) -> float:
            return ax + aw * (dia - desde).days / dias_total

        def px_fin(dia: date) -> float:
            return px(dia + timedelta(days=1))

        for indice, fila in enumerate(mostradas):
            yy = ay + indice * fila_h
            cr.set_source_rgb(*self._text_color)
            cr.set_font_size(max(10, self._font_size - 1))
            cr.move_to(x + 18, yy + fila_h / 2 + 4)
            cr.show_text(fila.tarea.titulo[:26])
            barra_h = (fila_h - 8) / 2
            cr.set_source_rgba(0.55, 0.58, 0.64, 0.9)
            cr.set_line_width(1.5)
            self._rounded_rectangle(
                cr, px(fila.inicio), yy + 3, max(8, px_fin(fila.fin_inicial) - px(fila.inicio)), barra_h, 3
            )
            cr.stroke()
            fin = fila.fin_real or (hoy if fila.tarea.porcentaje_completado < 100 else fila.fin_inicial)
            if fila.fin_real is None and fila.inicio > hoy:
                continue  # aún no ha empezado: solo el contorno del plan
            dias = fila.desviacion_dias
            if fila.fin_real is None:
                color = (0.88, 0.20, 0.14) if dias else (0.22, 0.47, 0.84)
            else:
                color = (0.20, 0.65, 0.42) if dias <= 0 else (0.95, 0.55, 0.08)
            self._rounded_rectangle(
                cr, px(fila.inicio), yy + 4 + barra_h, max(8, px_fin(max(fin, fila.inicio)) - px(fila.inicio)), barra_h, 3
            )
            cr.set_source_rgb(*color)
            cr.fill()
        cr.set_line_width(1.5)
        hoy_x = px(hoy) + (px_fin(hoy) - px(hoy)) / 2
        cr.set_source_rgba(0.98, 0.32, 0.16, 0.85)
        cr.move_to(hoy_x, ay - 6)
        cr.line_to(hoy_x, ay + len(mostradas) * fila_h)
        cr.stroke()
        cr.set_font_size(max(10, self._font_size - 1))
        etiqueta_hoy = _("Hoy")
        ext = cr.text_extents(etiqueta_hoy)
        self._rounded_rectangle(cr, hoy_x - ext.width / 2 - 6, ay - 26, ext.width + 12, 17, 4)
        cr.set_source_rgb(0.98, 0.32, 0.16)
        cr.fill()
        cr.set_source_rgb(1, 1, 1)
        cr.move_to(hoy_x - ext.width / 2, ay - 13)
        cr.show_text(etiqueta_hoy)
        cr.set_source_rgb(*self._text_color)
        base_y = ay + len(mostradas) * fila_h + 16
        for dia in (desde, hasta):
            etiqueta = dia.strftime("%d/%m")
            ext = cr.text_extents(etiqueta)
            cr.move_to(min(max(ax, px(dia) - ext.width / 2), ax + aw - ext.width), base_y)
            cr.show_text(etiqueta)
        resto = len(filas) - len(mostradas)
        pie = _("Contorno: previsto inicial · Relleno: real (verde a tiempo, naranja con retraso, rojo vencida, azul en curso)")
        if resto:
            pie += " · " + _("+{count} más").format(count=resto)
        cr.set_font_size(max(9, self._font_size - 2))
        cr.set_source_rgb(0.55, 0.57, 0.62)
        cr.move_to(x + 18, y + height - 12)
        cr.show_text(pie)

    def _draw_deviation(self, cr, x, y, width, height) -> None:
        """Resumen de cumplimiento del plan inicial y las tareas más retrasadas."""
        resumen = resumen_desviacion(self._tareas)
        medidas = resumen.a_tiempo + resumen.con_retraso + resumen.adelantadas
        if not medidas and not resumen.sin_medir:
            self._draw_nota(cr, x, y, width, height, _("Todavía no hay tareas con inicio y final planificado"))
            return
        fichas = (
            (_("A tiempo"), resumen.a_tiempo, (0.20, 0.65, 0.42)),
            (_("Adelantadas"), resumen.adelantadas, (0.22, 0.47, 0.84)),
            (_("Con retraso"), resumen.con_retraso, (0.88, 0.20, 0.14)),
        )
        hueco, ficha_h = 10, 64
        ficha_w = (width - 36 - hueco * 2) / 3
        for i, (etiqueta, valor, color) in enumerate(fichas):
            fx = x + 18 + i * (ficha_w + hueco)
            self._rounded_rectangle(cr, fx, y + 58, ficha_w, ficha_h, 8)
            cr.set_source_rgba(0.45, 0.48, 0.54, 0.16)
            cr.fill()
            cr.set_source_rgb(*color)
            cr.select_font_face(self._font_family, 0, 1)
            cr.set_font_size(max(20, self._font_size + 11))
            texto = str(valor)
            ext = cr.text_extents(texto)
            cr.move_to(fx + (ficha_w - ext.width) / 2, y + 58 + 30)
            cr.show_text(texto)
            cr.select_font_face(self._font_family, 0, 0)
            cr.set_source_rgb(*self._text_color)
            cr.set_font_size(max(10, self._font_size - 1))
            ext = cr.text_extents(etiqueta)
            cr.move_to(fx + (ficha_w - ext.width) / 2, y + 58 + ficha_h - 10)
            cr.show_text(etiqueta)
        yy = y + 58 + ficha_h + 26
        cr.set_source_rgb(*self._text_color)
        cr.set_font_size(max(11, self._font_size))
        if resumen.con_retraso:
            cr.move_to(x + 18, yy)
            cr.show_text(_("Retraso medio: {dias:.1f} días").format(dias=resumen.retraso_medio))
            yy += 24
        maximo = max((f.desviacion_dias for f in resumen.peores), default=1)
        fila_h = 24
        for fila in resumen.peores:
            if yy + fila_h > y + height - 28:
                break
            cr.set_source_rgb(*self._text_color)
            cr.set_font_size(max(10, self._font_size - 1))
            cr.move_to(x + 18, yy + 12)
            cr.show_text(fila.tarea.titulo[:22])
            bx = x + 18 + min(170, width * 0.34)
            bw = max(30, width - 36 - (bx - x - 18) - 60)
            self._rounded_rectangle(cr, bx, yy + 2, max(4, bw * fila.desviacion_dias / maximo), 12, 6)
            cr.set_source_rgb(0.88, 0.20, 0.14)
            cr.fill()
            cr.set_source_rgb(*self._text_color)
            cr.move_to(bx + bw + 8, yy + 12)
            cr.show_text(_("+{dias} d").format(dias=fila.desviacion_dias))
            yy += fila_h
        if resumen.sin_medir:
            cr.set_source_rgb(0.55, 0.57, 0.62)
            cr.set_font_size(max(9, self._font_size - 2))
            cr.move_to(x + 18, y + height - 12)
            cr.show_text(_("{count} tareas en plazo sin terminar, aún sin desviación").format(count=resumen.sin_medir))

    # ------------------------------------------------------------------
    # Planificación
    # ------------------------------------------------------------------

    def _draw_burnup(self, cr, x, y, width, height) -> None:
        """Curva burnup/burndown basada en las finalizaciones registradas en el historial."""
        total = len(self._tareas)
        progreso = sum(t.porcentaje_completado for t in self._tareas) / total if total else 0
        x0, y0 = x + 42, y + 70
        ancho, alto = width - 70, max(110, height - 125)
        self._draw_mode_selector(
            cr, x + 18, y + 16, width - 36,
            (_("Burndown"), _("Burnup")), self._avance_burndown,
            lambda: self._alternar("_avance_burndown"),
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
        # Solo cuentan las tareas visibles, las mismas que forman el total; las
        # archivadas quedan fuera del avance (el mapa de calor sí las conserva).
        visibles = {t.id for t in self._tareas}
        for evento in self._historial:
            if (evento.tipo == "progreso" and evento.valor_nuevo == "100"
                    and evento.tarea_id in visibles):
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
        desviacion_gradiente = cairo.LinearGradient(x0, y0, x0, y0 + alto)
        if progreso < 100:
            desviacion_gradiente.add_color_stop_rgba(0, 0.88, 0.20, 0.14, 0.28)
            desviacion_gradiente.add_color_stop_rgba(1, 0.88, 0.20, 0.14, 0.04)
        else:
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
        cr.set_line_width(1)
        cr.set_font_size(max(9, self._font_size - 2))
        leyenda_y = y0 + alto + 36
        cr.set_source_rgb(0.55, 0.58, 0.64)
        leyenda_x = x0 + 8
        ideal = _("Ideal")
        cr.move_to(leyenda_x, leyenda_y)
        cr.show_text(ideal)
        leyenda_x += cr.text_extents(ideal).width + 18
        cr.set_source_rgb(0.22, 0.65, 0.42)
        avance = _("Pendientes") if self._avance_burndown else _("Completadas")
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

    def _draw_critical_path(self, cr, x, y, width):
        if self._tareas_semana:
            self._draw_week_timeline(cr, x, y, width)
            return
        if not self._critica:
            cr.set_source_rgb(*self._text_color)
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
        cr.set_line_width(1)
        cr.set_font_size(max(11, self._font_size - 1))
        for i, tarea in enumerate(self._critica):
            xx = x + i * paso
            cr.set_source_rgb(0.88, 0.20, 0.14)
            self._rounded_rectangle(cr, xx - node_w / 2, node_y, node_w, node_h, 8)
            cr.fill()
            cr.set_source_rgb(*self._text_color)
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
        cr.set_source_rgb(*self._text_color)
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
        cr.set_source_rgba(*self._text_color, 0.65)
        cr.move_to(x, eje_y)
        cr.line_to(x + width, eje_y)
        cr.stroke()
        for dia in range(7):
            xx = x + width * dia / 6
            cr.set_source_rgba(*self._text_color, 0.35)
            cr.move_to(xx, eje_y - 5)
            cr.line_to(xx, eje_y + 5)
            cr.stroke()
            cr.set_source_rgb(*self._text_color)
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
            alternar = (lambda tarea_id=tarea.id: self._alternar_tarea(tarea_id))
            if not expandido:
                cr.set_source_rgb(*color)
                cr.arc(xx, eje_y, 7, 0, 2 * math.pi)
                cr.fill()
                self._registrar_zona(xx - 12, eje_y - 12, 24, 24, alternar)
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
            cr.set_source_rgb(*self._text_color)
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
            self._registrar_zona(xx - 14, eje_y - 14, 28, 28, alternar)
            self._registrar_zona(popup_x, popup_y, popup_w, popup_h, alternar)
        cr.set_line_width(1)
        cr.set_source_rgb(*self._text_color)
        cr.set_font_size(max(10, self._font_size - 1))
        leyenda = _("Ventana de 7 días centrada en el primer evento crítico · rojo = crítico")
        if not self._critica:
            leyenda = _("Ventana de 7 días centrada en el primer evento relevante")
        ext = cr.text_extents(leyenda)
        cr.move_to(x + (width - ext.width) / 2, y + 250)
        cr.show_text(leyenda)

    # ------------------------------------------------------------------
    # Equipo
    # ------------------------------------------------------------------

    def _draw_resource_bars(self, cr, x, y, width, height=None):
        visibles = max(1, int(height // 31)) if height else 7
        filas = self._reparto[:visibles]
        cr.set_font_size(max(12, self._font_size))
        if not filas:
            cr.set_source_rgb(0.55, 0.57, 0.62)
            cr.move_to(x, y + 12)
            cr.show_text(_("Sin recursos en el proyecto"))
            return
        max_tareas = max(1, max(f.tareas for f in filas))
        for i, fila in enumerate(filas):
            yy = y + i * 31
            cr.set_source_rgb(*self._text_color)
            cr.set_font_size(max(12, self._font_size))
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
            etiqueta = _("{tareas} tareas · {progreso:.0f}%").format(
                tareas=fila.tareas, progreso=fila.progreso_medio
            )
            ext = cr.text_extents(etiqueta)
            cr.move_to(bx + (bw - ext.width) / 2, bar_y + 14)
            cr.show_text(etiqueta)
