from __future__ import annotations

from collections.abc import Callable

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk

from gnomilestone.i18n import _
from gnomilestone.models import EstadoTablero
from gnomilestone.store import ColumnaNoVaciaError, Store


class BoardSettingsDialog(Gtk.Window):
    """Alta/renombrado/orden/borrado de las columnas (estado_tablero) de un proyecto."""

    def __init__(
        self, parent: Gtk.Window, store: Store, proyecto_id: int, on_changed: Callable[[], None]
    ) -> None:
        super().__init__(
            title=_("Columnas del tablero"),
            transient_for=parent,
            modal=True,
            default_width=360,
        )
        self._store = store
        self._proyecto_id = proyecto_id
        self._on_changed = on_changed

        box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=10,
            margin_top=16,
            margin_bottom=16,
            margin_start=16,
            margin_end=16,
        )
        self.set_child(box)

        self._list_box = Gtk.ListBox()
        box.append(self._list_box)

        add_row = Gtk.Box(spacing=6)
        self._new_entry = Gtk.Entry(placeholder_text=_("Nueva columna"), hexpand=True)
        self._new_entry.connect("activate", self._on_add)
        add_row.append(self._new_entry)
        add_button = Gtk.Button(icon_name="list-add-symbolic")
        add_button.connect("clicked", self._on_add)
        add_row.append(add_button)
        box.append(add_row)

        self._refresh()

    def _refresh(self) -> None:
        self._list_box.remove_all()
        estados = self._store.listar_estados(self._proyecto_id)
        for indice, estado in enumerate(estados):
            row = Gtk.ListBoxRow()
            fila = Gtk.Box(spacing=6)
            entry = Gtk.Entry(text=estado.nombre, hexpand=True)
            entry.connect("activate", self._on_rename, estado)
            fila.append(entry)

            up_button = Gtk.Button(icon_name="go-up-symbolic", sensitive=indice > 0)
            up_button.connect("clicked", self._on_move, estados, indice, -1)
            fila.append(up_button)

            down_button = Gtk.Button(
                icon_name="go-down-symbolic", sensitive=indice < len(estados) - 1
            )
            down_button.connect("clicked", self._on_move, estados, indice, 1)
            fila.append(down_button)

            delete_button = Gtk.Button(icon_name="user-trash-symbolic")
            delete_button.connect("clicked", self._on_delete, estado, estados)
            fila.append(delete_button)

            row.set_child(fila)
            self._list_box.append(row)

    def _on_add(self, _widget: Gtk.Widget) -> None:
        nombre = self._new_entry.get_text().strip()
        if not nombre:
            return
        self._store.crear_estado(self._proyecto_id, nombre)
        self._new_entry.set_text("")
        self._refresh()
        self._on_changed()

    def _on_rename(self, entry: Gtk.Entry, estado: EstadoTablero) -> None:
        nombre = entry.get_text().strip()
        if not nombre:
            return
        self._store.renombrar_estado(estado.id, nombre)
        self._on_changed()

    def _on_move(
        self, _button: Gtk.Button, estados: list[EstadoTablero], indice: int, direccion: int
    ) -> None:
        nuevo_orden = [e.id for e in estados]
        destino = indice + direccion
        nuevo_orden[indice], nuevo_orden[destino] = nuevo_orden[destino], nuevo_orden[indice]
        self._store.reordenar_estados(nuevo_orden)
        self._refresh()
        self._on_changed()

    def _on_delete(
        self, _button: Gtk.Button, estado: EstadoTablero, estados: list[EstadoTablero]
    ) -> None:
        try:
            self._store.eliminar_estado(estado.id)
        except ColumnaNoVaciaError:
            otras = [e for e in estados if e.id != estado.id]
            if not otras:
                self._mostrar_error(
                    _("No se puede eliminar la última columna mientras tenga tareas.")
                )
                return
            self._pedir_destino_y_eliminar(estado, otras)
            return
        self._refresh()
        self._on_changed()

    def _pedir_destino_y_eliminar(
        self, origen: EstadoTablero, otras: list[EstadoTablero]
    ) -> None:
        selector = Gtk.Window(
            title=_("Mover tareas antes de eliminar"), transient_for=self, modal=True
        )
        box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=10,
            margin_top=16,
            margin_bottom=16,
            margin_start=16,
            margin_end=16,
        )
        selector.set_child(box)
        box.append(
            Gtk.Label(
                label=_(
                    "«{nombre}» todavía tiene tareas. Elige a qué columna se mueven "
                    "antes de eliminarla."
                ).format(nombre=origen.nombre),
                wrap=True,
                xalign=0,
            )
        )
        dropdown = Gtk.DropDown.new_from_strings([e.nombre for e in otras])
        box.append(dropdown)

        def _confirmar(_button: Gtk.Button) -> None:
            destino = otras[dropdown.get_selected()]
            self._store.mover_tareas_a_estado(origen.id, destino.id)
            self._store.eliminar_estado(origen.id)
            selector.close()
            self._refresh()
            self._on_changed()

        confirm_button = Gtk.Button(label=_("Mover y eliminar"))
        confirm_button.add_css_class("destructive-action")
        confirm_button.connect("clicked", _confirmar)
        box.append(confirm_button)
        selector.present()

    def _mostrar_error(self, mensaje: str) -> None:
        dialog = Gtk.AlertDialog()
        dialog.set_message(mensaje)
        dialog.show(self)
