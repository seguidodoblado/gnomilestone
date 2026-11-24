from __future__ import annotations

from collections.abc import Callable
from datetime import date, timedelta

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, GLib, Gtk, Pango, PangoCairo

from gnomilestone import ganttcalc, settings, theme
from gnomilestone.i18n import N_, _, formatear_fecha_local
from gnomilestone.models import Tarea
from gnomilestone.resource_usage import (
    FilaUso,
    SegmentoUso,
    carga_equipo_por_dia,
    carga_por_dia,
    rango_fechas,
    resumen_uso,
)
from gnomilestone.ui import limite_dibujo
from gnomilestone.ui.arrastre_desplazamiento import instalar_arrastre
from gnomilestone.ui.avatar_widget import AvatarWidget
from gnomilestone.ui.regla_dibujo import (
    ALTURA_REGLA,
    color_fondo,
    dibujar_bandas,
    dibujar_regla,
)

_PASOS_ZOOM = (8.0, 12.0, 18.0, 24.0, 36.0, 54.0, 80.0)
_ESCALAS = (
    ("Diario", N_("Diario"), 80.0),
    ("Semanal", N_("Semanal"), 36.0),
    ("Mensual", N_("Mensual"), 18.0),
    ("Trimestral", N_("Trimestral"), 8.0),
    ("Anual", N_("Anual"), 4.0),
)
_ALTURA_FILA = 48
_ALTURA_REGLA = ALTURA_REGLA
_ANCHO_MIN_BARRA = 8.0  # una tarea de un día en escalas anchas sigue siendo visible
_ZOOM_ETIQUETA_FUERA = 40.0  # por debajo (Semanal y más ancho) las barras pequeñas llevan el título fuera
_ANCHO_BARRA_CON_ETIQUETA = 120.0
_ALTURA_CARGA_EQUIPO = 14
_MARGEN_DIAS = 3
_ANCHO_LATERAL = 386  # respaldo del panel de personas (se puede arrastrar)
_ANCHO_MIN_LATERAL = 220
_ANCHO_MAX_LATERAL = 480
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
        self.ajuste_horizontal: Gtk.Adjustment | None = None  # desplazamiento, para etiquetas
        self.set_draw_func(self._draw)

    def _draw(self, _area: Gtk.DrawingArea, cr, width: int, _height: int) -> None:
        dibujar_regla(
            cr,
            width,
            self.fecha_origen,
            self.px_por_dia,
            _color_texto(self),
            _color_texto_fecha(self),
            x_visible=self.ajuste_horizontal.get_value() if self.ajuste_horizontal else 0.0,
        )


_UMBRAL_CARGA_NORMAL = 70  # por debajo: poca carga (verde); desde aquí hasta 100: normal (azul)


def _rgba_carga(porcentaje: int, intensidad: float = 1.0) -> tuple[float, float, float, float]:
    """Color de la escala única de carga (verde poca, azul normal, rojo sobrecarga).

    La usan la franja de equipo y el tinte de fondo por persona, para que signifiquen lo
    mismo. `intensidad` (0-1) atenúa el color, p. ej. para el fondo tras las barras.
    """
    if porcentaje > 100:
        alpha = min(0.4 + (porcentaje - 100) / 250, 0.95)
        return (*_COLOR_SOBRECARGA, alpha * intensidad)
    if porcentaje >= _UMBRAL_CARGA_NORMAL:
        return (*_COLOR_CARGA_NORMAL, 0.55 * intensidad)
    return (*_COLOR_CARGA_OK, 0.55 * intensidad)


class _Leyenda(Gtk.Box):
    """Cuadraditos de color + etiqueta corta de la escala de carga."""

    def __init__(self) -> None:
        super().__init__(spacing=12)
        for porcentaje, texto in (
            (0, _("Poca carga")),
            (_UMBRAL_CARGA_NORMAL, _("Normal")),
            (101, _("Sobrecarga (>100 %)")),
        ):
            item = Gtk.Box(spacing=4)
            muestra = Gtk.DrawingArea(
                content_width=12, content_height=12, valign=Gtk.Align.CENTER
            )
            muestra.set_draw_func(self._pintar, porcentaje)
            item.append(muestra)
            etiqueta = Gtk.Label(label=texto)
            etiqueta.add_css_class("caption")
            etiqueta.add_css_class("dim-label")
            item.append(etiqueta)
            self.append(item)
        self.set_tooltip_text(
            _("Franja superior y fondo de cada persona: carga del día sobre su capacidad")
        )

    @staticmethod
    def _pintar(_area: Gtk.DrawingArea, cr, ancho: int, alto: int, porcentaje: int) -> None:
        cr.set_source_rgba(*_rgba_carga(porcentaje)[:3], 0.9)
        cr.rectangle(0, 0, ancho, alto)
        cr.fill()


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
            cr.set_source_rgba(*_rgba_carga(porcentaje))
            cr.rectangle(x, 0, self.px_por_dia, height)
            cr.fill()


class _LienzoUso(Gtk.DrawingArea):
    """Barras de asignación por persona; el fondo del día se tiñe con la escala de carga."""

    def __init__(
        self,
        on_editar_tarea: Callable[[int], None] | None = None,
        on_dedicacion_changed: Callable[[int, int, int], None] | None = None,
    ) -> None:
        super().__init__()
        self.ruler = _ReglaFechas()
        self._click_pendiente: int | None = None
        self._filas: list[FilaUso] = []
        # Cabecera de persona (segmento None, True) y, si está desplegada, una fila por
        # tarea (segmento, False).
        self._filas_dibujo: list[tuple[FilaUso, SegmentoUso | None, bool]] = []
        self._tareas: dict[int, Tarea] = {}
        self.px_por_dia = 24.0
        self.fecha_origen = date.today()
        self._on_editar_tarea = on_editar_tarea
        self._on_dedicacion_changed = on_dedicacion_changed
        self.set_draw_func(self._draw)

        if on_editar_tarea is not None or on_dedicacion_changed is not None:
            clic = Gtk.GestureClick(button=1)
            clic.connect("released", self._on_clic)
            self.add_controller(clic)

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
        filas: list[FilaUso],
        tareas_por_id: dict[int, Tarea] | None = None,
        plegadas: set[int] | None = None,
    ) -> None:
        self._filas = filas
        self._tareas = tareas_por_id or {}
        plegadas = plegadas or set()
        self._filas_dibujo = []
        for fila in filas:
            self._filas_dibujo.append((fila, None, True))
            if fila.recurso.id not in plegadas:
                self._filas_dibujo.extend((fila, segmento, False) for segmento in fila.segmentos)
        rango = rango_fechas(filas)
        hoy = date.today()
        origen = hoy if rango is None else rango[0]
        self.fecha_origen = ganttcalc.origen_con_cobertura(
            origen - timedelta(days=_MARGEN_DIAS), hoy
        )
        self.ruler.fecha_origen = self.fecha_origen
        self._recalcular_tamano()
        self.queue_draw()
        self.ruler.queue_draw()

    def _fecha_fin(self) -> date:
        rango = rango_fechas(self._filas)
        if rango is None:
            return ganttcalc.fin_con_cobertura(self.fecha_origen + timedelta(days=30), date.today())
        fin = rango[1]
        # Una fecha límite posterior a la última barra debe seguir cabiendo en el lienzo.
        for fila in self._filas:
            for segmento in fila.segmentos:
                tarea = self._tareas.get(segmento.tarea_id)
                if tarea is not None and tarea.fecha_limite:
                    fin = max(fin, ganttcalc.parse_fecha(tarea.fecha_limite) + timedelta(days=1))
        return ganttcalc.fin_con_cobertura(fin + timedelta(days=_MARGEN_DIAS), date.today())

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
        # Bandas por mes y guías al ritmo de la regla (días, semanas o meses según la escala).
        dibujar_bandas(cr, width, height, self.fecha_origen, self.px_por_dia, color_guia)
        cr.set_source_rgba(*color_guia, 0.08)
        cr.set_line_width(1)
        for fecha in ganttcalc.niveles_regla(self.fecha_origen, self.px_por_dia, width).cuadricula:
            x = ganttcalc.fecha_a_x(fecha, self.fecha_origen, self.px_por_dia)
            cr.move_to(x, 0)
            cr.line_to(x, height)
        cr.stroke()

        limites: list[tuple[float, float, float, limite_dibujo.Color]] = []
        for indice, (fila, segmento, cabecera) in enumerate(self._filas_dibujo):
            y = indice * _ALTURA_FILA
            # Separador de fila.
            cr.set_source_rgba(*color_guia, 0.12)
            cr.set_line_width(1)
            cr.move_to(0, y + _ALTURA_FILA)
            cr.line_to(width, y + _ALTURA_FILA)
            cr.stroke()

            carga = carga_por_dia(fila.segmentos)
            for dia, porcentaje in carga.items():
                x = ganttcalc.fecha_a_x(dia, self.fecha_origen, self.px_por_dia)
                # Misma escala que la franja de equipo; en la cabecera de persona es el
                # resumen de su carga, y en las filas de tarea un fondo suave tras las barras.
                cr.set_source_rgba(*_rgba_carga(porcentaje, 0.9 if cabecera else 0.35))
                cr.rectangle(x, y, self.px_por_dia, _ALTURA_FILA)
                cr.fill()

            if segmento is not None:
                self._dibujar_barra(cr, segmento, y)
                self._dibujar_etiqueta_fuera(cr, segmento, y)
                self._anotar_limite(limites, segmento, y)

        # Las fechas límite al final, para que la bandera quede por encima de las barras.
        for x_barra_fin, x_limite, y_linea, color in limites:
            limite_dibujo.dibujar_limite(cr, x_barra_fin, x_limite, y_linea, color)

        x_hoy = ganttcalc.fecha_a_x(date.today(), self.fecha_origen, self.px_por_dia)
        if 0 <= x_hoy <= width:
            cr.set_source_rgba(*_COLOR_HOY, 0.7)
            cr.set_line_width(1.5)
            cr.move_to(x_hoy, 0)
            cr.line_to(x_hoy, height)
            cr.stroke()

    def _anotar_limite(self, limites: list, segmento: SegmentoUso, y_fila: int) -> None:
        tarea = self._tareas.get(segmento.tarea_id)
        if tarea is None or not tarea.fecha_limite:
            return
        x_limite = limite_dibujo.x_limite(tarea.fecha_limite, self.fecha_origen, self.px_por_dia)
        if x_limite < 0:
            return
        x_barra_fin = ganttcalc.fecha_a_x(
            segmento.fecha_inicio, self.fecha_origen, self.px_por_dia
        ) + self._ancho_barra(segmento)
        limites.append(
            (x_barra_fin, x_limite, y_fila + _ALTURA_FILA / 2, limite_dibujo.color_limite(tarea))
        )

    def _tarea_limite_en(self, x: float, y: float) -> Tarea | None:
        """Tarea cuya bandera de fecha límite está bajo el puntero, si hay alguna."""
        for indice, (_fila, segmento, _cab) in enumerate(self._filas_dibujo):
            if segmento is None or not indice * _ALTURA_FILA <= y < (indice + 1) * _ALTURA_FILA:
                continue
            tarea = self._tareas.get(segmento.tarea_id)
            if tarea is None or not tarea.fecha_limite:
                continue
            x_limite = limite_dibujo.x_limite(
                tarea.fecha_limite, self.fecha_origen, self.px_por_dia
            )
            if abs(x - x_limite) <= limite_dibujo.TOLERANCIA_PX:
                return tarea
        return None

    def _ancho_barra(self, segmento: SegmentoUso) -> float:
        return max(
            ganttcalc.ancho_duracion(segmento.duracion_dias, self.px_por_dia), _ANCHO_MIN_BARRA
        )

    def _dibujar_etiqueta_fuera(self, cr, segmento: SegmentoUso, y_fila: int) -> None:
        """Título y dedicación a la derecha de una barra demasiado pequeña para llevarlos
        dentro (escalas anchas), tras la bandera de la fecha límite si la hay."""
        ancho_barra = self._ancho_barra(segmento)
        if self.px_por_dia >= _ZOOM_ETIQUETA_FUERA or ancho_barra >= _ANCHO_BARRA_CON_ETIQUETA:
            return
        layout = PangoCairo.create_layout(cr)
        layout.set_font_description(self.get_pango_context().get_font_description())
        layout.set_text(f"{segmento.titulo} ({segmento.porcentaje_dedicacion}%)", -1)
        layout.set_width(Pango.units_from_double(260))
        layout.set_ellipsize(Pango.EllipsizeMode.END)
        ancho, alto = layout.get_pixel_size()
        x = ganttcalc.fecha_a_x(segmento.fecha_inicio, self.fecha_origen, self.px_por_dia)
        x_texto = x + ancho_barra + 6
        tarea = self._tareas.get(segmento.tarea_id)
        if tarea is not None and tarea.fecha_limite:
            x_texto = max(
                x_texto,
                limite_dibujo.x_limite(tarea.fecha_limite, self.fecha_origen, self.px_por_dia) + 14,
            )
        centro_y = y_fila + _ALTURA_FILA / 2
        cr.set_source_rgba(*color_fondo(), 0.85)
        cr.rectangle(x_texto - 2, centro_y - alto / 2 - 1, ancho + 4, alto + 2)
        cr.fill()
        cr.set_source_rgba(*_color_texto_fecha(self), 0.95)
        cr.move_to(x_texto, centro_y - alto / 2)
        PangoCairo.show_layout(cr, layout)

    def _dibujar_barra(self, cr, segmento: SegmentoUso, y_fila: int) -> None:
        x = ganttcalc.fecha_a_x(segmento.fecha_inicio, self.fecha_origen, self.px_por_dia)
        ancho = self._ancho_barra(segmento)
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
        for indice, (_fila, segmento_fila, _cab) in enumerate(self._filas_dibujo):
            if segmento_fila is None:
                continue
            y0 = indice * _ALTURA_FILA
            if not y0 <= y < y0 + _ALTURA_FILA:
                continue
            x0 = ganttcalc.fecha_a_x(
                segmento_fila.fecha_inicio, self.fecha_origen, self.px_por_dia
            )
            x1 = x0 + self._ancho_barra(segmento_fila)
            if x0 <= x <= x1:
                encontrados.append(segmento_fila)
        if encontrados:
            return encontrados[-1]
        return None

    def _on_motion_leave(self, _controller: Gtk.EventControllerMotion) -> None:
        self.set_cursor_from_name(None)

    def _on_motion(self, _controller: Gtk.EventControllerMotion, x: float, y: float) -> None:
        self.set_cursor_from_name("pointer" if self._segmento_en(x, y) else None)

    def texto_tooltip(self, x: float, y: float) -> str | None:
        """Tooltip bajo (x, y), en coordenadas del lienzo: la fecha límite si el puntero está
        en su bandera; si no, los datos de la barra. Lo muestra el ScrolledWindow que
        contiene el lienzo (anclado a este widget, tan ancho, GTK lo colocaría mal)."""
        tarea = self._tarea_limite_en(x, y)
        if tarea is not None:
            return limite_dibujo.texto_limite(tarea)
        segmento = self._segmento_en(x, y)
        return self._texto_segmento(segmento) if segmento is not None else None

    def _texto_segmento(self, segmento: SegmentoUso) -> str:
        """Tooltip de una barra: título (con su proyecto), fechas y dedicación."""
        fin = segmento.fecha_fin - timedelta(days=1)
        titulo = f"{segmento.proyecto} · {segmento.titulo}" if segmento.proyecto else segmento.titulo
        return "\n".join(
            [
                titulo,
                _("{inicio} → {fin} · {n} día(s)").format(
                    inicio=formatear_fecha_local(segmento.fecha_inicio.isoformat()),
                    fin=formatear_fecha_local(fin.isoformat()),
                    n=segmento.duracion_dias,
                ),
                _("{pct} % de dedicación").format(pct=segmento.porcentaje_dedicacion),
            ]
        )

    def _on_clic(self, _gesture: Gtk.GestureClick, n_press: int, x: float, y: float) -> None:
        """Un clic sobre una barra abre el control de dedicación; el doble clic edita la tarea."""
        segmento = self._segmento_en(x, y)
        if segmento is None:
            return
        if n_press == 2 and self._on_editar_tarea is not None:
            self._cancelar_click_pendiente()
            self._on_editar_tarea(segmento.tarea_id)
        elif n_press == 1 and self._on_dedicacion_changed is not None:
            # Se espera un instante por si es el primer clic de un doble clic.
            self._cancelar_click_pendiente()
            self._click_pendiente = GLib.timeout_add(
                250, self._mostrar_menu_dedicacion_pendiente, segmento, x, y
            )

    def _cancelar_click_pendiente(self) -> None:
        if self._click_pendiente is not None:
            GLib.source_remove(self._click_pendiente)
            self._click_pendiente = None

    def _mostrar_menu_dedicacion_pendiente(self, segmento: SegmentoUso, x: float, y: float) -> bool:
        self._click_pendiente = None
        self._mostrar_menu_dedicacion(segmento, x, y)
        return GLib.SOURCE_REMOVE

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
        escala.connect("value-changed", lambda e: valor.set_text(f"{round(e.get_value())} %"))
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
            porcentaje = round(escala.get_value())
            if self._on_dedicacion_changed is not None and porcentaje != segmento.porcentaje_dedicacion:
                self._on_dedicacion_changed(
                    segmento.tarea_id, self._recurso_id_de_segmento(segmento), porcentaje
                )
            # Destruir el popover mientras se cierra provoca avisos de GTK: se retira después.
            GLib.idle_add(lambda: popover.unparent() or GLib.SOURCE_REMOVE)

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
        plegar_inicial: bool = False,
        on_dedicacion_changed: Callable[[int, int, int], None] | None = None,
    ) -> None:
        _asegurar_css_carga()
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self._on_editar_tarea = on_editar_tarea
        self._on_dedicacion_changed = on_dedicacion_changed
        self._tareas_por_id: dict[int, Tarea] = {}
        self._indice_zoom = _PASOS_ZOOM.index(80.0)  # vista diaria por defecto
        self._filas: list[FilaUso] = []
        self._filtro = ""
        # Personas con sus tareas plegadas (ids de recurso); `_conocidas` evita volver a
        # plegar al refrescar a quien el usuario ya desplegó.
        # Como en el Gantt: el eje se centra en hoy al cargar un proyecto, no en cada refresco.
        self._centrado_pendiente = True
        self.connect("map", lambda *_a: self._pedir_centrado_si_hace_falta())
        self._plegar_inicial = plegar_inicial
        self._plegadas: set[int] = set()
        self._conocidas: set[int] = set()

        toolbar = Gtk.Box(spacing=6, margin_top=6, margin_bottom=6, margin_start=6, margin_end=6)
        zoom_out = Gtk.Button(icon_name="zoom-out-symbolic", tooltip_text=_("Alejar"))
        zoom_out.connect("clicked", self._on_zoom_out)
        toolbar.append(zoom_out)
        zoom_in = Gtk.Button(icon_name="zoom-in-symbolic", tooltip_text=_("Acercar"))
        zoom_in.connect("clicked", self._on_zoom_in)
        toolbar.append(zoom_in)
        toolbar.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))
        hoy_boton = Gtk.Button(label=_("Hoy"), tooltip_text=_("Ir a la fecha de hoy"))
        hoy_boton.connect("clicked", lambda _b: GLib.idle_add(self._centrar_en_hoy))
        toolbar.append(hoy_boton)
        toolbar.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))
        grupo_escalas: Gtk.ToggleButton | None = None
        for etiqueta, texto, px_por_dia in _ESCALAS:
            boton_escala = Gtk.ToggleButton(label=_(texto))
            boton_escala.add_css_class("linked")
            if grupo_escalas is None:
                grupo_escalas = boton_escala
            else:
                boton_escala.set_group(grupo_escalas)
            boton_escala.set_active(etiqueta == "Diario")
            boton_escala.connect("clicked", self._on_escala, px_por_dia)
            toolbar.append(boton_escala)
        toolbar.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))
        toolbar.append(_Leyenda())
        espacio = Gtk.Box(hexpand=True)
        toolbar.append(espacio)
        self._buscar = Gtk.SearchEntry(placeholder_text=_("Buscar persona…"), width_chars=18)
        self._buscar.connect("search-changed", self._on_buscar)
        toolbar.append(self._buscar)
        self.append(toolbar)

        self._resumen = Gtk.Label(xalign=0, margin_start=12, margin_bottom=6)
        self._resumen.add_css_class("caption")
        self.append(self._resumen)

        self._vacio = Gtk.Label(
            label=_("Aún no hay recursos. Asígalos al crear o editar una tarea."),
            wrap=True,
            margin_top=24,
            margin_start=16,
            margin_end=16,
        )
        self._vacio.add_css_class("dim-label")
        self.append(self._vacio)

        # Gtk.Paned, como en el Gantt: el reparto entre el lateral y el lienzo se ajusta
        # arrastrando el divisor y se recuerda entre sesiones.
        self._timeout_guardar_ancho: int | None = None
        self._ultimo_ancho_guardado: int | None = None
        guardado = settings.read_settings().get("uso_panel_ancho")
        self._ajustar_ancho_a_nombres = guardado is None
        ancho_panel = guardado if guardado is not None else _ANCHO_LATERAL
        self._panel = Gtk.Paned(
            orientation=Gtk.Orientation.HORIZONTAL,
            position=ancho_panel,
            vexpand=True,
            hexpand=True,
        )
        self._panel.connect("notify::position", self._on_posicion_panel)
        self.append(self._panel)

        # EXTERNAL (no NEVER): con NEVER la lista pide alto para todas sus filas y, con
        # muchas, la ventana crece hacia abajo. La barra vertical la muestra el lienzo.
        # El ancho lo decide el Paned: con EXTERNAL el texto de las filas no fuerza ancho.
        lateral_scroller = Gtk.ScrolledWindow(
            vscrollbar_policy=Gtk.PolicyType.EXTERNAL,
            hscrollbar_policy=Gtk.PolicyType.EXTERNAL,
            vexpand=True,
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
        self._panel.set_start_child(lateral_scroller)
        self._panel.set_resize_start_child(False)
        self._panel.set_shrink_start_child(False)

        canvas_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True, vexpand=True)
        self._lienzo = _LienzoUso(
            on_editar_tarea=self._on_editar_desde_lienzo,
            on_dedicacion_changed=self._on_dedicacion_changed,
        )
        self._lienzo.set_zoom(_PASOS_ZOOM[self._indice_zoom])

        # EXTERNAL (no NEVER): con NEVER la regla pide el ancho completo del lienzo y, al
        # compartir ajuste con él, anula el desplazamiento horizontal (ver GanttView).
        ruler_scroller = Gtk.ScrolledWindow(
            vscrollbar_policy=Gtk.PolicyType.NEVER, hscrollbar_policy=Gtk.PolicyType.EXTERNAL
        )
        ruler_scroller.set_child(self._lienzo.ruler)
        canvas_box.append(ruler_scroller)

        self._barra_equipo = _BarraCargaEquipo()
        equipo_scroller = Gtk.ScrolledWindow(
            vscrollbar_policy=Gtk.PolicyType.NEVER, hscrollbar_policy=Gtk.PolicyType.EXTERNAL
        )
        equipo_scroller.set_child(self._barra_equipo)
        canvas_box.append(equipo_scroller)

        self._canvas_scroller = Gtk.ScrolledWindow(
            vexpand=True,
            hexpand=True,
            hscrollbar_policy=Gtk.PolicyType.ALWAYS,
            vscrollbar_policy=Gtk.PolicyType.AUTOMATIC,
        )
        self._canvas_scroller.set_child(self._lienzo)
        instalar_arrastre(self._canvas_scroller)
        instalar_arrastre(ruler_scroller, vertical=False)
        self._canvas_scroller.set_has_tooltip(True)
        self._canvas_scroller.connect("query-tooltip", self._on_query_tooltip)
        # Cada scroll conserva su propio ajuste (compartirlo provoca bucles de layout, como
        # en el Gantt); solo se sincroniza la posición.
        self._sincronizando_scroll = False
        adj_lateral = lateral_scroller.get_vadjustment()
        adj_lienzo = self._canvas_scroller.get_vadjustment()
        adj_lateral.connect("value-changed", self._sincronizar_scroll, adj_lienzo)
        adj_lienzo.connect("value-changed", self._sincronizar_scroll, adj_lateral)
        ruler_scroller.set_hadjustment(self._canvas_scroller.get_hadjustment())
        self._lienzo.ruler.ajuste_horizontal = self._canvas_scroller.get_hadjustment()
        self._canvas_scroller.get_hadjustment().connect(
            "value-changed", lambda _a: self._lienzo.ruler.queue_draw()
        )
        equipo_scroller.set_hadjustment(self._canvas_scroller.get_hadjustment())
        canvas_box.append(self._canvas_scroller)
        self._panel.set_end_child(canvas_box)
        self._panel.set_resize_end_child(True)
        self._panel.set_shrink_end_child(False)

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
        if self._ajustar_ancho_a_nombres:
            self._ajustar_ancho_a_nombres = False
            self._ancho_para_nombres(filas)
        nuevas = {f.recurso.id for f in filas} - self._conocidas
        self._conocidas |= nuevas
        if self._plegar_inicial:
            self._plegadas |= nuevas
        self._actualizar_resumen()
        self._aplicar_filtro()
        self._pedir_centrado_si_hace_falta()

    def _ancho_para_nombres(self, filas: list[FilaUso]) -> None:
        """Sin ancho guardado por el usuario, el panel arranca lo bastante ancho para leer
        el nombre más largo (sin guardarlo: es solo el valor inicial)."""
        mayor = 0
        for fila in filas:
            ancho, _alto = self.create_pango_layout(fila.recurso.nombre).get_pixel_size()
            mayor = max(mayor, ancho)
        # Margen, flecha, avatar y separaciones de la cabecera, más algo de holgura.
        ancho_panel = max(_ANCHO_MIN_LATERAL, min(mayor + 110, _ANCHO_MAX_LATERAL))
        self._ultimo_ancho_guardado = ancho_panel
        self._panel.set_position(ancho_panel)

    def _on_posicion_panel(self, panel: Gtk.Paned, _pspec) -> None:
        pos = panel.get_position()
        if pos <= 80 or self._ultimo_ancho_guardado == pos:
            return
        self._ultimo_ancho_guardado = pos
        if self._timeout_guardar_ancho is not None:
            GLib.source_remove(self._timeout_guardar_ancho)
        self._timeout_guardar_ancho = GLib.timeout_add(300, self._guardar_ancho_panel, pos)

    def _guardar_ancho_panel(self, pos: int) -> bool:
        self._timeout_guardar_ancho = None
        config = settings.read_settings()
        config["uso_panel_ancho"] = pos
        settings.write_settings(config)
        return False

    def _on_query_tooltip(self, scroller: Gtk.ScrolledWindow, x, y, _teclado, tooltip) -> bool:
        punto = scroller.translate_coordinates(self._lienzo, x, y)  # incluye el desplazamiento
        if punto is None:
            return False
        texto = self._lienzo.texto_tooltip(*punto)
        if not texto:
            return False
        tooltip.set_text(texto)
        return True

    def pedir_centrado(self) -> None:
        """Al cambiar de proyecto: la próxima carga de filas vuelve a centrar el eje en hoy."""
        self._centrado_pendiente = True

    def _pedir_centrado_si_hace_falta(self) -> None:
        if self._centrado_pendiente and self._filas:
            GLib.idle_add(self._centrado_inicial)

    def _centrado_inicial(self) -> bool:
        if not self._centrado_pendiente:
            return False
        if self._canvas_scroller.get_hadjustment().get_page_size() <= 0:
            return False  # vista oculta: sigue pendiente hasta que se muestre
        self._centrado_pendiente = False
        return self._centrar_en_hoy()

    def _centrar_en_hoy(self) -> bool:
        adj = self._canvas_scroller.get_hadjustment()
        if adj.get_page_size() <= 0:
            return False  # sin asignar aún: no re-registrar el idle (consumiría CPU)
        hoy_x = ganttcalc.fecha_a_x(date.today(), self._lienzo.fecha_origen, self._lienzo.px_por_dia)
        valor = max(0.0, hoy_x - adj.get_page_size() * 0.35)
        adj.set_value(min(valor, max(0.0, adj.get_upper() - adj.get_page_size())))
        return False

    def _filas_visibles(self) -> list[FilaUso]:
        if not self._filtro:
            return self._filas
        return [f for f in self._filas if self._filtro in f.recurso.nombre.casefold()]

    def _aplicar_filtro(self) -> None:
        visibles = self._filas_visibles()
        self._reconstruir_lista(visibles)
        self._lienzo.actualizar(visibles, self._tareas_por_id, self._plegadas)
        self._actualizar_barra_equipo()

    def _on_buscar(self, entry: Gtk.SearchEntry) -> None:
        self._filtro = entry.get_text().strip().casefold()
        if self._filas:
            self._aplicar_filtro()

    def _actualizar_resumen(self) -> None:
        resumen = resumen_uso(self._filas)
        if not resumen.personas_sobrecargadas and not resumen.dias_sobrecarga_equipo:
            self._resumen.set_label(_("Sin sobrecarga de personas ni de equipo."))
            self._resumen.remove_css_class("error")
            self._resumen.add_css_class("dim-label")
            return
        self._resumen.remove_css_class("dim-label")
        self._resumen.add_css_class("error")
        self._resumen.set_label(
            _(
                "{personas} persona(s) sobrecargada(s) · {dias} día(s) de sobrecarga del "
                "equipo ({mes} este mes)"
            ).format(
                personas=resumen.personas_sobrecargadas,
                dias=resumen.dias_sobrecarga_equipo,
                mes=resumen.dias_sobrecarga_equipo_mes,
            )
        )

    def _actualizar_barra_equipo(self) -> None:
        # La franja es del equipo completo: el buscador solo filtra las filas.
        carga = carga_equipo_por_dia(self._filas)
        self._barra_equipo.set_zoom(self._lienzo.px_por_dia)
        self._barra_equipo.actualizar(carga, self._lienzo.fecha_origen, self._lienzo.ancho_total())

    def _mostrar_contenido(self, visible: bool) -> None:
        self._panel.set_visible(visible)
        self._vacio.set_visible(not visible)

    def _reconstruir_lista(self, filas: list[FilaUso]) -> None:
        while (hijo := self._lista.get_first_child()) is not None:
            self._lista.remove(hijo)
        for fila in filas:
            self._lista.append(self._fila_lateral(fila, None))
            if fila.recurso.id not in self._plegadas:
                for segmento in fila.segmentos:
                    self._lista.append(self._fila_lateral(fila, segmento))

    def _alternar_plegado(self, recurso_id: int) -> None:
        self._plegadas ^= {recurso_id}
        self._aplicar_filtro()

    def _fila_lateral(self, fila: FilaUso, segmento: SegmentoUso | None = None) -> Gtk.Widget:
        caja = Gtk.Box(
            spacing=8,
            margin_start=8,
            margin_end=8,
            height_request=_ALTURA_FILA,
            valign=Gtk.Align.CENTER,
        )
        if segmento is None:
            plegada = fila.recurso.id in self._plegadas
            if fila.segmentos:
                flecha = Gtk.Button(
                    icon_name="pan-end-symbolic" if plegada else "pan-down-symbolic",
                    tooltip_text=_("Mostrar tareas") if plegada else _("Ocultar tareas"),
                    valign=Gtk.Align.CENTER,
                )
                flecha.add_css_class("flat")
                flecha.add_css_class("circular")
                flecha.connect("clicked", lambda _b, rid=fila.recurso.id: self._alternar_plegado(rid))
                caja.append(flecha)
            else:
                caja.append(Gtk.Box(width_request=34))
            caja.append(AvatarWidget(fila.recurso, size=28))
        else:
            caja.append(Gtk.Box(width_request=34))
        textos = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0, hexpand=True, valign=Gtk.Align.CENTER)
        nombre = Gtk.Label(
            label=fila.recurso.nombre if segmento is None else f"↳ {segmento.titulo}",
            xalign=0,
            ellipsize=Pango.EllipsizeMode.END,
        )
        textos.append(nombre)
        if segmento is not None:
            meta = _("{pct} % de dedicación").format(pct=segmento.porcentaje_dedicacion)
            if segmento.proyecto:
                meta = f"{segmento.proyecto} · {meta}"
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
        GLib.idle_add(self._centrar_en_hoy)

    def _sincronizar_scroll(self, origen: Gtk.Adjustment, destino: Gtk.Adjustment) -> None:
        if self._sincronizando_scroll:
            return
        self._sincronizando_scroll = True
        try:
            destino.set_value(origen.get_value())
        finally:
            self._sincronizando_scroll = False

    def _on_scroll(self, controller: Gtk.EventControllerScroll, _dx: float, dy: float) -> bool:
        if not (controller.get_current_event_state() & Gdk.ModifierType.CONTROL_MASK):
            return False
        if dy < 0:
            self._on_zoom_in()
        elif dy > 0:
            self._on_zoom_out()
        return True
