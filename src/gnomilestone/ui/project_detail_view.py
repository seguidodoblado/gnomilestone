from __future__ import annotations

import logging
import threading
from datetime import date, timedelta
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, GLib, Gtk

from gnomilestone import ganttcalc
from gnomilestone.filtros import ocultar_completadas
from gnomilestone.i18n import _
from gnomilestone.models import Proyecto, Tarea
from gnomilestone.resource_usage import construir_filas_uso
from gnomilestone.store import Store
from gnomilestone.sync import GitHubSyncManager
from gnomilestone.ui.archived_dialog import ArchivedTasksDialog
from gnomilestone.ui.board_settings_dialog import BoardSettingsDialog
from gnomilestone.ui.documentation_view import DocumentationView
from gnomilestone.ui.gantt_view import GanttView
from gnomilestone.ui.kanban_view import KanbanView
from gnomilestone.ui.labels_dialog import LabelsDialog
from gnomilestone.ui.report_view import ReportView
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
    ("informes", "x-office-chart-bar-symbolic", _("Informes"), _("Informes del proyecto")),
    (
        "documentacion",
        "text-x-generic-symbolic",
        _("Documentación"),
        _("Documentación del proyecto"),
    ),
)

_css_rail_aplicado = False
_REPORT_ICON = Path(__file__).resolve().parent.parent / "assets" / "mintinstall-office-symbolic.svg"


def _asegurar_css_rail() -> None:
    global _css_rail_aplicado
    if _css_rail_aplicado:
        return
    proveedor = Gtk.CssProvider()
    proveedor.load_from_string(
        ".gnomilestone-vista-rail { padding: 10px 6px; }\n"
        ".gnomilestone-vista-rail button { padding: 12px 10px; min-width: 64px; }\n"
        ".gnomilestone-vista-rail label { font-size: 1em; }\n"
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

        # Visibles por defecto en todas las vistas; para quitar de en medio las que ya no
        # interesan está «Archivar» (con su vista de archivadas para recuperarlas).
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

        toolbar.append(self._construir_menu_archivo())

        etiquetas_button = Gtk.Button(
            icon_name="etiqueta-symbolic", tooltip_text=_("Etiquetas del proyecto")
        )
        etiquetas_button.connect("clicked", self._on_open_labels)
        toolbar.append(etiquetas_button)

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
            on_editar_tarea=self._on_editar_tarea,
            on_eliminar_tarea=self._on_eliminar_tarea,
            on_archivar_tarea=self._on_archivar_tarea,
        )
        self._vista_stack.add_named(self._tabla, "tabla")

        # Ajustes de columnas del Tablero: solo en esa vista (engranaje), no en la barra común.
        self._tablero = KanbanView(
            store,
            on_editar_tarea=self._on_editar_tarea,
            on_eliminar_tarea=self._on_eliminar_tarea,
            on_cambio=self.refrescar,
            on_abrir_ajustes=self._on_open_board_settings,
            on_archivar_tarea=self._on_archivar_tarea,
        )
        self._vista_stack.add_named(self._tablero, "tablero")

        self._gantt = GanttView(
            on_editar_tarea=self._on_editar_tarea,
            on_eliminar_tarea=self._on_eliminar_tarea,
            on_tarea_arrastrada=self._on_tarea_arrastrada,
            on_archivar_tarea=self._on_archivar_tarea,
        )
        self._vista_stack.add_named(self._gantt, "gantt")

        self._recursos = ResourceView(store, on_changed=self.refrescar)
        self._vista_stack.add_named(self._recursos, "recursos")

        self._uso = ResourceUsageView(
            on_editar_tarea=self._on_editar_tarea,
            on_dedicacion_changed=self._on_dedicacion_changed,
        )
        self._vista_stack.add_named(self._uso, "uso")
        self._informes = ReportView()
        self._vista_stack.add_named(self._informes, "informes")
        self._documentacion = DocumentationView(store, self._on_abrir_tarea_por_id)
        self._vista_stack.add_named(self._documentacion, "documentacion")

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
            if nombre == "informes":
                imagen = Gtk.Image.new_from_file(str(_REPORT_ICON))
            else:
                imagen = Gtk.Image.new_from_icon_name(icono)
            imagen.set_pixel_size(28)
            cuerpo.append(imagen)
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
            # Recursos y Documentación no listan tareas: el filtro no pinta nada ahí.
            self._mostrar_completadas_check.set_visible(
                nombre in ("tabla", "tablero", "gantt", "uso", "informes")
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
        # El progreso de una tarea resumen cuenta también a sus subtareas archivadas.
        tareas_con_archivadas = self._store.listar_tareas(
            self._proyecto.id, incluir_archivadas=True
        )
        tareas = [t for t in tareas_con_archivadas if not t.archivada]
        tareas_visibles = tareas if self._mostrar_completadas else ocultar_completadas(tareas)
        recursos_por_tarea = self._store.listar_recursos_por_tarea(self._proyecto.id)

        etiquetas_por_tarea = self._store.listar_etiquetas_por_tarea(self._proyecto.id)

        self._tabla.set_tareas(
            tareas_visibles, estados, estados_por_id, recursos_por_tarea, etiquetas_por_tarea
        )

        filas_arbol = construir_filas(
            tareas_visibles, estados_por_id, recursos_por_tarea, etiquetas_por_tarea
        )
        dependencias = self._store.listar_dependencias(self._proyecto.id)
        self._gantt.set_filas(
            filas_arbol, dependencias, ganttcalc.progreso_resumen(tareas_con_archivadas)
        )

        self._tablero.mostrar_proyecto(self._proyecto.id, self._mostrar_completadas)
        self._recursos.mostrar_proyecto(self._proyecto.id)
        self._documentacion.mostrar_proyecto(self._proyecto, tareas_con_archivadas, dependencias)

        recursos = self._store.listar_recursos(self._proyecto.id)
        asignaciones = self._store.listar_asignaciones_del_proyecto(self._proyecto.id)
        tareas_uso = tareas_visibles
        self._uso.set_filas(construir_filas_uso(recursos, tareas_uso, asignaciones), tareas_uso)
        self._informes.set_data(
            tareas_visibles, estados, recursos, asignaciones,
            dependencias=self._store.listar_dependencias(self._proyecto.id),
        )

    def _on_dedicacion_changed(self, tarea_id: int, recurso_id: int, porcentaje: int) -> None:
        self._store.actualizar_dedicacion(tarea_id, recurso_id, porcentaje)
        self.refrescar()

    def _on_tarea_arrastrada(self, tarea_id: int, nueva_fecha_iso: str, nueva_duracion_dias: int) -> None:
        tarea = self._store.obtener_tarea(tarea_id)
        if tarea is None:
            return
        nuevo_fin = date.fromisoformat(nueva_fecha_iso) + timedelta(
            days=max(nueva_duracion_dias, 1) - 1
        )
        if tarea.fecha_limite and nuevo_fin > date.fromisoformat(tarea.fecha_limite):
            self._pedir_nueva_fecha_limite(tarea, nueva_fecha_iso, nueva_duracion_dias, nuevo_fin)
            return
        self._aplicar_movimiento_tarea(tarea, nueva_fecha_iso, nueva_duracion_dias)

    def _pedir_nueva_fecha_limite(
        self, tarea: Tarea, nueva_fecha_iso: str, nueva_duracion_dias: int, nuevo_fin: date
    ) -> None:
        ventana = Gtk.Window(
            title=_("Nueva fecha límite"),
            transient_for=self.get_root(),
            modal=True,
            default_width=360,
            default_height=420,
        )
        caja = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=12,
            margin_top=18,
            margin_bottom=18,
            margin_start=18,
            margin_end=18,
        )
        ventana.set_child(caja)
        caja.append(
            Gtk.Label(
                label=_(
                    "La nueva fecha de finalización ({fecha}) supera la fecha límite actual. "
                    "Selecciona una nueva fecha límite."
                ).format(fecha=nuevo_fin.strftime("%d/%m/%Y")),
                wrap=True,
                xalign=0,
            )
        )
        calendario = Gtk.Calendar()
        fecha_inicial = max(date.fromisoformat(tarea.fecha_limite), nuevo_fin)
        calendario.select_day(
            GLib.DateTime.new_local(
                fecha_inicial.year, fecha_inicial.month, fecha_inicial.day, 0, 0, 0
            )
        )
        caja.append(calendario)
        error = Gtk.Label(xalign=0, wrap=True)
        error.add_css_class("error")
        caja.append(error)
        botones = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8, halign=Gtk.Align.END)
        cancelar = Gtk.Button(label=_("Cancelar"))
        aceptar = Gtk.Button(label=_("Mover y actualizar fecha"))
        aceptar.add_css_class("suggested-action")
        botones.append(cancelar)
        botones.append(aceptar)
        caja.append(botones)

        cancelar.connect("clicked", lambda _button: ventana.close())

        def confirmar(_button: Gtk.Button) -> None:
            seleccion = calendario.get_date()
            fecha_limite = date(
                seleccion.get_year(), seleccion.get_month(), seleccion.get_day_of_month()
            )
            if fecha_limite < nuevo_fin:
                error.set_text(
                    _("La fecha límite debe ser igual o posterior al {fecha}.").format(
                        fecha=nuevo_fin.strftime("%d/%m/%Y")
                    )
                )
                return
            tarea.fecha_limite = fecha_limite.isoformat()
            ventana.close()
            self._aplicar_movimiento_tarea(tarea, nueva_fecha_iso, nueva_duracion_dias)

        aceptar.connect("clicked", confirmar)
        ventana.present()

    def _aplicar_movimiento_tarea(
        self, tarea: Tarea, nueva_fecha_iso: str, nueva_duracion_dias: int
    ) -> None:
        fecha_original = tarea.fecha_inicio
        duracion_original = tarea.duracion_dias
        tarea.fecha_inicio = nueva_fecha_iso
        tarea.duracion_dias = nueva_duracion_dias
        tarea = ganttcalc.sincronizar_fin_planificado(tarea)
        self._store.actualizar_tarea(tarea)
        afectadas = {tarea.id}
        afectadas |= self._propagar_jerarquia(tarea, fecha_original, duracion_original)
        afectadas |= self._propagar_dependencias(tarea.proyecto_id, tarea.id)
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

    def _on_abrir_tarea_por_id(self, tarea_id: int) -> None:
        tarea = self._store.obtener_tarea(tarea_id)
        if tarea is not None:
            self._on_editar_tarea(tarea)

    def _on_editar_tarea(self, tarea: Tarea) -> None:
        TaskDialog(
            self.get_root(), self._store, tarea.proyecto_id, on_saved=self.refrescar, tarea=tarea
        ).present()

    def _construir_menu_archivo(self) -> Gtk.MenuButton:
        """Menú «Archivo»: archivar las completadas y abrir la lista de archivadas."""
        caja = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=4,
            margin_top=6,
            margin_bottom=6,
            margin_start=6,
            margin_end=6,
        )
        archivar = Gtk.Button(label=_("Archivar completadas…"))
        archivar.add_css_class("flat")
        archivar.connect("clicked", self._on_archivar_completadas)
        caja.append(archivar)
        self._ver_archivadas_button = Gtk.Button(label=_("Tareas archivadas…"))
        self._ver_archivadas_button.add_css_class("flat")
        self._ver_archivadas_button.connect("clicked", self._on_ver_archivadas)
        caja.append(self._ver_archivadas_button)
        popover = Gtk.Popover()
        popover.set_child(caja)
        self._menu_archivo_popover = popover
        popover.connect("show", self._on_menu_archivo_visible)
        return Gtk.MenuButton(
            icon_name="archivar-symbolic",
            tooltip_text=_("Archivo de tareas"),
            popover=popover,
        )

    def _on_menu_archivo_visible(self, _popover: Gtk.Popover) -> None:
        n = (
            len(self._store.listar_tareas_archivadas(self._proyecto.id))
            if self._proyecto is not None
            else 0
        )
        self._ver_archivadas_button.set_label(
            _("Tareas archivadas ({n})…").format(n=n) if n else _("Tareas archivadas…")
        )

    def _on_ver_archivadas(self, _button: Gtk.Button) -> None:
        self._menu_archivo_popover.popdown()
        if self._proyecto is None:
            return
        ArchivedTasksDialog(
            self.get_root(), self._store, self._proyecto.id, on_changed=self.refrescar
        ).present()

    def _on_archivar_completadas(self, _button: Gtk.Button) -> None:
        self._menu_archivo_popover.popdown()
        if self._proyecto is None:
            return
        dialog = Gtk.AlertDialog()
        dialog.set_message(_("Archivar tareas completadas"))
        dialog.set_detail(
            _(
                "Las tareas completadas (con toda su rama al 100 %) dejarán de verse en todas "
                "las vistas. Podrás recuperarlas desde «Tareas archivadas»."
            )
        )
        dialog.set_buttons([_("Cancelar"), _("Archivar")])
        dialog.set_cancel_button(0)
        dialog.set_default_button(0)
        dialog.choose(self.get_root(), None, self._on_archivar_completadas_respuesta)

    def _on_archivar_completadas_respuesta(self, dialog: Gtk.AlertDialog, result) -> None:
        try:
            eleccion = dialog.choose_finish(result)
        except GLib.Error:  # diálogo cancelado o cerrado
            return
        if eleccion == 1 and self._proyecto is not None:
            self._store.archivar_completadas(self._proyecto.id)
            self.refrescar()

    def _on_archivar_tarea(self, tarea: Tarea) -> None:
        self._store.archivar_tarea(tarea.id)
        self.refrescar()

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
        GitHubSyncManager(self._store).eliminar_tarea(tarea.id)
        self.refrescar()

    def _on_open_labels(self, _button: Gtk.Button) -> None:
        if self._proyecto is None:
            return
        LabelsDialog(
            self.get_root(), self._store, self._proyecto.id, on_changed=self.refrescar
        ).present()

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
                    # También a la terminal: el diálogo no permite copiar el texto.
                    log.warning("Avisos de la sincronización con GitHub:\n%s", "\n".join(avisos))
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
