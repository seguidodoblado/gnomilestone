from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, Pango

from gnomilestone.i18n import _
from gnomilestone.models import Proyecto
from gnomilestone.store import Store
from gnomilestone.ui.project_dialog import ProjectDialog

log = logging.getLogger(__name__)


class ProjectListView(Gtk.Box):
    def __init__(self, store: Store, on_select: Callable[[Proyecto | None], None]) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6, width_request=300)
        self._store = store
        self._on_select = on_select
        self._selected_id: int | None = None
        self._project_dialog: ProjectDialog | None = None

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
            if proyecto.icon_path and Path(proyecto.icon_path).is_file():
                icon = Gtk.Image.new_from_file(proyecto.icon_path)
            else:
                icon = Gtk.Image.new_from_icon_name(proyecto.icon_name or "folder-symbolic")
            icon.set_pixel_size(24)
            icon.set_tooltip_text(proyecto.icon_path or proyecto.icon_name or "folder-symbolic")
            box.append(icon)
            datos = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True)
            nombre = Gtk.Label(label=proyecto.nombre, xalign=0, ellipsize=Pango.EllipsizeMode.END)
            datos.append(nombre)
            estado = {
                "pendiente": _("Pendiente"),
                "en_curso": _("En curso"),
                "pausado": _("Pausado"),
                "completado": _("Completado"),
            }.get(proyecto.estado, proyecto.estado)
            if proyecto.archivado:
                estado += f" · {_('Archivado')}"
            estado_label = Gtk.Label(label=estado, xalign=0)
            estado_label.add_css_class("dim-label")
            datos.append(estado_label)
            box.append(datos)
            edit_button = Gtk.Button(
                icon_name="document-edit-symbolic", tooltip_text=_("Editar proyecto")
            )
            edit_button.connect("clicked", self._on_edit_clicked, proyecto)
            box.append(edit_button)
            delete_button = Gtk.Button(
                icon_name="user-trash-symbolic", tooltip_text=_("Eliminar proyecto")
            )
            delete_button.connect("clicked", self._on_delete_clicked, proyecto)
            box.append(delete_button)
            row.set_child(box)
            self._list_box.append(row)
            if proyecto.id == self._selected_id:
                self._list_box.select_row(row)

    def _on_edit_clicked(self, _button: Gtk.Button, proyecto: Proyecto) -> None:
        self._project_dialog = ProjectDialog(
            self.get_root(), self._store, proyecto, self._on_project_saved
        )
        self._project_dialog.present()

    def _on_project_saved(self, proyecto: Proyecto) -> None:
        self._selected_id = proyecto.id
        self.refresh()
        self._on_select(self._store.obtener_proyecto(proyecto.id))

    def crear_proyecto(self, nombre: str) -> None:
        """Crea un proyecto con `nombre` y lo selecciona. Lo usan tanto el "+" junto al
        buscador como el botón grande de la pantalla inicial (`window.py`)."""
        proyecto = self._store.crear_proyecto(nombre)
        self._selected_id = proyecto.id
        self.refresh()
        self._on_select(proyecto)

    def deseleccionar(self) -> None:
        """Quita la selección actual (si hay una): lo usa el botón "inicio" de la
        cabecera para volver a la pantalla vacía sin elegir otro proyecto."""
        self._list_box.unselect_all()
        # No todas las versiones de Gtk.ListBox emiten "row-selected" con None al
        # deseleccionar en modo SINGLE: se fuerza el mismo efecto por si acaso.
        if self._selected_id is not None:
            self._selected_id = None
            self._on_select(None)

    def _on_create(self, _widget: Gtk.Widget) -> None:
        nombre = self._entry.get_text().strip()
        if not nombre:
            return
        self._entry.set_text("")
        self.crear_proyecto(nombre)

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
