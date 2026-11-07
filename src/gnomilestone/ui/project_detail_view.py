from __future__ import annotations

import logging
import threading

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, Gtk

from gnomilestone import ganttcalc
from gnomilestone.filtros import ocultar_completadas
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

        self._mostrar_completadas = True
        self._mostrar_completadas_check = Gtk.CheckButton(label=_("Mostrar completadas"))
        self._mostrar_completadas_check.set_active(True)
        self._mostrar_completadas_check.set_tooltip_text(
            _("Incluir en las vistas las tareas al 100 %")
        )
        self._mostrar_completadas_check.connect(
            "toggled", self._on_mostrar_completadas_toggled
        )
        toolbar.append(self._mostrar_completadas_check)

        toolbar.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))

        self._github_link_button = Gtk.Button(
            icon_name="github-symbolic",
            tooltip_text=_("Vincular con repositorio o proyecto de GitHub"),
        )
        self._github_link_button.connect("clicked", self._on_open_github_link)
        toolbar.append(self._github_link_button)

        self._sync_button = Gtk.Button(
            icon_name="view-refresh-symbolic",
            tooltip_text=_("Sincronizar con GitHub"),
        )
        self._sync_button.connect("clicked", self._on_sync_clicked)
        toolbar.append(self._sync_button)

        self._sync_progress = Gtk.ProgressBar(
            width_request=120, valign=Gtk.Align.CENTER, visible=False
        )
        toolbar.append(self._sync_progress)
        self._sync_pulse_id: int | None = None

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

        self._uso = ResourceUsageView(
            on_editar_tarea=self._on_editar_tarea,
            on_dedicacion_changed=self._on_dedicacion_changed,
        )
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
            # Recursos y Uso no listan tareas: el filtro no pinta nada ahí.
            self._mostrar_completadas_check.set_visible(
                nombre in ("tabla", "tablero", "gantt")
            )

    def _on_mostrar_completadas_toggled(self, check: Gtk.CheckButton) -> None:
        self._mostrar_completadas = check.get_active()
        self.refrescar()

    def mostrar_proyecto(self, proyecto: Proyecto) -> None:
        self._proyecto = proyecto
        self.refrescar()

    def refrescar(self) -> None:
        if self._proyecto is None:
            return
        estados = self._store.listar_estados(self._proyecto.id)
        estados_por_id = {estado.id: estado.nombre for estado in estados}
        tareas = self._store.listar_tareas(self._proyecto.id)
        tareas_visibles = tareas if self._mostrar_completadas else ocultar_completadas(tareas)
        recursos_por_tarea = self._store.listar_recursos_por_tarea(self._proyecto.id)

        self._tabla.set_tareas(tareas_visibles, estados, estados_por_id, recursos_por_tarea)

        filas_arbol = construir_filas(tareas_visibles, estados_por_id, recursos_por_tarea)
        dependencias = self._store.listar_dependencias(self._proyecto.id)
        self._gantt.set_filas(
            filas_arbol, dependencias, ganttcalc.progreso_resumen(tareas_visibles)
        )

        self._tablero.mostrar_proyecto(self._proyecto.id, self._mostrar_completadas)
        self._recursos.mostrar_proyecto(self._proyecto.id)

        recursos = self._store.listar_recursos(self._proyecto.id)
        asignaciones = self._store.listar_asignaciones_del_proyecto(self._proyecto.id)
        self._uso.set_filas(construir_filas_uso(recursos, tareas, asignaciones), tareas)

    def _on_dedicacion_changed(self, tarea_id: int, recurso_id: int, porcentaje: int) -> None:
        self._store.actualizar_dedicacion(tarea_id, recurso_id, porcentaje)

    def _on_tarea_arrastrada(self, tarea_id: int, nueva_fecha_iso: str, nueva_duracion_dias: int) -> None:
        tarea = self._store.obtener_tarea(tarea_id)
        if tarea is None:
            return
        fecha_original = tarea.fecha_inicio
        duracion_original = tarea.duracion_dias
        tarea.fecha_inicio = nueva_fecha_iso
        tarea.duracion_dias = nueva_duracion_dias
        tarea = ganttcalc.sincronizar_fin_planificado(tarea)
        self._store.actualizar_tarea(tarea)
        afectadas = {tarea.id}
        afectadas |= self._propagar_jerarquia(tarea, fecha_original, duracion_original)
        afectadas |= self._propagar_dependencias(tarea.proyecto_id, tarea_id)
        self.refrescar()
        # Mover o redimensionar en el Gantt cambia fechas tanto como guardar el diálogo de
        # tarea, y de la misma forma debe llegar a GitHub si el proyecto está vinculado
        # (incluye las tareas afectadas en cascada: jerarquía y dependencias).
        self._push_a_github(afectadas)

    def _propagar_jerarquia(
        self, tarea: Tarea, fecha_original: str | None, duracion_original: int
    ) -> set[int]:
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
        return {cambiada.id for cambiada in cambiadas}

    def _propagar_dependencias(self, proyecto_id: int, tarea_id: int) -> set[int]:
        tareas = self._store.listar_tareas(proyecto_id)
        dependencias = self._store.listar_dependencias(proyecto_id)
        cambiadas = ganttcalc.recalcular_dependientes(tareas, dependencias, tarea_id)
        for cambiada in cambiadas:
            self._store.actualizar_tarea(cambiada)
        return {cambiada.id for cambiada in cambiadas}

    def _push_a_github(self, tarea_ids: set[int]) -> None:
        if self._proyecto is None:
            return
        if not (self._proyecto.github_repo_name or self._proyecto.github_project_v2_id):
            return

        def _push() -> None:
            from gnomilestone.sync import GitHubSyncManager

            sync = GitHubSyncManager(self._store)
            for tarea_id in tarea_ids:
                try:
                    sync.push_tarea(tarea_id)
                except Exception:
                    log.debug("Error enviando tarea %s a GitHub", tarea_id, exc_info=True)

        threading.Thread(target=_push, daemon=True).start()

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

    def _on_open_github_link(self, _button: Gtk.Button) -> None:
        if self._proyecto is None:
            return
        from gnomilestone.ui.github_link_dialog import GitHubLinkDialog

        GitHubLinkDialog(
            self.get_root(), self._store, self._proyecto, on_linked=self.refrescar
        ).present()

    def _on_sync_clicked(self, _button: Gtk.Button) -> None:
        if self._proyecto is None:
            return
        if not self._proyecto.github_repo_owner:
            self._on_open_github_link(_button)
            return

        from gi.repository import GLib

        from gnomilestone.sync import GitHubSyncManager

        self._sync_progress.set_fraction(0.0)
        self._sync_progress.set_visible(True)
        self._sync_pulse_id = GLib.timeout_add(100, self._on_sync_pulse)
        self._sync_button.set_sensitive(False)

        def _do_sync() -> None:
            sync = GitHubSyncManager(self._store)
            res = sync.pull_proyecto(self._proyecto.id)

            def _done() -> bool:
                if self._sync_pulse_id is not None:
                    GLib.source_remove(self._sync_pulse_id)
                    self._sync_pulse_id = None
                self._sync_progress.set_visible(False)
                self._sync_button.set_sensitive(True)
                self.refrescar()
                avisos = list(res.errores) + list(res.conflictos)
                if avisos:
                    dialog = Gtk.AlertDialog()
                    dialog.set_message(_("Sincronización con GitHub"))
                    dialog.set_detail("\n".join(avisos))
                    dialog.show(self.get_root())
                return False

            GLib.idle_add(_done)

        threading.Thread(target=_do_sync, daemon=True).start()

    def _on_sync_pulse(self) -> bool:
        # pull_proyecto() es una sola llamada de bloque, sin pasos intermedios que
        # reportar, así que no hay un % de verdad que mostrar: una barra "pulsando"
        # (como el spinner, pero más visible) indica que sigue en marcha sin fingir
        # una precisión que no se tiene.
        self._sync_progress.pulse()
        return True
