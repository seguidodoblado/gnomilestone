from __future__ import annotations

from collections.abc import Callable

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gio, GLib, Gtk

from gnomilestone.i18n import _
from gnomilestone.models import Etiqueta, Recurso, Tarea
from gnomilestone.ui.avatar_widget import fila_avatares
from gnomilestone.ui.columnas_menu import aplicar_columnas_guardadas, crear_menu_columnas
from gnomilestone.ui.kanban_view import colores_de_estados
from gnomilestone.ui.task_tree_view import (
    ALTURA_FILA,
    CLASE_FILA_FIJA,
    COLUMNAS_INFO,
    TareaRow,
    adjuntar_menu_contextual,
    asegurar_css_fila_fija,
    estado_factory,
    etiquetas_factory,
    issue_factory,
    ordenar_jerarquicamente,
    prioridad_factory,
)
from gnomilestone.ui.vencimiento import (
    aplicar_estilo_vencimiento,
    asegurar_css_vencimientos,
    texto_vencimiento,
)

_ANCHO_TITULO = 360


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
        on_archivar_tarea: Callable[[Tarea], None] | None = None,
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
        # El botón se añade al final, cuando ya existen las columnas.
        self.append(barra_filtro)

        self._store_base = Gio.ListStore(item_type=TareaRow)
        self._filtro = Gtk.CustomFilter.new(self._coincide, None)
        self._modelo_filtrado = Gtk.FilterListModel(model=self._store_base, filter=self._filtro)
        self._selection = Gtk.SingleSelection(model=self._modelo_filtrado)

        self._view = Gtk.ColumnView(model=self._selection, vexpand=True)
        self._view.add_css_class(CLASE_FILA_FIJA)
        self._view.connect("activate", self._on_activate)
        if on_editar_tarea is not None and on_eliminar_tarea is not None:
            adjuntar_menu_contextual(self._view, on_editar_tarea, on_eliminar_tarea, on_archivar_tarea)

        # Clave -> (propiedad de texto | fábrica). El orden y los títulos salen de COLUMNAS_INFO.
        fabricas = {
            "titulo": _titulo_factory(),
            "asignado": _recursos_factory(),
            "estado": estado_factory(arbol=False),
            "prioridad": prioridad_factory(arbol=False),
            "etiquetas": etiquetas_factory(arbol=False),
            "issue": issue_factory(arbol=False),
        }
        propiedades = {
            "fecha_inicio": "fecha_inicio",
            "fecha_fin_planificada": "fecha_fin_planificada",
            "fecha_limite": "fecha_limite",
            "duracion_dias": "duracion_dias",
            "porcentaje_completado": "porcentaje_texto",
        }
        self._columnas: dict[str, Gtk.ColumnViewColumn] = {}
        for clave, titulo, _fija, _defecto in COLUMNAS_INFO:
            col = Gtk.ColumnViewColumn(
                title=titulo,
                factory=fabricas.get(clave) or _texto_factory(propiedades[clave]),
                resizable=True,
            )
            if clave == "titulo":
                # Sin expand: una columna expandida absorbe el espacio sobrante y, al tirar de
                # su borde, solo se deja ensanchar (no estrechar). Con ancho propio se
                # redimensiona igual que las demás.
                col.set_fixed_width(_ANCHO_TITULO)
            # En la Lista se ven todas salvo «Issue», que se activa desde el menú de columnas.
            col.set_visible(clave != "issue")
            self._view.append_column(col)
            self._columnas[clave] = col
        aplicar_columnas_guardadas(self, "lista_columnas_visibles")
        barra_filtro.append(crear_menu_columnas(self, "lista_columnas_visibles"))

        scroller = Gtk.ScrolledWindow(vexpand=True)
        scroller.set_child(self._view)
        self.append(scroller)

    def columnas_disponibles(self) -> list[tuple[str, str, bool]]:
        """(clave, etiqueta, es_fija) de cada columna, para el menú «Columnas visibles»."""
        return [(clave, etiqueta, fija) for clave, etiqueta, fija, _def in COLUMNAS_INFO]

    def set_columna_visible(self, clave: str, visible: bool) -> None:
        col = self._columnas.get(clave)
        if col is not None:
            col.set_visible(visible)

    def is_columna_visible(self, clave: str) -> bool:
        col = self._columnas.get(clave)
        return col.get_visible() if col is not None else False

    def set_tareas(
        self,
        tareas: list[Tarea],
        estados: list,
        estados_por_id: dict[int, str],
        recursos_por_tarea: dict[int, list[Recurso]] | None = None,
        etiquetas_por_tarea: dict[int, list[Etiqueta]] | None = None,
    ) -> None:
        recursos_por_tarea = recursos_por_tarea or {}
        etiquetas_por_tarea = etiquetas_por_tarea or {}
        etiquetas = [_("Todas las columnas")] + [estado.nombre for estado in estados]
        self._ids_estado = [None] + [estado.id for estado in estados]
        self._estado_dropdown.set_model(Gtk.StringList.new(etiquetas))
        if self._estado_filtro in self._ids_estado:
            self._estado_dropdown.set_selected(self._ids_estado.index(self._estado_filtro))
        else:
            self._estado_filtro = None
            self._estado_dropdown.set_selected(0)

        # La lista se reconstruye entera (p. ej. al guardar una tarea): se recuerda la fila
        # seleccionada para no volver a la primera.
        seleccionada = self._selection.get_selected_item()
        id_seleccionada = seleccionada.tarea.id if seleccionada and seleccionada.tarea else None

        colores_estado = colores_de_estados(estados)
        self._store_base.remove_all()
        for tarea, prefijo in ordenar_jerarquicamente(tareas):
            nombre_estado = estados_por_id.get(tarea.estado_id, "")
            color_estado = colores_estado.get(tarea.estado_id, "")
            self._store_base.append(
                TareaRow(
                    prefijo + tarea.titulo,
                    [],
                    tarea=tarea,
                    estado_nombre=nombre_estado,
                    estado_color=color_estado,
                    recursos=recursos_por_tarea.get(tarea.id, []),
                    etiquetas=etiquetas_por_tarea.get(tarea.id, []),
                )
            )
        if id_seleccionada is not None:
            self._seleccionar_tarea(id_seleccionada)

    def _seleccionar_tarea(self, tarea_id: int) -> None:
        """Selecciona (y deja a la vista) la fila de esa tarea, si sigue mostrándose."""
        for posicion in range(self._modelo_filtrado.get_n_items()):
            fila = self._modelo_filtrado.get_item(posicion)
            if fila.tarea is not None and fila.tarea.id == tarea_id:
                self._selection.set_selected(posicion)
                # El ColumnView aún no ha maquetado las filas nuevas: se desplaza al ocioso.
                GLib.idle_add(
                    lambda p=posicion: self._view.scroll_to(p, None, Gtk.ListScrollFlags.NONE, None)
                )
                return

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
