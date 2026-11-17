from __future__ import annotations

from collections.abc import Callable

import gi

gi.require_version("Gdk", "4.0")
gi.require_version("Gtk", "4.0")
from gi.repository import Gdk, GLib, Gtk, Pango

from gnomilestone.codigo import Codigo, Separador, Tabla, Texto, dividir_bloques
from gnomilestone.i18n import _
from gnomilestone.markdown_imagenes import SegmentoImagenes, segmentar
from gnomilestone.markdown_pango import ENLACE_TAREA, en_linea, markdown_a_pango
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
        # Las casillas de tarea son enlaces, pero se ven como el texto, sin subrayar.
        ".gnomilestone-tareas link { text-decoration: none; color: @theme_fg_color; }\n"
        ".gnomilestone-tabla-marco { border: 1px solid alpha(@theme_fg_color, 0.25);"
        " border-radius: 6px; }\n"
        ".gnomilestone-tabla-celda { padding: 5px 10px;"
        " border-right: 1px solid alpha(@theme_fg_color, 0.12);"
        " border-bottom: 1px solid alpha(@theme_fg_color, 0.12); }\n"
        ".gnomilestone-tabla-cabecera { background-color: alpha(@theme_fg_color, 0.10); }\n"
        ".gnomilestone-tabla-par { background-color: alpha(@theme_fg_color, 0.04); }\n"
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
        al_marcar: Callable[[int], None] | None = None,
    ) -> None:
        """Con `al_marcar(n)` las casillas de las tareas se pueden pulsar (n es su número de
        orden en el texto). `compacto` (para las tarjetas): bloques de código reducidos, textos de pocas líneas
        y nada seleccionable, para que el doble clic llegue a la tarjeta."""
        super().__init__(
            orientation=Gtk.Orientation.VERTICAL, spacing=6 if compacto else 12, hexpand=True
        )
        self._compacto = compacto
        _asegurar_css()
        self._texto_vacio = texto_vacio
        self._al_enlace = al_enlace
        self._preprocesar = preprocesar
        self._al_marcar = None if compacto else al_marcar

    def fijar(self, markdown: str) -> None:
        self.fijar_bloques(dividir_bloques(markdown))

    def fijar_bloques(self, bloques: list[Texto | Codigo | Separador | Tabla]) -> None:
        hijo = self.get_first_child()
        while hijo is not None:
            siguiente = hijo.get_next_sibling()
            self.remove(hijo)
            hijo = siguiente
        if not bloques:
            self.append(self._etiqueta(f"<i>{GLib.markup_escape_text(self._texto_vacio)}</i>", True))
            return
        tareas = [0] if self._al_marcar is not None else None
        for bloque in bloques:
            if isinstance(bloque, Separador):
                linea = Gtk.Box(hexpand=True)
                linea.add_css_class("gnomilestone-linea")
                self.append(linea)
            elif isinstance(bloque, Tabla):
                self.append(self._widget_tabla(bloque))
            elif isinstance(bloque, Codigo):
                self.append(self._widget_codigo(bloque))
            else:
                texto = self._preprocesar(bloque.markdown) if self._preprocesar else bloque.markdown
                for segmento in segmentar(texto):
                    if isinstance(segmento, SegmentoImagenes):
                        self.append(FilaImagenes(segmento.imagenes, self._al_enlace, self._compacto))
                    else:
                        self.append(self._etiqueta(markdown_a_pango(segmento.markdown, tareas), False))

    def _widget_tabla(self, tabla: Tabla) -> Gtk.Widget:
        """Una tabla como `Gtk.Grid` con scroll horizontal; la cabecera va en negrita."""
        rejilla = Gtk.Grid(column_spacing=0, row_spacing=0)
        rejilla.add_css_class("gnomilestone-tabla")
        xalign = {"left": 0.0, "center": 0.5, "right": 1.0}
        justificacion = {
            "left": Gtk.Justification.LEFT,
            "center": Gtk.Justification.CENTER,
            "right": Gtk.Justification.RIGHT,
        }
        filas = [tabla.cabecera, *tabla.filas]
        for y, fila in enumerate(filas):
            for x, celda in enumerate(fila):
                texto = self._preprocesar(celda) if self._preprocesar else celda
                marcado = en_linea(texto)
                if y == 0:
                    marcado = f"<b>{marcado}</b>"
                etiqueta = Gtk.Label(
                    xalign=xalign[tabla.alineaciones[x]],
                    justify=justificacion[tabla.alineaciones[x]],
                    use_markup=True, selectable=not self._compacto, hexpand=True,
                )
                etiqueta.set_focusable(False)
                if self._al_enlace is not None:
                    etiqueta.connect("activate-link", lambda _l, uri: self._al_enlace(uri))
                etiqueta.set_markup(marcado)
                caja = Gtk.Box(hexpand=True)
                caja.add_css_class("gnomilestone-tabla-celda")
                if y == 0:
                    caja.add_css_class("gnomilestone-tabla-cabecera")
                elif y % 2 == 0:
                    caja.add_css_class("gnomilestone-tabla-par")
                caja.append(etiqueta)
                rejilla.attach(caja, x, y, 1, 1)
        desplazable = Gtk.ScrolledWindow(
            hscrollbar_policy=Gtk.PolicyType.AUTOMATIC,
            vscrollbar_policy=Gtk.PolicyType.NEVER,
            propagate_natural_height=True, hexpand=True, valign=Gtk.Align.START,
        )
        marco = Gtk.Box(hexpand=True, valign=Gtk.Align.START)
        marco.add_css_class("gnomilestone-tabla-marco")
        marco.append(rejilla)
        desplazable.set_child(marco)
        return desplazable

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

    def _on_enlace_etiqueta(self, _etiqueta: Gtk.Label, uri: str) -> bool:
        if uri.startswith(ENLACE_TAREA) and self._al_marcar is not None:
            self._al_marcar(int(uri[len(ENLACE_TAREA):]))
            return True
        return self._al_enlace(uri) if self._al_enlace is not None else False

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
        if self._al_enlace is not None or self._al_marcar is not None:
            etiqueta.connect("activate-link", self._on_enlace_etiqueta)
        etiqueta.set_markup(marcado)
        if self._al_marcar is not None and ENLACE_TAREA in marcado:
            etiqueta.add_css_class("gnomilestone-tareas")
        if atenuada:
            etiqueta.add_css_class("dim-label")
        return etiqueta
