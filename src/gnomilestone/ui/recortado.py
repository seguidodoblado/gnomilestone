from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk


class _DisposicionAltoFijo(Gtk.LayoutManager):
    """Mide siempre el alto fijo y le da al hijo su altura natural (el sobrante se recorta)."""

    def __init__(self, alto: int) -> None:
        super().__init__()
        self._alto = alto

    def do_measure(self, widget: Gtk.Widget, orientation: Gtk.Orientation, for_size: int):
        hijo = widget.get_first_child()
        minimo, natural = (0, 0)
        if hijo is not None:
            minimo, natural, _base_min, _base_nat = hijo.measure(orientation, for_size)
        if orientation == Gtk.Orientation.VERTICAL:
            return self._alto, self._alto, -1, -1
        return minimo, natural, -1, -1

    def do_allocate(self, widget: Gtk.Widget, ancho: int, alto: int, linea_base: int) -> None:
        hijo = widget.get_first_child()
        if hijo is not None:
            natural = hijo.measure(Gtk.Orientation.VERTICAL, ancho)[1]
            hijo.allocate(ancho, max(natural, alto), linea_base, None)


class AlturaFija(Gtk.Box):
    """Contenedor de altura fija con un hijo: lo que no cabe se recorta por abajo en vez de
    estirar la tarjeta. Sirve para que las tarjetas de nota midan lo mismo aunque una tenga
    mucho contenido. Es un `Gtk.Box` con otro gestor de layout (así GTK se encarga de
    liberar al hijo; un `Gtk.Widget` propio dejaba el hijo huérfano al destruirse)."""

    def __init__(self, alto: int, hijo: Gtk.Widget) -> None:
        super().__init__()
        self.set_layout_manager(_DisposicionAltoFijo(alto))
        self.set_overflow(Gtk.Overflow.HIDDEN)
        self.append(hijo)
