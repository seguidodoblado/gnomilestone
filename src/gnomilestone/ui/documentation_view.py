from __future__ import annotations

import logging

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import GLib, Gtk

from gnomilestone.i18n import _
from gnomilestone.models import NotaDocumentacion
from gnomilestone.store import Store
from gnomilestone.ui.markdown_editor import MarkdownEditor

log = logging.getLogger(__name__)

# (sección, título visible): mismo orden que SECCIONES_DOCUMENTACION.
_SECCIONES = (
    ("arquitectura", _("Arquitectura")),
    ("especificaciones", _("Especificaciones")),
    ("blueprint", _("Blueprint")),
    ("decisiones_tecnicas", _("Decisiones técnicas")),
)
_AUTOGUARDADO_MS = 600


class DocumentationView(Gtk.Box):
    """Vista de documentación del proyecto (rail Documentación): cuatro secciones con sus
    notas Markdown a la izquierda y el editor de la nota seleccionada a la derecha. Todo el
    contenido es propio de la app; los cambios se guardan solos."""

    def __init__(self, store: Store) -> None:
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL)
        self._store = store
        self._proyecto_id: int | None = None
        self._nota: NotaDocumentacion | None = None
        self._cargando = False
        self._guardado_id: int | None = None

        self.append(self._construir_lateral())
        self.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))
        self.append(self._construir_editor())

    # -- Construcción ------------------------------------------------------

    def _construir_lateral(self) -> Gtk.Widget:
        self._lateral = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        for margen in ("top", "bottom", "start", "end"):
            getattr(self._lateral, f"set_margin_{margen}")(10)
        scroller = Gtk.ScrolledWindow(
            hscrollbar_policy=Gtk.PolicyType.NEVER, width_request=260, vexpand=True
        )
        scroller.set_child(self._lateral)
        return scroller

    def _construir_editor(self) -> Gtk.Widget:
        self._vacio = Gtk.Label(
            label=_("Selecciona una nota o crea la primera con el botón «+» de una sección."),
            wrap=True,
            justify=Gtk.Justification.CENTER,
        )
        self._vacio.add_css_class("dim-label")

        self._titulo_entry = Gtk.Entry(placeholder_text=_("Título de la nota"), hexpand=True)
        self._titulo_entry.connect("changed", lambda _e: self._programar_guardado())
        eliminar = Gtk.Button(icon_name="user-trash-symbolic", tooltip_text=_("Eliminar nota"))
        eliminar.connect("clicked", self._on_eliminar)
        cabecera = Gtk.Box(spacing=6)
        cabecera.append(self._titulo_entry)
        cabecera.append(eliminar)

        self._editor = MarkdownEditor(
            _("Contenido"), texto_vacio=_("Nota sin contenido"), alto_minimo=240
        )
        self._editor.al_cambiar(self._programar_guardado)

        formulario = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        for margen in ("top", "bottom", "start", "end"):
            getattr(formulario, f"set_margin_{margen}")(16)
        formulario.append(cabecera)
        formulario.append(self._editor)

        self._derecha = Gtk.Stack(hexpand=True, vexpand=True)
        self._derecha.add_named(self._vacio, "vacio")
        self._derecha.add_named(formulario, "editor")
        self._derecha.set_visible_child_name("vacio")
        return self._derecha

    # -- Datos -------------------------------------------------------------

    def mostrar_proyecto(self, proyecto_id: int) -> None:
        if proyecto_id != self._proyecto_id:
            self._guardar_ahora()
            self._proyecto_id = proyecto_id
            self._nota = None
        self.refrescar()

    def refrescar(self) -> None:
        if self._proyecto_id is None:
            return
        notas = self._store.listar_notas_documentacion(self._proyecto_id)
        if self._nota is not None and all(n.id != self._nota.id for n in notas):
            self._nota = None
        self._reconstruir_lateral(notas)
        self._cargar_nota(self._nota)

    def _reconstruir_lateral(self, notas: list[NotaDocumentacion]) -> None:
        hijo = self._lateral.get_first_child()
        while hijo is not None:
            siguiente = hijo.get_next_sibling()
            self._lateral.remove(hijo)
            hijo = siguiente
        for seccion, nombre in _SECCIONES:
            cabecera = Gtk.Box(spacing=4, margin_top=8)
            titulo = Gtk.Label(label=nombre, xalign=0, hexpand=True)
            titulo.add_css_class("heading")
            cabecera.append(titulo)
            nueva = Gtk.Button(icon_name="list-add-symbolic", tooltip_text=_("Nueva nota"))
            nueva.add_css_class("flat")
            nueva.connect("clicked", self._on_nueva, seccion)
            cabecera.append(nueva)
            self._lateral.append(cabecera)

            de_seccion = [n for n in notas if n.seccion == seccion]
            if not de_seccion:
                vacia = Gtk.Label(
                    label=_("Sin notas. Crea la primera con «+»."), xalign=0, wrap=True
                )
                vacia.add_css_class("dim-label")
                vacia.add_css_class("caption")
                self._lateral.append(vacia)
            for nota in de_seccion:
                boton = Gtk.ToggleButton(active=self._nota is not None and nota.id == self._nota.id)
                boton.add_css_class("flat")
                etiqueta = Gtk.Label(
                    label=nota.titulo or _("Sin título"),
                    xalign=0,
                    ellipsize=3,  # Pango.EllipsizeMode.END
                )
                boton.set_child(etiqueta)
                boton.connect("clicked", self._on_seleccionar, nota.id)
                self._lateral.append(boton)

    def _cargar_nota(self, nota: NotaDocumentacion | None) -> None:
        self._nota = nota
        if nota is None:
            self._derecha.set_visible_child_name("vacio")
            return
        self._cargando = True
        self._titulo_entry.set_text(nota.titulo)
        self._editor.fijar_texto(nota.contenido)
        self._cargando = False
        self._derecha.set_visible_child_name("editor")

    # -- Guardado ----------------------------------------------------------

    def _programar_guardado(self) -> None:
        if self._cargando or self._nota is None:
            return
        if self._guardado_id is not None:
            GLib.source_remove(self._guardado_id)
        self._guardado_id = GLib.timeout_add(_AUTOGUARDADO_MS, self._on_autoguardado)

    def _on_autoguardado(self) -> bool:
        self._guardado_id = None
        self._guardar_ahora()
        return False

    def _guardar_ahora(self) -> None:
        if self._guardado_id is not None:
            GLib.source_remove(self._guardado_id)
            self._guardado_id = None
        if self._nota is None:
            return
        titulo = self._titulo_entry.get_text().strip()
        contenido = self._editor.obtener_texto()
        if titulo == self._nota.titulo and contenido == self._nota.contenido:
            return
        self._nota.titulo = titulo
        self._nota.contenido = contenido
        self._store.actualizar_nota_documentacion(self._nota)
        # El editor está en el otro panel: reconstruir el lateral no le quita el foco.
        self._reconstruir_lateral(self._store.listar_notas_documentacion(self._nota.proyecto_id))

    # -- Acciones ----------------------------------------------------------

    def _on_nueva(self, _boton: Gtk.Button, seccion: str) -> None:
        if self._proyecto_id is None:
            return
        self._guardar_ahora()
        nota = self._store.crear_nota_documentacion(self._proyecto_id, seccion, _("Nueva nota"))
        self._nota = nota
        self.refrescar()
        self._titulo_entry.grab_focus()
        self._titulo_entry.select_region(0, -1)

    def _on_seleccionar(self, _boton: Gtk.ToggleButton, nota_id: int) -> None:
        self._guardar_ahora()
        self._nota = self._store.obtener_nota_documentacion(nota_id)
        self.refrescar()

    def _on_eliminar(self, _boton: Gtk.Button) -> None:
        if self._nota is None:
            return
        dialog = Gtk.AlertDialog()
        dialog.set_message(_("Eliminar nota"))
        dialog.set_detail(
            _(
                "¿Seguro que quieres eliminar «{titulo}»? Esta acción no se puede deshacer."
            ).format(titulo=self._nota.titulo or _("Sin título"))
        )
        dialog.set_buttons([_("Cancelar"), _("Eliminar")])
        dialog.set_cancel_button(0)
        dialog.set_default_button(0)
        dialog.choose(self.get_root(), None, self._on_eliminar_respuesta, self._nota.id)

    def _on_eliminar_respuesta(self, dialog: Gtk.AlertDialog, result, nota_id: int) -> None:
        try:
            eleccion = dialog.choose_finish(result)
        except GLib.Error:
            return
        if eleccion != 1:
            return
        if self._guardado_id is not None:
            GLib.source_remove(self._guardado_id)
            self._guardado_id = None
        self._store.eliminar_nota_documentacion(nota_id)
        self._nota = None
        self.refrescar()
