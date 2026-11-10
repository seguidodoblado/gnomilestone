from __future__ import annotations

from collections.abc import Callable

import gi

gi.require_version("Gdk", "4.0")
gi.require_version("Gtk", "4.0")
from gi.repository import Gdk, GLib, Gtk, Pango

from gnomilestone.codigo import Codigo, Separador, Texto, dividir_bloques
from gnomilestone.i18n import _
from gnomilestone.markdown_imagenes import SegmentoImagenes, segmentar
from gnomilestone.markdown_pango import markdown_a_pango
from gnomilestone.mermaid import MermaidNoSoportado, interpretar
from gnomilestone.ui.code_block import BloqueCodigo
from gnomilestone.ui.fila_imagenes import FilaImagenes
from gnomilestone.ui.mermaid_view import VistaMermaid

_css_aplicado = False


def _asegurar_css() -> None:
    global _css_aplicado
    if _css_aplicado:
        return
    proveedor = Gtk.CssProvider()
    # El `Gtk.Separator` de muchos temas oscuros casi no se ve: la línea se pinta aquí con
    # el color de texto del tema, así se distingue en claro y en oscuro.
    proveedor.load_from_string(
        ".gnomilestone-linea { min-height: 2px; border-radius: 1px;"
        " background-color: alpha(@theme_fg_color, 0.4); margin: 8px 0; }\n"
    )
    Gtk.StyleContext.add_provider_for_display(
        Gdk.Display.get_default(), proveedor, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
    )
    _css_aplicado = True


class VistaMarkdown(Gtk.Box):
    """Muestra Markdown ya formateado: el texto, como etiquetas Pango, y cada bloque de código
    como un `BloqueCodigo` (cabecera, numeración y colores). Se usa en la vista previa del
    editor y en la vista completa de las notas."""

    def __init__(
        self,
        texto_vacio: str = "",
        al_enlace: Callable[[str], bool] | None = None,
        preprocesar: Callable[[str], str] | None = None,
        compacto: bool = False,
    ) -> None:
        """`compacto` (para las tarjetas): bloques de código reducidos, textos de pocas líneas
        y nada seleccionable, para que el doble clic llegue a la tarjeta."""
        super().__init__(
            orientation=Gtk.Orientation.VERTICAL, spacing=6 if compacto else 12, hexpand=True
        )
        self._compacto = compacto
        _asegurar_css()
        self._texto_vacio = texto_vacio
        self._al_enlace = al_enlace
        self._preprocesar = preprocesar

    def fijar(self, markdown: str) -> None:
        self.fijar_bloques(dividir_bloques(markdown))

    def fijar_bloques(self, bloques: list[Texto | Codigo | Separador]) -> None:
        hijo = self.get_first_child()
        while hijo is not None:
            siguiente = hijo.get_next_sibling()
            self.remove(hijo)
            hijo = siguiente
        if not bloques:
            self.append(self._etiqueta(f"<i>{GLib.markup_escape_text(self._texto_vacio)}</i>", True))
            return
        for bloque in bloques:
            if isinstance(bloque, Separador):
                linea = Gtk.Box(hexpand=True)
                linea.add_css_class("gnomilestone-linea")
                self.append(linea)
            elif isinstance(bloque, Codigo):
                self.append(self._widget_codigo(bloque))
            else:
                texto = self._preprocesar(bloque.markdown) if self._preprocesar else bloque.markdown
                for segmento in segmentar(texto):
                    if isinstance(segmento, SegmentoImagenes):
                        self.append(FilaImagenes(segmento.imagenes, self._al_enlace, self._compacto))
                    else:
                        self.append(self._etiqueta(markdown_a_pango(segmento.markdown), False))

    def _widget_codigo(self, bloque: Codigo) -> Gtk.Widget:
        """Un bloque de código; si es Mermaid y lo sabemos dibujar, como diagrama. Si no
        (otro tipo de diagrama, texto inválido), se muestra el código con un aviso."""
        if bloque.lenguaje != "mermaid":
            return BloqueCodigo(bloque, compacto=self._compacto)
        try:
            diagrama = interpretar(bloque.codigo)
        except MermaidNoSoportado:
            diagrama = None
        if diagrama is None or not diagrama.nodos:
            codigo = BloqueCodigo(bloque, compacto=self._compacto)
            if self._compacto:
                return codigo
            aviso = Gtk.Label(
                label=_(
                    "Este tipo de diagrama de Mermaid todavía no se puede dibujar: "
                    "se muestra su código."
                ),
                xalign=0,
                wrap=True,
            )
            aviso.add_css_class("dim-label")
            aviso.add_css_class("caption")
            caja = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            caja.append(codigo)
            caja.append(aviso)
            return caja
        return VistaMermaid(bloque, diagrama, compacto=self._compacto)

    def _etiqueta(self, marcado: str, atenuada: bool) -> Gtk.Label:
        etiqueta = Gtk.Label(
            xalign=0, yalign=0, wrap=True, selectable=not self._compacto, use_markup=True,
            hexpand=True,
        )
        if self._compacto:
            etiqueta.set_lines(4)
            etiqueta.set_ellipsize(Pango.EllipsizeMode.END)
            etiqueta.set_max_width_chars(34)
        etiqueta.set_focusable(False)  # sin esto, al abrir se queda todo el texto seleccionado
        if self._al_enlace is not None:
            etiqueta.connect("activate-link", lambda _l, uri: self._al_enlace(uri))
        etiqueta.set_markup(marcado)
        if atenuada:
            etiqueta.add_css_class("dim-label")
        return etiqueta
