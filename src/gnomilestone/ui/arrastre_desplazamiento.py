"""Arrastrar con el ratón para desplazar el calendario (Gantt y Uso), como en GitHub."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk


def instalar_arrastre(scroller: Gtk.ScrolledWindow, *, vertical: bool = True) -> None:
    """Pulsar y arrastrar sobre `scroller` mueve su contenido (la mano agarra el calendario).

    El gesto va en el ScrolledWindow y no en el lienzo: así sus coordenadas no se mueven al
    desplazar (en el lienzo, el propio scroll cambiaría el desplazamiento medido y la vista
    temblaría). Quien tenga elementos arrastrables dentro (las barras del Gantt) debe
    reclamar la secuencia (`CLAIMED`) al moverse (no al pulsar: cancelaría el doble clic);
    así este gesto, que va en la fase de burbuja del contenedor, solo actúa sobre el fondo.
    """
    gesto = Gtk.GestureDrag(button=1)
    origen = {"h": 0.0, "v": 0.0}

    def _empezar(_g: Gtk.GestureDrag, _x: float, _y: float) -> None:
        origen["h"] = scroller.get_hadjustment().get_value()
        origen["v"] = scroller.get_vadjustment().get_value()

    def _mover(_g: Gtk.GestureDrag, dx: float, dy: float) -> None:
        scroller.set_cursor_from_name("grabbing")
        scroller.get_hadjustment().set_value(origen["h"] - dx)
        if vertical:
            scroller.get_vadjustment().set_value(origen["v"] - dy)

    def _terminar(_g: Gtk.GestureDrag, _dx: float, _dy: float) -> None:
        scroller.set_cursor_from_name(None)

    gesto.connect("drag-begin", _empezar)
    gesto.connect("drag-update", _mover)
    gesto.connect("drag-end", _terminar)
    scroller.add_controller(gesto)
