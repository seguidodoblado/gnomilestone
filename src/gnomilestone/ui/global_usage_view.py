from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk

from gnomilestone.filtros import ocultar_completadas
from gnomilestone.i18n import _
from gnomilestone.models import Tarea
from gnomilestone.resource_usage import construir_filas_uso_global
from gnomilestone.store import Store
from gnomilestone.ui.resource_usage_view import ResourceUsageView
from gnomilestone.ui.task_dialog import TaskDialog


class GlobalUsageView(Gtk.Box):
    """Uso de personas sumando varios proyectos a la vez (elegidos con checks).

    Las personas se agrupan por nombre, así la ocupación de quien trabaja en varios
    proyectos refleja la carga real y no la de cada proyecto por separado.
    """

    def __init__(self, store: Store) -> None:
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL)
        self._store = store
        self._checks: list[tuple[int, Gtk.CheckButton]] = []

        panel = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=6,
            width_request=200,
            margin_top=6,
            margin_bottom=6,
            margin_start=6,
            margin_end=6,
        )
        panel.append(Gtk.Label(label=_("Proyectos a sumar"), xalign=0))
        self._checks_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, vexpand=True)
        panel.append(self._checks_box)
        panel.append(Gtk.Separator())
        self._completadas = Gtk.CheckButton(label=_("Mostrar completadas"))
        self._completadas.set_active(True)
        self._completadas.connect("toggled", lambda _c: self.actualizar())
        panel.append(self._completadas)
        self.append(panel)

        self._uso = ResourceUsageView(
            on_editar_tarea=self._on_editar_tarea,
            plegar_inicial=True,
            on_dedicacion_changed=self._on_dedicacion_changed,
        )
        self._uso.set_hexpand(True)
        self.append(self._uso)

        self.refrescar_proyectos()

    def _on_editar_tarea(self, tarea: Tarea) -> None:
        TaskDialog(
            self.get_root(), self._store, tarea.proyecto_id, on_saved=self.actualizar, tarea=tarea
        ).present()

    def _on_dedicacion_changed(self, tarea_id: int, recurso_id: int, porcentaje: int) -> None:
        self._store.actualizar_dedicacion(tarea_id, recurso_id, porcentaje)
        self.actualizar()

    def refrescar_proyectos(self) -> None:
        seleccionados = {id_ for id_, check in self._checks if check.get_active()}
        for _id, check in self._checks:
            self._checks_box.remove(check)
        self._checks = []
        for proyecto in self._store.listar_proyectos():
            check = Gtk.CheckButton(label=proyecto.nombre)
            check.set_active(proyecto.id in seleccionados or not seleccionados)
            check.connect("toggled", lambda _c: self.actualizar())
            self._checks_box.append(check)
            self._checks.append((proyecto.id, check))
        self.actualizar()

    def actualizar(self) -> None:
        elegidos = [id_ for id_, check in self._checks if check.get_active()]
        nombres: dict[int, str] = {}
        recursos = {}
        tareas: list[Tarea] = []
        asignaciones = []
        for proyecto_id in elegidos:
            proyecto = self._store.obtener_proyecto(proyecto_id)
            if proyecto is None:
                continue
            nombres[proyecto_id] = proyecto.nombre
            for recurso in self._store.listar_recursos(proyecto_id):
                if recurso.categoria == "personas":
                    recursos[recurso.id] = recurso
            tareas_proyecto = self._store.listar_tareas(proyecto_id)
            if not self._completadas.get_active():
                tareas_proyecto = ocultar_completadas(tareas_proyecto)
            tareas.extend(tareas_proyecto)
            asignaciones.extend(self._store.listar_asignaciones_del_proyecto(proyecto_id))
        filas = construir_filas_uso_global(list(recursos.values()), tareas, asignaciones, nombres)
        self._uso.set_filas(filas, tareas)
