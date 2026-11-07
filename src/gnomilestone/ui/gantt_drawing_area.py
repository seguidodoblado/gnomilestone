from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import replace
from datetime import date, timedelta

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, Pango, PangoCairo

from gnomilestone import ganttcalc, settings, theme
from gnomilestone.i18n import _, formatear_fecha_local
from gnomilestone.models import Dependencia, Tarea
from gnomilestone.ui.task_tree_view import ALTURA_FILA, TareaRow

_MARGEN_DIAS = 3
_ALTURA_REGLA = 28
_ANCHO_ASA_REDIMENSIONAR = 8  # franja en píxeles junto al borde derecho de la barra
_COLOR_ACENTO_RESPALDO = (0.0, 0.47, 0.84)  # azul, si el tema no expone "accent_color"
_COLOR_HOY = (0.86, 0.2, 0.2)  # rojo fijo (no depende del tema): línea del día actual
_COLOR_LIMITE = (0.85, 0.11, 0.14)  # rojo de la fecha límite y su línea de holgura
_COLOR_LIMITE_PLANIFICADA = (0.93, 0.53, 0.0)  # naranja: plan ya pasado, límite aún no

# Estilos disponibles para la barra de tarea resumen (Preferencias), con su vista previa
# en `preferences.py` reutilizando las funciones de dibujo de abajo.
ESTILO_RESUMEN_PROGRESO = "progreso"
ESTILO_RESUMEN_CORCHETES = "corchetes"


def _color_acento(widget: Gtk.Widget) -> tuple[float, float, float]:
    encontrado, rgba = widget.get_style_context().lookup_color("accent_color")
    if encontrado:
        return (rgba.red, rgba.green, rgba.blue)
    return _COLOR_ACENTO_RESPALDO


def _color_texto(widget: Gtk.Widget) -> tuple[float, float, float]:
    encontrado, rgba = widget.get_style_context().lookup_color("window_fg_color")
    if encontrado:
        return (rgba.red, rgba.green, rgba.blue)
    return (0.0, 0.0, 0.0)


def _color_texto_fecha(widget: Gtk.Widget) -> tuple[float, float, float]:
    # Blanco puro en tema oscuro (más legible en la regla que el gris de window_fg_color);
    # en tema claro se mantiene el color de texto normal, porque blanco sería ilegible.
    nombre_tema = Gtk.Settings.get_default().get_property("gtk-theme-name")
    if theme.is_dark_theme(nombre_tema):
        return (1.0, 1.0, 1.0)
    return _color_texto(widget)


def trazar_rect_redondeado(cr, x: float, y: float, ancho: float, alto: float, radio: float) -> None:
    """Añade al trazado actual de `cr` un rectángulo de esquinas redondeadas, sin
    rellenarlo ni trazarlo (eso lo decide quien llama: fill(), stroke() o clip())."""
    radio = max(0.0, min(radio, ancho / 2, alto / 2))
    cr.new_sub_path()
    cr.arc(x + ancho - radio, y + radio, radio, -math.pi / 2, 0)
    cr.arc(x + ancho - radio, y + alto - radio, radio, 0, math.pi / 2)
    cr.arc(x + radio, y + alto - radio, radio, math.pi / 2, math.pi)
    cr.arc(x + radio, y + radio, radio, math.pi, math.pi * 1.5)
    cr.close_path()


ALTO_RESUMEN_PROGRESO = 16.0  # más alta que antes (9px): para que quepa el % dentro


def _dibujar_texto_porcentaje(
    cr,
    pango_context: Pango.Context,
    x_inicio: float,
    ancho: float,
    y_barra: float,
    alto: float,
    tema_oscuro: bool,
    progreso: int,
) -> None:
    """Centra "NN %" dentro de una barra ya dibujada (resumen o tarea hoja), en blanco/negro
    fijo según el tema (no el color de texto normal, que en algunos temas no contrastaría
    con el relleno de color). No escribe nada si no cabe: mejor sin número que desbordado."""
    if ancho < alto + 6:
        return
    layout = PangoCairo.create_layout(cr)
    layout.set_font_description(pango_context.get_font_description())
    layout.set_text(f"{progreso} %", -1)
    texto_ancho, texto_alto = layout.get_pixel_size()
    if texto_ancho > ancho - 6:
        return
    color_texto = (1.0, 1.0, 1.0) if tema_oscuro else (0.0, 0.0, 0.0)
    cr.set_source_rgba(*color_texto, 0.95)
    cr.move_to(x_inicio + (ancho - texto_ancho) / 2, y_barra + (alto - texto_alto) / 2)
    PangoCairo.show_layout(cr, layout)


def dibujar_resumen_progreso(
    cr,
    pango_context: Pango.Context,
    x_inicio: float,
    x_fin: float,
    y_barra: float,
    color: tuple[float, float, float],
    tema_oscuro: bool,
    progreso: int,
) -> None:
    """Tarea resumen (tiene subtareas): píldora con relleno de progreso (el % agregado de
    sus hojas, ver `ganttcalc.progreso_resumen`) igual que una tarea hoja normal, para
    distinguirla de un vistazo y mostrar a la vez cuánto lleva hecho el conjunto. El número
    se escribe centrado dentro de la píldora, en blanco/negro fijo según el tema (no el
    color de texto normal, que en algunos temas no contrastaría con el relleno de color)."""
    alto = ALTO_RESUMEN_PROGRESO
    ancho = max(x_fin - x_inicio, alto)
    radio = alto / 2
    cr.save()
    trazar_rect_redondeado(cr, x_inicio, y_barra, ancho, alto, radio)
    cr.clip()
    cr.set_source_rgba(*color, 0.45)
    cr.paint()
    relleno = ancho * (progreso / 100)
    if relleno > 0:
        cr.set_source_rgba(*color, 1.0)
        cr.rectangle(x_inicio, y_barra, relleno, alto)
        cr.fill()
    cr.restore()
    cr.set_source_rgba(*color, 1.0)
    cr.set_line_width(1.2)
    trazar_rect_redondeado(cr, x_inicio, y_barra, ancho, alto, radio)
    cr.stroke()

    _dibujar_texto_porcentaje(
        cr, pango_context, x_inicio, ancho, y_barra, alto, tema_oscuro, progreso
    )


def dibujar_resumen_corchetes(
    cr, x_inicio: float, x_fin: float, y_linea: float, color: tuple[float, float, float]
) -> None:
    """Tarea resumen (tiene subtareas): línea fina con un "gancho" triangular en cada
    extremo, al estilo clásico de MS Project/Planner para distinguirla de un vistazo de
    una tarea hoja. No muestra progreso: solo marca que es un resumen."""
    alto_linea = 4.0
    alto_gancho = 11.0
    ancho_gancho = 9.0
    ancho = max(x_fin - x_inicio, 1.0)

    cr.set_source_rgba(*color, 0.95)
    cr.rectangle(x_inicio, y_linea, ancho, alto_linea)
    cr.fill()

    for x_punta, signo in ((x_inicio, 1), (x_fin, -1)):
        cr.move_to(x_punta, y_linea)
        cr.line_to(x_punta + signo * ancho_gancho, y_linea)
        cr.line_to(x_punta, y_linea + alto_gancho)
        cr.close_path()
        cr.fill()


class _ReglaFechas(Gtk.DrawingArea):
    """Cabecera con las fechas, sincronizada en zoom y desplazamiento con el Gantt."""

    def __init__(self) -> None:
        super().__init__(content_height=_ALTURA_REGLA)
        self.fecha_origen = date.today()
        self.px_por_dia = 24.0
        self.set_draw_func(self._draw)

    def _draw(self, _area: Gtk.DrawingArea, cr, width: int, _height: int) -> None:
        color_marca = _color_texto(self)
        color_texto = _color_texto_fecha(self)
        dias = int(width / self.px_por_dia) + 2
        # En la escala anual las divisiones son meses y la etiqueta es el nombre
        # del mes; las demás escalas mantienen las fechas día/mes.
        anual = self.px_por_dia <= 4.0
        if anual:
            fecha = self.fecha_origen.replace(day=1)
            if fecha < self.fecha_origen:
                fecha = (fecha.replace(day=28) + timedelta(days=4)).replace(day=1)
            fechas = []
            while ganttcalc.fecha_a_x(fecha, self.fecha_origen, self.px_por_dia) <= width:
                fechas.append(fecha)
                fecha = (fecha.replace(day=28) + timedelta(days=4)).replace(day=1)
        else:
            paso = 7 if self.px_por_dia < 40 else 1
            fechas = [
                self.fecha_origen + timedelta(days=indice)
                for indice in range(0, dias, paso)
            ]
        cr.select_font_face("sans-serif", 0, 1)  # 1 = cairo.FONT_WEIGHT_BOLD
        cr.set_font_size(12)
        for fecha in fechas:
            x = ganttcalc.fecha_a_x(fecha, self.fecha_origen, self.px_por_dia)
            cr.set_source_rgba(*color_marca, 0.4)
            cr.set_line_width(1)
            cr.move_to(x, _ALTURA_REGLA - 6)
            cr.line_to(x, _ALTURA_REGLA)
            cr.stroke()
            cr.set_source_rgba(*color_texto, 0.95)
            cr.move_to(x + 2, _ALTURA_REGLA - 9)
            cr.show_text(fecha.strftime("%B" if anual else "%d/%m"))

        x_hoy = ganttcalc.fecha_a_x(date.today(), self.fecha_origen, self.px_por_dia)
        if 0 <= x_hoy <= width:
            cr.set_source_rgba(*_COLOR_HOY, 0.9)
            cr.set_line_width(2)
            cr.move_to(x_hoy, 0)
            cr.line_to(x_hoy, _ALTURA_REGLA)
            cr.stroke()


class GanttDrawingArea(Gtk.DrawingArea):
    """Dibuja las barras (con relleno de progreso), hitos y flechas de dependencia.

    Arrastrar el cuerpo de una barra mueve su fecha de inicio; arrastrar su borde derecho
    cambia la duración. Los hitos solo se pueden mover (su duración siempre es 0).
    """

    def __init__(
        self,
        on_tarea_arrastrada: Callable[[int, str, int], None] | None = None,
        on_origen_desplazado: Callable[[float], None] | None = None,
        on_editar_tarea: Callable[[Tarea], None] | None = None,
    ) -> None:
        super().__init__()
        self.ruler = _ReglaFechas()
        self._filas: list[tuple[TareaRow, int]] = []
        self._dependencias: list[Dependencia] = []
        self._progreso_resumen: dict[int, int] = {}
        self._estilo_resumen = settings.read_settings().get(
            "estilo_barra_resumen", ESTILO_RESUMEN_PROGRESO
        )
        self.px_por_dia = 24.0
        self.fecha_origen = date.today()
        self._on_tarea_arrastrada = on_tarea_arrastrada
        # Avisa a quien nos contiene (el ScrolledWindow) de que hay que desplazar el scroll
        # horizontal `delta_px` para compensar que el lienzo ha crecido por la izquierda
        # (si no, la vista "saltaría" al redefinirse dónde está el x=0 del lienzo).
        self._on_origen_desplazado = on_origen_desplazado
        self._on_editar_tarea = on_editar_tarea
        self._arrastre: dict | None = None
        self.set_draw_func(self._draw)

        gesture = Gtk.GestureDrag()
        gesture.connect("drag-begin", self._on_drag_begin)
        gesture.connect("drag-update", self._on_drag_update)
        gesture.connect("drag-end", self._on_drag_end)
        self.add_controller(gesture)

        if on_editar_tarea is not None:
            doble_clic = Gtk.GestureClick(button=1)
            doble_clic.connect("released", self._on_clic)
            self.add_controller(doble_clic)

        # Cambia el cursor sobre el borde derecho de una barra (asa de redimensionar) o
        # sobre su cuerpo (mover), para que se note que son arrastrables antes de soltar el clic.
        motion = Gtk.EventControllerMotion()
        motion.connect("motion", self._on_motion)
        motion.connect("leave", self._on_motion_leave)
        self.add_controller(motion)

    def set_zoom(self, px_por_dia: float) -> None:
        self.px_por_dia = max(4.0, min(px_por_dia, 200.0))
        self.ruler.px_por_dia = self.px_por_dia
        self._recalcular_tamano()
        self.queue_draw()
        self.ruler.queue_draw()

    def actualizar(
        self,
        filas: list[tuple[TareaRow, int]],
        dependencias: list[Dependencia],
        progreso_resumen: dict[int, int] | None = None,
    ) -> None:
        self._filas = filas
        self._dependencias = dependencias
        self._progreso_resumen = progreso_resumen or {}
        fechas_origen = [
            ganttcalc.parse_fecha(fila.tarea.fecha_inicio)
            for fila, _profundidad in filas
            if fila.tarea and fila.tarea.fecha_inicio
        ]
        # La fecha límite también cuenta para el origen: si el plan se ha movido a la
        # derecha de ella, la bandera debe seguir siendo visible.
        fechas_origen.extend(
            ganttcalc.parse_fecha(fila.tarea.fecha_limite)
            for fila, _profundidad in filas
            if fila.tarea and fila.tarea.fecha_inicio and fila.tarea.fecha_limite
        )
        self.fecha_origen = (
            min(fechas_origen) - timedelta(days=_MARGEN_DIAS) if fechas_origen else date.today()
        )
        self.ruler.fecha_origen = self.fecha_origen
        self._recalcular_tamano()
        self.queue_draw()
        self.ruler.queue_draw()

    def _fecha_fin(self) -> date:
        # Usa _valores_mostrados() (no fila.tarea directamente) para que, mientras se
        # redimensiona una barra hacia la derecha más allá de lo ya guardado, el lienzo
        # también crezca en vivo y la barra no se salga del área dibujable.
        fechas_fin = []
        for fila, _profundidad in self._filas:
            if not (fila.tarea and fila.tarea.fecha_inicio):
                continue
            fecha_mostrada, duracion_mostrada = self._valores_mostrados(fila.tarea)
            fechas_fin.append(fecha_mostrada + timedelta(days=max(duracion_mostrada, 1)))
            if fila.tarea.fecha_limite:
                # La fecha límite es un día inclusive: su borde derecho es el día siguiente.
                fechas_fin.append(
                    ganttcalc.parse_fecha(fila.tarea.fecha_limite) + timedelta(days=1)
                )
        base = max(fechas_fin) if fechas_fin else self.fecha_origen + timedelta(days=30)
        return base + timedelta(days=_MARGEN_DIAS)

    def _recalcular_tamano(self) -> None:
        dias = max((self._fecha_fin() - self.fecha_origen).days, 1)
        ancho = max(int(dias * self.px_por_dia), 1)
        alto = max(len(self._filas) * ALTURA_FILA, ALTURA_FILA)
        self.set_size_request(ancho, alto)
        self.ruler.set_size_request(ancho, _ALTURA_REGLA)

    def _valores_mostrados(self, tarea: Tarea) -> tuple[date, int]:
        """Fecha de inicio y duración a dibujar: las de la tarea, la vista previa en vivo
        mientras se arrastra su barra, o la de sus dependientes desplazados en cascada."""
        if self._arrastre is not None:
            if self._arrastre["tarea_id"] == tarea.id:
                return self._arrastre["fecha_preview"], self._arrastre["duracion_preview"]
            fecha_cascada = self._arrastre["cascada_preview"].get(tarea.id)
            if fecha_cascada is not None:
                return ganttcalc.parse_fecha(fecha_cascada), tarea.duracion_dias
        return ganttcalc.parse_fecha(tarea.fecha_inicio), tarea.duracion_dias

    def _tarea_en(self, x: float, y: float) -> tuple[Tarea, int] | None:
        indice = int(y // ALTURA_FILA)
        if indice < 0 or indice >= len(self._filas):
            return None
        fila, _profundidad = self._filas[indice]
        tarea = fila.tarea
        if tarea is None or not tarea.fecha_inicio:
            return None
        fecha_inicio, duracion_dias = self._valores_mostrados(tarea)
        x_tarea = ganttcalc.fecha_a_x(fecha_inicio, self.fecha_origen, self.px_por_dia)
        if tarea.es_hito:
            radio = ALTURA_FILA * 0.3
            return (tarea, indice) if x_tarea - radio <= x <= x_tarea + radio else None
        ancho_barra = ganttcalc.ancho_duracion(duracion_dias, self.px_por_dia)
        return (tarea, indice) if x_tarea <= x <= x_tarea + ancho_barra else None

    def _modo_en(self, x: float, y: float) -> tuple[Tarea, str] | None:
        """Tarea bajo el puntero y si (x, y) cae en su asa de redimensionar o en su cuerpo."""
        resultado = self._tarea_en(x, y)
        if resultado is None:
            return None
        tarea, _indice = resultado
        fecha_inicio, duracion_dias = self._valores_mostrados(tarea)
        x_tarea = ganttcalc.fecha_a_x(fecha_inicio, self.fecha_origen, self.px_por_dia)
        ancho_barra = ganttcalc.ancho_duracion(duracion_dias, self.px_por_dia)
        en_borde = not tarea.es_hito and x >= x_tarea + ancho_barra - _ANCHO_ASA_REDIMENSIONAR
        return tarea, "redimensionar" if en_borde else "mover"

    def _on_motion(self, _controller: Gtk.EventControllerMotion, x: float, y: float) -> None:
        if self._arrastre is not None:
            return  # no cambiar el cursor en mitad de un arrastre ya iniciado
        self._actualizar_tooltip_limite(x, y)
        resultado = self._modo_en(x, y)
        if resultado is None:
            self.set_cursor_from_name(None)
            return
        _tarea, modo = resultado
        self.set_cursor_from_name("col-resize" if modo == "redimensionar" else "grab")

    def _on_motion_leave(self, _controller: Gtk.EventControllerMotion) -> None:
        if self._arrastre is None:
            self.set_cursor_from_name(None)
        self.set_tooltip_text(None)

    def _x_limite(self, fecha_limite: str) -> float:
        # La fecha límite es inclusiva: se marca al final de ese día, que es el mismo
        # borde que usa la barra para su último día planificado.
        return ganttcalc.fecha_a_x(
            ganttcalc.parse_fecha(fecha_limite) + timedelta(days=1),
            self.fecha_origen,
            self.px_por_dia,
        )

    def _tarea_limite_en(self, x: float, y: float) -> Tarea | None:
        indice = int(y // ALTURA_FILA)
        if indice < 0 or indice >= len(self._filas):
            return None
        fila, _profundidad = self._filas[indice]
        tarea = fila.tarea
        if tarea is None or not tarea.fecha_inicio or not tarea.fecha_limite:
            return None
        x_limite = self._x_limite(tarea.fecha_limite)
        if x_limite < 0:
            return None
        return tarea if abs(x - x_limite) <= 6 else None

    def _texto_limite(self, tarea: Tarea) -> str:
        if not tarea.fecha_limite:
            return ""
        texto = _("Fecha límite: {fecha}").format(
            fecha=formatear_fecha_local(tarea.fecha_limite)
        )
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

    def _actualizar_tooltip_limite(self, x: float, y: float) -> None:
        tarea = self._tarea_limite_en(x, y)
        self.set_tooltip_text(self._texto_limite(tarea) if tarea is not None else None)

    def _on_clic(
        self, _gesture: Gtk.GestureClick, n_press: int, x: float, y: float
    ) -> None:
        if n_press != 2 or self._on_editar_tarea is None:
            return
        resultado = self._tarea_en(x, y)
        if resultado is not None:
            self._on_editar_tarea(resultado[0])

    def _on_drag_begin(self, gesture: Gtk.GestureDrag, start_x: float, start_y: float) -> None:
        resultado = self._modo_en(start_x, start_y)
        if resultado is None:
            gesture.set_state(Gtk.EventSequenceState.DENIED)
            return
        self.set_tooltip_text(None)
        tarea, modo = resultado
        fecha_inicio, duracion_dias = self._valores_mostrados(tarea)
        self._arrastre = {
            "tarea_id": tarea.id,
            "modo": modo,
            "fecha_inicio": fecha_inicio,
            "duracion_dias": duracion_dias,
            "fecha_preview": fecha_inicio,
            "duracion_preview": duracion_dias,
            "cascada_preview": {},
        }

    def _on_drag_update(
        self, _gesture: Gtk.GestureDrag, offset_x: float, _offset_y: float
    ) -> None:
        if self._arrastre is None:
            return
        delta_dias = round(offset_x / self.px_por_dia)
        if self._arrastre["modo"] == "mover":
            self._arrastre["fecha_preview"] = self._arrastre["fecha_inicio"] + timedelta(
                days=delta_dias
            )
        else:
            self._arrastre["duracion_preview"] = max(1, self._arrastre["duracion_dias"] + delta_dias)
        self._limitar_a_jerarquia()
        self._arrastre["cascada_preview"] = self._calcular_cascada_preview()
        self._ajustar_origen_si_hace_falta()
        self._recalcular_tamano()  # por si el redimensionado ha crecido más allá del borde derecho
        self.queue_draw()

    def _ajustar_origen_si_hace_falta(self) -> None:
        """Si el arrastre (o sus hijas/dependientes en cascada) se adelanta al origen
        actual del lienzo, lo retrasa para que la barra siga siendo visible y dibujable
        (de lo contrario quedaría en coordenadas negativas, fuera del área del DrawingArea).
        Compensa el scroll horizontal para que la vista no dé un salto al redefinirse x=0."""
        arrastre = self._arrastre
        if arrastre is None:
            return
        fechas = [arrastre["fecha_preview"]]
        fechas.extend(ganttcalc.parse_fecha(f) for f in arrastre["cascada_preview"].values())
        fecha_minima_necesaria = min(fechas) - timedelta(days=_MARGEN_DIAS)
        if fecha_minima_necesaria >= self.fecha_origen:
            return
        dias_retrasados = (self.fecha_origen - fecha_minima_necesaria).days
        self.fecha_origen = fecha_minima_necesaria
        self.ruler.fecha_origen = self.fecha_origen
        self._recalcular_tamano()
        if self._on_origen_desplazado is not None:
            self._on_origen_desplazado(dias_retrasados * self.px_por_dia)

    def _limitar_a_jerarquia(self) -> None:
        """Una hija arrastrada directamente nunca puede salirse del rango de su padre.
        El padre manda: si es el padre el que se arrastra, no se limita aquí — sus hijas
        lo siguen (al mover) o se ajustan a él (al redimensionar) en `_calcular_cascada_preview`
        y al soltar, nunca al revés."""
        arrastre = self._arrastre
        if arrastre is None:
            return
        por_id = {fila.tarea.id: fila.tarea for fila, _profundidad in self._filas if fila.tarea}
        tarea = por_id.get(arrastre["tarea_id"])
        if tarea is None or tarea.padre_id is None:
            return
        padre = por_id.get(tarea.padre_id)
        if padre is None or not padre.fecha_inicio:
            return
        arrastre["fecha_preview"], arrastre["duracion_preview"] = ganttcalc.limitar_hijo_a_padre(
            arrastre["fecha_preview"],
            arrastre["duracion_preview"],
            ganttcalc.parse_fecha(padre.fecha_inicio),
            padre.duracion_dias,
        )

    def _calcular_cascada_preview(self) -> dict[int, str]:
        """Fechas (ISO) que tomarían, si se soltase ahora, los dependientes de la tarea
        arrastrada y —si es un padre al que se mueve— sus hijas, para que se vean moverse
        en vivo junto a ella durante el arrastre."""
        arrastre = self._arrastre
        if arrastre is None:
            return {}
        tareas = []
        for fila, _profundidad in self._filas:
            tarea = fila.tarea
            if tarea is None:
                continue
            if tarea.id == arrastre["tarea_id"]:
                tarea = replace(
                    tarea,
                    fecha_inicio=ganttcalc.formatear_fecha(arrastre["fecha_preview"]),
                    duracion_dias=arrastre["duracion_preview"],
                )
            tareas.append(tarea)

        resultado: dict[int, str] = {}
        if arrastre["modo"] == "mover":
            delta_dias = (arrastre["fecha_preview"] - arrastre["fecha_inicio"]).days
            for hijo in ganttcalc.trasladar_hijos(tareas, arrastre["tarea_id"], delta_dias):
                resultado[hijo.id] = hijo.fecha_inicio

        cambiadas = ganttcalc.recalcular_dependientes(tareas, self._dependencias, arrastre["tarea_id"])
        for tarea in cambiadas:
            resultado[tarea.id] = tarea.fecha_inicio
        return resultado

    def _on_drag_end(
        self, _gesture: Gtk.GestureDrag, _offset_x: float, _offset_y: float
    ) -> None:
        arrastre = self._arrastre
        self._arrastre = None
        self.queue_draw()
        if arrastre is None or self._on_tarea_arrastrada is None:
            return
        sin_cambios = (
            arrastre["fecha_preview"] == arrastre["fecha_inicio"]
            and arrastre["duracion_preview"] == arrastre["duracion_dias"]
        )
        if sin_cambios:
            return
        self._on_tarea_arrastrada(
            arrastre["tarea_id"],
            ganttcalc.formatear_fecha(arrastre["fecha_preview"]),
            arrastre["duracion_preview"],
        )

    def _draw(self, _area: Gtk.DrawingArea, cr, width: int, _height: int) -> None:
        color_acento = _color_acento(self)
        color_texto = _color_texto(self)
        tema_oscuro = theme.is_dark_theme(
            Gtk.Settings.get_default().get_property("gtk-theme-name")
        )
        posiciones: dict[int, tuple[float, float, float]] = {}
        limites: list[tuple[float, float, float, tuple[float, float, float, float]]] = []

        alto_total = max(len(self._filas), 1) * ALTURA_FILA
        # Cuadrícula de referencia, igual que en Uso: blanco en oscuro y negro en claro.
        color_division = (1.0, 1.0, 1.0) if tema_oscuro else (0.0, 0.0, 0.0)
        dias = int(width / self.px_por_dia) + 2
        anual = self.px_por_dia <= 4.0
        if anual:
            fecha = self.fecha_origen.replace(day=1)
            if fecha < self.fecha_origen:
                fecha = (fecha.replace(day=28) + timedelta(days=4)).replace(day=1)
            fechas = []
            while ganttcalc.fecha_a_x(fecha, self.fecha_origen, self.px_por_dia) <= width:
                fechas.append(fecha)
                fecha = (fecha.replace(day=28) + timedelta(days=4)).replace(day=1)
        else:
            paso = 7 if self.px_por_dia < 40 else 1
            fechas = [
                self.fecha_origen + timedelta(days=indice)
                for indice in range(0, dias, paso)
            ]
        cr.set_source_rgba(*color_division, 0.12)
        cr.set_line_width(1)
        for fecha in fechas:
            x = ganttcalc.fecha_a_x(fecha, self.fecha_origen, self.px_por_dia)
            cr.move_to(x, 0)
            cr.line_to(x, alto_total)
        for indice in range(1, len(self._filas) + 1):
            y = indice * ALTURA_FILA
            cr.move_to(0, y)
            cr.line_to(width, y)
        cr.stroke()

        x_hoy = ganttcalc.fecha_a_x(date.today(), self.fecha_origen, self.px_por_dia)
        if x_hoy >= 0:
            cr.set_source_rgba(*_COLOR_HOY, 0.5)
            cr.set_line_width(2)
            cr.move_to(x_hoy, 0)
            cr.line_to(x_hoy, alto_total)
            cr.stroke()

        ids_con_hijos = {
            fila.tarea.padre_id
            for fila, _profundidad in self._filas
            if fila.tarea and fila.tarea.padre_id is not None
        }

        for indice, (fila, _profundidad) in enumerate(self._filas):
            tarea = fila.tarea
            if tarea is None or not tarea.fecha_inicio:
                continue
            y = indice * ALTURA_FILA
            centro_y = y + ALTURA_FILA / 2
            fecha_mostrada, duracion_mostrada = self._valores_mostrados(tarea)
            x = ganttcalc.fecha_a_x(fecha_mostrada, self.fecha_origen, self.px_por_dia)
            if tarea.es_hito:
                self._dibujar_hito(cr, x, centro_y, color_acento)
                posiciones[tarea.id] = (x, x, centro_y)
                self._anotar_limite(limites, tarea, x, centro_y)
                continue

            ancho_barra = ganttcalc.ancho_duracion(duracion_mostrada, self.px_por_dia)
            if tarea.id in ids_con_hijos:
                # Tarea resumen (tiene subtareas): una fila fina arriba de la fila normal,
                # para distinguirla de un vistazo de una tarea hoja. El estilo exacto
                # (píldora con progreso agregado, o ganchos clásicos de Planner) se elige
                # en Preferencias.
                if self._estilo_resumen == ESTILO_RESUMEN_CORCHETES:
                    y_linea = y + ALTURA_FILA * 0.26
                    dibujar_resumen_corchetes(cr, x, x + ancho_barra, y_linea, color_acento)
                else:
                    y_barra = y + (ALTURA_FILA - ALTO_RESUMEN_PROGRESO) / 2
                    y_linea = y_barra + ALTO_RESUMEN_PROGRESO / 2
                    progreso = self._progreso_resumen.get(tarea.id, 0)
                    dibujar_resumen_progreso(
                        cr,
                        self.get_pango_context(),
                        x,
                        x + ancho_barra,
                        y_barra,
                        color_acento,
                        tema_oscuro,
                        progreso,
                    )
                posiciones[tarea.id] = (x, x + ancho_barra, centro_y)
                self._anotar_limite(limites, tarea, x + ancho_barra, y_linea)
                continue

            alto_barra = ALTURA_FILA * 0.8
            y_barra = y + (ALTURA_FILA - alto_barra) / 2
            radio = min(6.0, alto_barra / 2)

            cr.save()
            trazar_rect_redondeado(cr, x, y_barra, ancho_barra, alto_barra, radio)
            cr.clip()
            cr.set_source_rgba(*color_acento, 0.55)
            cr.paint()
            relleno = ancho_barra * (tarea.porcentaje_completado / 100)
            if relleno > 0:
                cr.set_source_rgba(*color_acento, 1.0)
                cr.rectangle(x, y_barra, relleno, alto_barra)
                cr.fill()
            cr.restore()

            cr.set_source_rgba(*color_acento, 1.0)
            cr.set_line_width(1.5)
            trazar_rect_redondeado(cr, x, y_barra, ancho_barra, alto_barra, radio)
            cr.stroke()

            _dibujar_texto_porcentaje(
                cr,
                self.get_pango_context(),
                x,
                ancho_barra,
                y_barra,
                alto_barra,
                tema_oscuro,
                tarea.porcentaje_completado,
            )

            posiciones[tarea.id] = (x, x + ancho_barra, centro_y)
            self._anotar_limite(limites, tarea, x + ancho_barra, centro_y)

        cr.set_source_rgba(*color_texto, 0.6)
        cr.set_line_width(1.5)
        for dependencia in self._dependencias:
            origen = posiciones.get(dependencia.tarea_origen_id)
            destino = posiciones.get(dependencia.tarea_destino_id)
            if origen and destino:
                self._dibujar_flecha(cr, origen[1], origen[2], destino[0], destino[2])

        # Las fechas límite se dibujan al final para que la bandera quede por encima de
        # barras y flechas cuando cae dentro de una barra.
        for x_barra_fin, x_limite, y_linea, color in limites:
            self._dibujar_limite(cr, x_barra_fin, x_limite, y_linea, color)

    def _color_limite(self, tarea: Tarea) -> tuple[float, float, float, float]:
        dias_alerta = settings.read_settings().get("dias_alerta_vencimiento", 1)
        try:
            dias_alerta = max(0, int(dias_alerta))
        except (TypeError, ValueError):
            dias_alerta = 1
        estado = ganttcalc.estado_vencimiento(tarea, dias_alerta=dias_alerta)
        if estado == ganttcalc.VENCIDA:
            return (*_COLOR_LIMITE, 1.0)
        if estado == ganttcalc.PLANIFICADA_PASADA:
            return (*_COLOR_LIMITE_PLANIFICADA, 1.0)
        # Una fecha límite futura y alejada es informativa, no una alerta: blanco puro
        # sobre tema oscuro y negro puro sobre tema claro, con baja opacidad.
        tema_oscuro = theme.is_dark_theme(
            Gtk.Settings.get_default().get_property("gtk-theme-name")
        )
        color_neutro = (1.0, 1.0, 1.0) if tema_oscuro else (0.0, 0.0, 0.0)
        return (*color_neutro, 0.55)

    def _anotar_limite(
        self,
        limites: list[tuple[float, float, float, tuple[float, float, float, float]]],
        tarea: Tarea,
        x_barra_fin: float,
        y_linea: float,
    ) -> None:
        if not tarea.fecha_limite:
            return
        x_limite = self._x_limite(tarea.fecha_limite)
        if x_limite >= 0:
            limites.append((x_barra_fin, x_limite, y_linea, self._color_limite(tarea)))

    def _dibujar_limite(
        self,
        cr,
        x_barra_fin: float,
        x_limite: float,
        y_linea: float,
        color: tuple[float, float, float, float],
    ) -> None:
        if x_limite > x_barra_fin + 0.5:
            cr.set_source_rgba(color[0], color[1], color[2], min(color[3], 0.6))
            cr.set_line_width(1.5)
            cr.set_dash([3.0, 3.0])
            cr.move_to(x_barra_fin, y_linea)
            cr.line_to(x_limite, y_linea)
            cr.stroke()
            cr.set_dash([])
        self._dibujar_bandera(cr, x_limite, y_linea, color)

    def _dibujar_bandera(
        self, cr, x: float, y: float, color: tuple[float, float, float, float]
    ) -> None:
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

    def _dibujar_hito(self, cr, x: float, centro_y: float, color: tuple[float, float, float]) -> None:
        radio = ALTURA_FILA * 0.3
        cr.set_source_rgba(*color, 0.9)
        cr.move_to(x, centro_y - radio)
        cr.line_to(x + radio, centro_y)
        cr.line_to(x, centro_y + radio)
        cr.line_to(x - radio, centro_y)
        cr.close_path()
        cr.fill()

    def _dibujar_flecha(
        self, cr, x_origen: float, y_origen: float, x_destino: float, y_destino: float
    ) -> None:
        # Curva suave (bézier), no en ángulo recto ni en diagonal: los puntos de control
        # se separan horizontalmente del origen/destino, dando una "S" que fluye de una
        # tarea a otra en vez de quebrarse en esquinas.
        distancia = max(abs(x_destino - x_origen) * 0.5, 24.0)
        cp1x, cp1y = x_origen + distancia, y_origen
        cp2x, cp2y = x_destino - distancia, y_destino
        cr.move_to(x_origen, y_origen)
        cr.curve_to(cp1x, cp1y, cp2x, cp2y, x_destino, y_destino)
        cr.stroke()

        # Punta de flecha orientada según la tangente final de la curva (de cp2 a destino).
        dx, dy = x_destino - cp2x, y_destino - cp2y
        longitud = math.hypot(dx, dy) or 1.0
        ux, uy = dx / longitud, dy / longitud
        perp_x, perp_y = -uy, ux
        punta = 6.0
        cr.move_to(x_destino, y_destino)
        cr.line_to(
            x_destino - punta * ux + punta * 0.5 * perp_x,
            y_destino - punta * uy + punta * 0.5 * perp_y,
        )
        cr.move_to(x_destino, y_destino)
        cr.line_to(
            x_destino - punta * ux - punta * 0.5 * perp_x,
            y_destino - punta * uy - punta * 0.5 * perp_y,
        )
        cr.stroke()
