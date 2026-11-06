from __future__ import annotations

import logging

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, Gtk

from gnomilestone import ganttcalc
from gnomilestone.i18n import _
from gnomilestone.models import Proyecto, Tarea
from gnomilestone.resource_usage import construir_filas_uso
from gnomilestone.store import Store
from gnomilestone.ui.board_settings_dialog import BoardSettingsDialog
from gnomilestone.ui.gantt_view import GanttView
from gnomilestone.ui.kanban_view import KanbanView
from gnomilestone.ui.resource_dialog import ResourceView
from gnomilestone.ui.resource_usage_view import ResourceUsageView
from gnomilestone.ui.table_view import TableView
from gnomilestone.ui.task_dialog import TaskDialog
from gnomilestone.ui.task_tree_view import construir_filas

log = logging.getLogger(__name__)

# Accesos del rail (estilo Planner): icono + etiqueta + tooltip.
_VISTAS_RAIL = (
    ("tabla", "view-list-symbolic", _("Lista"), _("Lista")),
    ("tablero", "view-dual-symbolic", _("Tablero"), _("Tablero")),
    ("gantt", "view-continuous-symbolic", _("Gantt"), _("Gantt")),
    ("recursos", "system-users-symbolic", _("Recursos"), _("Recursos")),
    ("uso", "preferences-system-time-symbolic", _("Uso"), _("Uso de recursos")),
)

_css_rail_aplicado = False


def _asegurar_css_rail() -> None:
    global _css_rail_aplicado
    if _css_rail_aplicado:
        return
    proveedor = Gtk.CssProvider()
    proveedor.load_from_string(
        ".gnomilestone-vista-rail { padding: 8px 4px; }\n"
        ".gnomilestone-vista-rail button { padding: 8px 6px; }\n"
        ".gnomilestone-vista-rail label { font-size: 0.85em; }\n"
    )
    Gtk.StyleContext.add_provider_for_display(
        Gdk.Display.get_default(), proveedor, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
    )
    _css_rail_aplicado = True


class ProjectDetailView(Gtk.Box):
    """Detalle de un proyecto: rail de vistas (Lista/Tablero/Gantt/Recursos/Uso) al estilo
    Planner, barra con Nueva tarea, y el contenido de la vista activa."""

    def __init__(self, store: Store) -> None:
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL)
        _asegurar_css_rail()
        self._store = store
        self._proyecto: Proyecto | None = None
        self._rail_buttons: dict[str, Gtk.ToggleButton] = {}

        self._vista_stack = Gtk.Stack(
            hexpand=True, vexpand=True, hhomogeneous=False, vhomogeneous=False
        )

        self.append(self._construir_rail())

        contenido = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True, vexpand=True)
        toolbar = Gtk.Box(spacing=6, margin_top=6, margin_bottom=6, margin_start=6, margin_end=6)
        new_task_button = Gtk.Button(label=_("Nueva tarea"))
        new_task_button.add_css_class("suggested-action")
        new_task_button.connect("clicked", self._on_new_task)
        toolbar.append(new_task_button)
        contenido.append(toolbar)

        self._tabla = TableView(
            on_editar_tarea=self._on_editar_tarea, on_eliminar_tarea=self._on_eliminar_tarea
        )
        self._vista_stack.add_named(self._tabla, "tabla")

        # Ajustes de columnas del Tablero: solo en esa vista (engranaje), no en la barra común.
        self._tablero = KanbanView(
            store,
            on_editar_tarea=self._on_editar_tarea,
            on_eliminar_tarea=self._on_eliminar_tarea,
            on_cambio=self.refrescar,
            on_abrir_ajustes=self._on_open_board_settings,
        )
        self._vista_stack.add_named(self._tablero, "tablero")

        self._gantt = GanttView(
            on_editar_tarea=self._on_editar_tarea,
            on_eliminar_tarea=self._on_eliminar_tarea,
            on_tarea_arrastrada=self._on_tarea_arrastrada,
        )
        self._vista_stack.add_named(self._gantt, "gantt")

        self._recursos = ResourceView(store, on_changed=self.refrescar)
        self._vista_stack.add_named(self._recursos, "recursos")

        self._uso = ResourceUsageView(on_editar_tarea=self._on_editar_tarea)
        self._vista_stack.add_named(self._uso, "uso")

        contenido.append(self._vista_stack)
        self.append(contenido)

        self._rail_buttons["tabla"].set_active(True)

    def _construir_rail(self) -> Gtk.Widget:
        rail = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        rail.add_css_class("gnomilestone-vista-rail")
        grupo: Gtk.ToggleButton | None = None
        for nombre, icono, etiqueta, tooltip in _VISTAS_RAIL:
            boton = Gtk.ToggleButton()
            boton.set_tooltip_text(tooltip)
            cuerpo = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            cuerpo.set_halign(Gtk.Align.CENTER)
            cuerpo.append(Gtk.Image.new_from_icon_name(icono))
            texto = Gtk.Label(label=etiqueta)
            texto.add_css_class("caption")
            cuerpo.append(texto)
            boton.set_child(cuerpo)
            if grupo is None:
                grupo = boton
            else:
                boton.set_group(grupo)
            boton.connect("toggled", self._on_rail_toggled, nombre)
            self._rail_buttons[nombre] = boton
            rail.append(boton)
        return rail

    def _on_rail_toggled(self, boton: Gtk.ToggleButton, nombre: str) -> None:
        if boton.get_active():
            self._vista_stack.set_visible_child_name(nombre)

    def mostrar_proyecto(self, proyecto: Proyecto) -> None:
        self._proyecto = proyecto
        self.refrescar()

    def refrescar(self) -> None:
        if self._proyecto is None:
            return
        estados = self._store.listar_estados(self._proyecto.id)
        estados_por_id = {estado.id: estado.nombre for estado in estados}
        tareas = self._store.listar_tareas(self._proyecto.id)
        recursos_por_tarea = self._store.listar_recursos_por_tarea(self._proyecto.id)

        self._tabla.set_tareas(tareas, estados, estados_por_id, recursos_por_tarea)

        filas_arbol = construir_filas(tareas, estados_por_id, recursos_por_tarea)
        dependencias = self._store.listar_dependencias(self._proyecto.id)
        self._gantt.set_filas(filas_arbol, dependencias)

        self._tablero.mostrar_proyecto(self._proyecto.id)
        self._recursos.mostrar_proyecto(self._proyecto.id)

        recursos = self._store.listar_recursos(self._proyecto.id)
        asignaciones = self._store.listar_asignaciones_del_proyecto(self._proyecto.id)
        self._uso.set_filas(construir_filas_uso(recursos, tareas, asignaciones), tareas)

    def _on_tarea_arrastrada(self, tarea_id: int, nueva_fecha_iso: str, nueva_duracion_dias: int) -> None:
        tarea = self._store.obtener_tarea(tarea_id)
        if tarea is None:
            return
        fecha_original = tarea.fecha_inicio
        duracion_original = tarea.duracion_dias
        tarea.fecha_inicio = nueva_fecha_iso
        tarea.duracion_dias = nueva_duracion_dias
        self._store.actualizar_tarea(tarea)
        self._propagar_jerarquia(tarea, fecha_original, duracion_original)
        self._propagar_dependencias(tarea.proyecto_id, tarea_id)
        self.refrescar()

    def _propagar_jerarquia(self, tarea: Tarea, fecha_original: str | None, duracion_original: int) -> None:
        # El padre manda: al moverlo, sus hijas le siguen (mismo delta); al redimensionarlo,
        # las que ya no quepan se recortan a su nuevo rango. Nunca al revés.
        tareas = self._store.listar_tareas(tarea.proyecto_id)
        if tarea.duracion_dias != duracion_original:
            cambiadas = ganttcalc.limitar_hijos_tras_redimensionar(
                tareas, tarea.id, ganttcalc.parse_fecha(tarea.fecha_inicio), tarea.duracion_dias
            )
        elif fecha_original and tarea.fecha_inicio != fecha_original:
            delta_dias = (
                ganttcalc.parse_fecha(tarea.fecha_inicio) - ganttcalc.parse_fecha(fecha_original)
            ).days
            cambiadas = ganttcalc.trasladar_hijos(tareas, tarea.id, delta_dias)
        else:
            cambiadas = []
        for cambiada in cambiadas:
            self._store.actualizar_tarea(cambiada)

    def _propagar_dependencias(self, proyecto_id: int, tarea_id: int) -> None:
        tareas = self._store.listar_tareas(proyecto_id)
        dependencias = self._store.listar_dependencias(proyecto_id)
        for cambiada in ganttcalc.recalcular_dependientes(tareas, dependencias, tarea_id):
            self._store.actualizar_tarea(cambiada)

    def _on_new_task(self, _button: Gtk.Button) -> None:
        if self._proyecto is None:
            return
        TaskDialog(
            self.get_root(), self._store, self._proyecto.id, on_saved=self.refrescar
        ).present()

    def _on_editar_tarea(self, tarea: Tarea) -> None:
        TaskDialog(
            self.get_root(), self._store, tarea.proyecto_id, on_saved=self.refrescar, tarea=tarea
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
        self.refrescar()

    def _on_open_board_settings(self) -> None:
        if self._proyecto is None:
            return
        BoardSettingsDialog(
            self.get_root(), self._store, self._proyecto.id, on_changed=self.refrescar
        ).present()
