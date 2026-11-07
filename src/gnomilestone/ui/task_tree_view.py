from __future__ import annotations

from collections.abc import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, Gio, GObject, Gtk, Pango

from gnomilestone.ganttcalc import tarea_vencida
from gnomilestone.i18n import _, formatear_fecha_local
from gnomilestone.models import Recurso, Tarea
from gnomilestone.ui.avatar_widget import fila_avatares

ALTURA_FILA = 32

# El tema añade su propio relleno vertical a las filas Y a las celdas de Gtk.ColumnView,
# por encima del height_request que se fija en las fábricas de columnas: poner un
# min-height en la fila no basta (es un mínimo, no un tope; si el contenido ya pide más
# por el relleno de las celdas, no hace nada), así que la altura real de fila no coincidía
# con ALTURA_FILA y desalineaba el árbol respecto a las barras del Gantt (que sí usan
# ALTURA_FILA al pie de la letra). Se anula el relleno de fila y de celda por CSS.
CLASE_FILA_FIJA = "gnomilestone-fila-fija"
_CSS_FILA_FIJA = (
    f".{CLASE_FILA_FIJA} row {{ padding-top: 0; padding-bottom: 0; min-height: 0px; }}"
    f" .{CLASE_FILA_FIJA} cell {{ padding-top: 0; padding-bottom: 0; min-height: 0px; }}"
)
_css_fila_aplicado = False


def asegurar_css_fila_fija() -> None:
    global _css_fila_aplicado
    if _css_fila_aplicado:
        return
    display = Gdk.Display.get_default()
    if display is None:
        return
    proveedor = Gtk.CssProvider()
    proveedor.load_from_string(_CSS_FILA_FIJA)
    Gtk.StyleContext.add_provider_for_display(
        display, proveedor, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
    )
    _css_fila_aplicado = True


class TareaRow(GObject.Object):
    """Fila del árbol: una Tarea real, o (en la vista global) un proyecto como nodo raíz."""

    def __init__(
        self,
        titulo: str,
        hijos: list[TareaRow],
        tarea: Tarea | None = None,
        estado_nombre: str = "",
        recursos: list[Recurso] | None = None,
    ) -> None:
        super().__init__()
        self.titulo = titulo
        self.hijos = hijos
        self.tarea = tarea
        self.estado = estado_nombre
        self.recursos: list[Recurso] = recursos or []

    @property
    def fecha_inicio(self) -> str:
        return formatear_fecha_local(self.tarea.fecha_inicio) if self.tarea and self.tarea.fecha_inicio else ""

    @property
    def fecha_fin_planificada(self) -> str:
        return (
            formatear_fecha_local(self.tarea.fecha_fin_planificada)
            if self.tarea and self.tarea.fecha_fin_planificada
            else ""
        )

    @property
    def fecha_limite(self) -> str:
        return formatear_fecha_local(self.tarea.fecha_limite) if self.tarea and self.tarea.fecha_limite else ""

    @property
    def duracion_dias(self) -> int:
        return self.tarea.duracion_dias if self.tarea else 0

    @property
    def porcentaje_completado(self) -> int:
        return self.tarea.porcentaje_completado if self.tarea else 0


def construir_filas(
    tareas: list[Tarea],
    estados_por_id: dict[int, str],
    recursos_por_tarea: dict[int, list[Recurso]] | None = None,
) -> list[TareaRow]:
    """Árbol de TareaRow (raíces con sus hijos anidados) a partir de una lista plana."""
    recursos_por_tarea = recursos_por_tarea or {}
    hijos_por_padre: dict[int | None, list[Tarea]] = {}
    for tarea in tareas:
        hijos_por_padre.setdefault(tarea.padre_id, []).append(tarea)
    for hijos in hijos_por_padre.values():
        hijos.sort(key=lambda t: t.orden)

    def _construir(tarea: Tarea) -> TareaRow:
        hijos = [_construir(hijo) for hijo in hijos_por_padre.get(tarea.id, [])]
        return TareaRow(
            tarea.titulo,
            hijos,
            tarea=tarea,
            estado_nombre=estados_por_id.get(tarea.estado_id, ""),
            recursos=recursos_por_tarea.get(tarea.id, []),
        )

    return [_construir(tarea) for tarea in hijos_por_padre.get(None, [])]


def ordenar_jerarquicamente(tareas: list[Tarea]) -> list[tuple[Tarea, str]]:
    """Tareas en orden padre-luego-hijos, con el prefijo de líneas conectoras de su fila.

    Prefijo al estilo `tree`: "├─ "/"└─ " para la propia tarea, y "│  "/"   " heredado
    de cada ancestro según si este era o no el último de sus hermanos. Lo usa `table_view.py`
    para su listado plano (sin árbol real) con indentación visual por jerarquía.
    """
    hijos_por_padre: dict[int | None, list[Tarea]] = {}
    for tarea in tareas:
        hijos_por_padre.setdefault(tarea.padre_id, []).append(tarea)
    for hijos in hijos_por_padre.values():
        hijos.sort(key=lambda t: t.orden)

    resultado: list[tuple[Tarea, str]] = []

    def _visitar(padre_id: int | None, prefijo_heredado: str) -> None:
        hijos = hijos_por_padre.get(padre_id, [])
        for indice, tarea in enumerate(hijos):
            if padre_id is None:
                # Las tareas raíz no cuelgan de ninguna línea visible: ni ellas ni sus
                # hijos heredan columna de conector por estar "bajo" la raíz.
                prefijo_propio = ""
                prefijo_para_hijos = ""
            else:
                es_ultimo = indice == len(hijos) - 1
                conector = "└─ " if es_ultimo else "├─ "
                prefijo_propio = prefijo_heredado + conector
                prefijo_para_hijos = prefijo_heredado + ("   " if es_ultimo else "│  ")
            resultado.append((tarea, prefijo_propio))
            _visitar(tarea.id, prefijo_para_hijos)

    _visitar(None, "")
    return resultado


def _crear_modelo_hijos(item: TareaRow) -> Gio.ListModel | None:
    if not item.hijos:
        return None
    store = Gio.ListStore(item_type=GObject.Object)
    for hijo in item.hijos:
        store.append(hijo)
    return store


def _widget_con_fila(widget: Gtk.Widget | None) -> TareaRow | None:
    """Sube por los padres del widget pulsado hasta encontrar la fila que llevan marcada."""
    profundidad = 0
    while widget is not None and profundidad < 10:
        fila = getattr(widget, "fila_asociada", None)
        if fila is not None:
            return fila
        widget = widget.get_parent()
        profundidad += 1
    return None


def adjuntar_menu_contextual(
    vista: Gtk.Widget,
    on_editar: Callable[[Tarea], None],
    on_eliminar: Callable[[Tarea], None],
) -> None:
    """Botón derecho sobre una fila con tarea real: Editar tarea / Eliminar tarea.

    `vista` debe pintar sus celdas con `_bind_fila` (deja marcado `fila_asociada` en el
    widget), para poder resolver con `vista.pick()` sobre qué fila se ha pulsado.
    """
    estado: dict[str, Tarea | None] = {"tarea": None}

    menu = Gio.Menu()
    menu.append(_("Editar tarea"), "contextual.editar")
    menu.append(_("Eliminar tarea"), "contextual.eliminar")
    popover = Gtk.PopoverMenu.new_from_model(menu)
    popover.set_parent(vista)

    acciones = Gio.SimpleActionGroup()
    accion_editar = Gio.SimpleAction.new("editar", None)
    accion_editar.connect("activate", lambda *_a: estado["tarea"] and on_editar(estado["tarea"]))
    acciones.add_action(accion_editar)
    accion_eliminar = Gio.SimpleAction.new("eliminar", None)
    accion_eliminar.connect(
        "activate", lambda *_a: estado["tarea"] and on_eliminar(estado["tarea"])
    )
    acciones.add_action(accion_eliminar)
    vista.insert_action_group("contextual", acciones)

    def _pulsado(gesture: Gtk.GestureClick, _n_press: int, x: float, y: float) -> None:
        fila = _widget_con_fila(vista.pick(x, y, Gtk.PickFlags.DEFAULT))
        tarea = fila.tarea if fila else None
        if tarea is None:
            return
        # Se reclama la secuencia para que el ColumnView no procese también este clic
        # (selección de fila, posible activación): si no, al soltar el botón sobre el
        # popover que se acaba de abrir se podía disparar de rebote una opción no elegida.
        gesture.set_state(Gtk.EventSequenceState.CLAIMED)
        estado["tarea"] = tarea
        # Gdk.Rectangle es un Boxed: pasarle x/y/width/height al constructor se ignora en
        # silencio (quedaba siempre en el rectángulo por defecto, de ahí que el menú
        # apareciera siempre en el mismo sitio en vez de donde se pulsaba). Hay que fijar
        # los atributos después de crearlo.
        rectangulo = Gdk.Rectangle()
        rectangulo.x = int(x)
        rectangulo.y = int(y)
        rectangulo.width = 1
        rectangulo.height = 1
        popover.set_pointing_to(rectangulo)
        popover.popup()

    gesture = Gtk.GestureClick(button=Gdk.BUTTON_SECONDARY)
    gesture.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
    gesture.connect("pressed", _pulsado)
    vista.add_controller(gesture)


def _bind_fila(label: Gtk.Widget, fila: TareaRow) -> None:
    # Permite a adjuntar_menu_contextual()/_widget_con_fila() saber, tras un widget.pick(),
    # a qué TareaRow corresponde la celda pulsada.
    label.fila_asociada = fila


def _texto_factory(bind_prop: str) -> Gtk.SignalListItemFactory:
    factory = Gtk.SignalListItemFactory()
    factory.connect(
        "setup", lambda _f, item: item.set_child(Gtk.Label(xalign=0, height_request=ALTURA_FILA))
    )

    def _bind(_factory: Gtk.SignalListItemFactory, item: Gtk.ListItem) -> None:
        fila: TareaRow = item.get_item().get_item()
        label = item.get_child()
        label.set_label(str(getattr(fila, bind_prop)))
        _bind_fila(label, fila)

    factory.connect("bind", _bind)
    return factory


def _titulo_factory() -> Gtk.SignalListItemFactory:
    factory = Gtk.SignalListItemFactory()

    def _setup(_factory: Gtk.SignalListItemFactory, item: Gtk.ListItem) -> None:
        expander = Gtk.TreeExpander()
        label = Gtk.Label(xalign=0, height_request=ALTURA_FILA)
        label.set_ellipsize(Pango.EllipsizeMode.END)
        expander.set_child(label)
        item.set_child(expander)

    def _bind(_factory: Gtk.SignalListItemFactory, item: Gtk.ListItem) -> None:
        tree_row = item.get_item()
        fila: TareaRow = tree_row.get_item()
        expander = item.get_child()
        expander.set_list_row(tree_row)
        label = expander.get_child()
        label.set_label(fila.titulo)
        vencida = fila.tarea is not None and tarea_vencida(fila.tarea)
        tooltip = fila.titulo
        if vencida:
            tooltip += f"\n({_('Vencida: ya pasó su fecha de fin')})"
            label.add_css_class("error")
        else:
            label.remove_css_class("error")
        label.set_tooltip_text(tooltip)
        _bind_fila(expander, fila)

    factory.connect("setup", _setup)
    factory.connect("bind", _bind)
    return factory


def _recursos_factory() -> Gtk.SignalListItemFactory:
    factory = Gtk.SignalListItemFactory()

    def _setup(_factory: Gtk.SignalListItemFactory, item: Gtk.ListItem) -> None:
        item.set_child(Gtk.Box(height_request=ALTURA_FILA, valign=Gtk.Align.CENTER))

    def _bind(_factory: Gtk.SignalListItemFactory, item: Gtk.ListItem) -> None:
        tree_row = item.get_item()
        fila: TareaRow = tree_row.get_item()
        caja = item.get_child()
        while (hijo := caja.get_first_child()) is not None:
            caja.remove(hijo)
        avatares = fila_avatares(fila.recursos, size=24, maximo=3, height_request=ALTURA_FILA)
        caja.append(avatares)
        _bind_fila(caja, fila)

    factory.connect("setup", _setup)
    factory.connect("bind", _bind)
    return factory


COLUMNAS_INFO: tuple[tuple[str, str, bool, bool], ...] = (
    ("titulo", _("Título"), True, True),
    ("asignado", _("Asignado"), False, True),
    ("estado", _("Columna"), False, False),
    ("fecha_inicio", _("Inicio"), False, False),
    ("fecha_fin_planificada", _("Final planificado"), False, False),
    ("fecha_limite", _("Fecha límite"), False, False),
    ("duracion_dias", _("Duración (días)"), False, False),
    ("porcentaje_completado", _("% completado"), False, False),
)


class TaskTreeView(Gtk.ColumnView):
    """Árbol de tareas/subtareas sincronizable (por fila visible) con el Gantt.

    Doble clic y menú contextual (botón derecho) para editar/eliminar la tarea de la
    fila pulsada, si se pasan `on_editar`/`on_eliminar`.
    """

    def __init__(
        self,
        on_editar: Callable[[Tarea], None] | None = None,
        on_eliminar: Callable[[Tarea], None] | None = None,
    ) -> None:
        asegurar_css_fila_fija()
        self._root_store = Gio.ListStore(item_type=GObject.Object)
        self.tree_model = Gtk.TreeListModel.new(self._root_store, False, True, _crear_modelo_hijos)
        self._selection = Gtk.SingleSelection(model=self.tree_model)
        super().__init__(model=self._selection)
        self.add_css_class(CLASE_FILA_FIJA)

        self._columnas: dict[str, Gtk.ColumnViewColumn] = {}

        col_titulo = Gtk.ColumnViewColumn(
            title=_("Título"), factory=_titulo_factory(), expand=True, resizable=True
        )
        self.append_column(col_titulo)
        self._columnas["titulo"] = col_titulo

        col_asignado = Gtk.ColumnViewColumn(
            title=_("Asignado"), factory=_recursos_factory(), resizable=True
        )
        self.append_column(col_asignado)
        self._columnas["asignado"] = col_asignado

        for clave, titulo, propiedad, visible_defecto in (
            ("estado", _("Columna"), "estado", False),
            ("fecha_inicio", _("Inicio"), "fecha_inicio", False),
            ("fecha_fin_planificada", _("Final planificado"), "fecha_fin_planificada", False),
            ("fecha_limite", _("Fecha límite"), "fecha_limite", False),
            ("duracion_dias", _("Duración (días)"), "duracion_dias", False),
            ("porcentaje_completado", _("% completado"), "porcentaje_completado", False),
        ):
            col = Gtk.ColumnViewColumn(
                title=titulo, factory=_texto_factory(propiedad), resizable=True
            )
            col.set_visible(visible_defecto)
            self.append_column(col)
            self._columnas[clave] = col

        if on_editar is not None:
            self.connect("activate", self._on_activate, on_editar)
        if on_editar is not None and on_eliminar is not None:
            adjuntar_menu_contextual(self, on_editar, on_eliminar)

    def columnas_disponibles(self) -> list[tuple[str, str, bool]]:
        """Devuelve (clave, etiqueta, es_fija) para cada columna del árbol."""
        return [(clave, etiqueta, fija) for clave, etiqueta, fija, _def in COLUMNAS_INFO]

    def set_columna_visible(self, clave: str, visible: bool) -> None:
        col = self._columnas.get(clave)
        if col is not None:
            col.set_visible(visible)

    def is_columna_visible(self, clave: str) -> bool:
        col = self._columnas.get(clave)
        return col.get_visible() if col is not None else False

    def _on_activate(
        self, _view: Gtk.ColumnView, posicion: int, on_editar: Callable[[Tarea], None]
    ) -> None:
        tree_row = self.tree_model.get_item(posicion)
        fila: TareaRow = tree_row.get_item()
        if fila.tarea is not None:
            on_editar(fila.tarea)

    def set_filas(self, filas: list[TareaRow]) -> None:
        self._root_store.remove_all()
        for fila in filas:
            self._root_store.append(fila)

    def filas_visibles(self) -> list[tuple[TareaRow, int]]:
        """(fila, profundidad) de cada fila mostrada ahora (según expandir/colapsar), en orden."""
        resultado = []
        for indice in range(self.tree_model.get_n_items()):
            tree_row = self.tree_model.get_item(indice)
            resultado.append((tree_row.get_item(), tree_row.get_depth()))
        return resultado
