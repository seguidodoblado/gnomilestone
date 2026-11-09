from __future__ import annotations

from collections.abc import Callable

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import GLib, Gtk

from gnomilestone.diagrama import Arista, Diagrama, Nodo
from gnomilestone.i18n import _
from gnomilestone.models import DiagramaDocumentacion, VersionDocumentacion
from gnomilestone.store import Store
from gnomilestone.ui.diagram_canvas import IconoForma, LienzoDiagrama
from gnomilestone.ui.dialogos import boton_con_icono, pedir_texto
from gnomilestone.ui.versiones_window import VersionesWindow


def _texto_por_defecto(tipo: str) -> str:
    return {
        "inicio": _("Inicio"),
        "paso": _("Paso"),
        "decision": _("¿Decisión?"),
        "fin": _("Fin"),
    }[tipo]


class DiagramWindow(Gtk.Window):
    """Ventana independiente para editar un diagrama de flujo. Igual que la de notas: los
    cambios solo se aplican con «Guardar» y un diagrama con `id == 0` es nuevo (no existe en
    la base de datos hasta que se guarda)."""

    def __init__(
        self,
        parent: Gtk.Window | None,
        store: Store,
        diagrama: DiagramaDocumentacion,
        al_cambiar: Callable[[], None],
    ) -> None:
        super().__init__(
            title=diagrama.titulo or _("Nuevo diagrama"),
            transient_for=parent,
            default_width=1100,
            default_height=760,
        )
        self._store = store
        self._registro = diagrama
        self._al_cambiar = al_cambiar
        self._cerrar_sin_preguntar = False
        self._modelo = Diagrama.de_json(diagrama.datos)
        self._original = (diagrama.titulo, self._modelo.a_json())

        self._titulo = Gtk.Entry(
            text=diagrama.titulo, placeholder_text=_("Título del diagrama"), hexpand=True
        )

        self._lienzo = LienzoDiagrama(self._modelo, lambda: None, self._editar_texto)
        marco = Gtk.Frame(hexpand=True, vexpand=True)
        marco.set_child(self._lienzo)

        cancelar = Gtk.Button(label=_("Cancelar"))
        cancelar.connect("clicked", lambda _b: self.close())
        guardar = Gtk.Button(label=_("Guardar"))
        guardar.add_css_class("suggested-action")
        guardar.connect("clicked", self._on_guardar)
        # «Eliminar» abajo a la izquierda y solo si el diagrama ya existe.
        eliminar = Gtk.Button(label=_("Eliminar"), tooltip_text=_("Eliminar diagrama"))
        eliminar.add_css_class("destructive-action")
        eliminar.connect("clicked", self._on_eliminar)
        eliminar.set_visible(diagrama.id != 0)
        versiones = boton_con_icono(_("Versiones"), "document-open-recent-symbolic")
        versiones.set_tooltip_text(_("Ver y restaurar versiones anteriores del diagrama"))
        versiones.connect("clicked", self._on_versiones)
        versiones.set_visible(diagrama.id != 0)
        botones = Gtk.Box(spacing=8)
        botones.append(eliminar)
        botones.append(versiones)
        botones.append(Gtk.Box(hexpand=True))
        botones.append(cancelar)
        botones.append(guardar)

        caja = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        for margen in ("top", "bottom", "start", "end"):
            getattr(caja, f"set_margin_{margen}")(16)
        caja.append(self._titulo)
        caja.append(self._construir_herramientas())
        caja.append(marco)
        caja.append(botones)
        self.set_child(caja)
        self.connect("close-request", self._on_cerrar)

    # -- Herramientas ------------------------------------------------------

    def _construir_herramientas(self) -> Gtk.Widget:
        barra = Gtk.Box(spacing=12)

        modos = Gtk.Box()
        modos.add_css_class("linked")
        seleccionar = Gtk.ToggleButton(
            label=_("Seleccionar"),
            active=True,
            tooltip_text=_("Clic para seleccionar, arrastrar para mover; doble clic edita el texto"),
        )
        conectar = Gtk.ToggleButton(
            label=_("Conectar"),
            group=seleccionar,
            tooltip_text=_("Arrastra de un elemento a otro para unirlos con una flecha"),
        )
        seleccionar.connect("toggled", self._on_modo, "seleccionar")
        conectar.connect("toggled", self._on_modo, "conectar")
        modos.append(seleccionar)
        modos.append(conectar)
        barra.append(modos)

        barra.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))
        for tipo, etiqueta in (
            ("inicio", _("Inicio")),
            ("paso", _("Paso")),
            ("decision", _("Decisión")),
            ("fin", _("Fin")),
        ):
            contenido = Gtk.Box(spacing=6)
            contenido.append(IconoForma(tipo))
            contenido.append(Gtk.Label(label=etiqueta))
            boton = Gtk.Button(child=contenido)
            boton.set_tooltip_text(_("Añadir elemento: {tipo}").format(tipo=etiqueta))
            boton.connect("clicked", self._on_anadir, tipo)
            barra.append(boton)

        barra.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))
        borrar = Gtk.Button(
            icon_name="edit-delete-symbolic", tooltip_text=_("Borrar la selección (Supr)")
        )
        borrar.connect("clicked", lambda _b: self._lienzo.eliminar_seleccion())
        barra.append(borrar)

        zoom = Gtk.Box(spacing=6, hexpand=True, halign=Gtk.Align.END)
        for icono, tooltip, accion in (
            ("zoom-fit-best-symbolic", _("Ajustar a la vista"), self._lienzo_ajustar),
            ("zoom-out-symbolic", _("Alejar"), lambda: self._lienzo.zoom_por(1 / 1.25)),
            ("zoom-in-symbolic", _("Acercar"), lambda: self._lienzo.zoom_por(1.25)),
        ):
            boton = Gtk.Button(icon_name=icono, tooltip_text=tooltip)
            boton.connect("clicked", lambda _b, a=accion: a())
            zoom.append(boton)
        barra.append(zoom)
        return barra

    def _lienzo_ajustar(self) -> None:
        self._lienzo.ajustar()

    def _on_modo(self, boton: Gtk.ToggleButton, modo: str) -> None:
        if boton.get_active():
            self._lienzo.herramienta = modo

    def _on_anadir(self, _boton: Gtk.Button, tipo: str) -> None:
        nodo = self._lienzo.anadir_nodo(tipo, _texto_por_defecto(tipo))
        self._editar_texto(nodo)

    def _editar_texto(self, objeto: Nodo | Arista) -> None:
        if isinstance(objeto, Nodo):
            titulo, valor = _("Texto del elemento"), objeto.texto
        else:
            titulo, valor = _("Etiqueta de la flecha"), objeto.etiqueta

        def aplicar(texto: str) -> None:
            if isinstance(objeto, Nodo):
                objeto.texto = texto
            else:
                objeto.etiqueta = texto
            self._lienzo.refrescar()

        pedir_texto(self, titulo, valor, aplicar, permitir_vacio=isinstance(objeto, Arista))

    # -- Versiones -----------------------------------------------------------

    def _on_versiones(self, _boton: Gtk.Button) -> None:
        VersionesWindow(
            self,
            "diagrama",
            self._store.listar_versiones_diagrama(self._registro.id),
            self._modelo.a_json(),
            self._restaurar_version,
        ).present()

    def _restaurar_version(self, version: VersionDocumentacion) -> None:
        """Devuelve la versión al lienzo; no se guarda hasta pulsar «Guardar»."""
        antiguo = Diagrama.de_json(version.contenido)
        self._modelo.nodos[:] = antiguo.nodos
        self._modelo.aristas[:] = antiguo.aristas
        self._titulo.set_text(version.titulo)
        self._lienzo.deseleccionar()
        self._lienzo.ajustar()

    # -- Guardado y cierre ---------------------------------------------------

    def _hay_cambios(self) -> bool:
        return (self._titulo.get_text().strip(), self._modelo.a_json()) != self._original

    def _guardar(self) -> None:
        titulo = self._titulo.get_text().strip()
        datos = self._modelo.a_json()
        if self._registro.id == 0:
            self._registro = self._store.crear_diagrama_documentacion(
                self._registro.proyecto_id, self._registro.subseccion_id, titulo, datos
            )
        else:
            self._registro.titulo = titulo
            self._registro.datos = datos
            self._store.actualizar_diagrama_documentacion(self._registro)
        self._original = (titulo, datos)
        self._al_cambiar()

    def _on_guardar(self, _boton: Gtk.Button) -> None:
        if self._hay_cambios():
            self._guardar()
        self._cerrar_sin_preguntar = True
        self.close()

    def _on_cerrar(self, _ventana: Gtk.Window) -> bool:
        if self._cerrar_sin_preguntar or not self._hay_cambios():
            return False
        dialog = Gtk.AlertDialog()
        dialog.set_message(_("Cambios sin guardar"))
        dialog.set_detail(_("Si cierras ahora, se perderán los cambios del diagrama."))
        dialog.set_buttons([_("Seguir editando"), _("Descartar"), _("Guardar")])
        dialog.set_cancel_button(0)
        dialog.set_default_button(2)
        dialog.choose(self, None, self._on_cierre_respuesta)
        return True

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

    def _on_eliminar(self, _boton: Gtk.Button) -> None:
        dialog = Gtk.AlertDialog()
        dialog.set_message(_("Eliminar diagrama"))
        dialog.set_detail(
            _("¿Seguro que quieres eliminar «{titulo}»? Esta acción no se puede deshacer.").format(
                titulo=self._registro.titulo or _("Sin título")
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
        self._store.eliminar_diagrama_documentacion(self._registro.id)
        self._al_cambiar()
        self._cerrar_sin_preguntar = True
        self.close()
