from __future__ import annotations

from collections.abc import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, Gtk

from gnomilestone.i18n import _
from gnomilestone.models import Dependencia, Tarea
from gnomilestone.ui.gantt_drawing_area import GanttDrawingArea
from gnomilestone.ui.task_tree_view import TareaRow, TaskTreeView

_PASOS_ZOOM = (8.0, 12.0, 18.0, 24.0, 36.0, 54.0, 80.0)


class GanttView(Gtk.Box):
    """Árbol de tareas (izquierda) sincronizado en scroll vertical con el Gantt (derecha)."""

    def __init__(
        self,
        on_editar_tarea: Callable[[Tarea], None] | None = None,
        on_eliminar_tarea: Callable[[Tarea], None] | None = None,
        on_tarea_arrastrada: Callable[[int, str, int], None] | None = None,
    ) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self._indice_zoom = _PASOS_ZOOM.index(24.0)

        toolbar = Gtk.Box(spacing=6, margin_top=6, margin_bottom=6, margin_start=6, margin_end=6)
        zoom_out = Gtk.Button(icon_name="zoom-out-symbolic", tooltip_text=_("Alejar"))
        zoom_out.connect("clicked", self._on_zoom_out)
        toolbar.append(zoom_out)
        zoom_in = Gtk.Button(icon_name="zoom-in-symbolic", tooltip_text=_("Acercar"))
        zoom_in.connect("clicked", self._on_zoom_in)
        toolbar.append(zoom_in)
        self.append(toolbar)

        # Gtk.Paned (no una Gtk.Box fija): el reparto entre el árbol y el lienzo del Gantt
        # debe poder ajustarse arrastrando el divisor, además de poder redimensionar cada
        # columna del árbol por separado.
        panel = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL, position=420, vexpand=True)

        self._tree = TaskTreeView(on_editar=on_editar_tarea, on_eliminar=on_eliminar_tarea)
        self._tree.tree_model.connect("items-changed", self._on_filas_cambiadas)
        tree_scroller = Gtk.ScrolledWindow(vscrollbar_policy=Gtk.PolicyType.NEVER)
        tree_scroller.set_child(self._tree)
        panel.set_start_child(tree_scroller)
        panel.set_resize_start_child(False)
        panel.set_shrink_start_child(False)

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

        self._canvas_scroller = Gtk.ScrolledWindow(vexpand=True)
        self._canvas_scroller.set_child(self._drawing_area)
        self._canvas_scroller.set_vadjustment(tree_scroller.get_vadjustment())
        ruler_scroller.set_hadjustment(self._canvas_scroller.get_hadjustment())
        canvas_box.append(self._canvas_scroller)

        panel.set_end_child(canvas_box)
        panel.set_resize_end_child(True)
        self.append(panel)

        # Ctrl+rueda, además de los botones, para ajustar el nivel de zoom del Gantt.
        scroll = Gtk.EventControllerScroll(flags=Gtk.EventControllerScrollFlags.VERTICAL)
        scroll.connect("scroll", self._on_scroll)
        self._canvas_scroller.add_controller(scroll)

    def set_filas(self, filas: list[TareaRow], dependencias: list[Dependencia]) -> None:
        self._dependencias = dependencias
        self._tree.set_filas(filas)
        # set_filas() ya dispara "items-changed" (vía _on_filas_cambiadas), que repinta el Gantt.

    def _on_origen_desplazado(self, delta_px: float) -> None:
        # El lienzo ha crecido por la izquierda durante un arrastre (ver
        # GanttDrawingArea._ajustar_origen_si_hace_falta): se compensa el scroll para que
        # la barra arrastrada no "salte" de sitio al redefinirse dónde está su x=0.
        adj = self._canvas_scroller.get_hadjustment()
        adj.set_value(adj.get_value() + delta_px)

    def _on_filas_cambiadas(self, *_args) -> None:
        self._drawing_area.actualizar(self._tree.filas_visibles(), getattr(self, "_dependencias", []))

    def _on_zoom_in(self, _button: Gtk.Button | None = None) -> None:
        self._indice_zoom = min(self._indice_zoom + 1, len(_PASOS_ZOOM) - 1)
        self._drawing_area.set_zoom(_PASOS_ZOOM[self._indice_zoom])

    def _on_zoom_out(self, _button: Gtk.Button | None = None) -> None:
        self._indice_zoom = max(self._indice_zoom - 1, 0)
        self._drawing_area.set_zoom(_PASOS_ZOOM[self._indice_zoom])

    def _on_scroll(self, controller: Gtk.EventControllerScroll, _dx: float, dy: float) -> bool:
        estado = controller.get_current_event_state()
        if not (estado & Gdk.ModifierType.CONTROL_MASK):
            return False  # sin Ctrl, se deja desplazarse (scroll) con normalidad
        if dy < 0:
            self._on_zoom_in()
        elif dy > 0:
            self._on_zoom_out()
        return True  # con Ctrl, el scroll no desplaza: solo hace zoom
