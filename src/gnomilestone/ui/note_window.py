from __future__ import annotations

from collections.abc import Callable

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import GLib, Gtk

from gnomilestone.i18n import _
from gnomilestone.models import ESTADOS_NOTA, NotaDocumentacion, VersionDocumentacion
from gnomilestone.store import Store
from gnomilestone.ui.dialogos import boton_con_icono
from gnomilestone.ui.hoja import ZoomHoja
from gnomilestone.ui.markdown_editor import MarkdownEditor
from gnomilestone.ui.versiones_window import VersionesWindow

# Texto de cada estado de nota (el estado vacío es «sin estado»).
ETIQUETAS_ESTADO = {
    "": _("Sin estado"),
    "borrador": _("Borrador"),
    "vigente": _("Vigente"),
    "obsoleta": _("Obsoleta"),
}


class NoteWindow(Gtk.Window):
    """Ventana independiente para editar una nota de documentación (título y contenido
    Markdown con vista previa). Los cambios solo se aplican con «Guardar»; «Cancelar» (o
    cerrar la ventana) los descarta, avisando antes si hay cambios sin guardar. Una nota con
    `id == 0` es nueva y no se crea en la base de datos hasta que se guarda."""

    def __init__(
        self,
        parent: Gtk.Window | None,
        store: Store,
        nota: NotaDocumentacion,
        al_cambiar: Callable[[], None],
        preprocesar: Callable[[str], str] | None = None,
        al_enlace: Callable[[str], bool] | None = None,
        padres: list[tuple[int, str]] | None = None,
    ) -> None:
        """`padres` = [(id, título sangrado)] de las notas que pueden ser su página padre."""
        super().__init__(
            title=nota.titulo or _("Nueva nota"),
            # Sin transient_for: con él, X11 la marca como «diálogo» y el gestor de ventanas
            # quita el botón de maximizar y puede ignorar maximize(). Es una ventana de
            # documento, así que se asocia a la aplicación y no a la ventana principal.
            application=parent.get_application() if parent is not None else None,
            default_width=1000,
            default_height=860,
        )
        self._store = store
        self._nota = nota
        self._al_cambiar = al_cambiar
        self._cerrar_sin_preguntar = False
        self._zoom = ZoomHoja()

        self._titulo = Gtk.Entry(
            text=nota.titulo, placeholder_text=_("Título de la nota"), hexpand=True
        )
        self._estado = Gtk.DropDown.new_from_strings([ETIQUETAS_ESTADO[e] for e in ESTADOS_NOTA])
        self._estado.set_selected(ESTADOS_NOTA.index(nota.estado))
        self._estado.set_tooltip_text(_("Estado de la nota"))
        fila_titulo = Gtk.Box(spacing=8)
        fila_titulo.append(self._titulo)
        fila_titulo.append(self._estado)

        # Página padre: «Ninguna» (nivel raíz) o una de las notas candidatas.
        self._padres = [None, *(ident for ident, _t in (padres or []))]
        self._padre = Gtk.DropDown.new_from_strings(
            [_("Ninguna (nivel raíz)"), *(t for _i, t in (padres or []))]
        )
        self._padre.set_selected(
            self._padres.index(nota.padre_id) if nota.padre_id in self._padres else 0
        )
        fila_padre = Gtk.Box(spacing=8)
        fila_padre.append(Gtk.Label(label=_("Página padre"), xalign=0))
        fila_padre.append(self._padre)
        fila_padre.set_visible(len(self._padres) > 1)

        self._editor = MarkdownEditor(
            _("Contenido"),
            texto=nota.contenido,
            texto_vacio=_("Nota sin contenido"),
            alto_minimo=360,
            preprocesar=preprocesar,
            al_enlace=al_enlace,
            zoom_hoja=self._zoom,
        )

        cancelar = Gtk.Button(label=_("Cancelar"))
        cancelar.connect("clicked", lambda _b: self.close())
        guardar = Gtk.Button(label=_("Guardar"))
        guardar.add_css_class("suggested-action")
        guardar.connect("clicked", self._on_guardar)
        # «Eliminar» abajo a la izquierda y solo si la nota ya existe.
        eliminar = Gtk.Button(label=_("Eliminar"), tooltip_text=_("Eliminar nota"))
        eliminar.add_css_class("destructive-action")
        eliminar.connect("clicked", self._on_eliminar)
        eliminar.set_visible(nota.id != 0)
        versiones = boton_con_icono(_("Versiones"), "document-open-recent-symbolic")
        versiones.set_tooltip_text(_("Ver y restaurar versiones anteriores de la nota"))
        versiones.connect("clicked", self._on_versiones)
        versiones.set_visible(nota.id != 0)
        botones = Gtk.Box(spacing=8)
        botones.append(eliminar)
        botones.append(versiones)
        botones.append(self._zoom.botones())
        botones.append(Gtk.Box(hexpand=True))
        botones.append(cancelar)
        botones.append(guardar)

        caja = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        for margen in ("top", "bottom", "start", "end"):
            getattr(caja, f"set_margin_{margen}")(16)
        caja.append(fila_titulo)
        caja.append(fila_padre)
        caja.append(self._editor)
        caja.append(botones)
        self.set_child(caja)
        self.set_default_widget(guardar)
        self.connect("close-request", self._on_cerrar)

    # -- Guardado ----------------------------------------------------------

    def _hay_cambios(self) -> bool:
        titulo = self._titulo.get_text().strip()
        contenido = self._editor.obtener_texto()
        return (titulo, contenido, self._estado_elegido(), self._padre_elegido()) != (
            self._nota.titulo.strip(),
            self._nota.contenido,
            self._nota.estado,
            self._nota.padre_id,
        )

    def _padre_elegido(self) -> int | None:
        return self._padres[self._padre.get_selected()]

    def _estado_elegido(self) -> str:
        return ESTADOS_NOTA[self._estado.get_selected()]

    def _guardar(self) -> None:
        titulo = self._titulo.get_text().strip()
        contenido = self._editor.obtener_texto()
        if self._nota.id == 0:
            self._nota = self._store.crear_nota_documentacion(
                self._nota.proyecto_id,
                self._nota.seccion,
                titulo,
                contenido,
                subseccion_id=self._nota.subseccion_id,
                estado=self._estado_elegido(),
                padre_id=self._padre_elegido(),
            )
        else:
            self._nota.titulo = titulo
            self._nota.contenido = contenido
            self._nota.estado = self._estado_elegido()
            self._nota.padre_id = self._padre_elegido()
            self._store.actualizar_nota_documentacion(self._nota)
        self._al_cambiar()

    def _on_guardar(self, _boton: Gtk.Button) -> None:
        # Una nota nueva se crea siempre (puede venir de una plantilla sin tocar).
        if self._nota.id == 0 or self._hay_cambios():
            self._guardar()
        self._cerrar_sin_preguntar = True
        self.close()

    # -- Versiones ---------------------------------------------------------

    def _on_versiones(self, _boton: Gtk.Button) -> None:
        VersionesWindow(
            self,
            "nota",
            self._store.listar_versiones_nota(self._nota.id),
            self._editor.obtener_texto(),
            self._restaurar_version,
        ).present()

    def _restaurar_version(self, version: VersionDocumentacion) -> None:
        """Devuelve la versión al editor; no se guarda hasta pulsar «Guardar»."""
        self._titulo.set_text(version.titulo)
        self._editor.fijar_texto(version.contenido)

    # -- Cierre ------------------------------------------------------------

    def _on_cerrar(self, _ventana: Gtk.Window) -> bool:
        if self._cerrar_sin_preguntar or not self._hay_cambios():
            return False  # deja cerrar
        dialog = Gtk.AlertDialog()
        dialog.set_message(_("Cambios sin guardar"))
        dialog.set_detail(_("Si cierras ahora, se perderán los cambios de la nota."))
        dialog.set_buttons([_("Seguir editando"), _("Descartar"), _("Guardar")])
        dialog.set_cancel_button(0)
        dialog.set_default_button(2)
        dialog.choose(self, None, self._on_cierre_respuesta)
        return True  # frena el cierre hasta que se responda

    def _on_cierre_respuesta(self, dialog: Gtk.AlertDialog, result) -> None:
        try:
            eleccion = dialog.choose_finish(result)
        except GLib.Error:
            return
        if eleccion == 0:
            return
        if eleccion == 2:
            self._guardar()
        self._cerrar_sin_preguntar = True
        self.close()

    # -- Eliminación -------------------------------------------------------

    def _on_eliminar(self, _boton: Gtk.Button) -> None:
        dialog = Gtk.AlertDialog()
        dialog.set_message(_("Eliminar nota"))
        dialog.set_detail(
            _("¿Seguro que quieres eliminar «{titulo}»? Esta acción no se puede deshacer.").format(
                titulo=self._nota.titulo or _("Sin título")
            )
        )
        dialog.set_buttons([_("Cancelar"), _("Eliminar")])
        dialog.set_cancel_button(0)
        dialog.set_default_button(0)
        dialog.choose(self, None, self._on_eliminar_respuesta)

    def _on_eliminar_respuesta(self, dialog: Gtk.AlertDialog, result) -> None:
        try:
            eleccion = dialog.choose_finish(result)
        except GLib.Error:
            return
        if eleccion != 1:
            return
        self._store.eliminar_nota_documentacion(self._nota.id)
        self._al_cambiar()
        self._cerrar_sin_preguntar = True
        self.close()
