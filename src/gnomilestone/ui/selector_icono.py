"""Selector de icono simbólico: un botón con una cuadrícula de iconos del tema."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gdk, Gtk

from gnomilestone.i18n import _

# Selección curada de iconos simbólicos; solo se ofrecen los que el tema instalado tiene.
ICONOS_ELEGIBLES = (
    "balanza-symbolic", "user-home-symbolic", "view-grid-symbolic", "package-x-generic-symbolic",
    "emblem-ok-symbolic", "drive-harddisk-symbolic", "system-users-symbolic", "view-dual-symbolic",
    "network-wired-symbolic", "system-run-symbolic", "emblem-system-symbolic",
    "applications-graphics-symbolic", "applications-engineering-symbolic", "applications-science-symbolic",
    "preferences-other-symbolic", "security-high-symbolic", "folder-symbolic", "folder-documents-symbolic",
    "text-x-generic-symbolic", "document-edit-symbolic", "emblem-documents-symbolic", "starred-symbolic",
    "find-location-symbolic", "mail-send-symbolic", "document-send-symbolic", "folder-download-symbolic",
    "emblem-shared-symbolic", "emblem-important-symbolic", "dialog-information-symbolic",
    "utilities-terminal-symbolic", "insert-object-symbolic", "color-select-symbolic",
    "view-list-symbolic", "view-paged-symbolic", "task-due-symbolic", "weather-clear-symbolic",
    "media-playlist-shuffle-symbolic", "x-office-calendar-symbolic", "x-office-chart-bar-symbolic",
    "network-server-symbolic", "computer-symbolic", "input-tablet-symbolic", "edit-find-symbolic",
)


class SelectorIcono(Gtk.MenuButton):
    """Botón que muestra el icono elegido; `icono` es None para «el de por defecto»."""

    def __init__(self, icono: str | None, por_defecto: str) -> None:
        super().__init__(tooltip_text=_("Icono"))
        self._por_defecto = por_defecto
        self.icono = icono
        popover = Gtk.Popover()
        caja = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        for margen in ("top", "bottom", "start", "end"):
            getattr(caja, f"set_margin_{margen}")(8)
        cuadricula = Gtk.FlowBox(
            max_children_per_line=7, min_children_per_line=7, selection_mode=Gtk.SelectionMode.NONE
        )
        tema = Gtk.IconTheme.get_for_display(Gdk.Display.get_default())
        for nombre in ICONOS_ELEGIBLES:
            if tema.has_icon(nombre):
                boton = Gtk.Button(icon_name=nombre)
                boton.add_css_class("flat")
                boton.connect("clicked", self._elegir, nombre, popover)
                cuadricula.append(boton)
        caja.append(cuadricula)
        defecto = Gtk.Button(label=_("Por defecto"))
        defecto.connect("clicked", self._elegir, None, popover)
        caja.append(defecto)
        popover.set_child(caja)
        self.set_popover(popover)
        self._pintar()

    @property
    def por_defecto(self) -> str:
        return self._por_defecto

    @por_defecto.setter
    def por_defecto(self, nombre: str) -> None:
        self._por_defecto = nombre
        self._pintar()

    def _elegir(self, _boton: Gtk.Button, nombre: str | None, popover: Gtk.Popover) -> None:
        self.icono = nombre
        self._pintar()
        popover.popdown()

    def _pintar(self) -> None:
        self.set_icon_name(self.icono or self._por_defecto)
