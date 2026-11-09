from __future__ import annotations

from collections.abc import Callable

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import GLib, Gtk, Pango

from gnomilestone.diagrama import Diagrama
from gnomilestone.i18n import _
from gnomilestone.markdown_pango import markdown_a_pango
from gnomilestone.models import VersionDocumentacion
from gnomilestone.ui.diagram_canvas import MiniaturaDiagrama
from gnomilestone.versiones import diferencias, formatear_fecha, hay_cambios, resumen_diagrama


class VersionesWindow(Gtk.Window):
    """Versiones anteriores de una nota o de un diagrama: lista a la izquierda y, a la
    derecha, el contenido de la elegida (en una nota, también lo que cambia respecto al
    contenido actual del editor). «Restaurar» devuelve esa versión al editor, sin guardar:
    se confirma con el «Guardar» de la ventana de edición."""

    def __init__(
        self,
        parent: Gtk.Window | None,
        tipo: str,  # "nota" | "diagrama"
        versiones: list[VersionDocumentacion],
        actual: str,  # contenido actual del editor (Markdown o JSON del diagrama)
        al_restaurar: Callable[[VersionDocumentacion], None],
    ) -> None:
        super().__init__(
            title=_("Versiones anteriores"),
            transient_for=parent,
            modal=True,
            default_width=980,
            default_height=640,
        )
        self._tipo = tipo
        self._versiones = versiones
        self._actual = actual
        self._al_restaurar = al_restaurar
        self._seleccionada: VersionDocumentacion | None = None

        self._lista = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        self._lista.add_css_class("navigation-sidebar")
        for version in versiones:
            self._lista.append(self._fila(version))
        self._lista.connect("row-selected", self._on_fila)
        lista_scroller = Gtk.ScrolledWindow(
            hscrollbar_policy=Gtk.PolicyType.NEVER, width_request=260, vexpand=True
        )
        lista_scroller.set_child(self._lista)

        self._titulo = Gtk.Label(xalign=0, wrap=True)
        self._titulo.add_css_class("title-3")
        self._resumen = Gtk.Label(xalign=0, wrap=True)
        self._resumen.add_css_class("dim-label")
        self._contenido = self._construir_contenido()
        derecha = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, hexpand=True)
        derecha.append(self._titulo)
        derecha.append(self._resumen)
        if tipo == "nota":
            derecha.append(self._construir_modo())
        derecha.append(self._contenido)

        self._restaurar = Gtk.Button(label=_("Restaurar esta versión"))
        self._restaurar.add_css_class("suggested-action")
        self._restaurar.set_sensitive(False)
        self._restaurar.connect("clicked", self._on_restaurar)
        cerrar = Gtk.Button(label=_("Cerrar"))
        cerrar.connect("clicked", lambda _b: self.close())
        botones = Gtk.Box(spacing=8, halign=Gtk.Align.END)
        botones.append(cerrar)
        botones.append(self._restaurar)

        cuerpo = Gtk.Box(spacing=16, vexpand=True)
        cuerpo.append(lista_scroller)
        cuerpo.append(derecha)
        raiz = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        for margen in ("top", "bottom", "start", "end"):
            getattr(raiz, f"set_margin_{margen}")(16)
        raiz.append(cuerpo)
        raiz.append(botones)
        self.set_child(raiz)

        if versiones:
            self._lista.select_row(self._lista.get_row_at_index(0))
        else:
            self._titulo.set_text(_("Aún no hay versiones anteriores."))
            self._resumen.set_text(
                _("Se guarda una versión cada vez que sobrescribes con «Guardar».")
            )

    # -- Construcción ------------------------------------------------------

    def _fila(self, version: VersionDocumentacion) -> Gtk.ListBoxRow:
        caja = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, margin_top=6, margin_bottom=6)
        fecha = Gtk.Label(label=formatear_fecha(version.creado) or _("Sin fecha"), xalign=0)
        fecha.add_css_class("heading")
        titulo = Gtk.Label(
            label=version.titulo or _("Sin título"), xalign=0, ellipsize=Pango.EllipsizeMode.END
        )
        titulo.add_css_class("dim-label")
        caja.append(fecha)
        caja.append(titulo)
        return Gtk.ListBoxRow(child=caja)

    def _construir_modo(self) -> Gtk.Widget:
        modo = Gtk.Box(halign=Gtk.Align.START)
        modo.add_css_class("linked")
        self._ver_contenido = Gtk.ToggleButton(label=_("Contenido"), active=True)
        self._ver_cambios = Gtk.ToggleButton(label=_("Cambios hasta ahora"), group=self._ver_contenido)
        self._ver_contenido.connect("toggled", lambda _b: self._pintar())
        modo.append(self._ver_contenido)
        modo.append(self._ver_cambios)
        return modo

    def _construir_contenido(self) -> Gtk.Widget:
        marco = Gtk.Frame(vexpand=True, hexpand=True)
        if self._tipo == "nota":
            self._texto = Gtk.Label(
                xalign=0, yalign=0, wrap=True, selectable=True, use_markup=True, margin_top=10,
                margin_bottom=10, margin_start=12, margin_end=12,
            )
            self._texto.set_focusable(False)
            scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
            scroller.set_child(self._texto)
            marco.set_child(scroller)
        else:
            self._miniatura_caja = Gtk.Box(hexpand=True, vexpand=True)
            marco.set_child(self._miniatura_caja)
        return marco

    # -- Interacción -------------------------------------------------------

    def _on_fila(self, _lista: Gtk.ListBox, fila: Gtk.ListBoxRow | None) -> None:
        if fila is None:
            return
        self._seleccionada = self._versiones[fila.get_index()]
        self._restaurar.set_sensitive(True)
        self._titulo.set_text(
            f"{formatear_fecha(self._seleccionada.creado)} · {self._seleccionada.titulo or _('Sin título')}"
        )
        self._pintar()

    def _pintar(self) -> None:
        version = self._seleccionada
        if version is None:
            return
        if self._tipo == "diagrama":
            antiguo = Diagrama.de_json(version.contenido)
            self._resumen.set_text(resumen_diagrama(antiguo, Diagrama.de_json(self._actual)))
            hijo = self._miniatura_caja.get_first_child()
            if hijo is not None:
                self._miniatura_caja.remove(hijo)
            self._miniatura_caja.append(MiniaturaDiagrama(antiguo, ancho=520, alto=360))
            return
        diff = diferencias(version.contenido, self._actual)
        self._resumen.set_text(
            _("Hay cambios respecto a esta versión.")
            if hay_cambios(diff)
            else _("Idéntica al contenido actual.")
        )
        if self._ver_cambios.get_active():
            self._texto.set_markup(self._marcado_diff(diff))
        elif version.contenido.strip():
            self._texto.set_markup(markdown_a_pango(version.contenido))
        else:
            self._texto.set_markup(f"<i>{GLib.markup_escape_text(_('Nota sin contenido'))}</i>")

    @staticmethod
    def _marcado_diff(diff: list[tuple[str, str]]) -> str:
        """Líneas con marca: lo quitado en rojo y lo nuevo en verde (fondo translúcido, que
        funciona en tema claro y oscuro)."""
        partes = []
        for marca, linea in diff:
            texto = GLib.markup_escape_text(linea or " ")
            if marca == "-":
                partes.append(f'<span background="#e01b24" bgalpha="30%">− {texto}</span>')
            elif marca == "+":
                partes.append(f'<span background="#26a269" bgalpha="30%">+ {texto}</span>')
            else:
                partes.append(f"  {texto}")
        return "\n".join(partes) or f"<i>{GLib.markup_escape_text(_('Nota sin contenido'))}</i>"

    def _on_restaurar(self, _boton: Gtk.Button) -> None:
        if self._seleccionada is not None:
            self._al_restaurar(self._seleccionada)
        self.close()
