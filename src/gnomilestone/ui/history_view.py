from __future__ import annotations

from datetime import date

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gdk, Gtk, Pango

from gnomilestone.i18n import _
from gnomilestone.models import Tarea
from gnomilestone.ui.zoom import Centrador, Zoom, factor_de_ajuste

_proveedor: Gtk.CssProvider | None = None


def _aplicar_css(z: float) -> None:
    """(Re)carga el CSS con las medidas escaladas por el zoom."""
    global _proveedor
    if _proveedor is None:
        _proveedor = Gtk.CssProvider()
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), _proveedor, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

    def px(valor: float) -> int:
        return max(1, round(valor * z))

    _proveedor.load_from_string(
        f".gnomilestone-hist-linea {{ min-width: {px(4)}px; background-image: linear-gradient("
        "to bottom, alpha(#5fb67d, 0.15), alpha(#5fb67d, 0.55), alpha(#5fb67d, 0.15));"
        " border-radius: 2px; }\n"
        f".gnomilestone-hist-nodo {{ min-width: {px(22)}px; min-height: {px(22)}px;"
        " border-radius: 999px; background-image: linear-gradient(to bottom, #8be0a6, #2f7f4f);"
        f" box-shadow: 0 0 0 {px(4)}px alpha(#5fb67d, 0.28); }}\n"
        ".gnomilestone-hist-tarjeta { background-image: linear-gradient(to bottom, #6cc78a,"
        f" #2f7f4f); color: #0e2417; border-radius: {px(14)}px; padding: {px(12)}px {px(16)}px;"
        " box-shadow: 0 2px 8px alpha(black, 0.35); }\n"
        f".gnomilestone-hist-dia {{ font-size: {px(18)}px; font-weight: 800; }}\n"
        f".gnomilestone-hist-anio {{ font-size: {px(11)}px; font-weight: 700; opacity: 0.7; }}\n"
        ".gnomilestone-hist-chip { background-color: alpha(black, 0.22); color: white;"
        f" border-radius: 999px; padding: 2px {px(10)}px; font-size: {px(11)}px;"
        " font-weight: 700; }\n"
        ".gnomilestone-hist-tarea { background-color: alpha(white, 0.28);"
        f" border-radius: {px(10)}px; padding: {px(4)}px {px(10)}px; font-size: {px(13)}px; }}\n"
    )


class HistorialView(Gtk.Box):
    """Historial de lo realizado como línea de tiempo vertical: una espina central con un
    nodo por día y, alternando a izquierda y derecha, una tarjeta con las tareas que se
    completaron ese día (de lo más antiguo, arriba, a lo más reciente, abajo). Zoom con botones o Ctrl+rueda; al abrirse
    queda centrada horizontalmente."""

    def __init__(self) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6, hexpand=True, vexpand=True)
        self._historial: list[tuple[str, list[Tarea]]] = []
        self._ajustando = False
        self._zoom = Zoom(self._on_zoom, self._ajustar)
        _aplicar_css(1.0)
        self.append(self._zoom.botones())
        self._cuadricula = Gtk.Grid(column_spacing=0, row_spacing=0, halign=Gtk.Align.CENTER)
        for margen in ("top", "bottom", "start", "end"):
            getattr(self._cuadricula, f"set_margin_{margen}")(16)
        self._scroller = Gtk.ScrolledWindow(hexpand=True, vexpand=True)
        self._scroller.set_child(self._cuadricula)
        self.append(self._scroller)
        self._zoom.conectar_rueda(self._scroller)
        self._centrador = Centrador(self._scroller)
        self._centrador.al_cambiar_vista(self._ajustar_si_auto)

    def set_datos(self, historial: list[tuple[str, list[Tarea]]]) -> None:
        self._historial = historial
        self._zoom.auto = True
        self._ajustar()

    def _ajustar(self) -> None:
        """Zoom con el que se ve todo el historial, centrado."""
        ancho = self._scroller.get_hadjustment().get_page_size()
        alto = self._scroller.get_vadjustment().get_page_size()
        if ancho > 0 and alto > 0:
            # Se mide el contenido a escala 1 para saber cuánto ocupa de verdad.
            self._aplicar(1.0)
            ancho_nat = self._cuadricula.measure(Gtk.Orientation.HORIZONTAL, -1)[1]
            alto_nat = self._cuadricula.measure(Gtk.Orientation.VERTICAL, ancho_nat)[1]
            self._zoom.factor = factor_de_ajuste(ancho, alto, ancho_nat, alto_nat)
        self._aplicar(self._zoom.factor)
        self._centrador.pedir(0.5, None)  # centrado en horizontal; arriba lo más antiguo

    def _ajustar_si_auto(self) -> None:
        # Un reajuste puede mover el tamaño visible: no se re-entra mientras se aplica.
        if self._zoom.auto and not self._ajustando:
            self._ajustando = True
            try:
                self._ajustar()
            finally:
                self._ajustando = False

    def _aplicar(self, factor: float) -> None:
        _aplicar_css(factor)
        self._reconstruir(factor)

    def _on_zoom(self, ancla) -> None:
        fx, fy, ox, oy = self._centrador.capturar(ancla)
        self._aplicar(self._zoom.factor)
        self._centrador.pedir(fx, fy, ox, oy)

    def _reconstruir(self, z: float) -> None:
        hijo = self._cuadricula.get_first_child()
        while hijo is not None:
            siguiente = hijo.get_next_sibling()
            self._cuadricula.remove(hijo)
            hijo = siguiente
        historial = self._historial
        if not historial:
            vacio = Gtk.Label(label=_("Aún no hay tareas completadas."), xalign=0)
            vacio.add_css_class("dim-label")
            self._cuadricula.attach(vacio, 0, 0, 3, 1)
            return
        for fila, (dia, tareas) in enumerate(historial):
            izquierda = fila % 2 == 0
            tarjeta = self._tarjeta(dia, tareas, z)
            tarjeta.set_halign(Gtk.Align.END if izquierda else Gtk.Align.START)
            tarjeta.set_margin_bottom(round(18 * z))
            self._cuadricula.attach(tarjeta, 0 if izquierda else 2, fila, 1, 1)
            self._cuadricula.attach(self._espina(z), 1, fila, 1, 1)

    @staticmethod
    def _espina(z: float) -> Gtk.Widget:
        caja = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            halign=Gtk.Align.CENTER,
            margin_start=round(20 * z),
            margin_end=round(20 * z),
        )
        nodo = Gtk.Box(halign=Gtk.Align.CENTER, margin_top=round(14 * z))
        nodo.add_css_class("gnomilestone-hist-nodo")
        linea = Gtk.Box(halign=Gtk.Align.CENTER, vexpand=True)
        linea.add_css_class("gnomilestone-hist-linea")
        caja.append(nodo)
        caja.append(linea)
        return caja

    @staticmethod
    def _tarjeta(dia: str, tareas: list[Tarea], z: float) -> Gtk.Widget:
        try:
            d = date.fromisoformat(dia)
            titulo = f"{d.day} {d.strftime('%b').upper()}"
            anio = str(d.year)
        except ValueError:
            titulo, anio = _("Sin fecha"), ""
        cabecera = Gtk.Box(spacing=10)
        izq = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True)
        etiqueta_dia = Gtk.Label(label=titulo, xalign=0)
        etiqueta_dia.add_css_class("gnomilestone-hist-dia")
        izq.append(etiqueta_dia)
        if anio:
            etiqueta_anio = Gtk.Label(label=anio, xalign=0)
            etiqueta_anio.add_css_class("gnomilestone-hist-anio")
            izq.append(etiqueta_anio)
        cabecera.append(izq)
        chip = Gtk.Label(
            label=_("{n} completadas").format(n=len(tareas)), valign=Gtk.Align.CENTER
        )
        chip.add_css_class("gnomilestone-hist-chip")
        cabecera.append(chip)

        tarjeta = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=round(8 * z), width_request=round(320 * z))
        tarjeta.add_css_class("gnomilestone-hist-tarjeta")
        tarjeta.append(cabecera)
        for tarea in tareas:
            fila = Gtk.Label(
                label=f"✓  {tarea.titulo}",
                xalign=0,
                ellipsize=Pango.EllipsizeMode.END,
            )
            fila.add_css_class("gnomilestone-hist-tarea")
            tarjeta.append(fila)
        return tarjeta
