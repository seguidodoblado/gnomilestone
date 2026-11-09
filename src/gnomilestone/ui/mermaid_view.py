from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import GLib, Gtk

from gnomilestone.codigo import Codigo
from gnomilestone.diagrama import Diagrama
from gnomilestone.i18n import _
from gnomilestone.ui.code_block import _asegurar_css, cuerpo_de_codigo
from gnomilestone.ui.diagram_canvas import MiniaturaDiagrama, pintar_diagrama

_MARGEN = 20  # alrededor del diagrama, en unidades del lienzo


class _Dibujo(Gtk.DrawingArea):
    """El diagrama dibujado a la escala que cabe (y, como mucho, a tamaño natural)."""

    def __init__(self, diagrama: Diagrama) -> None:
        super().__init__(hexpand=True)
        minx, miny, maxx, maxy = diagrama.limites() or (0.0, 0.0, 1.0, 1.0)
        self._diagrama = diagrama
        self._origen = (minx - _MARGEN, miny - _MARGEN)
        self.ancho = maxx - minx + 2 * _MARGEN
        self.alto = maxy - miny + 2 * _MARGEN
        self.set_content_width(int(self.ancho))
        self.set_content_height(int(self.alto))
        self.set_draw_func(self._dibujar)

    def _dibujar(self, _area, cr, ancho: int, alto: int) -> None:
        escala = min(ancho / self.ancho, alto / self.alto, 1.0)
        cr.translate((ancho - self.ancho * escala) / 2, (alto - self.alto * escala) / 2)
        cr.scale(escala, escala)
        cr.translate(-self._origen[0], -self._origen[1])
        pintar_diagrama(cr, self, self._diagrama)


class VistaMermaid(Gtk.Box):
    """Bloque ```mermaid``` dibujado como diagrama. En la vista normal lleva cabecera con
    un botón para ver el código fuente y otro para copiarlo; en la tarjeta (`compacto`) es
    solo una miniatura."""

    def __init__(self, bloque: Codigo, diagrama: Diagrama, compacto: bool = False) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        _asegurar_css()
        self.add_css_class("gnomilestone-codigo")
        self._codigo = bloque.codigo

        if compacto:
            miniatura = MiniaturaDiagrama(diagrama, ancho=270, alto=130)
            miniatura.set_margin_top(6)
            miniatura.set_margin_bottom(6)
            self.append(miniatura)
            return

        cabecera = Gtk.Box(spacing=10)
        cabecera.add_css_class("gnomilestone-codigo-cabecera")
        cabecera.append(Gtk.Image.new_from_icon_name("media-playlist-shuffle-symbolic"))
        titulo = Gtk.Label(label="Mermaid", xalign=0)
        titulo.add_css_class("heading")
        cabecera.append(titulo)
        leyenda = Gtk.Label(xalign=0, hexpand=True)
        leyenda.set_markup(f"<i>{GLib.markup_escape_text(bloque.titulo)}</i>")
        leyenda.add_css_class("dim-label")
        cabecera.append(leyenda)
        self._ver_codigo = Gtk.ToggleButton(
            icon_name="utilities-terminal-symbolic", tooltip_text=_("Ver el código del diagrama")
        )
        self._ver_codigo.add_css_class("flat")
        self._ver_codigo.connect("toggled", self._on_alternar)
        cabecera.append(self._ver_codigo)
        copiar = Gtk.Button(icon_name="edit-copy-symbolic", tooltip_text=_("Copiar el código"))
        copiar.add_css_class("flat")
        copiar.connect("clicked", self._on_copiar)
        cabecera.append(copiar)
        self.append(cabecera)

        dibujo = _Dibujo(diagrama)
        marco = Gtk.AspectFrame(
            ratio=dibujo.ancho / dibujo.alto, obey_child=False, xalign=0.5, yalign=0.0,
            halign=Gtk.Align.CENTER, margin_top=8, margin_bottom=8,
        )
        marco.set_child(dibujo)
        self._pila = Gtk.Stack()
        self._pila.add_named(marco, "diagrama")
        self.append(self._pila)

    def _on_alternar(self, boton: Gtk.ToggleButton) -> None:
        # La página del código se construye la primera vez que se pide, no al abrir la nota.
        if boton.get_active() and self._pila.get_child_by_name("codigo") is None:
            self._pila.add_named(cuerpo_de_codigo(Codigo("", "", self._codigo)), "codigo")
        self._pila.set_visible_child_name("codigo" if boton.get_active() else "diagrama")

    def _on_copiar(self, _boton: Gtk.Button) -> None:
        self.get_clipboard().set(self._codigo)
