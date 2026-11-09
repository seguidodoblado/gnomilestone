"""Menú «Columnas visibles» compartido por la Lista y el Gantt (con la elección recordada)."""

from __future__ import annotations

from typing import Protocol

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk

from gnomilestone import settings
from gnomilestone.i18n import _


class VistaConColumnas(Protocol):
    def columnas_disponibles(self) -> list[tuple[str, str, bool]]: ...
    def set_columna_visible(self, clave: str, visible: bool) -> None: ...
    def is_columna_visible(self, clave: str) -> bool: ...


def aplicar_columnas_guardadas(vista: VistaConColumnas, clave_ajuste: str) -> None:
    config = settings.read_settings().get(clave_ajuste)
    if config is not None:
        for clave, visible in config.items():
            if clave != "titulo":
                vista.set_columna_visible(clave, bool(visible))


def crear_menu_columnas(vista: VistaConColumnas, clave_ajuste: str) -> Gtk.MenuButton:
    """Botón con un desplegable de casillas, una por columna (la fija no se puede quitar);
    cada cambio se guarda en los ajustes bajo `clave_ajuste`."""
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

    def _on_toggled(check: Gtk.CheckButton, clave: str) -> None:
        vista.set_columna_visible(clave, check.get_active())
        config = settings.read_settings()
        config[clave_ajuste] = {
            c: vista.is_columna_visible(c) for c, _etiqueta, _fija in vista.columnas_disponibles()
        }
        settings.write_settings(config)

    for clave, etiqueta, fija in vista.columnas_disponibles():
        check = Gtk.CheckButton(label=etiqueta)
        check.set_active(vista.is_columna_visible(clave))
        if fija:
            check.set_sensitive(False)
        else:
            check.connect("toggled", _on_toggled, clave)
        box.append(check)

    popover.set_child(box)
    return Gtk.MenuButton(
        icon_name="view-more-symbolic", tooltip_text=_("Columnas visibles"), popover=popover
    )
