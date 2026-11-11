from __future__ import annotations

from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gio, Gtk

from gnomilestone.i18n import _
from gnomilestone.models import Proyecto
from gnomilestone.store import Store
from gnomilestone.ui.about import build_about_dialog
from gnomilestone.ui.global_gantt_view import GlobalGanttView
from gnomilestone.ui.project_detail_view import ProjectDetailView
from gnomilestone.ui.project_list_view import ProjectListView

_GLOBE_ICON = Path(__file__).resolve().parent.parent / "assets" / "globe-symbolic.svg"


def _globe_icon_path() -> Path:
    settings = Gtk.Settings.get_default()
    dark = bool(settings and "dark" in (settings.get_property("gtk-theme-name") or "").lower())
    return _GLOBE_ICON.with_name("globe-symbolic-dark.svg" if dark else "globe-symbolic-light.svg")


class MainWindow(Gtk.ApplicationWindow):
    def __init__(self, application: Gtk.Application) -> None:
        super().__init__(
            application=application,
            title="GnoMilestone",
            default_width=1000,
            default_height=700,
        )
        self._store = Store()
        self._proyecto_actual: Proyecto | None = None

        header = Gtk.HeaderBar()
        header.set_title_widget(Gtk.Label(label="GnoMilestone"))
        sidebar_button = Gtk.ToggleButton(
            icon_name="sidebar-show-symbolic", tooltip_text=_("Mostrar/ocultar proyectos"),
            active=True,
        )
        sidebar_button.connect("toggled", self._on_sidebar_toggled)
        header.pack_start(sidebar_button)
        home_button = Gtk.Button(
            icon_name="go-home-symbolic", tooltip_text=_("Pantalla inicial")
        )
        home_button.connect("clicked", self._on_home_clicked)
        header.pack_start(home_button)
        global_button = Gtk.ToggleButton()
        global_button.set_tooltip_text(_("Vista global"))
        global_content = Gtk.Box(spacing=6)
        global_content.append(Gtk.Image.new_from_file(str(_globe_icon_path())))
        global_content.append(Gtk.Label(label=_("Vista global")))
        global_button.set_child(global_content)
        global_button.connect("toggled", self._on_global_toggled)
        header.pack_start(global_button)
        header.pack_end(self._build_menu_button())
        self.set_titlebar(header)
        self._global_button = global_button

        self._paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL, position=300)
        self._project_list = ProjectListView(self._store, on_select=self._on_project_selected)
        self._paned.set_start_child(self._project_list)
        self._paned.set_resize_start_child(False)
        self._paned.set_shrink_start_child(False)

        # No homogéneo: por defecto Gtk.Stack mide su ancho/alto como el máximo entre
        # TODAS sus páginas (aunque no estén visibles), no solo la activa. La página del
        # Gantt pide mucho ancho (según el rango de fechas del proyecto), lo que desplazaba
        # el centrado del estado vacío aunque esa página ni se estuviera mostrando.
        self._detail_stack = Gtk.Stack(
            hexpand=True, vexpand=True, hhomogeneous=False, vhomogeneous=False
        )
        self._detail_stack.add_named(self._build_empty_state(), "empty")
        self._project_detail = ProjectDetailView(
            self._store, on_avance_changed=self._project_list.refresh
        )
        self._detail_stack.add_named(self._project_detail, "detail")
        self._global_gantt = GlobalGanttView(self._store)
        self._detail_stack.add_named(self._global_gantt, "global")
        self._detail_stack.set_visible_child_name("empty")
        self._paned.set_end_child(self._detail_stack)
        self._paned.set_resize_end_child(True)

        self.set_child(self._paned)

    def _build_menu_button(self) -> Gtk.Widget:
        # Menú de la cabecera: botones con icono del sistema (simbólico, con el normal como
        # alternativa si el tema no lo tiene) y etiqueta, como en Bloguero y Telegraph Writer.
        popover = Gtk.Popover()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        box.set_margin_start(6)
        box.set_margin_end(6)
        box.set_margin_top(6)
        box.set_margin_bottom(6)

        entries = (
            (
                _("Preferencias"),
                ("preferences-system-symbolic", "preferences-system"),
                self._open_preferences,
            ),
            (
                _("Acerca de GnoMilestone"),
                ("help-about-symbolic", "help-about"),
                self._open_about,
            ),
        )
        for label, icon_names, callback in entries:
            item = Gtk.Button()
            content = Gtk.Box(spacing=8)
            icon = Gio.ThemedIcon.new_from_names(list(icon_names))
            content.append(Gtk.Image.new_from_gicon(icon))
            content.append(Gtk.Label(label=label, xalign=0))
            item.set_child(content)
            item.set_halign(Gtk.Align.FILL)
            item.connect("clicked", lambda _btn, fn=callback: (popover.popdown(), fn()))
            box.append(item)
        popover.set_child(box)

        menu_button = Gtk.MenuButton(
            icon_name="open-menu-symbolic", tooltip_text=_("Menú principal")
        )
        menu_button.set_popover(popover)
        return menu_button

    def _open_preferences(self) -> None:
        from gnomilestone.ui.preferences import PreferencesWindow

        PreferencesWindow(self.get_application()).present()

    def _open_about(self) -> None:
        build_about_dialog(self).present()

    def _build_empty_state(self) -> Gtk.Widget:
        box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=12,
            halign=Gtk.Align.CENTER,
            valign=Gtk.Align.CENTER,
            hexpand=True,
            vexpand=True,
        )
        icon = Gtk.Image.new_from_icon_name("folder-new-symbolic")
        icon.set_pixel_size(64)
        icon.add_css_class("dim-label")
        box.append(icon)
        label = Gtk.Label(
            label=_("Selecciona o crea un proyecto"),
            wrap=True,
            justify=Gtk.Justification.CENTER,
            max_width_chars=30,
        )
        label.add_css_class("title-2")
        box.append(label)
        crear_button = Gtk.Button(label=_("Crear proyecto"))
        crear_button.add_css_class("suggested-action")
        crear_button.add_css_class("pill")
        crear_button.connect("clicked", self._on_crear_proyecto_rapido)
        box.append(crear_button)
        return box

    def _on_home_clicked(self, _button: Gtk.Button) -> None:
        self._global_button.set_active(False)
        self._project_list.deseleccionar()

    def _on_crear_proyecto_rapido(self, _button: Gtk.Button) -> None:
        self._project_list.crear_proyecto(_("Nuevo proyecto"))

    def _on_sidebar_toggled(self, button: Gtk.ToggleButton) -> None:
        visible = button.get_active()
        if visible:
            # Volver a insertar el hijo evita que Gtk.Paned conserve un panel visible
            # pero con ancho cero después de ocultarlo.
            if self._paned.get_start_child() is None:
                self._paned.set_start_child(self._project_list)
                self._paned.set_resize_start_child(False)
                self._paned.set_shrink_start_child(False)
            self._project_list.set_visible(True)
            self._paned.set_position(300)
        else:
            self._paned.set_start_child(None)

    def _on_global_toggled(self, button: Gtk.ToggleButton) -> None:
        if button.get_active():
            self._global_gantt.refrescar_proyectos()
            self._detail_stack.set_visible_child_name("global")
        elif self._proyecto_actual is not None:
            self._detail_stack.set_visible_child_name("detail")
        else:
            self._detail_stack.set_visible_child_name("empty")

    def _on_project_selected(self, proyecto: Proyecto | None) -> None:
        self._proyecto_actual = proyecto
        self._global_button.set_active(False)
        if proyecto is None:
            self._detail_stack.set_visible_child_name("empty")
            return
        self._project_detail.mostrar_proyecto(proyecto)
        self._detail_stack.set_visible_child_name("detail")
