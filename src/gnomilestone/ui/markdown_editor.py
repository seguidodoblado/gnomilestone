"""Editor Markdown con barra de formato y alternancia Editar/Vista previa.

Lo usan la descripción de tarea y las notas de documentación del proyecto.
"""

from __future__ import annotations

from collections.abc import Callable

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import GLib, Gtk

from gnomilestone.i18n import _
from gnomilestone.markdown_pango import markdown_a_pango
from gnomilestone.ui import markdown_edicion


class MarkdownEditor(Gtk.Box):
    def __init__(
        self,
        titulo: str,
        texto: str = "",
        texto_vacio: str = "",
        alto_minimo: int = 130,
    ) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self._texto_vacio = texto_vacio

        cabecera = Gtk.Box(spacing=6)
        cabecera.append(Gtk.Label(label=titulo, xalign=0, hexpand=True))
        modo_box = Gtk.Box()
        modo_box.add_css_class("linked")
        self._editar_toggle = Gtk.ToggleButton(label=_("Editar"), active=True)
        self._vista_toggle = Gtk.ToggleButton(label=_("Vista previa"), group=self._editar_toggle)
        self._vista_toggle.connect("toggled", self._on_modo)
        modo_box.append(self._editar_toggle)
        modo_box.append(self._vista_toggle)
        cabecera.append(modo_box)
        self.append(cabecera)

        self._buffer = Gtk.TextBuffer(text=texto)
        self._barra = self._crear_barra_formato()
        self.append(self._barra)
        vista_edicion = Gtk.TextView(
            buffer=self._buffer,
            wrap_mode=Gtk.WrapMode.WORD_CHAR,
            top_margin=6,
            bottom_margin=6,
            left_margin=6,
            right_margin=6,
        )
        edicion_scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        edicion_scroller.set_child(vista_edicion)
        self._vista_label = Gtk.Label(
            xalign=0, yalign=0, wrap=True, selectable=True, use_markup=True, margin_top=6,
            margin_bottom=6, margin_start=6, margin_end=6,
        )
        vista_scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        vista_scroller.set_child(self._vista_label)
        self._stack = Gtk.Stack()
        self._stack.add_named(edicion_scroller, "editar")
        self._stack.add_named(vista_scroller, "vista")
        self._stack.set_size_request(-1, alto_minimo)
        self._stack.set_vexpand(True)  # crece al maximizar la ventana
        self._stack.add_css_class("card")  # mismo marco visual que un Entry/SpinButton
        self.append(self._stack)

    # -- API ---------------------------------------------------------------

    def obtener_texto(self) -> str:
        inicio, fin = self._buffer.get_bounds()
        return self._buffer.get_text(inicio, fin, False)

    def fijar_texto(self, texto: str) -> None:
        """Sustituye el contenido y vuelve al modo de edición."""
        self._buffer.set_text(texto)
        self._editar_toggle.set_active(True)

    def al_cambiar(self, callback: Callable[[], None]) -> None:
        self._buffer.connect("changed", lambda _b: callback())

    # -- Interacción -------------------------------------------------------

    def _on_modo(self, boton: Gtk.ToggleButton) -> None:
        if boton.get_active():
            texto = self.obtener_texto()
            if texto.strip():
                self._vista_label.set_markup(markdown_a_pango(texto))
            else:
                self._vista_label.set_markup(
                    f"<i>{GLib.markup_escape_text(self._texto_vacio)}</i>"
                )
            self._stack.set_visible_child_name("vista")
            self._barra.set_visible(False)
        else:
            self._stack.set_visible_child_name("editar")
            self._barra.set_visible(True)

    def _crear_barra_formato(self) -> Gtk.Box:
        barra = Gtk.Box(spacing=4)
        botones = (
            ("format-text-bold-symbolic", _("Negrita"), "**", "**", _("texto")),
            ("format-text-italic-symbolic", _("Cursiva"), "*", "*", _("texto")),
            ("format-text-strikethrough-symbolic", _("Tachado"), "~~", "~~", _("texto")),
            ("utilities-terminal-symbolic", _("Código"), "`", "`", _("código")),
            ("insert-link-symbolic", _("Enlace"), "[", "](https://)", _("texto")),
        )
        for icono, tooltip, antes, despues, ejemplo in botones:
            boton = Gtk.Button(icon_name=icono, tooltip_text=tooltip)
            boton.add_css_class("flat")
            boton.connect(
                "clicked",
                lambda _b, a=antes, d=despues, e=ejemplo: markdown_edicion.envolver(
                    self._buffer, a, d, e
                ),
            )
            barra.append(boton)
        barra.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))
        lineas = (
            ("H", _("Título"), "## "),
            ("view-list-bullet-symbolic", _("Lista"), "- "),
            ("view-list-ordered-symbolic", _("Lista numerada"), "1. "),
            ("selection-mode-symbolic", _("Lista de tareas"), "- [ ] "),
            ("format-indent-more-symbolic", _("Cita"), "> "),
        )
        for icono, tooltip, prefijo in lineas:
            if icono == "H":  # no hay icono simbólico de título fiable en todos los temas
                boton = Gtk.Button(tooltip_text=tooltip)
                boton.set_child(Gtk.Label(label="<b>H</b>", use_markup=True))
            else:
                boton = Gtk.Button(icon_name=icono, tooltip_text=tooltip)
            boton.add_css_class("flat")
            boton.connect(
                "clicked",
                lambda _b, p=prefijo: markdown_edicion.prefijar_lineas(self._buffer, p),
            )
            barra.append(boton)
        return barra
