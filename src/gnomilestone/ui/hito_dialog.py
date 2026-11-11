from __future__ import annotations

import threading
from collections.abc import Callable

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, Pango

from gnomilestone.i18n import _
from gnomilestone.models import Hito, Tarea
from gnomilestone.store import Store
from gnomilestone.sync import GitHubSyncManager
from gnomilestone.ui.asignar_hito import asignar_tareas_a_hito, diferir
from gnomilestone.ui.task_dialog import _SelectorFecha
from gnomilestone.ui.task_tree_view import ordenar_jerarquicamente


class HitoDialog(Gtk.Window):
    """Alta y edición de un Hito: título, fecha objetivo, descripción y si ya se ha conseguido.
    Un Hito es un Milestone de GitHub, no una tarea: no lleva columna, recursos ni duración;
    las tareas que contribuyen a él lo eligen en su propio diálogo."""

    def __init__(
        self,
        parent: Gtk.Window | None,
        store: Store,
        proyecto_id: int,
        hito: Hito | None,
        on_changed: Callable[[], None],
    ) -> None:
        super().__init__(
            title=_("Editar hito") if hito else _("Nuevo hito"),
            transient_for=parent,
            modal=True,
            default_width=420,
        )
        self._store = store
        self._proyecto_id = proyecto_id
        self._hito = hito
        self._on_changed = on_changed

        caja = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        for margen in ("top", "bottom", "start", "end"):
            getattr(caja, f"set_margin_{margen}")(16)
        self.set_child(caja)

        caja.append(Gtk.Label(label=_("Título"), xalign=0))
        self._titulo = Gtk.Entry(text=hito.titulo if hito else "", activates_default=True)
        caja.append(self._titulo)

        caja.append(Gtk.Label(label=_("Fecha objetivo"), xalign=0))
        self._fecha = _SelectorFecha(hito.fecha if hito else None, lambda: None)
        caja.append(self._fecha.widget)

        caja.append(Gtk.Label(label=_("Descripción"), xalign=0))
        self._descripcion = Gtk.TextBuffer(text=hito.descripcion if hito else "")
        vista = Gtk.TextView(buffer=self._descripcion, wrap_mode=Gtk.WrapMode.WORD_CHAR)
        for lado in ("top", "bottom", "left", "right"):
            getattr(vista, f"set_{lado}_margin")(6)
        scroll = Gtk.ScrolledWindow(
            hscrollbar_policy=Gtk.PolicyType.NEVER,
            min_content_height=90,
            max_content_height=160,
            propagate_natural_height=True,
        )
        scroll.add_css_class("card")
        scroll.set_child(vista)
        caja.append(scroll)

        self._conseguido = Gtk.CheckButton(label=_("Conseguido"))
        self._conseguido.set_active(bool(hito and hito.conseguido))
        self._conseguido.set_tooltip_text(
            _("También se da por conseguido cuando todas sus tareas están completas.")
        )
        caja.append(self._conseguido)

        self._error = Gtk.Label(xalign=0, wrap=True)
        self._error.add_css_class("error")
        self._error.set_visible(False)
        caja.append(self._error)

        botones = Gtk.Box(spacing=8)
        if hito is not None:
            eliminar = Gtk.Button(label=_("Eliminar"))
            eliminar.add_css_class("destructive-action")
            eliminar.connect("clicked", self._on_eliminar)
            botones.append(eliminar)
        botones.append(Gtk.Box(hexpand=True))
        cancelar = Gtk.Button(label=_("Cancelar"))
        cancelar.connect("clicked", lambda _b: self.close())
        guardar = Gtk.Button(label=_("Guardar"))
        guardar.add_css_class("suggested-action")
        guardar.connect("clicked", self._on_guardar)
        botones.append(cancelar)
        botones.append(guardar)
        caja.append(botones)
        self.set_default_widget(guardar)

    def _on_guardar(self, _b: Gtk.Widget) -> None:
        titulo = self._titulo.get_text().strip()
        if not titulo:
            self._error.set_label(_("El título no puede estar vacío."))
            self._error.set_visible(True)
            return
        descripcion = self._descripcion.get_text(
            self._descripcion.get_start_iter(), self._descripcion.get_end_iter(), False
        ).strip()
        if self._hito is None:
            hito = self._store.crear_hito(
                self._proyecto_id, titulo, self._fecha.valor, descripcion,
                self._conseguido.get_active(),
            )
        else:
            hito = self._hito
            hito.titulo, hito.fecha, hito.descripcion = titulo, self._fecha.valor, descripcion
            hito.conseguido = self._conseguido.get_active()
            self._store.actualizar_hito(hito)
        self._enviar_a_github(hito.id)
        self.close()
        diferir(self._on_changed)

    def _enviar_a_github(self, hito_id: int) -> None:
        proyecto = self._store.obtener_proyecto(self._proyecto_id)
        if proyecto and proyecto.github_repo_owner and proyecto.github_repo_name:
            threading.Thread(
                target=lambda: GitHubSyncManager(self._store).push_hito(hito_id), daemon=True
            ).start()

    def _on_eliminar(self, _b: Gtk.Widget) -> None:
        assert self._hito is not None
        GitHubSyncManager(self._store).eliminar_hito(self._hito.id)
        self.close()
        diferir(self._on_changed)


class SeleccionTareasHito(Gtk.Window):
    """Elige, marcando casillas, qué tareas contribuyen a un Hito (varias de una vez). Las
    que ya pertenecen a otro Hito muestran cuál: marcarlas las mueve a este."""

    def __init__(
        self,
        parent: Gtk.Window | None,
        store: Store,
        hito: Hito,
        tareas: list[Tarea],
        on_changed: Callable[[], None],
    ) -> None:
        super().__init__(
            title=_("Tareas del hito «{titulo}»").format(titulo=hito.titulo),
            transient_for=parent,
            modal=True,
            default_width=520,
            default_height=520,
        )
        self._store = store
        self._hito = hito
        self._on_changed = on_changed
        titulos_hito = {h.id: h.titulo for h in store.listar_hitos(hito.proyecto_id)}
        self._marcas: list[tuple[Tarea, Gtk.CheckButton]] = []

        raiz = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        for margen in ("top", "bottom", "start", "end"):
            getattr(raiz, f"set_margin_{margen}")(16)
        self.set_child(raiz)
        buscador = Gtk.SearchEntry(placeholder_text=_("Buscar tarea…"))
        raiz.append(buscador)

        lista = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self._filas: list[tuple[Gtk.Widget, str]] = []
        for tarea, prefijo in ordenar_jerarquicamente(tareas):
            fila = Gtk.Box(spacing=6)
            marca = Gtk.CheckButton()
            marca.set_active(tarea.hito_id == hito.id)
            fila.append(marca)
            if prefijo:
                lprefijo = Gtk.Label(label=prefijo)
                lprefijo.add_css_class("monospace")
                fila.append(lprefijo)
            fila.append(
                Gtk.Label(label=tarea.titulo, xalign=0, hexpand=True, ellipsize=Pango.EllipsizeMode.END)
            )
            if tarea.hito_id is not None and tarea.hito_id != hito.id:
                otro = Gtk.Label(label="◆ " + titulos_hito.get(tarea.hito_id, ""))
                otro.add_css_class("dim-label")
                otro.add_css_class("caption")
                fila.append(otro)
            click = Gtk.GestureClick()
            click.connect("released", lambda *_a, m=marca: m.set_active(not m.get_active()))
            fila.add_controller(click)
            lista.append(fila)
            self._marcas.append((tarea, marca))
            self._filas.append((fila, tarea.titulo.casefold()))
        if not self._marcas:
            lista.append(Gtk.Label(label=_("No hay tareas en el proyecto."), xalign=0))
        buscador.connect("search-changed", self._on_buscar)
        desplazable = Gtk.ScrolledWindow(vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
        desplazable.set_child(lista)
        raiz.append(desplazable)

        botones = Gtk.Box(spacing=8, halign=Gtk.Align.END)
        cancelar = Gtk.Button(label=_("Cancelar"))
        cancelar.connect("clicked", lambda _b: self.close())
        guardar = Gtk.Button(label=_("Guardar"))
        guardar.add_css_class("suggested-action")
        guardar.connect("clicked", self._on_guardar)
        botones.append(cancelar)
        botones.append(guardar)
        raiz.append(botones)

    def _on_buscar(self, entrada: Gtk.SearchEntry) -> None:
        texto = entrada.get_text().strip().casefold()
        for fila, titulo in self._filas:
            fila.set_visible(not texto or texto in titulo)

    def _on_guardar(self, _b: Gtk.Widget) -> None:
        añadir = [t.id for t, m in self._marcas if m.get_active() and t.hito_id != self._hito.id]
        quitar = [t.id for t, m in self._marcas if not m.get_active() and t.hito_id == self._hito.id]
        asignar_tareas_a_hito(self._store, añadir, self._hito.id)
        asignar_tareas_a_hito(self._store, quitar, None)
        self.close()
        diferir(self._on_changed)
