from __future__ import annotations

from collections.abc import Callable
from datetime import date, timedelta

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, GLib, Gtk

from gnomilestone import settings
from gnomilestone.i18n import _
from gnomilestone.models import Dependencia, Tarea
from gnomilestone.ui.gantt_drawing_area import GanttDrawingArea
from gnomilestone.ui.task_tree_view import TareaRow, TaskTreeView

_PASOS_ZOOM = (8.0, 12.0, 18.0, 24.0, 36.0, 54.0, 80.0)
_ESCALAS = (("Semanal", 36.0), ("Mensual", 18.0), ("Trimestral", 8.0), ("Anual", 4.0))


class GanttView(Gtk.Box):
    """Árbol de tareas (izquierda) sincronizado en scroll vertical con el Gantt (derecha)."""

    def __init__(
        self,
        on_editar_tarea: Callable[[Tarea], None] | None = None,
        on_eliminar_tarea: Callable[[Tarea], None] | None = None,
        on_tarea_arrastrada: Callable[[int, str, int], None] | None = None,
    ) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self._indice_zoom = _PASOS_ZOOM.index(36.0)
        self._escala_activa = "Semanal"
        self._timeout_guardar_ancho: int | None = None
        self._ultimo_ancho_guardado: int | None = None

        self._tree = TaskTreeView(on_editar=on_editar_tarea, on_eliminar=on_eliminar_tarea)
        self._tree.tree_model.connect("items-changed", self._on_filas_cambiadas)
        self._aplicar_columnas_visibles()

        toolbar = Gtk.Box(spacing=6, margin_top=6, margin_bottom=6, margin_start=6, margin_end=6)

        self._btn_sidebar = Gtk.ToggleButton(
            icon_name="sidebar-show-symbolic",
            tooltip_text=_("Ocultar lista de tareas"),
            active=True,
        )
        self._btn_sidebar.connect("toggled", self._on_toggle_sidebar)
        toolbar.append(self._btn_sidebar)

        self._btn_columnas = self._crear_menu_columnas()
        toolbar.append(self._btn_columnas)

        toolbar.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))

        zoom_out = Gtk.Button(icon_name="zoom-out-symbolic", tooltip_text=_("Alejar"))
        zoom_out.connect("clicked", self._on_zoom_out)
        toolbar.append(zoom_out)
        zoom_in = Gtk.Button(icon_name="zoom-in-symbolic", tooltip_text=_("Acercar"))
        zoom_in.connect("clicked", self._on_zoom_in)
        toolbar.append(zoom_in)
        toolbar.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))
        for etiqueta, px_por_dia in _ESCALAS:
            boton_escala = Gtk.Button(label=_(etiqueta))
            boton_escala.add_css_class("flat")
            boton_escala.connect("clicked", self._on_escala, etiqueta, px_por_dia)
            toolbar.append(boton_escala)
        self.append(toolbar)

        # Gtk.Paned (no una Gtk.Box fija): el reparto entre el árbol y el lienzo del Gantt
        # debe poder ajustarse arrastrando el divisor, además de poder redimensionar cada
        # columna del árbol por separado.
        ancho_panel = settings.read_settings().get("gantt_panel_ancho", 240)
        panel = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL, position=ancho_panel, vexpand=True)

        self._tree_scroller = Gtk.ScrolledWindow(vscrollbar_policy=Gtk.PolicyType.NEVER)
        self._tree_scroller.set_child(self._tree)
        panel.set_start_child(self._tree_scroller)
        panel.set_resize_start_child(False)
        panel.set_shrink_start_child(True)
        panel.connect("notify::position", self._on_posicion_panel)
        self._panel = panel

        canvas_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True)

        self._drawing_area = GanttDrawingArea(
            on_tarea_arrastrada=on_tarea_arrastrada,
            on_origen_desplazado=self._on_origen_desplazado,
            on_editar_tarea=on_editar_tarea,
        )
        self._drawing_area.set_zoom(_PASOS_ZOOM[self._indice_zoom])

        ruler_scroller = Gtk.ScrolledWindow(
            vscrollbar_policy=Gtk.PolicyType.NEVER, hscrollbar_policy=Gtk.PolicyType.NEVER
        )
        ruler_scroller.set_child(self._drawing_area.ruler)
        canvas_box.append(ruler_scroller)

        self._canvas_scroller = Gtk.ScrolledWindow(
            vexpand=True,
            hexpand=True,
            hscrollbar_policy=Gtk.PolicyType.ALWAYS,
            vscrollbar_policy=Gtk.PolicyType.NEVER,
        )
        self._canvas_scroller.set_child(self._drawing_area)
        self._canvas_scroller.set_vadjustment(self._tree_scroller.get_vadjustment())
        ruler_scroller.set_hadjustment(self._canvas_scroller.get_hadjustment())
        canvas_box.append(self._canvas_scroller)

        panel.set_end_child(canvas_box)
        panel.set_resize_end_child(True)
        self.append(panel)

        # Ctrl+rueda, además de los botones, para ajustar el nivel de zoom del Gantt.
        scroll = Gtk.EventControllerScroll(flags=Gtk.EventControllerScrollFlags.VERTICAL)
        scroll.connect("scroll", self._on_scroll)
        self._canvas_scroller.add_controller(scroll)

    def set_filas(
        self,
        filas: list[TareaRow],
        dependencias: list[Dependencia],
        progreso_resumen: dict[int, int] | None = None,
    ) -> None:
        self._dependencias = dependencias
        self._progreso_resumen = progreso_resumen or {}
        self._tree.set_filas(filas)
        # set_filas() ya dispara "items-changed" (vía _on_filas_cambiadas), que repinta el Gantt.

    def _on_origen_desplazado(self, delta_px: float) -> None:
        # El lienzo ha crecido por la izquierda durante un arrastre (ver
        # GanttDrawingArea._ajustar_origen_si_hace_falta): se compensa el scroll para que
        # la barra arrastrada no "salte" de sitio al redefinirse dónde está su x=0.
        adj = self._canvas_scroller.get_hadjustment()
        adj.set_value(adj.get_value() + delta_px)

    def _on_filas_cambiadas(self, *_args) -> None:
        self._drawing_area.actualizar(
            self._tree.filas_visibles(),
            getattr(self, "_dependencias", []),
            getattr(self, "_progreso_resumen", {}),
        )
        # Las tareas históricas no deben dejar la vista inicial semanas/meses atrás.
        GLib.idle_add(self._centrar_en_hoy)

    def _on_zoom_in(self, _button: Gtk.Button | None = None) -> None:
        self._indice_zoom = min(self._indice_zoom + 1, len(_PASOS_ZOOM) - 1)
        self._drawing_area.set_zoom(_PASOS_ZOOM[self._indice_zoom])

    def _on_zoom_out(self, _button: Gtk.Button | None = None) -> None:
        self._indice_zoom = max(self._indice_zoom - 1, 0)
        self._drawing_area.set_zoom(_PASOS_ZOOM[self._indice_zoom])

    def _on_escala(self, _button: Gtk.Button, etiqueta: str, px_por_dia: float) -> None:
        self._escala_activa = etiqueta
        self._drawing_area.set_zoom(px_por_dia)
        self._indice_zoom = min(
            range(len(_PASOS_ZOOM)), key=lambda i: abs(_PASOS_ZOOM[i] - px_por_dia)
        )
        GLib.idle_add(self._centrar_en_hoy)

    def _centrar_en_hoy(self) -> bool:
        adj = self._canvas_scroller.get_hadjustment()
        if adj.get_page_size() <= 0:
            # El lienzo aún no está asignado: no volver a registrar el idle sin fin,
            # porque eso mantiene la aplicación al 100 % de CPU.
            return False
        hoy = date.today()
        if self._escala_activa == "Semanal":
            hoy -= timedelta(days=hoy.weekday())
        hoy_x = (hoy - self._drawing_area.fecha_origen).days * self._drawing_area.px_por_dia
        valor = max(0.0, hoy_x - adj.get_page_size() * (0.05 if self._escala_activa == "Semanal" else 0.35))
        adj.set_value(min(valor, max(0.0, adj.get_upper() - adj.get_page_size())))
        return False

    def _on_scroll(self, controller: Gtk.EventControllerScroll, _dx: float, dy: float) -> bool:
        estado = controller.get_current_event_state()
        if not (estado & Gdk.ModifierType.CONTROL_MASK):
            return False  # sin Ctrl, se deja desplazarse (scroll) con normalidad
        if dy < 0:
            self._on_zoom_in()
        elif dy > 0:
            self._on_zoom_out()
        return True  # con Ctrl, el scroll no desplaza: solo hace zoom

    def _crear_menu_columnas(self) -> Gtk.MenuButton:
        popover = Gtk.Popover()
        box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=4,
            margin_top=8,
            margin_bottom=8,
            margin_start=8,
            margin_end=8,
        )
        titulo = Gtk.Label(label=_("Columnas visibles"), xalign=0)
        titulo.add_css_class("heading")
        box.append(titulo)

        for clave, etiqueta, fija in self._tree.columnas_disponibles():
            check = Gtk.CheckButton(label=etiqueta)
            check.set_active(self._tree.is_columna_visible(clave))
            if fija:
                check.set_sensitive(False)
            else:
                check.connect("toggled", self._on_columna_toggled, clave)
            box.append(check)

        popover.set_child(box)
        return Gtk.MenuButton(
            icon_name="view-more-symbolic",
            tooltip_text=_("Columnas visibles"),
            popover=popover,
        )

    def _aplicar_columnas_visibles(self) -> None:
        config = settings.read_settings().get("gantt_columnas_visibles")
        if config is not None:
            for clave, visible in config.items():
                if clave != "titulo":
                    self._tree.set_columna_visible(clave, bool(visible))

    def _on_columna_toggled(self, check: Gtk.CheckButton, clave: str) -> None:
        self._tree.set_columna_visible(clave, check.get_active())
        visibles = {
            c_clave: self._tree.is_columna_visible(c_clave)
            for c_clave, _etiqueta, _fija in self._tree.columnas_disponibles()
        }
        config = settings.read_settings()
        config["gantt_columnas_visibles"] = visibles
        settings.write_settings(config)

    def _on_toggle_sidebar(self, btn: Gtk.ToggleButton) -> None:
        activo = btn.get_active()
        self._tree_scroller.set_visible(activo)
        self._btn_columnas.set_sensitive(activo)
        btn.set_tooltip_text(_("Ocultar lista de tareas") if activo else _("Mostrar lista de tareas"))

    def _on_posicion_panel(self, panel: Gtk.Paned, _pspec) -> None:
        if not getattr(self, "_btn_sidebar", None) or not self._btn_sidebar.get_active():
            return
        pos = panel.get_position()
        if pos > 80:
            if self._ultimo_ancho_guardado == pos:
                return
            self._ultimo_ancho_guardado = pos
            if self._timeout_guardar_ancho is not None:
                GLib.source_remove(self._timeout_guardar_ancho)
            self._timeout_guardar_ancho = GLib.timeout_add(300, self._guardar_ancho_panel, pos)

    def _guardar_ancho_panel(self, pos: int) -> bool:
        self._timeout_guardar_ancho = None
        config = settings.read_settings()
        config["gantt_panel_ancho"] = pos
        settings.write_settings(config)
        return False
