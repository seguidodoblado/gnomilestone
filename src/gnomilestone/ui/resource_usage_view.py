from __future__ import annotations

from collections.abc import Callable
from datetime import date, timedelta

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, GLib, Gtk, Pango, PangoCairo

from gnomilestone import ganttcalc, theme
from gnomilestone.i18n import _
from gnomilestone.models import Tarea
from gnomilestone.resource_usage import (
    FilaUso,
    SegmentoUso,
    carga_equipo_por_dia,
    carga_por_dia,
    rango_fechas,
)
from gnomilestone.ui.avatar_widget import AvatarWidget

_PASOS_ZOOM = (8.0, 12.0, 18.0, 24.0, 36.0, 54.0, 80.0)
_ESCALAS = (("Diario", 80.0), ("Semanal", 36.0), ("Mensual", 18.0), ("Trimestral", 8.0), ("Anual", 4.0))
_ALTURA_FILA = 48
_ALTURA_REGLA = 28
_ALTURA_CARGA_EQUIPO = 14
_MARGEN_DIAS = 3
_ANCHO_LATERAL = 220
_COLOR_HOY = (0.86, 0.2, 0.2)
_COLOR_SOBRECARGA = (0.86, 0.2, 0.2)
_COLOR_CARGA_OK = (0.18, 0.6, 0.32)
_COLOR_CARGA_NORMAL = (0.21, 0.52, 0.89)  # azul fijo, no el acento del tema: no se puede
# confundir con las barras de los propios recursos, que sí cambian con el acento.
_COLOR_ACENTO_RESPALDO = (0.21, 0.52, 0.89)
_CSS_CARGA_APLICADO = False


def _asegurar_css_carga() -> None:
    global _CSS_CARGA_APLICADO
    if _CSS_CARGA_APLICADO:
        return
    display = Gdk.Display.get_default()
    if display is None:
        return
    proveedor = Gtk.CssProvider()
    proveedor.load_from_string(
        ".gnomilestone-carga-baja { color: #33d17a; }\n"
        ".gnomilestone-carga-normal { color: #3584e4; }\n"
        ".gnomilestone-carga-alta { color: #e01b24; }\n"
    )
    Gtk.StyleContext.add_provider_for_display(
        display, proveedor, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
    )
    _CSS_CARGA_APLICADO = True


def _aplicar_color_carga(widget: Gtk.Widget, porcentaje: int) -> None:
    for clase in (
        "gnomilestone-carga-baja",
        "gnomilestone-carga-normal",
        "gnomilestone-carga-alta",
    ):
        widget.remove_css_class(clase)
    if porcentaje > 100:
        widget.add_css_class("gnomilestone-carga-alta")
    elif porcentaje >= _UMBRAL_CARGA_NORMAL:
        widget.add_css_class("gnomilestone-carga-normal")
    else:
        widget.add_css_class("gnomilestone-carga-baja")


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
    nombre_tema = Gtk.Settings.get_default().get_property("gtk-theme-name")
    if theme.is_dark_theme(nombre_tema):
        return (1.0, 1.0, 1.0)
    return _color_texto(widget)


class _ReglaFechas(Gtk.DrawingArea):
    def __init__(self) -> None:
        super().__init__(content_height=_ALTURA_REGLA)
        self.fecha_origen = date.today()
        self.px_por_dia = 24.0
        self.set_draw_func(self._draw)

    def _draw(self, _area: Gtk.DrawingArea, cr, width: int, _height: int) -> None:
        color_marca = _color_texto(self)
        color_texto = _color_texto_fecha(self)
        dias = int(width / self.px_por_dia) + 2
        paso = 7 if self.px_por_dia < 40 else 1
        cr.select_font_face("sans-serif", 0, 1)
        cr.set_font_size(12)
        for indice in range(0, dias, paso):
            fecha = self.fecha_origen + timedelta(days=indice)
            x = ganttcalc.fecha_a_x(fecha, self.fecha_origen, self.px_por_dia)
            cr.set_source_rgba(*color_marca, 0.4)
            cr.set_line_width(1)
            cr.move_to(x, _ALTURA_REGLA - 6)
            cr.line_to(x, _ALTURA_REGLA)
            cr.stroke()
            cr.set_source_rgba(*color_texto, 0.95)
            cr.move_to(x + 2, _ALTURA_REGLA - 9)
            cr.show_text(fecha.strftime("%d/%m"))

        x_hoy = ganttcalc.fecha_a_x(date.today(), self.fecha_origen, self.px_por_dia)
        if 0 <= x_hoy <= width:
            cr.set_source_rgba(*_COLOR_HOY, 0.9)
            cr.set_line_width(2)
            cr.move_to(x_hoy, 0)
            cr.line_to(x_hoy, _ALTURA_REGLA)
            cr.stroke()


_UMBRAL_CARGA_NORMAL = 70  # por debajo: poca carga (verde); desde aquí hasta 100: normal (azul)


class _BarraCargaEquipo(Gtk.DrawingArea):
    """Franja fija sobre las filas de personas: carga total del equipo por día, en tres
    colores según `resource_usage.carga_equipo_por_dia` (100 % = capacidad normal del
    equipo ese día: una persona asignada aporta 100, tenga lo que tenga asignado).

    Por debajo de `_UMBRAL_CARGA_NORMAL`: poca carga (verde). Entre ese umbral y 100:
    carga normal (azul fijo, no el acento del tema: así no se confunde con las barras de
    los propios recursos). Por encima de 100: sobrecarga real del equipo, ya sea por
    solapes entre varias personas o porque una sola está individualmente sobrecargada
    (rojo).
    """

    def __init__(self) -> None:
        super().__init__(content_height=_ALTURA_CARGA_EQUIPO)
        self.fecha_origen = date.today()
        self.px_por_dia = 24.0
        self._carga: dict[date, int] = {}
        self.set_draw_func(self._draw)

    def set_zoom(self, px_por_dia: float) -> None:
        self.px_por_dia = px_por_dia

    def actualizar(self, carga: dict[date, int], fecha_origen: date, ancho: int) -> None:
        self._carga = carga
        self.fecha_origen = fecha_origen
        self.set_size_request(ancho, _ALTURA_CARGA_EQUIPO)
        self.queue_draw()

    def _draw(self, _area: Gtk.DrawingArea, cr, width: int, height: int) -> None:
        for dia, porcentaje in self._carga.items():
            x = ganttcalc.fecha_a_x(dia, self.fecha_origen, self.px_por_dia)
            if x + self.px_por_dia < 0 or x > width:
                continue
            if porcentaje > 100:
                alpha = min(0.4 + (porcentaje - 100) / 250, 0.95)
                cr.set_source_rgba(*_COLOR_SOBRECARGA, alpha)
            elif porcentaje >= _UMBRAL_CARGA_NORMAL:
                cr.set_source_rgba(*_COLOR_CARGA_NORMAL, 0.55)
            else:
                cr.set_source_rgba(*_COLOR_CARGA_OK, 0.55)
            cr.rectangle(x, 0, self.px_por_dia, height)
            cr.fill()


class _LienzoUso(Gtk.DrawingArea):
    """Barras de asignación por persona; el fondo del día se tiñe si hay sobrecarga."""

    def __init__(
        self,
        on_editar_tarea: Callable[[int], None] | None = None,
        on_dedicacion_changed: Callable[[int, int, int], None] | None = None,
    ) -> None:
        super().__init__()
        self.ruler = _ReglaFechas()
        self._filas: list[FilaUso] = []
        self._click_pendiente: int | None = None
        self._filas_dibujo: list[tuple[FilaUso, SegmentoUso | None]] = []
        self.px_por_dia = 24.0
        self.fecha_origen = date.today()
        self._on_editar_tarea = on_editar_tarea
        self._on_dedicacion_changed = on_dedicacion_changed
        self.set_draw_func(self._draw)

        if on_editar_tarea is not None:
            doble_clic = Gtk.GestureClick(button=1)
            doble_clic.connect("released", self._on_clic)
            self.add_controller(doble_clic)

        motion = Gtk.EventControllerMotion()
        motion.connect("motion", self._on_motion)
        motion.connect("leave", lambda *_: self.set_cursor_from_name(None))
        self.add_controller(motion)

    def set_zoom(self, px_por_dia: float) -> None:
        self.px_por_dia = max(4.0, min(px_por_dia, 200.0))
        self.ruler.px_por_dia = self.px_por_dia
        self._recalcular_tamano()
        self.queue_draw()
        self.ruler.queue_draw()

    def actualizar(self, filas: list[FilaUso]) -> None:
        self._filas = filas
        self._filas_dibujo = [
            (fila, segmento)
            for fila in filas
            for segmento in (fila.segmentos or (None,))
        ]
        rango = rango_fechas(filas)
        if rango is None:
            self.fecha_origen = date.today() - timedelta(days=_MARGEN_DIAS)
        else:
            self.fecha_origen = rango[0] - timedelta(days=_MARGEN_DIAS)
        self.ruler.fecha_origen = self.fecha_origen
        self._recalcular_tamano()
        self.queue_draw()
        self.ruler.queue_draw()

    def _fecha_fin(self) -> date:
        rango = rango_fechas(self._filas)
        if rango is None:
            return self.fecha_origen + timedelta(days=30)
        return rango[1] + timedelta(days=_MARGEN_DIAS)

    def ancho_total(self) -> int:
        dias = max((self._fecha_fin() - self.fecha_origen).days, 1)
        return max(int(dias * self.px_por_dia), 1)

    def _recalcular_tamano(self) -> None:
        ancho = self.ancho_total()
        alto = max(len(self._filas_dibujo) * _ALTURA_FILA, _ALTURA_FILA)
        self.set_size_request(ancho, alto)
        self.ruler.set_size_request(ancho, _ALTURA_REGLA)

    def _draw(self, _area: Gtk.DrawingArea, cr, width: int, height: int) -> None:
        color_guia = _color_texto(self)
        # Guías verticales semanales.
        dias = int(width / self.px_por_dia) + 2
        for indice in range(0, dias, 7):
            x = indice * self.px_por_dia
            cr.set_source_rgba(*color_guia, 0.08)
            cr.set_line_width(1)
            cr.move_to(x, 0)
            cr.line_to(x, height)
            cr.stroke()

        for indice, (fila, segmento) in enumerate(self._filas_dibujo):
            y = indice * _ALTURA_FILA
            # Separador de fila.
            cr.set_source_rgba(*color_guia, 0.12)
            cr.set_line_width(1)
            cr.move_to(0, y + _ALTURA_FILA)
            cr.line_to(width, y + _ALTURA_FILA)
            cr.stroke()

            carga = carga_por_dia(fila.segmentos)
            for dia, porcentaje in carga.items():
                if porcentaje <= 100:
                    continue
                x = ganttcalc.fecha_a_x(dia, self.fecha_origen, self.px_por_dia)
                cr.set_source_rgba(*_COLOR_SOBRECARGA, min(0.18 + (porcentaje - 100) / 400, 0.45))
                cr.rectangle(x, y, self.px_por_dia, _ALTURA_FILA)
                cr.fill()

            if segmento is not None:
                self._dibujar_barra(cr, segmento, y)

        x_hoy = ganttcalc.fecha_a_x(date.today(), self.fecha_origen, self.px_por_dia)
        if 0 <= x_hoy <= width:
            cr.set_source_rgba(*_COLOR_HOY, 0.7)
            cr.set_line_width(1.5)
            cr.move_to(x_hoy, 0)
            cr.line_to(x_hoy, height)
            cr.stroke()

    def _dibujar_barra(self, cr, segmento: SegmentoUso, y_fila: int) -> None:
        x = ganttcalc.fecha_a_x(segmento.fecha_inicio, self.fecha_origen, self.px_por_dia)
        ancho = ganttcalc.ancho_duracion(segmento.duracion_dias, self.px_por_dia)
        margen = 8
        alto = _ALTURA_FILA - 2 * margen
        y = y_fila + margen
        r, g, b = _color_acento(self)
        radio = min(6, alto / 2)

        cr.new_path()
        cr.arc(x + radio, y + radio, radio, 3.1416, 4.7124)
        cr.arc(x + ancho - radio, y + radio, radio, 4.7124, 6.2832)
        cr.arc(x + ancho - radio, y + alto - radio, radio, 0, 1.5708)
        cr.arc(x + radio, y + alto - radio, radio, 1.5708, 3.1416)
        cr.close_path()
        cr.set_source_rgba(r, g, b, 0.85)
        cr.fill_preserve()
        cr.set_source_rgba(r, g, b, 1.0)
        cr.set_line_width(1)
        cr.stroke()

        if ancho < 28:
            return
        etiqueta = f"{segmento.titulo} ({segmento.porcentaje_dedicacion}%)"

        layout = PangoCairo.create_layout(cr)
        layout.set_font_description(self.get_pango_context().get_font_description())
        layout.set_text(etiqueta, -1)
        layout.set_width(Pango.units_from_double(ancho - 12))
        layout.set_ellipsize(Pango.EllipsizeMode.END)
        _, texto_h = layout.get_pixel_size()
        cr.set_source_rgba(1, 1, 1, 0.95)
        cr.move_to(x + 6, y + alto / 2 - texto_h / 2)
        PangoCairo.show_layout(cr, layout)

    def _segmento_en(self, x: float, y: float) -> SegmentoUso | None:
        # Buscar por los límites de cada fila, en vez de confiar solo en y // altura:
        # el lienzo puede tener desplazamiento vertical y las filas pueden cambiar al
        # reconstruirse tras filtrar completadas.
        encontrados: list[SegmentoUso] = []
        for indice, (_fila, segmento_fila) in enumerate(self._filas_dibujo):
            if segmento_fila is None:
                continue
            y0 = indice * _ALTURA_FILA
            if not y0 <= y < y0 + _ALTURA_FILA:
                continue
            x0 = ganttcalc.fecha_a_x(
                segmento_fila.fecha_inicio, self.fecha_origen, self.px_por_dia
            )
            x1 = x0 + ganttcalc.ancho_duracion(segmento_fila.duracion_dias, self.px_por_dia)
            if x0 <= x <= x1:
                encontrados.append(segmento_fila)
        if encontrados:
            return encontrados[-1]
        return None

    def _on_motion(self, _controller: Gtk.EventControllerMotion, x: float, y: float) -> None:
        self.set_cursor_from_name("pointer" if self._segmento_en(x, y) else None)

    def _on_clic(self, _gesture: Gtk.GestureClick, n_press: int, x: float, y: float) -> None:
        segmento = self._segmento_en(x, y)
        if segmento is None:
            return
        if n_press == 2 and self._on_editar_tarea is not None:
            if self._click_pendiente is not None:
                GLib.source_remove(self._click_pendiente)
                self._click_pendiente = None
            self._on_editar_tarea(segmento.tarea_id)
        elif n_press == 1:
            if self._click_pendiente is not None:
                GLib.source_remove(self._click_pendiente)
            self._click_pendiente = GLib.timeout_add(
                250, self._mostrar_menu_dedicacion_pendiente, segmento, x, y
            )

    def _mostrar_menu_dedicacion_pendiente(
        self, segmento: SegmentoUso, x: float, y: float
    ) -> bool:
        self._click_pendiente = None
        self._mostrar_menu_dedicacion(segmento, x, y)
        return False

    def _mostrar_menu_dedicacion(self, segmento: SegmentoUso, x: float, y: float) -> None:
        popover = Gtk.Popover()
        popover.set_parent(self)
        caja = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=8,
            margin_top=10,
            margin_bottom=10,
            margin_start=12,
            margin_end=12,
        )
        titulo = Gtk.Label(label=segmento.titulo, xalign=0)
        titulo.add_css_class("heading")
        caja.append(titulo)
        valor = Gtk.Label(label=f"{segmento.porcentaje_dedicacion} %", xalign=0)
        caja.append(valor)
        escala = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 5)
        escala.set_value(segmento.porcentaje_dedicacion)
        escala.set_digits(0)
        escala.set_size_request(180, -1)
        escala.set_hexpand(False)

        def _cambio(slider: Gtk.Scale) -> None:
            porcentaje = round(slider.get_value())
            valor.set_text(f"{porcentaje} %")

        escala.connect("value-changed", _cambio)
        caja.append(escala)
        popover.set_child(caja)
        popover.set_has_arrow(True)
        rectangulo = Gdk.Rectangle()
        rectangulo.x = int(x)
        rectangulo.y = int(y)
        rectangulo.width = 1
        rectangulo.height = 1
        popover.set_pointing_to(rectangulo)

        def _guardar_al_cerrar(_popover: Gtk.Popover) -> None:
            if self._on_dedicacion_changed is not None:
                self._on_dedicacion_changed(
                    segmento.tarea_id,
                    self._recurso_id_de_segmento(segmento),
                    round(escala.get_value()),
                )

        popover.connect("closed", _guardar_al_cerrar)
        popover.popup()

    def _recurso_id_de_segmento(self, segmento: SegmentoUso) -> int:
        for fila in self._filas:
            if segmento in fila.segmentos:
                return fila.recurso.id
        return 0


class ResourceUsageView(Gtk.Box):
    """Vista Uso de recursos: ocupación en el tiempo por persona, con sobrecarga marcada."""

    def __init__(
        self,
        on_editar_tarea: Callable[[Tarea], None] | None = None,
        on_dedicacion_changed: Callable[[int, int, int], None] | None = None,
    ) -> None:
        _asegurar_css_carga()
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self._on_editar_tarea = on_editar_tarea
        self._tareas_por_id: dict[int, Tarea] = {}
        self._indice_zoom = _PASOS_ZOOM.index(80.0)  # vista diaria por defecto
        self._on_dedicacion_changed = on_dedicacion_changed
        self._filas: list[FilaUso] = []

        toolbar = Gtk.Box(spacing=6, margin_top=6, margin_bottom=6, margin_start=6, margin_end=6)
        zoom_out = Gtk.Button(icon_name="zoom-out-symbolic", tooltip_text=_("Alejar"))
        zoom_out.connect("clicked", self._on_zoom_out)
        toolbar.append(zoom_out)
        zoom_in = Gtk.Button(icon_name="zoom-in-symbolic", tooltip_text=_("Acercar"))
        zoom_in.connect("clicked", self._on_zoom_in)
        toolbar.append(zoom_in)
        toolbar.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))
        grupo_escalas: Gtk.ToggleButton | None = None
        for etiqueta, px_por_dia in _ESCALAS:
            boton_escala = Gtk.ToggleButton(label=_(etiqueta))
            boton_escala.add_css_class("linked")
            if grupo_escalas is None:
                grupo_escalas = boton_escala
            else:
                boton_escala.set_group(grupo_escalas)
            boton_escala.set_active(etiqueta == "Diario")
            boton_escala.connect("clicked", self._on_escala, px_por_dia)
            toolbar.append(boton_escala)
        toolbar.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))
        leyenda = Gtk.Label(
            label=_(
                "Rojo de fondo: más del 100 % de dedicación ese día · "
                "Franja superior: carga del equipo (verde poca, azul normal, rojo sobrecarga)"
            ),
            xalign=0,
            hexpand=True,
        )
        leyenda.add_css_class("dim-label")
        leyenda.add_css_class("caption")
        toolbar.append(leyenda)
        self.append(toolbar)

        self._vacio = Gtk.Label(
            label=_("Aún no hay recursos. Asígalos al crear o editar una tarea."),
            wrap=True,
            margin_top=24,
            margin_start=16,
            margin_end=16,
        )
        self._vacio.add_css_class("dim-label")
        self.append(self._vacio)

        self._panel = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, vexpand=True, hexpand=True)
        self.append(self._panel)

        lateral_scroller = Gtk.ScrolledWindow(
            vscrollbar_policy=Gtk.PolicyType.NEVER, width_request=_ANCHO_LATERAL
        )
        self._lateral = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        # Espacio bajo la regla de fechas del lienzo.
        self._lateral.append(Gtk.Box(height_request=_ALTURA_REGLA))
        equipo_lateral = Gtk.Label(
            label=_("Equipo"),
            xalign=0,
            margin_start=8,
            height_request=_ALTURA_CARGA_EQUIPO,
            valign=Gtk.Align.CENTER,
        )
        equipo_lateral.add_css_class("caption")
        equipo_lateral.add_css_class("dim-label")
        self._lateral.append(equipo_lateral)
        self._lista = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self._lateral.append(self._lista)
        lateral_scroller.set_child(self._lateral)
        self._panel.append(lateral_scroller)

        canvas_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True, vexpand=True)
        self._lienzo = _LienzoUso(
            on_editar_tarea=self._on_editar_desde_lienzo,
            on_dedicacion_changed=self._on_dedicacion_changed,
        )
        self._lienzo.set_zoom(_PASOS_ZOOM[self._indice_zoom])

        ruler_scroller = Gtk.ScrolledWindow(
            vscrollbar_policy=Gtk.PolicyType.NEVER, hscrollbar_policy=Gtk.PolicyType.NEVER
        )
        ruler_scroller.set_child(self._lienzo.ruler)
        canvas_box.append(ruler_scroller)

        self._barra_equipo = _BarraCargaEquipo()
        equipo_scroller = Gtk.ScrolledWindow(
            vscrollbar_policy=Gtk.PolicyType.NEVER, hscrollbar_policy=Gtk.PolicyType.NEVER
        )
        equipo_scroller.set_child(self._barra_equipo)
        canvas_box.append(equipo_scroller)

        self._canvas_scroller = Gtk.ScrolledWindow(
            vexpand=True,
            hexpand=True,
            hscrollbar_policy=Gtk.PolicyType.ALWAYS,
            vscrollbar_policy=Gtk.PolicyType.NEVER,
        )
        self._canvas_scroller.set_child(self._lienzo)
        self._canvas_scroller.set_vadjustment(lateral_scroller.get_vadjustment())
        ruler_scroller.set_hadjustment(self._canvas_scroller.get_hadjustment())
        equipo_scroller.set_hadjustment(self._canvas_scroller.get_hadjustment())
        canvas_box.append(self._canvas_scroller)
        self._panel.append(canvas_box)

        scroll = Gtk.EventControllerScroll(flags=Gtk.EventControllerScrollFlags.VERTICAL)
        scroll.connect("scroll", self._on_scroll)
        self._canvas_scroller.add_controller(scroll)

        self._mostrar_contenido(False)

    def set_filas(self, filas: list[FilaUso], tareas: list[Tarea]) -> None:
        self._filas = filas
        self._tareas_por_id = {tarea.id: tarea for tarea in tareas}
        if not filas:
            self._vacio.set_label(_("Aún no hay recursos. Asígalos al crear o editar una tarea."))
            self._mostrar_contenido(False)
            return
        self._mostrar_contenido(True)
        self._reconstruir_lista()
        self._lienzo.actualizar(filas)
        self._actualizar_barra_equipo()

    def _actualizar_barra_equipo(self) -> None:
        carga = carga_equipo_por_dia(self._filas)
        self._barra_equipo.set_zoom(self._lienzo.px_por_dia)
        self._barra_equipo.actualizar(carga, self._lienzo.fecha_origen, self._lienzo.ancho_total())

    def _mostrar_contenido(self, visible: bool) -> None:
        self._panel.set_visible(visible)
        self._vacio.set_visible(not visible)

    def _reconstruir_lista(self) -> None:
        while (hijo := self._lista.get_first_child()) is not None:
            self._lista.remove(hijo)
        for fila in self._filas:
            segmentos = fila.segmentos or (None,)
            for segmento in segmentos:
                self._lista.append(self._fila_lateral(fila, segmento))

    def _fila_lateral(self, fila: FilaUso, segmento: SegmentoUso | None = None) -> Gtk.Widget:
        caja = Gtk.Box(
            spacing=8,
            margin_start=8,
            margin_end=8,
            height_request=_ALTURA_FILA,
            valign=Gtk.Align.CENTER,
        )
        caja.append(AvatarWidget(fila.recurso, size=28))
        textos = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0, hexpand=True, valign=Gtk.Align.CENTER)
        nombre = Gtk.Label(
            label=fila.recurso.nombre if segmento is None else f"↳ {segmento.titulo}",
            xalign=0,
            ellipsize=Pango.EllipsizeMode.END,
        )
        textos.append(nombre)
        if segmento is not None:
            meta = _("{pct} % de dedicación").format(pct=segmento.porcentaje_dedicacion)
        elif fila.segmentos:
            if fila.sobrecargado:
                meta = _("{pct} % máx. · sobrecarga").format(pct=fila.carga_maxima)
            else:
                meta = _("{pct} % máx.").format(pct=fila.carga_maxima)
        else:
            meta = _("Sin tareas datadas")
        detalle = Gtk.Label(label=meta, xalign=0)
        detalle.add_css_class("caption")
        porcentaje_color = (
            segmento.porcentaje_dedicacion if segmento is not None else fila.carga_maxima
        )
        _aplicar_color_carga(detalle, porcentaje_color)
        if segmento is None and not fila.sobrecargado:
            detalle.add_css_class("dim-label")
        elif segmento is None and fila.sobrecargado:
            detalle.add_css_class("error")
        else:
            # La clase de carga sustituye al gris de dim-label para que el porcentaje
            # individual siga el mismo código cromático que la franja superior.
            pass
        textos.append(detalle)
        caja.append(textos)
        return caja

    def _on_editar_desde_lienzo(self, tarea_id: int) -> None:
        if self._on_editar_tarea is None:
            return
        tarea = self._tareas_por_id.get(tarea_id)
        if tarea is not None:
            self._on_editar_tarea(tarea)

    def _on_zoom_in(self, _button: Gtk.Button | None = None) -> None:
        self._indice_zoom = min(self._indice_zoom + 1, len(_PASOS_ZOOM) - 1)
        self._lienzo.set_zoom(_PASOS_ZOOM[self._indice_zoom])
        self._actualizar_barra_equipo()

    def _on_zoom_out(self, _button: Gtk.Button | None = None) -> None:
        self._indice_zoom = max(self._indice_zoom - 1, 0)
        self._lienzo.set_zoom(_PASOS_ZOOM[self._indice_zoom])
        self._actualizar_barra_equipo()

    def _on_escala(self, _button: Gtk.ToggleButton, px_por_dia: float) -> None:
        self._indice_zoom = min(
            range(len(_PASOS_ZOOM)), key=lambda i: abs(_PASOS_ZOOM[i] - px_por_dia)
        )
        self._lienzo.set_zoom(px_por_dia)
        self._actualizar_barra_equipo()

    def _on_scroll(self, controller: Gtk.EventControllerScroll, _dx: float, dy: float) -> bool:
        if not (controller.get_current_event_state() & Gdk.ModifierType.CONTROL_MASK):
            return False
        if dy < 0:
            self._on_zoom_in()
        elif dy > 0:
            self._on_zoom_out()
        return True
