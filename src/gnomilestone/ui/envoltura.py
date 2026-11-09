"""Contenedor que coloca sus hijos en fila, uno tras otro con su ancho natural, y salta de
línea solo cuando no caben (a diferencia de `Gtk.FlowBox`, que reparte el espacio sobrante
entre columnas iguales y deja huecos enormes entre elementos de distinto ancho)."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, Gtk


class _Envoltura(Gtk.LayoutManager):
    def __init__(self, espacio: int, espacio_vertical: int) -> None:
        super().__init__()
        self._espacio = espacio
        self._espacio_vertical = espacio_vertical

    @staticmethod
    def _hijos(widget: Gtk.Widget) -> list[Gtk.Widget]:
        hijos = []
        hijo = widget.get_first_child()
        while hijo is not None:
            if hijo.should_layout():
                hijos.append(hijo)
            hijo = hijo.get_next_sibling()
        return hijos

    def _filas(self, hijos: list[Gtk.Widget], ancho: int) -> list[list[tuple[Gtk.Widget, int]]]:
        """Reparte los hijos en filas que caben en `ancho` (cada uno con su ancho natural)."""
        filas: list[list[tuple[Gtk.Widget, int]]] = [[]]
        usado = 0
        for hijo in hijos:
            natural = hijo.measure(Gtk.Orientation.HORIZONTAL, -1)[1]
            necesario = natural + (self._espacio if filas[-1] else 0)
            if filas[-1] and usado + necesario > ancho:
                filas.append([])
                usado = 0
                necesario = natural
            filas[-1].append((hijo, min(natural, ancho) if ancho > 0 else natural))
            usado += necesario
        return filas

    def do_get_request_mode(self, widget: Gtk.Widget) -> Gtk.SizeRequestMode:
        return Gtk.SizeRequestMode.HEIGHT_FOR_WIDTH

    def do_measure(
        self, widget: Gtk.Widget, orientation: Gtk.Orientation, for_size: int
    ) -> tuple[int, int, int, int]:
        hijos = self._hijos(widget)
        if not hijos:
            return 0, 0, -1, -1
        if orientation == Gtk.Orientation.HORIZONTAL:
            minimo = max(h.measure(Gtk.Orientation.HORIZONTAL, -1)[0] for h in hijos)
            natural = sum(h.measure(Gtk.Orientation.HORIZONTAL, -1)[1] for h in hijos)
            natural += self._espacio * (len(hijos) - 1)
            return minimo, natural, -1, -1
        ancho = for_size if for_size >= 0 else 10**6
        alto = 0
        for i, fila in enumerate(self._filas(hijos, ancho)):
            alto += max(h.measure(Gtk.Orientation.VERTICAL, w)[1] for h, w in fila)
            alto += self._espacio_vertical if i else 0
        return alto, alto, -1, -1

    def do_allocate(self, widget: Gtk.Widget, width: int, height: int, baseline: int) -> None:
        y = 0
        for i, fila in enumerate(self._filas(self._hijos(widget), width)):
            if i:
                y += self._espacio_vertical
            alto_fila = max(h.measure(Gtk.Orientation.VERTICAL, w)[1] for h, w in fila)
            x = 0
            for hijo, ancho in fila:
                rect = Gdk.Rectangle()
                rect.x, rect.y, rect.width, rect.height = x, y, ancho, alto_fila
                hijo.size_allocate(rect, -1)
                x += ancho + self._espacio
            y += alto_fila


def crear_envoltura(espacio: int = 6, espacio_vertical: int = 4) -> Gtk.Box:
    """Caja que dispone sus hijos en línea y salta de renglón al llegar al borde."""
    caja = Gtk.Box()
    caja.set_layout_manager(_Envoltura(espacio, espacio_vertical))
    return caja


def vaciar(caja: Gtk.Widget) -> None:
    while (hijo := caja.get_first_child()) is not None:
        caja.remove(hijo)
