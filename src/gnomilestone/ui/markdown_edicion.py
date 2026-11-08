"""Acciones de la barra de formato Markdown sobre un `Gtk.TextBuffer` (sin interfaz)."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk


def _iter_de_linea(buf: Gtk.TextBuffer, linea: int) -> Gtk.TextIter:
    # En PyGObject, get_iter_at_line() devuelve (éxito, iter), no solo el iter.
    return buf.get_iter_at_line(linea)[1]


def _fin_de_linea(buf: Gtk.TextBuffer, linea: int) -> Gtk.TextIter:
    fin = _iter_de_linea(buf, linea)
    if not fin.ends_line():
        fin.forward_to_line_end()
    return fin


def envolver(buf: Gtk.TextBuffer, antes: str, despues: str, ejemplo: str) -> None:
    """Rodea la selección con `antes`/`despues`; sin selección inserta un texto de ejemplo
    y lo deja seleccionado para sobrescribirlo escribiendo."""
    if buf.get_has_selection():
        inicio, fin = buf.get_selection_bounds()
        texto = buf.get_text(inicio, fin, False)
        buf.begin_user_action()
        buf.delete(inicio, fin)
        buf.insert(inicio, f"{antes}{texto}{despues}")
        buf.end_user_action()
        return
    buf.begin_user_action()
    buf.insert_at_cursor(f"{antes}{ejemplo}{despues}")
    buf.end_user_action()
    fin_iter = buf.get_iter_at_mark(buf.get_insert())
    fin_iter.backward_chars(len(despues))
    inicio_iter = fin_iter.copy()
    inicio_iter.backward_chars(len(ejemplo))
    buf.select_range(inicio_iter, fin_iter)


def prefijar_lineas(buf: Gtk.TextBuffer, prefijo: str) -> None:
    """Añade `prefijo` a cada línea de la selección (o a la actual); si todas lo llevan, lo
    quita. Con «1. » numera las líneas."""
    if buf.get_has_selection():
        inicio, fin = buf.get_selection_bounds()
    else:
        inicio = fin = buf.get_iter_at_mark(buf.get_insert())
    primera = inicio.get_line()
    ultima = fin.get_line()
    if fin.starts_line() and ultima > primera:
        ultima -= 1  # una selección que termina al inicio de línea no incluye esa línea
    lineas = [
        buf.get_text(_iter_de_linea(buf, n), _fin_de_linea(buf, n), False)
        for n in range(primera, ultima + 1)
    ]
    numeradas = prefijo == "1. "
    quitar = not numeradas and all(linea.startswith(prefijo) for linea in lineas)
    nuevas = []
    for i, linea in enumerate(lineas, start=1):
        if quitar:
            nuevas.append(linea[len(prefijo) :])
        elif numeradas:
            nuevas.append(f"{i}. {linea}")
        else:
            nuevas.append(prefijo + linea)
    buf.begin_user_action()
    buf.delete(_iter_de_linea(buf, primera), _fin_de_linea(buf, ultima))
    buf.insert(_iter_de_linea(buf, primera), "\n".join(nuevas))
    buf.end_user_action()
