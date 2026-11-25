"""Ventana para elegir de qué issue es duplicado el que se mueve a una columna «Duplicate»."""

from __future__ import annotations

from collections.abc import Callable

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk

from gnomilestone.i18n import _
from gnomilestone.models import Tarea


def candidatas_a_original(tareas: list[Tarea], tarea: Tarea) -> list[Tarea]:
    """Tareas del proyecto con issue en GitHub que pueden ser el original: todas menos ella."""
    return [t for t in tareas if t.id != tarea.id and t.github_issue_number]


def pedir_original(
    parent: Gtk.Window | None,
    tarea: Tarea,
    candidatas: list[Tarea],
    al_elegir: Callable[[Tarea], None],
) -> None:
    """Pide el issue original de `tarea` y llama a `al_elegir` con la tarea elegida."""
    ventana = Gtk.Window(
        title=_("Duplicado de…"), transient_for=parent, modal=True, default_width=380
    )
    caja = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
    for margen in ("top", "bottom", "start", "end"):
        getattr(caja, f"set_margin_{margen}")(18)
    ventana.set_child(caja)
    caja.append(
        Gtk.Label(
            label=_("«{titulo}» es un duplicado de:").format(titulo=tarea.titulo),
            xalign=0,
            wrap=True,
        )
    )
    if not candidatas:
        aviso = Gtk.Label(
            label=_("No hay otras tareas con issue en GitHub que puedan ser el original."),
            xalign=0,
            wrap=True,
        )
        aviso.add_css_class("dim-label")
        caja.append(aviso)
        cerrar = Gtk.Button(label=_("Cerrar"), halign=Gtk.Align.END)
        cerrar.connect("clicked", lambda _b: ventana.close())
        caja.append(cerrar)
        ventana.present()
        return
    selector = Gtk.DropDown.new_from_strings([f"{t.titulo} (#{t.github_issue_number})" for t in candidatas])
    selector.set_enable_search(True)
    selector.set_search_match_mode(Gtk.StringFilterMatchMode.SUBSTRING)
    selector.set_expression(Gtk.PropertyExpression.new(Gtk.StringObject, None, "string"))
    caja.append(selector)
    botones = Gtk.Box(spacing=8, halign=Gtk.Align.END)
    cancelar = Gtk.Button(label=_("Cancelar"))
    aceptar = Gtk.Button(label=_("Aceptar"))
    aceptar.add_css_class("suggested-action")
    botones.append(cancelar)
    botones.append(aceptar)
    caja.append(botones)

    def confirmar(_b: Gtk.Widget) -> None:
        elegida = candidatas[selector.get_selected()]
        ventana.close()
        al_elegir(elegida)

    cancelar.connect("clicked", lambda _b: ventana.close())
    aceptar.connect("clicked", confirmar)
    ventana.present()
