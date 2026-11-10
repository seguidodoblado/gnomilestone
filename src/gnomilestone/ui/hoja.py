"""Aspecto de «suite ofimática» para las notas: una página tipo A4 centrada, con sombra,
sobre un escritorio gris.

La página no crece con la ventana: al maximizar solo se centra, y el zoom (botones y
Ctrl+rueda) cambia su ancho. En ventanas más estrechas que la página se encoge para no
desbordar. El color de página y de escritorio sale del tema, así que sirve en claro y oscuro.
"""

from __future__ import annotations

from collections.abc import Callable

import gi

gi.require_version("Gdk", "4.0")
gi.require_version("Gtk", "4.0")
from gi.repository import Gdk, Gtk

from gnomilestone.i18n import _

ANCHO_A4 = 794  # px de un A4 a 96 ppp; el zoom 1,0 equivale a este ancho
PROPORCION_A4 = 297 / 210
MARGEN_ESCRITORIO = 28  # hueco mínimo entre la página y el borde de la ventana
ZOOM_MIN = 0.6
ZOOM_MAX = 1.6
ZOOM_PASO = 1.1

_CSS = """
.gnomilestone-escritorio { background-color: shade(@theme_bg_color, 0.8); }
.gnomilestone-hoja {
    background-color: @theme_base_color;
    border-radius: 3px;
    padding: 56px 72px;
    box-shadow: 0 1px 2px alpha(black, 0.35), 0 10px 28px alpha(black, 0.28);
}
.gnomilestone-hoja textview,
.gnomilestone-hoja textview text { background-color: transparent; }
"""
_proveedor: Gtk.CssProvider | None = None


def _aplicar_css() -> None:
    global _proveedor
    if _proveedor is not None:
        return
    _proveedor = Gtk.CssProvider()
    _proveedor.load_from_string(_CSS)
    Gtk.StyleContext.add_provider_for_display(
        Gdk.Display.get_default(), _proveedor, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
    )


class ZoomHoja:
    """Factor de zoom compartido por las páginas que deban moverse juntas."""

    def __init__(self) -> None:
        self.factor = 1.0
        self._oyentes: list[Callable[[], None]] = []

    def conectar(self, callback: Callable[[], None]) -> None:
        self._oyentes.append(callback)

    def fijar(self, factor: float) -> None:
        factor = min(ZOOM_MAX, max(ZOOM_MIN, factor))
        if abs(factor - self.factor) < 1e-6:
            return
        self.factor = factor
        for callback in self._oyentes:
            callback()

    def acercar(self) -> None:
        self.fijar(self.factor * ZOOM_PASO)

    def alejar(self) -> None:
        self.fijar(self.factor / ZOOM_PASO)

    def botones(self) -> Gtk.Box:
        """Alejar / Restablecer / Acercar, con el ancho de página actual."""
        caja = Gtk.Box(spacing=4)
        caja.add_css_class("linked")
        for icono, tooltip, accion in (
            ("zoom-out-symbolic", _("Alejar (Ctrl+rueda)"), self.alejar),
            ("zoom-original-symbolic", _("Tamaño original"), lambda: self.fijar(1.0)),
            ("zoom-in-symbolic", _("Acercar (Ctrl+rueda)"), self.acercar),
        ):
            boton = Gtk.Button(icon_name=icono, tooltip_text=tooltip)
            boton.connect("clicked", lambda _b, a=accion: a())
            caja.append(boton)
        return caja


class HojaPagina(Gtk.ScrolledWindow):
    """Escritorio gris con una página centrada. `hoja` es el contenedor de la página:
    se le añade el contenido.

    Con `desplazable=True` (lectura) la página tiene altura mínima de A4 y crece con el
    contenido; el escritorio se desplaza en vertical. Con `False` (edición) la página
    ocupa el alto de la ventana y es su contenido el que se desplaza.
    """

    def __init__(self, zoom: ZoomHoja, desplazable: bool = True) -> None:
        _aplicar_css()
        super().__init__(
            hexpand=True,
            vexpand=True,
            hscrollbar_policy=Gtk.PolicyType.NEVER,
            vscrollbar_policy=Gtk.PolicyType.AUTOMATIC if desplazable else Gtk.PolicyType.NEVER,
        )
        self._zoom = zoom
        self._desplazable = desplazable
        self._ancho_aplicado: int | None = None
        self.hoja = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.hoja.add_css_class("gnomilestone-hoja")
        # hexpand: en una caja horizontal solo un hijo que se expande recibe el espacio
        # sobrante, y es dentro de él donde halign=CENTER deja la página en el medio.
        self.hoja.set_hexpand(True)
        self.hoja.set_halign(Gtk.Align.CENTER)
        self.hoja.set_valign(Gtk.Align.START if desplazable else Gtk.Align.FILL)
        self.hoja.set_vexpand(not desplazable)
        self.escritorio = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True, vexpand=True)
        self.escritorio.add_css_class("gnomilestone-escritorio")
        for lado in ("top", "bottom", "start", "end"):
            getattr(self.escritorio, f"set_margin_{lado}")(0)
        self.escritorio.set_spacing(0)
        envoltorio = Gtk.Box(hexpand=True, vexpand=True)
        envoltorio.set_margin_top(MARGEN_ESCRITORIO)
        envoltorio.set_margin_bottom(MARGEN_ESCRITORIO)
        envoltorio.append(self.hoja)
        self.escritorio.append(envoltorio)
        self.set_child(self.escritorio)

        # El ancho útil sale del ajuste horizontal (su «page size» es el ancho visible),
        # no de un callback por fotograma, que mantendría la CPU ocupada.
        self.get_hadjustment().connect("notify::page-size", lambda *_a: self._ajustar())
        zoom.conectar(self._ajustar)

        rueda = Gtk.EventControllerScroll(flags=Gtk.EventControllerScrollFlags.VERTICAL)
        rueda.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        rueda.connect("scroll", self._on_rueda)
        self.add_controller(rueda)

    def _ajustar(self) -> None:
        disponible = int(self.get_hadjustment().get_page_size())
        if disponible <= 0:
            return
        ancho = max(300, min(round(ANCHO_A4 * self._zoom.factor), disponible - 2 * MARGEN_ESCRITORIO))
        clave = ancho
        if clave == self._ancho_aplicado:
            return
        self._ancho_aplicado = clave
        alto = round(ancho * PROPORCION_A4) if self._desplazable else -1
        self.hoja.set_size_request(ancho, alto)

    def _on_rueda(self, controlador: Gtk.EventControllerScroll, _dx: float, dy: float) -> bool:
        if not controlador.get_current_event_state() & Gdk.ModifierType.CONTROL_MASK:
            return False  # sin Ctrl, el desplazamiento normal
        if dy < 0:
            self._zoom.acercar()
        elif dy > 0:
            self._zoom.alejar()
        return True
