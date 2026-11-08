from __future__ import annotations

from collections.abc import Callable

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk

from gnomilestone.i18n import _
from gnomilestone.models import Tarea
from gnomilestone.store import Store


def ordenar_archivadas(tareas: list[Tarea]) -> list[tuple[Tarea, int]]:
    """(tarea, profundidad) en orden de lista. La profundidad cuenta solo ancestros también
    archivados: una tarea archivada sola, con el padre a la vista, queda al nivel 0."""
    por_id = {t.id: t for t in tareas}

    def profundidad(t: Tarea) -> int:
        nivel = 0
        while t.padre_id in por_id:
            t = por_id[t.padre_id]
            nivel += 1
        return nivel

    return [(t, profundidad(t)) for t in sorted(tareas, key=lambda t: t.orden)]


class ArchivedTasksDialog(Gtk.Window):
    """Tareas archivadas de un proyecto: buscarlas y devolverlas a las vistas."""

    def __init__(
        self, parent: Gtk.Window, store: Store, proyecto_id: int, on_changed: Callable[[], None]
    ) -> None:
        super().__init__(
            title=_("Tareas archivadas"),
            transient_for=parent,
            modal=True,
            default_width=520,
            default_height=480,
        )
        self._store = store
        self._proyecto_id = proyecto_id
        self._on_changed = on_changed

        raiz = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=10,
            margin_top=16,
            margin_bottom=16,
            margin_start=16,
            margin_end=16,
        )
        self.set_child(raiz)

        self._buscar = Gtk.SearchEntry(placeholder_text=_("Buscar tarea…"))
        self._buscar.connect("search-changed", lambda _e: self._refrescar())
        raiz.append(self._buscar)

        self._lista = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self._lista.add_css_class("boxed-list")
        scroller = Gtk.ScrolledWindow(vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
        scroller.set_child(self._lista)
        raiz.append(scroller)

        pie = Gtk.Box(spacing=8, halign=Gtk.Align.END)
        self._todas_button = Gtk.Button(label=_("Desarchivar todas"))
        self._todas_button.connect("clicked", self._on_desarchivar_todas)
        pie.append(self._todas_button)
        cerrar = Gtk.Button(label=_("Cerrar"))
        cerrar.connect("clicked", lambda _b: self.close())
        pie.append(cerrar)
        raiz.append(pie)

        self._refrescar()

    def _refrescar(self) -> None:
        self._lista.remove_all()
        texto = self._buscar.get_text().strip().casefold()
        archivadas = self._store.listar_tareas_archivadas(self._proyecto_id)
        self._todas_button.set_sensitive(bool(archivadas))
        estados = {e.id: e.nombre for e in self._store.listar_estados(self._proyecto_id)}
        mostradas = 0
        for tarea, nivel in ordenar_archivadas(archivadas):
            if texto and texto not in tarea.titulo.casefold():
                continue
            mostradas += 1
            fila = Gtk.Box(
                spacing=8, margin_top=6, margin_bottom=6, margin_start=8 + 18 * nivel, margin_end=8
            )
            datos = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True)
            datos.append(Gtk.Label(label=tarea.titulo, xalign=0, wrap=True))
            detalle = Gtk.Label(
                label=f"{estados.get(tarea.estado_id, '')} · {tarea.porcentaje_completado} %",
                xalign=0,
            )
            detalle.add_css_class("dim-label")
            detalle.add_css_class("caption")
            datos.append(detalle)
            fila.append(datos)
            boton = Gtk.Button(label=_("Desarchivar"), valign=Gtk.Align.CENTER)
            boton.connect("clicked", self._on_desarchivar, tarea.id)
            fila.append(boton)
            self._lista.append(fila)
        if mostradas == 0:
            vacio = Gtk.Label(
                label=_("No hay tareas archivadas.") if not texto else _("Sin resultados."),
                margin_top=12,
                margin_bottom=12,
            )
            vacio.add_css_class("dim-label")
            self._lista.append(vacio)

    def _on_desarchivar(self, _boton: Gtk.Button, tarea_id: int) -> None:
        self._store.desarchivar_tarea(tarea_id)
        self._refrescar()
        self._on_changed()

    def _on_desarchivar_todas(self, _boton: Gtk.Button) -> None:
        for tarea in self._store.listar_tareas_archivadas(self._proyecto_id):
            self._store.desarchivar_tarea(tarea.id)
        self._refrescar()
        self._on_changed()
