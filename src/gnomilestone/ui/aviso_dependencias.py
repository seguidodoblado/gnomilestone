"""Aviso al completar una tarea cuyas dependencias aún no están terminadas."""

from __future__ import annotations

from collections.abc import Callable

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import GLib, Gtk

from gnomilestone.i18n import _
from gnomilestone.models import Tarea


def confirmar_completar(
    ventana: Gtk.Window | None, pendientes: list[Tarea], al_confirmar: Callable[[], None]
) -> None:
    """Pregunta si completar de todos modos; `al_confirmar` solo se llama si el usuario acepta."""
    nombres = "\n".join(f"• {t.titulo} ({t.porcentaje_completado} %)" for t in pendientes)
    dialogo = Gtk.AlertDialog()
    dialogo.set_message(_("Hay dependencias sin terminar"))
    dialogo.set_detail(
        _("Esta tarea depende de:\n{tareas}\n\n¿Completarla de todos modos?").format(tareas=nombres)
    )
    dialogo.set_buttons([_("Cancelar"), _("Completar de todos modos")])
    dialogo.set_cancel_button(0)
    dialogo.set_default_button(0)

    def _respuesta(d: Gtk.AlertDialog, resultado) -> None:
        try:
            eleccion = d.choose_finish(resultado)
        except GLib.Error:
            return
        if eleccion == 1:
            al_confirmar()

    dialogo.choose(ventana, None, _respuesta)
