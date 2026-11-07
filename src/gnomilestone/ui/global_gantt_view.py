from __future__ import annotations

import logging

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk

from gnomilestone import ganttcalc
from gnomilestone.i18n import _
from gnomilestone.models import Dependencia, Tarea
from gnomilestone.store import Store
from gnomilestone.ui.gantt_view import GanttView
from gnomilestone.ui.task_dialog import TaskDialog
from gnomilestone.ui.task_tree_view import TareaRow, construir_filas

log = logging.getLogger(__name__)


class GlobalGanttView(Gtk.Box):
    """Gantt que superpone varios proyectos a la vez (elegidos con checks) para ver solapes."""

    def __init__(self, store: Store) -> None:
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL)
        self._store = store
        self._checks: list[tuple[int, Gtk.CheckButton]] = []

        panel_proyectos = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=6,
            width_request=200,
            margin_top=6,
            margin_bottom=6,
            margin_start=6,
            margin_end=6,
        )
        panel_proyectos.append(Gtk.Label(label=_("Proyectos a comparar"), xalign=0))
        self._checks_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        panel_proyectos.append(self._checks_box)
        self.append(panel_proyectos)

        self._gantt = GanttView(
            on_editar_tarea=self._on_editar_tarea,
            on_eliminar_tarea=self._on_eliminar_tarea,
            on_tarea_arrastrada=self._on_tarea_arrastrada,
        )
        self._gantt.set_hexpand(True)
        self.append(self._gantt)

        self.refrescar_proyectos()

    def _on_editar_tarea(self, tarea: Tarea) -> None:
        TaskDialog(
            self.get_root(), self._store, tarea.proyecto_id, on_saved=self._actualizar_gantt,
            tarea=tarea,
        ).present()

    def _on_eliminar_tarea(self, tarea: Tarea) -> None:
        dialog = Gtk.AlertDialog()
        dialog.set_message(_("Eliminar tarea"))
        dialog.set_detail(
            _(
                "¿Seguro que quieres eliminar «{titulo}»? Sus subtareas y dependencias "
                "también se eliminarán. Esta acción no se puede deshacer."
            ).format(titulo=tarea.titulo)
        )
        dialog.set_buttons([_("Cancelar"), _("Eliminar")])
        dialog.set_cancel_button(0)
        dialog.set_default_button(0)
        dialog.choose(self.get_root(), None, self._on_eliminar_tarea_confirmado, tarea)

    def _on_eliminar_tarea_confirmado(self, dialog: Gtk.AlertDialog, result, tarea: Tarea) -> None:
        try:
            choice = dialog.choose_finish(result)
        except Exception:
            log.exception("Falló _on_eliminar_tarea_confirmado")
            return
        if choice != 1:
            return
        self._store.eliminar_tarea(tarea.id)
        self._actualizar_gantt()

    def _on_tarea_arrastrada(self, tarea_id: int, nueva_fecha_iso: str, nueva_duracion_dias: int) -> None:
        tarea = self._store.obtener_tarea(tarea_id)
        if tarea is None:
            return
        fecha_original = tarea.fecha_inicio
        duracion_original = tarea.duracion_dias
        tarea.fecha_inicio = nueva_fecha_iso
        tarea.duracion_dias = nueva_duracion_dias
        self._store.actualizar_tarea(tarea)

        tareas = self._store.listar_tareas(tarea.proyecto_id)
        # El padre manda: al moverlo, sus hijas le siguen (mismo delta); al redimensionarlo,
        # las que ya no quepan se recortan a su nuevo rango. Nunca al revés.
        if tarea.duracion_dias != duracion_original:
            cambiadas_jerarquia = ganttcalc.limitar_hijos_tras_redimensionar(
                tareas, tarea.id, ganttcalc.parse_fecha(tarea.fecha_inicio), tarea.duracion_dias
            )
        elif fecha_original and tarea.fecha_inicio != fecha_original:
            delta_dias = (
                ganttcalc.parse_fecha(tarea.fecha_inicio) - ganttcalc.parse_fecha(fecha_original)
            ).days
            cambiadas_jerarquia = ganttcalc.trasladar_hijos(tareas, tarea.id, delta_dias)
        else:
            cambiadas_jerarquia = []
        for cambiada in cambiadas_jerarquia:
            self._store.actualizar_tarea(cambiada)

        dependencias = self._store.listar_dependencias(tarea.proyecto_id)
        for cambiada in ganttcalc.recalcular_dependientes(tareas, dependencias, tarea_id):
            self._store.actualizar_tarea(cambiada)
        self._actualizar_gantt()

    def refrescar_proyectos(self) -> None:
        seleccionados = {id_ for id_, check in self._checks if check.get_active()}
        for _id, check in self._checks:
            self._checks_box.remove(check)
        self._checks = []
        for proyecto in self._store.listar_proyectos():
            check = Gtk.CheckButton(label=proyecto.nombre)
            check.set_active(proyecto.id in seleccionados or not seleccionados)
            check.connect("toggled", lambda _c: self._actualizar_gantt())
            self._checks_box.append(check)
            self._checks.append((proyecto.id, check))
        self._actualizar_gantt()

    def _actualizar_gantt(self) -> None:
        ids_elegidos = [id_ for id_, check in self._checks if check.get_active()]
        filas: list[TareaRow] = []
        dependencias: list[Dependencia] = []
        progreso_resumen: dict[int, int] = {}
        for proyecto_id in ids_elegidos:
            proyecto = self._store.obtener_proyecto(proyecto_id)
            if proyecto is None:
                continue
            estados_por_id = {e.id: e.nombre for e in self._store.listar_estados(proyecto_id)}
            tareas = self._store.listar_tareas(proyecto_id)
            recursos_por_tarea = self._store.listar_recursos_por_tarea(proyecto_id)
            fila_proyecto = TareaRow(
                proyecto.nombre,
                construir_filas(tareas, estados_por_id, recursos_por_tarea),
            )
            filas.append(fila_proyecto)
            dependencias.extend(self._store.listar_dependencias(proyecto_id))
            progreso_resumen.update(ganttcalc.progreso_resumen(tareas))
        self._gantt.set_filas(filas, dependencias, progreso_resumen)
