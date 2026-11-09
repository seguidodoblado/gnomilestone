"""Zoom continuo (botones y Ctrl+rueda, como en el Gantt) y ajuste a la vista para los
timelines: el zoom se aplica donde apunta el puntero y, al abrir, se ve todo el contenido."""

from __future__ import annotations

from collections.abc import Callable

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gdk, GLib, Gtk

from gnomilestone.i18n import _

ZOOM_MIN = 0.15
ZOOM_MAX = 4.0
ZOOM_PASO = 1.25
AJUSTE_MIN = 0.35  # el «ajustar a la vista» no baja de aquí (más allá, se desplaza)
AJUSTE_MAX = 1.25  # ...ni agranda un contenido pequeño por encima de esto

Ancla = tuple[float, float] | None  # (x, y) en coordenadas de la vista; None = su centro


class Zoom:
    """Nivel de zoom con botones Alejar/Acercar/Ajustar y Ctrl+rueda sobre un widget.
    `auto` indica que el factor lo manda el ajuste a la vista (hasta que el usuario haga
    zoom a mano o pulse «Ajustar»)."""

    def __init__(
        self, al_cambiar: Callable[[Ancla], None], al_ajustar: Callable[[], None]
    ) -> None:
        self.factor = 1.0
        self.auto = True
        self._al_cambiar = al_cambiar
        self._al_ajustar = al_ajustar
        self._puntero: tuple[float, float] | None = None

    def botones(self) -> Gtk.Box:
        caja = Gtk.Box(spacing=6, halign=Gtk.Align.END)
        for icono, tooltip, accion in (
            ("zoom-fit-best-symbolic", _("Ajustar a la vista"), self.ajustar),
            ("zoom-out-symbolic", _("Alejar"), self.alejar),
            ("zoom-in-symbolic", _("Acercar"), self.acercar),
        ):
            boton = Gtk.Button(icon_name=icono, tooltip_text=tooltip)
            boton.connect("clicked", lambda _b, a=accion: a())
            caja.append(boton)
        return caja

    def conectar_rueda(self, widget: Gtk.Widget) -> None:
        rueda = Gtk.EventControllerScroll(flags=Gtk.EventControllerScrollFlags.VERTICAL)
        rueda.connect("scroll", self._on_rueda)
        widget.add_controller(rueda)
        movimiento = Gtk.EventControllerMotion()
        movimiento.connect("motion", lambda _c, x, y: setattr(self, "_puntero", (x, y)))
        movimiento.connect("leave", lambda _c: setattr(self, "_puntero", None))
        widget.add_controller(movimiento)

    def acercar(self, ancla: Ancla = None) -> None:
        self._cambiar(self.factor * ZOOM_PASO, ancla)

    def alejar(self, ancla: Ancla = None) -> None:
        self._cambiar(self.factor / ZOOM_PASO, ancla)

    def ajustar(self) -> None:
        self.auto = True
        self._al_ajustar()

    def _cambiar(self, nuevo: float, ancla: Ancla) -> None:
        nuevo = max(ZOOM_MIN, min(ZOOM_MAX, nuevo))
        if abs(nuevo - self.factor) < 1e-6:
            return
        self.auto = False
        self.factor = nuevo
        self._al_cambiar(ancla)

    def _on_rueda(self, controlador: Gtk.EventControllerScroll, _dx: float, dy: float) -> bool:
        if not (controlador.get_current_event_state() & Gdk.ModifierType.CONTROL_MASK):
            return False  # sin Ctrl, el scroll desplaza con normalidad
        if dy < 0:
            self.acercar(self._puntero)
        elif dy > 0:
            self.alejar(self._puntero)
        return True


def factor_de_ajuste(ancho_vista: float, alto_vista: float, ancho: float, alto: float) -> float:
    """Zoom con el que un contenido de `ancho`×`alto` cabe entero en la vista."""
    if min(ancho_vista, alto_vista, ancho, alto) <= 0:
        return 1.0
    return max(AJUSTE_MIN, min(AJUSTE_MAX, ancho_vista / ancho, alto_vista / alto))


class Centrador:
    """Posiciona el scroll de un `Gtk.ScrolledWindow` cuando el contenido ya tiene su nuevo
    tamaño. Un punto del contenido se identifica por su fracción del total (así sobrevive al
    cambio de escala) y por dónde debe quedar en la vista: `None` = centro."""

    def __init__(self, scroller: Gtk.ScrolledWindow) -> None:
        self._scroller = scroller
        self._h = scroller.get_hadjustment()
        self._v = scroller.get_vadjustment()
        self._pendiente: tuple[float | None, float | None, float | None, float | None] | None = None
        for adj in (self._h, self._v):
            adj.connect("changed", lambda _a: self._aplicar())

    def capturar(self, ancla: Ancla) -> tuple[float, float, float | None, float | None]:
        """Fracciones del contenido bajo `ancla` (o bajo el centro) y su posición en la vista."""

        def fraccion(adj: Gtk.Adjustment, pos: float | None) -> tuple[float, float | None]:
            desplazamiento = adj.get_page_size() / 2 if pos is None else pos
            if adj.get_upper() <= 0:
                return 0.5, pos
            return (adj.get_value() + desplazamiento) / adj.get_upper(), pos

        fx, ox = fraccion(self._h, ancla[0] if ancla else None)
        fy, oy = fraccion(self._v, ancla[1] if ancla else None)
        return fx, fy, ox, oy

    def pedir(
        self,
        fx: float | None = 0.5,
        fy: float | None = 0.5,
        ox: float | None = None,
        oy: float | None = None,
    ) -> None:
        """`fx`/`fy` = None deja ese eje donde está."""
        self._pendiente = (fx, fy, ox, oy)
        GLib.idle_add(self._aplicar)

    def _aplicar(self) -> bool:
        if self._pendiente is None or self._h.get_page_size() <= 0:
            return False  # aún sin asignar: lo reintenta el próximo «changed»
        fx, fy, ox, oy = self._pendiente
        if fx is not None:
            self._poner(self._h, fx, ox)
        if fy is not None:
            self._poner(self._v, fy, oy)
        self._pendiente = None
        return False

    @staticmethod
    def _poner(adj: Gtk.Adjustment, fraccion: float, pos: float | None) -> None:
        desplazamiento = adj.get_page_size() / 2 if pos is None else pos
        maximo = max(0.0, adj.get_upper() - adj.get_page_size())
        adj.set_value(max(0.0, min(maximo, fraccion * adj.get_upper() - desplazamiento)))

    def al_cambiar_vista(self, callback: Callable[[], None]) -> None:
        """Avisa cuando cambia el tamaño visible (p. ej. al redimensionar la ventana)."""
        for adj in (self._h, self._v):
            adj.connect("notify::page-size", lambda *_a: callback())
