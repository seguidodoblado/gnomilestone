from __future__ import annotations

from collections.abc import Callable

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gio, Gtk

from gnomilestone.i18n import _
from gnomilestone.models import Recurso, Tarea
from gnomilestone.ui.avatar_widget import fila_avatares
from gnomilestone.ui.task_tree_view import (
    ALTURA_FILA,
    CLASE_FILA_FIJA,
    TareaRow,
    adjuntar_menu_contextual,
    asegurar_css_fila_fija,
    ordenar_jerarquicamente,
)
from gnomilestone.ui.vencimiento import (
    aplicar_estilo_vencimiento,
    asegurar_css_vencimientos,
    texto_vencimiento,
)


def coincide_con_filtro(fila: TareaRow, texto: str, estado_id: int | None) -> bool:
    """Lógica pura del filtro de la Tabla: separada de GTK para poder probarla sin pantalla."""
    if estado_id is not None and (fila.tarea is None or fila.tarea.estado_id != estado_id):
        return False
    texto = texto.strip().lower()
    if not texto:
        return True
    return texto in fila.titulo.lower()


def _texto_factory(bind_prop: str) -> Gtk.SignalListItemFactory:
    factory = Gtk.SignalListItemFactory()
    factory.connect(
        "setup", lambda _f, item: item.set_child(Gtk.Label(xalign=0, height_request=ALTURA_FILA))
    )

    def _bind(_factory: Gtk.SignalListItemFactory, item: Gtk.ListItem) -> None:
        fila: TareaRow = item.get_item()
        label = item.get_child()
        label.set_label(str(getattr(fila, bind_prop)))
        label.fila_asociada = fila

    factory.connect("bind", _bind)
    return factory


def _titulo_factory() -> Gtk.SignalListItemFactory:
    factory = Gtk.SignalListItemFactory()

    def _setup(_factory: Gtk.SignalListItemFactory, item: Gtk.ListItem) -> None:
        label = Gtk.Label(xalign=0, height_request=ALTURA_FILA)
        label.add_css_class("monospace")
        item.set_child(label)

    def _bind(_factory: Gtk.SignalListItemFactory, item: Gtk.ListItem) -> None:
        fila: TareaRow = item.get_item()
        label = item.get_child()
        label.set_label(fila.titulo)
        label.fila_asociada = fila
        estado = aplicar_estilo_vencimiento(label, fila.tarea)
        label.set_tooltip_text(texto_vencimiento(estado))

    factory.connect("setup", _setup)
    factory.connect("bind", _bind)
    return factory


def _recursos_factory() -> Gtk.SignalListItemFactory:
    factory = Gtk.SignalListItemFactory()

    def _setup(_factory: Gtk.SignalListItemFactory, item: Gtk.ListItem) -> None:
        item.set_child(Gtk.Box(height_request=ALTURA_FILA, valign=Gtk.Align.CENTER))

    def _bind(_factory: Gtk.SignalListItemFactory, item: Gtk.ListItem) -> None:
        fila: TareaRow = item.get_item()
        caja = item.get_child()
        while (hijo := caja.get_first_child()) is not None:
            caja.remove(hijo)
        avatares = fila_avatares(fila.recursos, size=24, maximo=3, height_request=ALTURA_FILA)
        caja.append(avatares)
        caja.fila_asociada = fila

    factory.connect("setup", _setup)
    factory.connect("bind", _bind)
    return factory


class TableView(Gtk.Box):
    """Listado plano (sin árbol real) de las tareas de un proyecto, con filtro por texto
    y por columna del tablero, e indentación visual de la jerarquía por prefijo (como en
    `task_tree_view.ordenar_jerarquicamente`)."""

    def __init__(
        self,
        on_editar_tarea: Callable[[Tarea], None] | None = None,
        on_eliminar_tarea: Callable[[Tarea], None] | None = None,
    ) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        asegurar_css_fila_fija()
        asegurar_css_vencimientos()
        self._on_editar_tarea = on_editar_tarea
        self._estado_filtro: int | None = None

        barra_filtro = Gtk.Box(
            spacing=6, margin_top=6, margin_bottom=6, margin_start=6, margin_end=6
        )
        self._buscar_entry = Gtk.SearchEntry(placeholder_text=_("Buscar tarea…"), hexpand=True)
        self._buscar_entry.connect("search-changed", self._on_filtro_cambiado)
        barra_filtro.append(self._buscar_entry)

        self._estado_dropdown = Gtk.DropDown.new_from_strings([_("Todas las columnas")])
        self._estado_dropdown.connect("notify::selected", self._on_filtro_estado_cambiado)
        barra_filtro.append(self._estado_dropdown)
        self.append(barra_filtro)

        self._store_base = Gio.ListStore(item_type=TareaRow)
        self._filtro = Gtk.CustomFilter.new(self._coincide, None)
        self._modelo_filtrado = Gtk.FilterListModel(model=self._store_base, filter=self._filtro)
        self._selection = Gtk.SingleSelection(model=self._modelo_filtrado)

        self._view = Gtk.ColumnView(model=self._selection, vexpand=True)
        self._view.add_css_class(CLASE_FILA_FIJA)
        self._view.connect("activate", self._on_activate)
        if on_editar_tarea is not None and on_eliminar_tarea is not None:
            adjuntar_menu_contextual(self._view, on_editar_tarea, on_eliminar_tarea)

        self._view.append_column(
            Gtk.ColumnViewColumn(
                title=_("Título"), factory=_titulo_factory(), expand=True, resizable=True
            )
        )
        self._view.append_column(
            Gtk.ColumnViewColumn(
                title=_("Asignado"), factory=_recursos_factory(), resizable=True
            )
        )
        for titulo, propiedad in (
            (_("Columna"), "estado"),
            (_("Inicio"), "fecha_inicio"),
            (_("Final planificado"), "fecha_fin_planificada"),
            (_("Fecha límite"), "fecha_limite"),
            (_("Duración (días)"), "duracion_dias"),
            (_("% completado"), "porcentaje_completado"),
        ):
            self._view.append_column(
                Gtk.ColumnViewColumn(title=titulo, factory=_texto_factory(propiedad), resizable=True)
            )

        scroller = Gtk.ScrolledWindow(vexpand=True)
        scroller.set_child(self._view)
        self.append(scroller)

    def set_tareas(
        self,
        tareas: list[Tarea],
        estados: list,
        estados_por_id: dict[int, str],
        recursos_por_tarea: dict[int, list[Recurso]] | None = None,
    ) -> None:
        recursos_por_tarea = recursos_por_tarea or {}
        etiquetas = [_("Todas las columnas")] + [estado.nombre for estado in estados]
        self._ids_estado = [None] + [estado.id for estado in estados]
        self._estado_dropdown.set_model(Gtk.StringList.new(etiquetas))
        if self._estado_filtro in self._ids_estado:
            self._estado_dropdown.set_selected(self._ids_estado.index(self._estado_filtro))
        else:
            self._estado_filtro = None
            self._estado_dropdown.set_selected(0)

        self._store_base.remove_all()
        for tarea, prefijo in ordenar_jerarquicamente(tareas):
            nombre_estado = estados_por_id.get(tarea.estado_id, "")
            self._store_base.append(
                TareaRow(
                    prefijo + tarea.titulo,
                    [],
                    tarea=tarea,
                    estado_nombre=nombre_estado,
                    recursos=recursos_por_tarea.get(tarea.id, []),
                )
            )

    def _coincide(self, fila: TareaRow, _datos) -> bool:
        return coincide_con_filtro(fila, self._buscar_entry.get_text(), self._estado_filtro)

    def _on_filtro_cambiado(self, _entry: Gtk.SearchEntry) -> None:
        self._filtro.changed(Gtk.FilterChange.DIFFERENT)

    def _on_filtro_estado_cambiado(self, dropdown: Gtk.DropDown, _param) -> None:
        indice = dropdown.get_selected()
        self._estado_filtro = self._ids_estado[indice] if indice < len(self._ids_estado) else None
        self._filtro.changed(Gtk.FilterChange.DIFFERENT)

    def _on_activate(self, _view: Gtk.ColumnView, posicion: int) -> None:
        fila = self._modelo_filtrado.get_item(posicion)
        if self._on_editar_tarea is not None and fila.tarea is not None:
            self._on_editar_tarea(fila.tarea)
