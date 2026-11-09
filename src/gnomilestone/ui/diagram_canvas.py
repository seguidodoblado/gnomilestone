from __future__ import annotations

import math
from collections.abc import Callable

import gi

gi.require_version("Gdk", "4.0")
gi.require_version("Gtk", "4.0")
from gi.repository import Gdk, Gtk, Pango, PangoCairo

from gnomilestone.diagrama import Arista, Diagrama, Nodo, punto_borde

_ACENTO = (0.21, 0.52, 0.89)
_ZOOM_MIN, _ZOOM_MAX = 0.2, 4.0


def _caja(cr, x: float, y: float, w: float, h: float, radio: float) -> None:
    radio = min(radio, w / 2, h / 2)
    cr.new_sub_path()
    cr.arc(x + w - radio, y + radio, radio, -math.pi / 2, 0)
    cr.arc(x + w - radio, y + h - radio, radio, 0, math.pi / 2)
    cr.arc(x + radio, y + h - radio, radio, math.pi / 2, math.pi)
    cr.arc(x + radio, y + radio, radio, math.pi, 3 * math.pi / 2)
    cr.close_path()


def _colores(widget: Gtk.Widget) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    """(primer plano, fondo aproximado) del tema actual, para un dibujo que sigue al tema."""
    color = widget.get_color()
    fg = (color.red, color.green, color.blue)
    luminosidad = 0.299 * fg[0] + 0.587 * fg[1] + 0.114 * fg[2]
    fondo = (0.19, 0.19, 0.21) if luminosidad > 0.5 else (0.97, 0.97, 0.98)
    return fg, fondo


def _texto(
    cr, widget: Gtk.Widget, texto: str, cx: float, cy: float, ancho: float, px: float = 13,
    lineas: int = 3,
) -> tuple[float, float]:
    """Texto centrado en (cx, cy) con la tipografía del sistema; devuelve su tamaño."""
    layout = widget.create_pango_layout(texto)
    descripcion = widget.get_pango_context().get_font_description().copy()
    descripcion.set_absolute_size(px * Pango.SCALE)
    layout.set_font_description(descripcion)
    layout.set_width(int(ancho * Pango.SCALE))
    layout.set_height(-lineas)
    layout.set_ellipsize(Pango.EllipsizeMode.END)
    layout.set_alignment(Pango.Alignment.CENTER)
    w, h = layout.get_pixel_size()
    cr.move_to(cx - ancho / 2, cy - h / 2)
    PangoCairo.show_layout(cr, layout)
    return w, h


def pintar_diagrama(
    cr,
    widget: Gtk.Widget,
    diagrama: Diagrama,
    nodo_sel: int | None = None,
    arista_sel: Arista | None = None,
    conexion: tuple[Nodo, float, float] | None = None,
) -> None:
    """Dibuja el diagrama en coordenadas del lienzo (el llamador ya aplicó zoom y desplazamiento)."""
    fg, fondo = _colores(widget)

    for arista in diagrama.aristas:
        extremos = diagrama.extremos(arista)
        if extremos is None:
            continue
        (x1, y1), (x2, y2) = extremos
        if any(o.desde == arista.hasta and o.hasta == arista.desde for o in diagrama.aristas):
            # Dos flechas en sentidos opuestos entre los mismos nodos: se separan un poco.
            largo = math.hypot(x2 - x1, y2 - y1) or 1.0
            dx, dy = -(y2 - y1) / largo * 7, (x2 - x1) / largo * 7
            x1, y1, x2, y2 = x1 + dx, y1 + dy, x2 + dx, y2 + dy
        seleccionada = arista is arista_sel
        cr.set_source_rgba(*(_ACENTO if seleccionada else fg), 1.0 if seleccionada else 0.7)
        grosor = 3.6 if arista.estilo == "gruesa" else 1.8
        cr.set_line_width(grosor + (0.8 if seleccionada else 0))
        if arista.estilo == "discontinua":
            cr.set_dash([7, 5])
        cr.move_to(x1, y1)
        cr.line_to(x2, y2)
        cr.stroke()
        cr.set_dash([])
        if arista.punta:
            angulo = math.atan2(y2 - y1, x2 - x1)
            cr.move_to(x2, y2)
            for lado in (-1, 1):
                cr.line_to(
                    x2 - 13 * math.cos(angulo) + lado * 6 * math.sin(angulo),
                    y2 - 13 * math.sin(angulo) - lado * 6 * math.cos(angulo),
                )
            cr.close_path()
            cr.fill()
        if arista.etiqueta:
            mx, my = (x1 + x2) / 2, (y1 + y2) / 2
            layout = widget.create_pango_layout(arista.etiqueta)
            descripcion = widget.get_pango_context().get_font_description().copy()
            descripcion.set_absolute_size(12 * Pango.SCALE)
            layout.set_font_description(descripcion)
            w, h = layout.get_pixel_size()
            _caja(cr, mx - w / 2 - 5, my - h / 2 - 2, w + 10, h + 4, 6)
            cr.set_source_rgb(*fondo)
            cr.fill()
            cr.set_source_rgba(*(_ACENTO if seleccionada else fg), 0.95)
            cr.move_to(mx - w / 2, my - h / 2)
            PangoCairo.show_layout(cr, layout)

    for nodo in diagrama.nodos:
        _trazar_forma(cr, nodo)
        cr.set_source_rgba(*fg, 0.20 if nodo.tipo in ("inicio", "fin") else 0.11)
        cr.fill_preserve()
        seleccionado = nodo.id == nodo_sel
        cr.set_source_rgba(*(_ACENTO if seleccionado else fg), 1.0 if seleccionado else 0.6)
        cr.set_line_width(3 if seleccionado else 1.5)
        cr.stroke()
        cr.set_source_rgba(*fg, 0.95)
        _texto(cr, widget, nodo.texto, nodo.x, nodo.y, nodo.w - (60 if nodo.tipo == "decision" else 20))

    if conexion is not None:
        origen, x, y = conexion
        px, py = punto_borde(origen, x, y)
        cr.set_source_rgba(*_ACENTO, 0.9)
        cr.set_line_width(2)
        cr.set_dash([6, 4])
        cr.move_to(px, py)
        cr.line_to(x, y)
        cr.stroke()
        cr.set_dash([])


def _trazar_forma(cr, nodo: Nodo) -> None:
    x0, y0 = nodo.x - nodo.w / 2, nodo.y - nodo.h / 2
    if nodo.tipo == "decision":
        cr.new_path()
        cr.move_to(nodo.x, y0)
        cr.line_to(nodo.x + nodo.w / 2, nodo.y)
        cr.line_to(nodo.x, y0 + nodo.h)
        cr.line_to(x0, nodo.y)
        cr.close_path()
    elif nodo.tipo in ("inicio", "fin"):
        _caja(cr, x0, y0, nodo.w, nodo.h, nodo.h / 2)
    else:
        _caja(cr, x0, y0, nodo.w, nodo.h, 10)


class MiniaturaDiagrama(Gtk.DrawingArea):
    """Vista previa estática de un diagrama, ajustada al tamaño disponible (para tarjetas)."""

    def __init__(self, diagrama: Diagrama, ancho: int = 270, alto: int = 150) -> None:
        super().__init__(content_width=ancho, content_height=alto, hexpand=True, vexpand=True)
        self._diagrama = diagrama
        self.set_draw_func(self._dibujar)

    def _dibujar(self, _area, cr, ancho: int, alto: int) -> None:
        limites = self._diagrama.limites()
        if limites is None:
            fg, _fondo = _colores(self)
            cr.set_source_rgba(*fg, 0.5)
            _texto(cr, self, "∅", ancho / 2, alto / 2, ancho, px=28, lineas=1)
            return
        minx, miny, maxx, maxy = limites
        margen = 8
        escala = min(
            (ancho - 2 * margen) / max(maxx - minx, 1), (alto - 2 * margen) / max(maxy - miny, 1)
        )
        escala = min(escala, 1.0)
        cr.translate(
            (ancho - (maxx - minx) * escala) / 2 - minx * escala,
            (alto - (maxy - miny) * escala) / 2 - miny * escala,
        )
        cr.scale(escala, escala)
        pintar_diagrama(cr, self, self._diagrama)


class LienzoDiagrama(Gtk.DrawingArea):
    """Lienzo editable de un diagrama de flujo.

    Herramienta «seleccionar»: clic selecciona (nodo o flecha), arrastrar un nodo lo mueve,
    arrastrar el fondo desplaza la vista y doble clic edita el texto. Herramienta
    «conectar»: arrastrar de un nodo a otro crea una flecha. Ctrl+rueda hace zoom bajo el
    puntero; la rueda sola desplaza. Supr borra la selección."""

    def __init__(
        self,
        diagrama: Diagrama,
        al_cambiar: Callable[[], None],
        al_editar_texto: Callable[[Nodo | Arista], None],
    ) -> None:
        super().__init__(hexpand=True, vexpand=True, focusable=True)
        self.diagrama = diagrama
        self._al_cambiar = al_cambiar
        self._al_editar_texto = al_editar_texto
        self.herramienta = "seleccionar"
        self._nodo_sel: int | None = None
        self._arista_sel: Arista | None = None
        self._z, self._ox, self._oy = 1.0, 0.0, 0.0
        self._ajustado = False
        self._accion: tuple | None = None
        self._conexion: tuple[Nodo, float, float] | None = None
        self.set_draw_func(self._dibujar)

        arrastre = Gtk.GestureDrag(button=1)
        arrastre.connect("drag-begin", self._on_inicio)
        arrastre.connect("drag-update", self._on_arrastre)
        arrastre.connect("drag-end", self._on_fin)
        self.add_controller(arrastre)
        clic = Gtk.GestureClick(button=1)
        clic.connect("pressed", self._on_clic)
        self.add_controller(clic)
        rueda = Gtk.EventControllerScroll(
            flags=Gtk.EventControllerScrollFlags.BOTH_AXES
        )
        rueda.connect("scroll", self._on_rueda)
        self.add_controller(rueda)
        movimiento = Gtk.EventControllerMotion()
        movimiento.connect("motion", lambda _c, x, y: setattr(self, "_puntero", (x, y)))
        self.add_controller(movimiento)
        self._puntero = (0.0, 0.0)
        teclas = Gtk.EventControllerKey()
        teclas.connect("key-pressed", self._on_tecla)
        self.add_controller(teclas)

    # -- Transformación ----------------------------------------------------

    def _a_lienzo(self, x: float, y: float) -> tuple[float, float]:
        return (x - self._ox) / self._z, (y - self._oy) / self._z

    def ajustar(self) -> None:
        """Zoom y desplazamiento para ver todo el diagrama, centrado."""
        ancho, alto = self.get_width(), self.get_height()
        limites = self.diagrama.limites()
        if ancho <= 0 or alto <= 0:
            self._ajustado = False
            return
        if limites is None:
            self._z, self._ox, self._oy = 1.0, ancho / 2, alto / 2
        else:
            minx, miny, maxx, maxy = limites
            margen = 40
            self._z = max(
                _ZOOM_MIN,
                min(1.25, (ancho - 2 * margen) / max(maxx - minx, 1),
                    (alto - 2 * margen) / max(maxy - miny, 1)),
            )
            self._ox = ancho / 2 - (minx + maxx) / 2 * self._z
            self._oy = alto / 2 - (miny + maxy) / 2 * self._z
        self._ajustado = True
        self.queue_draw()

    def zoom_por(self, factor: float, ancla: tuple[float, float] | None = None) -> None:
        ax, ay = ancla or (self.get_width() / 2, self.get_height() / 2)
        nuevo = max(_ZOOM_MIN, min(_ZOOM_MAX, self._z * factor))
        factor = nuevo / self._z
        self._ox = ax - (ax - self._ox) * factor
        self._oy = ay - (ay - self._oy) * factor
        self._z = nuevo
        self.queue_draw()

    def centro_en_lienzo(self) -> tuple[float, float]:
        return self._a_lienzo(self.get_width() / 2, self.get_height() / 2)

    # -- Edición -----------------------------------------------------------

    def anadir_nodo(self, tipo: str, texto: str) -> Nodo:
        cx, cy = self.centro_en_lienzo()
        desplazamiento = 24 * (len(self.diagrama.nodos) % 6)
        nodo = self.diagrama.nuevo_nodo(tipo, texto, cx + desplazamiento, cy + desplazamiento)
        self._nodo_sel, self._arista_sel = nodo.id, None
        self.queue_draw()
        self._al_cambiar()
        return nodo

    def eliminar_seleccion(self) -> None:
        if self._nodo_sel is not None:
            self.diagrama.eliminar_nodo(self._nodo_sel)
        elif self._arista_sel is not None:
            self.diagrama.aristas = [a for a in self.diagrama.aristas if a is not self._arista_sel]
        else:
            return
        self._nodo_sel, self._arista_sel = None, None
        self.queue_draw()
        self._al_cambiar()

    def deseleccionar(self) -> None:
        self._nodo_sel, self._arista_sel = None, None
        self.queue_draw()

    def refrescar(self) -> None:
        self.queue_draw()

    # -- Eventos -----------------------------------------------------------

    def _on_inicio(self, _gesto: Gtk.GestureDrag, x: float, y: float) -> None:
        self.grab_focus()
        lx, ly = self._a_lienzo(x, y)
        nodo = self.diagrama.nodo_en(lx, ly)
        if self.herramienta == "conectar":
            if nodo is not None:
                self._accion = ("conectar", nodo)
                self._conexion = (nodo, lx, ly)
            return
        if nodo is not None:
            self._nodo_sel, self._arista_sel = nodo.id, None
            self._accion = ("mover", nodo, nodo.x, nodo.y, False)
        else:
            arista = self.diagrama.arista_en(lx, ly, 8 / self._z)
            self._nodo_sel, self._arista_sel = None, arista
            self._accion = ("desplazar", self._ox, self._oy)
        self.queue_draw()

    def _on_arrastre(self, _gesto: Gtk.GestureDrag, dx: float, dy: float) -> None:
        if self._accion is None:
            return
        tipo = self._accion[0]
        if tipo == "mover":
            _t, nodo, x0, y0, _movido = self._accion
            nodo.x, nodo.y = x0 + dx / self._z, y0 + dy / self._z
            self._accion = ("mover", nodo, x0, y0, True)
        elif tipo == "desplazar":
            self._ox, self._oy = self._accion[1] + dx, self._accion[2] + dy
        elif tipo == "conectar":
            ok, ix, iy = _gesto.get_start_point()
            if ok:
                lx, ly = self._a_lienzo(ix + dx, iy + dy)
                self._conexion = (self._accion[1], lx, ly)
        self.queue_draw()

    def _on_fin(self, _gesto: Gtk.GestureDrag, dx: float, dy: float) -> None:
        accion, self._accion = self._accion, None
        if accion is None:
            return
        if accion[0] == "mover" and accion[4]:
            self._al_cambiar()
        elif accion[0] == "conectar" and self._conexion is not None:
            _origen, lx, ly = self._conexion
            destino = self.diagrama.nodo_en(lx, ly)
            if destino is not None:
                arista = self.diagrama.conectar(accion[1].id, destino.id)
                if arista is not None:
                    self._nodo_sel, self._arista_sel = None, arista
                    self._al_cambiar()
        self._conexion = None
        self.queue_draw()

    def _on_clic(self, _gesto: Gtk.GestureClick, n_press: int, x: float, y: float) -> None:
        if n_press != 2 or self.herramienta != "seleccionar":
            return
        lx, ly = self._a_lienzo(x, y)
        nodo = self.diagrama.nodo_en(lx, ly)
        if nodo is not None:
            self._al_editar_texto(nodo)
            return
        arista = self.diagrama.arista_en(lx, ly, 8 / self._z)
        if arista is not None:
            self._al_editar_texto(arista)

    def _on_rueda(self, controlador: Gtk.EventControllerScroll, dx: float, dy: float) -> bool:
        if controlador.get_current_event_state() & Gdk.ModifierType.CONTROL_MASK:
            self.zoom_por(1.15 if dy < 0 else 1 / 1.15, self._puntero)
        else:
            self._ox -= dx * 40
            self._oy -= dy * 40
            self.queue_draw()
        return True

    def _on_tecla(self, _c: Gtk.EventControllerKey, keyval: int, _code: int, _estado) -> bool:
        if keyval in (Gdk.KEY_Delete, Gdk.KEY_BackSpace):
            self.eliminar_seleccion()
            return True
        return False

    def _dibujar(self, _area, cr, ancho: int, alto: int) -> None:
        if not self._ajustado:
            self.ajustar()
        fg, _fondo = _colores(self)
        # Rejilla de puntos discreta.
        paso = 40 * self._z
        if paso >= 12:
            cr.set_source_rgba(*fg, 0.12)
            x = self._ox % paso
            while x < ancho:
                y = self._oy % paso
                while y < alto:
                    cr.rectangle(x - 1, y - 1, 2, 2)
                    y += paso
                x += paso
            cr.fill()
        cr.translate(self._ox, self._oy)
        cr.scale(self._z, self._z)
        pintar_diagrama(cr, self, self.diagrama, self._nodo_sel, self._arista_sel, self._conexion)


class IconoForma(Gtk.DrawingArea):
    """Icono con la forma de un tipo de elemento (para los botones de la barra): píldora con
    ▶ para Inicio, píldora con ■ para Fin, rectángulo para Paso y rombo para Decisión."""

    def __init__(self, tipo: str) -> None:
        super().__init__(content_width=34, content_height=22, valign=Gtk.Align.CENTER)
        self._tipo = tipo
        self.set_draw_func(self._dibujar)

    def _dibujar(self, _area, cr, ancho: int, alto: int) -> None:
        fg, _fondo = _colores(self)
        x0, y0, w, h = 2, 2, ancho - 4, alto - 4
        cr.set_line_width(1.6)
        if self._tipo == "decision":
            cr.move_to(ancho / 2, y0)
            cr.line_to(x0 + w, alto / 2)
            cr.line_to(ancho / 2, y0 + h)
            cr.line_to(x0, alto / 2)
            cr.close_path()
        elif self._tipo in ("inicio", "fin"):
            _caja(cr, x0, y0, w, h, h / 2)
        else:
            _caja(cr, x0, y0, w, h, 3)
        cr.set_source_rgba(*fg, 0.9)
        cr.stroke()
        cr.set_source_rgba(*fg, 0.9)
        cx, cy = ancho / 2, alto / 2
        if self._tipo == "inicio":  # ▶
            cr.move_to(cx - 3, cy - 4)
            cr.line_to(cx + 4, cy)
            cr.line_to(cx - 3, cy + 4)
            cr.close_path()
            cr.fill()
        elif self._tipo == "fin":  # ■
            cr.rectangle(cx - 3.5, cy - 3.5, 7, 7)
            cr.fill()
