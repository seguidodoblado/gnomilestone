from __future__ import annotations

import logging
from collections.abc import Callable

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk

from gnomilestone.i18n import _
from gnomilestone.models import Proyecto
from gnomilestone.store import Store

log = logging.getLogger(__name__)


class ProjectListView(Gtk.Box):
    def __init__(self, store: Store, on_select: Callable[[Proyecto | None], None]) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6, width_request=240)
        self._store = store
        self._on_select = on_select
        self._selected_id: int | None = None

        header = Gtk.Box(spacing=6, margin_start=6, margin_end=6, margin_top=6)
        header.append(Gtk.Label(label=_("Proyectos"), xalign=0, hexpand=True))
        self.append(header)

        self._entry = Gtk.Entry(placeholder_text=_("Nombre del nuevo proyecto"))
        self._entry.connect("activate", self._on_create)
        add_row = Gtk.Box(spacing=6, margin_start=6, margin_end=6)
        add_row.append(self._entry)
        add_button = Gtk.Button(icon_name="list-add-symbolic", tooltip_text=_("Crear proyecto"))
        add_button.connect("clicked", self._on_create)
        add_row.append(add_button)
        self.append(add_row)

        scroller = Gtk.ScrolledWindow(vexpand=True)
        self._list_box = Gtk.ListBox()
        self._list_box.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self._list_box.connect("row-selected", self._on_row_selected)
        scroller.set_child(self._list_box)
        self.append(scroller)

        self.refresh()

    def refresh(self) -> None:
        self._list_box.remove_all()
        for proyecto in self._store.listar_proyectos():
            row = Gtk.ListBoxRow()
            row.proyecto_id = proyecto.id  # type: ignore[attr-defined]
            box = Gtk.Box(spacing=6, margin_start=6, margin_end=6, margin_top=4, margin_bottom=4)
            box.append(Gtk.Label(label=proyecto.nombre, xalign=0, hexpand=True))
            delete_button = Gtk.Button(
                icon_name="user-trash-symbolic", tooltip_text=_("Eliminar proyecto")
            )
            delete_button.connect("clicked", self._on_delete_clicked, proyecto)
            box.append(delete_button)
            row.set_child(box)
            self._list_box.append(row)
            if proyecto.id == self._selected_id:
                self._list_box.select_row(row)

    def _on_create(self, _widget: Gtk.Widget) -> None:
        nombre = self._entry.get_text().strip()
        if not nombre:
            return
        proyecto = self._store.crear_proyecto(nombre)
        self._entry.set_text("")
        self._selected_id = proyecto.id
        self.refresh()
        self._on_select(proyecto)

    def _on_row_selected(self, _list_box: Gtk.ListBox, row: Gtk.ListBoxRow | None) -> None:
        if row is None:
            self._selected_id = None
            self._on_select(None)
            return
        self._selected_id = row.proyecto_id  # type: ignore[attr-defined]
        self._on_select(self._store.obtener_proyecto(self._selected_id))

    def _on_delete_clicked(self, _button: Gtk.Button, proyecto: Proyecto) -> None:
        dialog = Gtk.AlertDialog()
        dialog.set_message(_("Eliminar proyecto"))
        dialog.set_detail(
            _("¿Seguro que quieres eliminar «{nombre}»? Se borrarán también sus tareas, "
              "columnas y recursos. Esta acción no se puede deshacer.").format(
                nombre=proyecto.nombre
            )
        )
        dialog.set_buttons([_("Cancelar"), _("Eliminar")])
        dialog.set_cancel_button(0)
        dialog.set_default_button(0)
        dialog.choose(self.get_root(), None, self._on_delete_confirmed, proyecto)

    def _on_delete_confirmed(self, dialog: Gtk.AlertDialog, result, proyecto: Proyecto) -> None:
        try:
            choice = dialog.choose_finish(result)
        except Exception:
            log.exception("Falló _on_delete_confirmed")
            return
        if choice != 1:
            return
        self._store.eliminar_proyecto(proyecto.id)
        if self._selected_id == proyecto.id:
            self._selected_id = None
        self.refresh()
        if self._selected_id is None:
            self._on_select(None)
