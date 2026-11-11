from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from datetime import date, datetime, timedelta

import gi

gi.require_version("Gdk", "4.0")
gi.require_version("Gtk", "4.0")
from gi.repository import Gdk, GLib, Gtk

from gnomilestone import completado
from gnomilestone.etiquetas import color_automatico, color_de_texto
from gnomilestone.i18n import _, formatear_fecha_local
from gnomilestone.markdown_pango import markdown_a_pango
from gnomilestone.models import Recurso, Tarea
from gnomilestone.store import CicloDependenciaError, Store
from gnomilestone.sync import GitHubSyncManager
from gnomilestone.ui.avatar_widget import AvatarWidget
from gnomilestone.ui.aviso_dependencias import confirmar_completar
from gnomilestone.ui.envoltura import crear_envoltura
from gnomilestone.ui.envoltura import vaciar as vaciar_envoltura
from gnomilestone.ui.kanban_view import _PALETA_COLUMNAS
from gnomilestone.ui.markdown_editor import MarkdownEditor
from gnomilestone.ui.prioridad_icono import crear_icono_prioridad
from gnomilestone.ui.task_tree_view import ordenar_jerarquicamente

log = logging.getLogger(__name__)

_PORCENTAJES_RAPIDOS = (0, 25, 50, 75, 100)

_css_completar: Gtk.CssProvider | None = None


def _aplicar_css_completar() -> None:
    """Estilo verde del botón «Completar» (el mismo verde que las tareas completadas)."""
    global _css_completar
    if _css_completar is not None:
        return
    _css_completar = Gtk.CssProvider()
    _css_completar.load_from_string(
        "button.gnomilestone-completar { background-image: linear-gradient(to bottom,"
        " #4fa86f, #2f7f4f); color: white; border-color: #2a6e44; text-shadow: none; }\n"
        "button.gnomilestone-completar:hover { background-image: linear-gradient(to bottom,"
        " #5fb87f, #38905a); }\n"
        "button.gnomilestone-completar:active { background-image: none; background-color: #2a6e44; }\n"
    )
    Gtk.StyleContext.add_provider_for_display(
        Gdk.Display.get_default(), _css_completar, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
    )


def _descendientes(tareas: list[Tarea], raiz_id: int) -> set[int]:
    hijos_por_padre: dict[int | None, list[int]] = {}
    for tarea in tareas:
        hijos_por_padre.setdefault(tarea.padre_id, []).append(tarea.id)
    resultado: set[int] = set()
    pendientes = list(hijos_por_padre.get(raiz_id, []))
    while pendientes:
        actual = pendientes.pop()
        if actual in resultado:
            continue
        resultado.add(actual)
        pendientes.extend(hijos_por_padre.get(actual, []))
    return resultado


def _fecha_a_iso(fecha: GLib.DateTime) -> str:
    return f"{fecha.get_year():04d}-{fecha.get_month():02d}-{fecha.get_day_of_month():02d}"


_COLOR_HITO = "#f2a61f"  # ámbar, el mismo de los hitos del Gantt y el Tablero
_ANCHO_INICIAL = 720
_ALTO_INICIAL = 860
_ALTO_MINIMO = 640


def _alto_inicial(parent: Gtk.Window | None) -> int:
    """Alto con el que se abre el diálogo: el que cabe sin scroll en lo posible, pero sin pasarse
    del 90 % del alto de la pantalla donde está la ventana principal."""
    try:
        display = Gdk.Display.get_default()
        superficie = parent.get_surface() if parent is not None else None
        monitor = display.get_monitor_at_surface(superficie) if superficie else None
        if monitor is None:
            monitor = display.get_monitors().get_item(0)
        return max(_ALTO_MINIMO, min(_ALTO_INICIAL, int(monitor.get_geometry().height * 0.9)))
    except (AttributeError, TypeError, GLib.Error):
        return _ALTO_MINIMO


class _SelectorFecha:
    """Botón con calendario emergente. `valor` es ISO o None.

    El día elegido en el calendario no se aplica hasta pulsar «Aplicar»; los atajos
    (Hoy, Mañana, Próxima semana, Sin fecha) aplican y cierran al momento."""

    def __init__(self, fecha_inicial: str | None, on_change: Callable[[], None]) -> None:
        self.valor = fecha_inicial
        self._on_change = on_change
        self.widget = Gtk.MenuButton()

        popover = Gtk.Popover()
        self._popover = popover
        popover_box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=8,
            margin_top=10,
            margin_bottom=10,
            margin_start=10,
            margin_end=10,
        )
        self._calendar = Gtk.Calendar()
        self._mostrar_en_calendario(fecha_inicial)
        # Al reabrir, el calendario vuelve a mostrar la fecha aplicada (se descarta lo
        # que se hubiera navegado o marcado sin pulsar «Aplicar»).
        popover.connect("show", lambda _p: self._mostrar_en_calendario(self.valor))
        popover_box.append(self._calendar)

        botones_rapidos = Gtk.Box(spacing=6, homogeneous=True)
        for icono, etiqueta, dias in (
            ("x-office-calendar-symbolic", _("Hoy"), lambda hoy: 0),
            ("go-next-symbolic", _("Mañana"), lambda hoy: 1),
            # Lunes de la semana siguiente (si hoy es lunes, el de dentro de 7 días).
            ("media-skip-forward-symbolic", _("Próxima semana"), lambda hoy: 7 - hoy.weekday()),
        ):
            boton = self._boton_con_icono(icono, etiqueta)
            boton.connect("clicked", self._on_preset, dias)
            botones_rapidos.append(boton)
        popover_box.append(botones_rapidos)
        quitar_button = self._boton_con_icono("edit-clear-symbolic", _("Sin fecha"))
        quitar_button.connect("clicked", lambda _b: self._aplicar(None))
        popover_box.append(quitar_button)
        aplicar_button = Gtk.Button(label=_("Aplicar"))
        aplicar_button.add_css_class("suggested-action")
        aplicar_button.connect(
            "clicked", lambda _b: self._aplicar(_fecha_a_iso(self._calendar.get_date()))
        )
        popover_box.append(aplicar_button)

        popover.set_child(popover_box)
        self.widget.set_popover(popover)
        self._actualizar_etiqueta()

    @staticmethod
    def _boton_con_icono(icono: str, etiqueta: str) -> Gtk.Button:
        contenido = Gtk.Box(spacing=6, halign=Gtk.Align.CENTER)
        contenido.append(Gtk.Image.new_from_icon_name(icono))
        contenido.append(Gtk.Label(label=etiqueta))
        boton = Gtk.Button()
        boton.set_child(contenido)
        return boton

    def _mostrar_en_calendario(self, valor: str | None) -> None:
        if valor:
            anio, mes, dia = (int(parte) for parte in valor.split("-"))
            self._calendar.select_day(GLib.DateTime.new_local(anio, mes, dia, 0, 0, 0))

    def _actualizar_etiqueta(self) -> None:
        if self.valor:
            anio, mes, dia = self.valor.split("-")
            self.widget.set_label(f"{dia}/{mes}/{anio}")
        else:
            self.widget.set_label(_("Sin fecha"))

    def establecer(self, valor: str | None) -> None:
        cambio = valor != self.valor
        self.valor = valor
        self._actualizar_etiqueta()
        if cambio:
            self._on_change()

    def _aplicar(self, valor: str | None) -> None:
        self.establecer(valor)
        self._popover.popdown()

    def _on_preset(self, _button: Gtk.Button, dias_desde_hoy: Callable[[date], int]) -> None:
        ahora = GLib.DateTime.new_now_local()
        hoy = date(ahora.get_year(), ahora.get_month(), ahora.get_day_of_month())
        destino = hoy + timedelta(days=dias_desde_hoy(hoy))
        # select_day no dispara "day-selected" si el calendario ya mostraba ese día
        # (p. ej. al reabrir el diálogo): se actualiza el estado a mano, no solo por la señal.
        self._mostrar_en_calendario(destino.isoformat())
        self._aplicar(destino.isoformat())


class _SugerenciasEntry:
    """Lista de sugerencias bajo un `Gtk.Entry`: un clic en un nombre llama a `on_elegida`.

    `obtener(texto)` recibe el texto ya en minúsculas y devuelve los nombres a mostrar.
    La lista no toma el foco, así que el campo sigue recibiendo lo que se escribe.
    """

    def __init__(
        self,
        entry: Gtk.Entry,
        obtener: Callable[[str], list[str]],
        on_elegida: Callable[[str], None],
    ) -> None:
        self._entry = entry
        self._obtener = obtener
        self._on_elegida = on_elegida
        self._lista = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE, focusable=False)
        self._lista.connect("row-activated", self._on_fila)
        scroller = Gtk.ScrolledWindow(
            hscrollbar_policy=Gtk.PolicyType.NEVER,
            propagate_natural_height=True,
            max_content_height=200,
            focusable=False,
        )
        scroller.set_child(self._lista)
        self._popover = Gtk.Popover(
            autohide=False, has_arrow=False, position=Gtk.PositionType.BOTTOM, focusable=False
        )
        self._popover.set_child(scroller)
        self._popover.set_parent(entry)
        entry.connect("destroy", lambda _w: self._popover.unparent())
        entry.connect("changed", lambda _e: self.actualizar(False))
        foco = Gtk.EventControllerFocus()
        foco.connect("enter", lambda _c: self.actualizar(True))
        foco.connect("leave", lambda _c: GLib.timeout_add(150, self._ocultar))
        entry.add_controller(foco)
        teclas = Gtk.EventControllerKey()
        teclas.connect("key-pressed", self._on_tecla)
        entry.add_controller(teclas)

    def _on_tecla(self, _ctrl, keyval, _keycode, _estado) -> bool:
        if keyval == Gdk.KEY_Escape and self._popover.get_visible():
            self._popover.popdown()
            return True
        return False

    def _ocultar(self) -> bool:
        if not self._entry.has_focus():
            self._popover.popdown()
        return GLib.SOURCE_REMOVE

    def actualizar(self, mostrar_si_vacio: bool) -> None:
        texto = self._entry.get_text().strip().casefold()
        if not texto and not mostrar_si_vacio:
            self._popover.popdown()
            return
        nombres = self._obtener(texto)
        while (fila := self._lista.get_first_child()) is not None:
            self._lista.remove(fila)
        if not nombres:
            self._popover.popdown()
            return
        for nombre in nombres:
            self._lista.append(
                Gtk.Label(
                    label=nombre, xalign=0, margin_top=4, margin_bottom=4, margin_start=8, margin_end=8
                )
            )
        self._popover.set_size_request(self._entry.get_width(), -1)
        self._popover.popup()

    def _on_fila(self, _lista: Gtk.ListBox, fila: Gtk.ListBoxRow) -> None:
        self._popover.popdown()
        self._on_elegida(fila.get_child().get_label())


class TaskDialog(Gtk.Window):
    """Alta/edición de una tarea: jerarquía, estado, fechas, progreso y dependencias."""

    def __init__(
        self,
        parent: Gtk.Window,
        store: Store,
        proyecto_id: int,
        on_saved: Callable[[], None],
        tarea: Tarea | None = None,
    ) -> None:
        super().__init__(
            title=_("Editar tarea") if tarea else _("Nueva tarea"),
            default_width=_ANCHO_INICIAL,
            default_height=_alto_inicial(parent),
        )
        self.set_resizable(True)
        # Ni modal ni «transient»: Mutter no deja maximizar los diálogos con ventana madre;
        # así el escritorio ofrece su botón de maximizar normal.
        self._parent = parent
        self._store = store
        self._proyecto_id = proyecto_id
        self._on_saved = on_saved
        self._tarea = tarea
        self._cierre_forzado = False
        self._actualizando_fechas = False
        self._marcados_error: list[Gtk.Widget] = []

        todas = store.listar_tareas(proyecto_id)
        excluidas = {tarea.id} | _descendientes(todas, tarea.id) if tarea else set()
        # Orden jerárquico (padre y luego hijos) con el prefijo de conectores del listado.
        ordenadas = ordenar_jerarquicamente([t for t in todas if t.id not in excluidas])
        self._candidatas_padre = [t for t, _prefijo in ordenadas]
        self._prefijos_jerarquia = {t.id: prefijo for t, prefijo in ordenadas}
        self._candidatas_dependencia = self._candidatas_padre
        self._estados = store.listar_estados(proyecto_id)

        dependencias_actuales = {
            d.tarea_origen_id
            for d in store.listar_dependencias(proyecto_id)
            if tarea and d.tarea_destino_id == tarea.id
        }

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.set_child(root)

        self._notebook = Gtk.Notebook(vexpand=True)
        root.append(self._notebook)
        self._pagina_general = self._nueva_pagina(_("General"))
        self._pagina_fechas = self._nueva_pagina(_("Fechas y progreso"))
        self._pagina_asignaciones = self._nueva_pagina(_("Asignaciones"))
        self._pagina_dependencias = self._nueva_pagina(_("Dependencias"))
        # Los comentarios cuelgan de una tarea ya guardada: solo al editar.
        self._pagina_comentarios = self._nueva_pagina(_("Comentarios")) if tarea else None
        self._pagina_historial = self._nueva_pagina(_("Historial")) if tarea else None

        self._construir_general(tarea)
        self._construir_fechas(tarea)
        self._construir_asignaciones(tarea)
        self._construir_dependencias(dependencias_actuales)
        if tarea:
            self._construir_comentarios()
            self._construir_historial()

        self._error_label = Gtk.Label(
            xalign=0, wrap=True, margin_start=16, margin_end=16, margin_top=4
        )
        self._error_label.add_css_class("error")
        self._error_label.set_visible(False)
        root.append(self._error_label)

        if self._tarea and (self._tarea.github_url or self._tarea.github_issue_number):
            texto_gh = _("Ver en GitHub (#{num})").format(num=self._tarea.github_issue_number or "")
            gh_link = Gtk.LinkButton(uri=self._tarea.github_url or "", label=texto_gh)
            gh_link.set_halign(Gtk.Align.START)
            gh_link.set_margin_start(10)
            root.append(gh_link)

        acciones = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=8,
            margin_top=8,
            margin_bottom=10,
            margin_start=16,
            margin_end=16,
        )
        if self._tarea is not None:
            eliminar_button = Gtk.Button(label=_("Eliminar"))
            eliminar_button.add_css_class("destructive-action")
            eliminar_button.connect("clicked", self._on_eliminar)
            acciones.append(eliminar_button)
            archivar_button = Gtk.Button(label=_("Archivar"))
            archivar_button.set_tooltip_text(
                _("Quitarla de todas las vistas; se recupera desde «Tareas archivadas»")
            )
            archivar_button.connect("clicked", self._on_archivar)
            acciones.append(archivar_button)
        acciones.append(Gtk.Box(hexpand=True))
        cancelar_button = Gtk.Button(label=_("Cancelar"))
        cancelar_button.connect("clicked", lambda _button: self.close())
        acciones.append(cancelar_button)
        if self._tarea is None:
            otra_button = Gtk.Button(label=_("Guardar y crear otra"))
            otra_button.connect("clicked", self._on_guardar_y_crear_otra)
            acciones.append(otra_button)
        if self._tarea is not None:
            # Solo en tareas abiertas: se oculta al llegar al 100 %.
            self._completar_button = Gtk.Button(label=_("Completar"))
            _aplicar_css_completar()
            self._completar_button.add_css_class("gnomilestone-completar")
            self._completar_button.set_tooltip_text(
                _("Marcarla al 100 %, moverla a la columna de completadas y guardar")
            )
            self._completar_button.connect("clicked", self._on_completar)
            self._completar_button.set_visible(self._porcentaje_scale.get_value() < 100)
            acciones.append(self._completar_button)
        save_button = Gtk.Button(label=_("Guardar"))
        save_button.add_css_class("suggested-action")
        save_button.connect("clicked", self._on_save)
        acciones.append(save_button)
        root.append(acciones)

        self._estado_inicial = self._capturar_estado()
        self.connect("close-request", self._on_close_request)

    # ------------------------------------------------------------------ construcción

    def _nueva_pagina(self, titulo: str) -> Gtk.Box:
        box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=10,
            margin_top=16,
            margin_bottom=16,
            margin_start=16,
            margin_end=16,
        )
        scroller = Gtk.ScrolledWindow(
            vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER, kinetic_scrolling=True
        )
        scroller.set_child(box)
        self._notebook.append_page(scroller, Gtk.Label(label=titulo))
        return box

    def _construir_general(self, tarea: Tarea | None) -> None:
        box = self._pagina_general
        box.append(Gtk.Label(label=_("Título"), xalign=0))
        self._titulo_entry = Gtk.Entry(text=tarea.titulo if tarea else "")
        box.append(self._titulo_entry)

        self._descripcion_editor = MarkdownEditor(
            _("Descripción"),
            texto=tarea.descripcion if tarea else "",
            texto_vacio=_("Sin descripción"),
        )
        box.append(self._descripcion_editor)

        box.append(Gtk.Label(label=_("Tarea padre"), xalign=0))
        self._padre_dropdown = self._crear_selector_tareas(tarea)
        box.append(self._padre_dropdown)

        box.append(Gtk.Label(label=_("Columna"), xalign=0))
        self._estado_dropdown = self._crear_selector_columnas(tarea)
        box.append(self._estado_dropdown)

        # Hito (Milestone de GitHub) al que contribuye la tarea.
        etiqueta_hito = Gtk.Label(xalign=0, use_markup=True)
        etiqueta_hito.set_markup(f'<span foreground="{_COLOR_HITO}">◆</span> {_("Hito")}')
        box.append(etiqueta_hito)
        self._hitos = self._store.listar_hitos(self._proyecto_id)
        self._hito_dropdown = Gtk.DropDown.new_from_strings(
            [_("Sin hito")]
            + [
                f"{h.titulo} · {formatear_fecha_local(h.fecha)}" if h.fecha else h.titulo
                for h in self._hitos
            ]
        )
        if tarea and tarea.hito_id is not None:
            ids = [h.id for h in self._hitos]
            if tarea.hito_id in ids:
                self._hito_dropdown.set_selected(ids.index(tarea.hito_id) + 1)
        box.append(self._hito_dropdown)

        box.append(Gtk.Label(label=_("Prioridad"), xalign=0))
        self._prioridad_dropdown = self._crear_selector_prioridad(tarea)
        box.append(self._prioridad_dropdown)

        box.append(Gtk.Label(label=_("Etiquetas"), xalign=0))
        self._colores_etiquetas = {
            e.nombre.casefold(): e.color for e in self._store.listar_etiquetas(self._proyecto_id)
        }
        self._etiquetas: list[tuple[str, str]] = (
            [(e.nombre, e.color) for e in self._store.listar_etiquetas_de_tarea(tarea.id)]
            if tarea
            else []
        )
        # Chips en fila, cada uno con su ancho (un FlowBox los reparte en columnas iguales y los
        # separa cientos de píxeles); saltan de línea solo si no caben.
        self._etiquetas_box = crear_envoltura(espacio=4, espacio_vertical=4)
        box.append(self._etiquetas_box)
        self._etiqueta_entry = Gtk.Entry(placeholder_text=_("Añadir etiqueta (Enter para crear)"))
        self._etiqueta_entry.connect("activate", self._on_etiqueta_escrita)
        _SugerenciasEntry(self._etiqueta_entry, self._sugerencias_etiquetas, self._anadir_etiqueta)
        box.append(self._etiqueta_entry)
        self._refrescar_etiquetas()

    def _crear_selector_tareas(self, tarea: Tarea | None) -> Gtk.DropDown:
        titulos = [_("Ninguna")] + [t.titulo for t in self._candidatas_padre]
        dropdown = Gtk.DropDown.new_from_strings(titulos)
        dropdown.set_enable_search(True)
        # Por defecto GTK busca por prefijo; aquí, como en Dependencias, se busca en
        # cualquier parte del título («informes» encuentra «Mejorar informes»).
        dropdown.set_search_match_mode(Gtk.StringFilterMatchMode.SUBSTRING)
        dropdown.set_expression(Gtk.PropertyExpression.new(Gtk.StringObject, None, "string"))
        prefijos = [""] + [self._prefijos_jerarquia[t.id] for t in self._candidatas_padre]

        # En la lista desplegable cada tarea lleva sus conectores de jerarquía; el botón
        # cerrado solo muestra el título.
        factory = Gtk.SignalListItemFactory()
        factory.connect("setup", lambda _f, item: item.set_child(Gtk.Label(xalign=0)))

        def _vincular(_f: Gtk.SignalListItemFactory, item: Gtk.ListItem) -> None:
            item.get_child().set_text(prefijos[item.get_position()] + item.get_item().get_string())

        factory.connect("bind", _vincular)
        dropdown.set_list_factory(factory)

        if tarea and tarea.padre_id is not None:
            ids = [t.id for t in self._candidatas_padre]
            if tarea.padre_id in ids:
                dropdown.set_selected(ids.index(tarea.padre_id) + 1)
        return dropdown

    def _crear_selector_prioridad(self, tarea: Tarea | None) -> Gtk.DropDown:
        # El orden de la lista es el del nivel (0 ninguna … 4 urgente): el índice seleccionado
        # es directamente el valor que se guarda.
        dropdown = Gtk.DropDown.new_from_strings(
            [_("Sin prioridad"), _("Baja"), _("Media"), _("Alta"), _("Urgente")]
        )

        def _preparar(_f: Gtk.SignalListItemFactory, item: Gtk.ListItem) -> None:
            item.set_child(Gtk.Box(spacing=8))

        def _vincular(_f: Gtk.SignalListItemFactory, item: Gtk.ListItem) -> None:
            caja = item.get_child()
            while (hijo := caja.get_first_child()) is not None:
                caja.remove(hijo)
            icono = crear_icono_prioridad(item.get_position())
            # «Sin prioridad» lleva un hueco del tamaño del icono para alinear los textos.
            caja.append(icono if icono is not None else Gtk.Box(width_request=16))
            caja.append(Gtk.Label(label=item.get_item().get_string(), xalign=0))

        factory = Gtk.SignalListItemFactory()
        factory.connect("setup", _preparar)
        factory.connect("bind", _vincular)
        dropdown.set_factory(factory)
        dropdown.set_list_factory(factory)
        dropdown.set_selected(tarea.prioridad if tarea else 0)
        return dropdown

    def _crear_selector_columnas(self, tarea: Tarea | None) -> Gtk.DropDown:
        dropdown = Gtk.DropDown.new_from_strings([e.nombre for e in self._estados])
        colores = [_PALETA_COLUMNAS[i % len(_PALETA_COLUMNAS)] for i in range(len(self._estados))]

        # Punto del mismo color que la franja de la columna en el Tablero.
        def _vincular(_f: Gtk.SignalListItemFactory, item: Gtk.ListItem) -> None:
            nombre = GLib.markup_escape_text(item.get_item().get_string())
            item.get_child().set_markup(
                f'<span foreground="{colores[item.get_position()]}">●</span> {nombre}'
            )

        factory = Gtk.SignalListItemFactory()
        factory.connect("setup", lambda _f, item: item.set_child(Gtk.Label(xalign=0)))
        factory.connect("bind", _vincular)
        dropdown.set_factory(factory)
        dropdown.set_list_factory(factory)

        if tarea and tarea.estado_id is not None:
            ids = [e.id for e in self._estados]
            if tarea.estado_id in ids:
                dropdown.set_selected(ids.index(tarea.estado_id))
        return dropdown

    def _construir_fechas(self, tarea: Tarea | None) -> None:
        box = self._pagina_fechas
        fecha_fin = tarea.fecha_fin_planificada if tarea else None
        if not fecha_fin and tarea and tarea.fecha_inicio:
            fecha_fin = (
                date.fromisoformat(tarea.fecha_inicio)
                + timedelta(days=max(tarea.duracion_dias, 1) - 1)
            ).isoformat()

        box.append(Gtk.Label(label=_("Fecha de inicio"), xalign=0))
        self._inicio = _SelectorFecha(tarea.fecha_inicio if tarea else None, self._on_inicio_cambio)
        box.append(self._inicio.widget)

        fin_label = Gtk.Label(label=_("Planificado"), xalign=0)
        self._fin = _SelectorFecha(fecha_fin, self._on_fin_cambio)
        box.append(fin_label)
        box.append(self._fin.widget)

        box.append(Gtk.Label(label=_("Planificado inicial"), xalign=0))
        self._fin_inicial = _SelectorFecha(
            tarea.fecha_fin_planificada_inicial if tarea else fecha_fin,
            lambda: None,
        )
        self._fin_inicial.widget.set_sensitive(False)
        box.append(self._fin_inicial.widget)
        self._editar_planificacion_base = Gtk.CheckButton(label=_("Desbloquear edición"))
        self._editar_planificacion_base.connect(
            "toggled", lambda check: self._fin_inicial.widget.set_sensitive(check.get_active())
        )
        box.append(self._editar_planificacion_base)

        box.append(Gtk.Label(label=_("Final real"), xalign=0))
        self._fin_real = _SelectorFecha(tarea.fecha_fin_real if tarea else None, lambda: None)
        box.append(self._fin_real.widget)

        duracion_label = Gtk.Label(label=_("Duración (días)"), xalign=0)
        self._duracion_spin = Gtk.SpinButton.new_with_range(1, 3650, 1)
        self._duracion_spin.set_value(max(tarea.duracion_dias, 1) if tarea else 1)
        if tarea and tarea.fecha_inicio and fecha_fin:
            self._duracion_spin.set_value(self._duracion_entre(tarea.fecha_inicio, fecha_fin))
        self._duracion_spin.connect("value-changed", self._on_duracion_cambio)
        box.append(duracion_label)
        box.append(self._duracion_spin)
        # El día final cuenta: del 11 al 15 son 5 días (inicio + duración − 1).
        ayuda_dias = _("Se cuentan el día de inicio y el final: del 11 al 15 son 5 días.")
        for widget in (fin_label, self._fin.widget, duracion_label, self._duracion_spin):
            widget.set_tooltip_text(ayuda_dias)

        box.append(Gtk.Label(label=_("Límite"), xalign=0))
        self._limite = _SelectorFecha(tarea.fecha_limite if tarea else None, lambda: None)
        box.append(self._limite.widget)

        box.append(Gtk.Label(label=_("Porcentaje completado"), xalign=0))
        fila_porcentaje = Gtk.Box(spacing=8)
        self._porcentaje_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 5)
        self._porcentaje_scale.set_digits(0)
        self._porcentaje_scale.set_hexpand(True)
        self._porcentaje_scale.set_value(tarea.porcentaje_completado if tarea else 0)
        self._porcentaje_label = Gtk.Label(width_chars=5)
        self._porcentaje_scale.connect("value-changed", self._on_porcentaje_cambio)
        self._on_porcentaje_cambio(self._porcentaje_scale)
        # Solo ante cambios del usuario (no al abrir): al completar se ve la fecha de hoy.
        self._porcentaje_scale.connect("value-changed", self._on_porcentaje_fin_real)
        fila_porcentaje.append(self._porcentaje_scale)
        fila_porcentaje.append(self._porcentaje_label)
        box.append(fila_porcentaje)
        rapidos = Gtk.Box(spacing=6)
        for valor in _PORCENTAJES_RAPIDOS:
            boton = Gtk.Button(label=f"{valor} %")
            boton.connect("clicked", lambda _b, v=valor: self._porcentaje_scale.set_value(v))
            rapidos.append(boton)
        box.append(rapidos)


    def _construir_asignaciones(self, tarea: Tarea | None) -> None:
        box = self._pagina_asignaciones
        box.append(Gtk.Label(label=_("Asignado a"), xalign=0))
        self._asignados: list[Recurso] = (
            list(self._store.listar_recursos_de_tarea(tarea.id)) if tarea else []
        )
        self._dedicaciones: dict[int, int] = {
            asignacion.recurso_id: asignacion.porcentaje_dedicacion
            for asignacion in (self._store.listar_asignaciones(tarea.id) if tarea else [])
        }
        self._asignados_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.append(self._asignados_box)
        asignar_fila = Gtk.Box(spacing=6)
        self._asignar_entry = Gtk.Entry(
            placeholder_text=_("Nombre (se crea al asignar)"), hexpand=True
        )
        self._asignar_entry.connect("activate", self._on_asignar)
        _SugerenciasEntry(self._asignar_entry, self._sugerencias_recursos, self._on_recurso_sugerido)
        asignar_fila.append(self._asignar_entry)
        asignar_button = Gtk.Button(icon_name="list-add-symbolic", tooltip_text=_("Asignar"))
        asignar_button.connect("clicked", self._on_asignar)
        asignar_fila.append(asignar_button)
        box.append(asignar_fila)
        self._refrescar_asignados()

    def _construir_dependencias(self, dependencias_actuales: set[int]) -> None:
        box = self._pagina_dependencias
        self._dependencia_checks: list[tuple[int, Gtk.CheckButton]] = []
        if not self._candidatas_dependencia:
            vacio = Gtk.Label(label=_("No hay otras tareas de las que depender."), xalign=0)
            vacio.add_css_class("dim-label")
            box.append(vacio)
            return
        box.append(Gtk.Label(label=_("Depende de"), xalign=0))
        self._dependencias_busqueda = Gtk.SearchEntry(
            placeholder_text=_("Buscar tarea…"), hexpand=True
        )
        self._dependencias_busqueda.connect("search-changed", self._on_buscar_dependencia)
        box.append(self._dependencias_busqueda)
        dependencias_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        for candidata in self._candidatas_dependencia:
            check = Gtk.CheckButton(
                label=self._prefijos_jerarquia[candidata.id] + candidata.titulo
            )
            check.set_active(candidata.id in dependencias_actuales)
            dependencias_box.append(check)
            self._dependencia_checks.append((candidata.id, check))
        box.append(dependencias_box)

    def _construir_comentarios(self) -> None:
        box = self._pagina_comentarios
        self._comentarios_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.append(self._comentarios_box)

        self._comentario_editando: int | None = None
        self._comentario_titulo = Gtk.Label(label=_("Nuevo comentario"), xalign=0, margin_top=8)
        box.append(self._comentario_titulo)
        self._comentario_buffer = Gtk.TextBuffer()
        vista = Gtk.TextView(
            buffer=self._comentario_buffer,
            wrap_mode=Gtk.WrapMode.WORD_CHAR,
            top_margin=6,
            bottom_margin=6,
            left_margin=6,
            right_margin=6,
        )
        scroller = Gtk.ScrolledWindow(height_request=80, hscrollbar_policy=Gtk.PolicyType.NEVER)
        scroller.add_css_class("card")
        scroller.set_child(vista)
        box.append(scroller)
        botones = Gtk.Box(spacing=8, halign=Gtk.Align.END)
        self._comentario_cancelar = Gtk.Button(label=_("Cancelar edición"), visible=False)
        self._comentario_cancelar.connect("clicked", lambda _b: self._salir_de_edicion_comentario())
        botones.append(self._comentario_cancelar)
        self._comentario_enviar = Gtk.Button(label=_("Comentar"))
        self._comentario_enviar.add_css_class("suggested-action")
        self._comentario_enviar.connect("clicked", self._on_comentar)
        botones.append(self._comentario_enviar)
        box.append(botones)
        self._refrescar_comentarios()

    def _construir_historial(self) -> None:
        box = self._pagina_historial
        eventos = self._store.listar_historial_tarea(self._tarea.id)
        if not eventos:
            vacio = Gtk.Label(label=_("Sin actividad registrada"), xalign=0)
            vacio.add_css_class("dim-label")
            box.append(vacio)
            return
        for evento in eventos:
            tarjeta = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
            tarjeta.add_css_class("card")
            fecha = Gtk.Label(label=evento.creado, xalign=0)
            fecha.add_css_class("dim-label")
            tarjeta.append(fecha)
            titulo = {
                "creacion": _("Tarea creada"),
                "estado": _("Estado cambiado"),
                "progreso": _("Progreso cambiado"),
                "planificacion": _("Final planificado cambiado"),
                "planificacion_base": _("Planificado inicial cambiado"),
                "fin_real": _("Final real cambiado"),
                "fecha_inicio": _("Inicio cambiado"),
                "limite": _("Límite cambiado"),
            }.get(evento.tipo, evento.tipo)
            tarjeta.append(Gtk.Label(label=titulo, xalign=0))
            detalle = evento.detalle
            if evento.valor_anterior is not None or evento.valor_nuevo is not None:
                detalle = f"{evento.valor_anterior or '—'} → {evento.valor_nuevo or '—'}"
            if detalle:
                tarjeta.append(Gtk.Label(label=detalle, xalign=0, wrap=True))
            box.append(tarjeta)

    @staticmethod
    def _fecha_comentario(creado: str) -> str:
        try:
            return datetime.fromisoformat(creado).astimezone().strftime(
                "%d/%m/%Y %H:%M"
            )
        except ValueError:
            return creado

    def _refrescar_comentarios(self) -> None:
        while (hijo := self._comentarios_box.get_first_child()) is not None:
            self._comentarios_box.remove(hijo)
        comentarios = self._store.listar_comentarios(self._tarea.id)
        if not comentarios:
            vacio = Gtk.Label(label=_("Sin comentarios"), xalign=0)
            vacio.add_css_class("dim-label")
            self._comentarios_box.append(vacio)
            return
        for comentario in comentarios:
            tarjeta = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            tarjeta.add_css_class("card")
            cabecera = Gtk.Box(spacing=8, margin_top=6, margin_start=8, margin_end=4)
            autor = Gtk.Label(label=comentario.autor or _("Tú"), xalign=0)
            autor.add_css_class("heading")
            cabecera.append(autor)
            fecha = Gtk.Label(label=self._fecha_comentario(comentario.creado), xalign=0, hexpand=True)
            fecha.add_css_class("dim-label")
            fecha.add_css_class("caption")
            cabecera.append(fecha)
            editar = Gtk.Button(icon_name="document-edit-symbolic", tooltip_text=_("Editar comentario"))
            editar.add_css_class("flat")
            editar.add_css_class("circular")
            editar.connect("clicked", self._on_editar_comentario, comentario)
            cabecera.append(editar)
            borrar = Gtk.Button(icon_name="user-trash-symbolic", tooltip_text=_("Eliminar comentario"))
            borrar.add_css_class("flat")
            borrar.add_css_class("circular")
            borrar.connect("clicked", self._on_eliminar_comentario, comentario.id)
            cabecera.append(borrar)
            tarjeta.append(cabecera)
            cuerpo = Gtk.Label(
                xalign=0, wrap=True, selectable=True, use_markup=True,
                margin_start=8, margin_end=8, margin_bottom=8,
            )
            cuerpo.set_markup(markdown_a_pango(comentario.cuerpo))
            tarjeta.append(cuerpo)
            self._comentarios_box.append(tarjeta)

    def _on_comentar(self, _button: Gtk.Button) -> None:
        inicio, fin = self._comentario_buffer.get_bounds()
        texto = self._comentario_buffer.get_text(inicio, fin, False).strip()
        if not texto:
            return
        if self._comentario_editando is not None:
            GitHubSyncManager(self._store).editar_comentario(self._comentario_editando, texto)
            self._salir_de_edicion_comentario()
            return
        comentario = self._store.crear_comentario(self._tarea.id, texto)
        self._comentario_buffer.set_text("")
        self._refrescar_comentarios()

        def _publicar() -> None:
            try:
                if GitHubSyncManager(self._store).push_comentario(comentario.id):
                    GLib.idle_add(self._refrescar_comentarios)
            except Exception as e:  # noqa: BLE001 - se reintenta en el siguiente sync
                log.debug("Error publicando comentario: %s", e)

        threading.Thread(target=_publicar, daemon=True).start()

    def _on_editar_comentario(self, _button: Gtk.Button, comentario) -> None:
        self._comentario_editando = comentario.id
        self._comentario_buffer.set_text(comentario.cuerpo)
        self._comentario_titulo.set_text(_("Editar comentario"))
        self._comentario_enviar.set_label(_("Guardar cambios"))
        self._comentario_cancelar.set_visible(True)

    def _salir_de_edicion_comentario(self) -> None:
        self._comentario_editando = None
        self._comentario_buffer.set_text("")
        self._comentario_titulo.set_text(_("Nuevo comentario"))
        self._comentario_enviar.set_label(_("Comentar"))
        self._comentario_cancelar.set_visible(False)
        self._refrescar_comentarios()

    def _on_eliminar_comentario(self, _button: Gtk.Button, comentario_id: int) -> None:
        dialog = Gtk.AlertDialog()
        dialog.set_message(_("Eliminar comentario"))
        dialog.set_detail(
            _("Si el comentario está en GitHub, también se eliminará allí. No se puede deshacer.")
        )
        dialog.set_buttons([_("Cancelar"), _("Eliminar")])
        dialog.set_cancel_button(0)
        dialog.set_default_button(0)
        dialog.choose(self, None, self._on_eliminar_comentario_respuesta, comentario_id)

    def _on_eliminar_comentario_respuesta(self, dialog: Gtk.AlertDialog, result, comentario_id: int) -> None:
        try:
            eleccion = dialog.choose_finish(result)
        except GLib.Error:
            return
        if eleccion == 1:
            GitHubSyncManager(self._store).eliminar_comentario(comentario_id)
            self._refrescar_comentarios()

    # ------------------------------------------------------------------ interacción

    def _on_buscar_dependencia(self, entrada: Gtk.SearchEntry) -> None:
        texto = entrada.get_text().strip().casefold()
        for _origen_id, check in self._dependencia_checks:
            check.set_visible(not texto or texto in check.get_label().casefold())

    def _on_porcentaje_fin_real(self, escala: Gtk.Scale) -> None:
        self._fin_real.establecer(
            completado.fecha_fin_real_para(round(escala.get_value()), self._fin_real.valor)
        )

    def _on_porcentaje_cambio(self, escala: Gtk.Scale) -> None:
        self._porcentaje_label.set_text(f"{round(escala.get_value())} %")
        boton = getattr(self, "_completar_button", None)
        if boton is not None:
            boton.set_visible(round(escala.get_value()) < 100)

    def _on_completar(self, _button: Gtk.Button) -> None:
        self._porcentaje_scale.set_value(100)
        final = completado.id_columna_final(self._estados)
        for indice, estado in enumerate(self._estados):
            if estado.id == final:
                self._estado_dropdown.set_selected(indice)
                break
        self._on_save(_button)

    @staticmethod
    def _duracion_entre(inicio: str, fin: str) -> int:
        return max((date.fromisoformat(fin) - date.fromisoformat(inicio)).days + 1, 1)

    def _on_inicio_cambio(self) -> None:
        # Conservar la duración: el final se desplaza con el inicio.
        self._recalcular_fin_desde_duracion()

    def _on_fin_cambio(self) -> None:
        if self._actualizando_fechas or not (self._inicio.valor and self._fin.valor):
            return
        if self._fin.valor < self._inicio.valor:
            return  # el error se avisa al guardar
        self._actualizando_fechas = True
        self._duracion_spin.set_value(self._duracion_entre(self._inicio.valor, self._fin.valor))
        self._actualizando_fechas = False

    def _on_duracion_cambio(self, _spin: Gtk.SpinButton) -> None:
        if not self._actualizando_fechas:
            self._recalcular_fin_desde_duracion()

    def _recalcular_fin_desde_duracion(self) -> None:
        if self._actualizando_fechas or not self._inicio.valor:
            return
        dias = int(self._duracion_spin.get_value())
        fin = date.fromisoformat(self._inicio.valor) + timedelta(days=dias - 1)
        self._actualizando_fechas = True
        self._fin.establecer(fin.isoformat())
        self._actualizando_fechas = False

    # ------------------------------------------------------------------ cambios sin guardar

    def _capturar_estado(self) -> tuple:
        return (
            self._titulo_entry.get_text(),
            self._descripcion_editor.obtener_texto(),
            self._padre_dropdown.get_selected(),
            self._estado_dropdown.get_selected(),
            self._prioridad_dropdown.get_selected(),
            tuple(sorted(n.casefold() for n, _c in self._etiquetas)),
            self._inicio.valor,
            self._fin.valor,
            int(self._duracion_spin.get_value()),
            self._limite.valor,
            round(self._porcentaje_scale.get_value()),
            self._hito_dropdown.get_selected(),
            tuple(sorted((r.id, self._dedicaciones.get(r.id, 100)) for r in self._asignados)),
            frozenset(i for i, check in self._dependencia_checks if check.get_active()),
        )

    def _on_close_request(self, _window: Gtk.Window) -> bool:
        if self._cierre_forzado or self._capturar_estado() == self._estado_inicial:
            return False
        dialog = Gtk.AlertDialog()
        dialog.set_message(_("Hay cambios sin guardar"))
        dialog.set_detail(_("Si cierras ahora se perderán los cambios de esta tarea."))
        dialog.set_buttons([_("Seguir editando"), _("Descartar cambios")])
        dialog.set_cancel_button(0)
        dialog.set_default_button(0)
        dialog.choose(self, None, self._on_descartar_respuesta)
        return True

    def _on_descartar_respuesta(self, dialog: Gtk.AlertDialog, result) -> None:
        try:
            eleccion = dialog.choose_finish(result)
        except GLib.Error:
            return
        if eleccion == 1:
            self._cierre_forzado = True
            self.close()

    # ------------------------------------------------------------------ eliminar

    def _on_archivar(self, _button: Gtk.Button) -> None:
        if self._tarea is None:
            return
        self._store.archivar_tarea(self._tarea.id)
        self._on_saved()
        self._cierre_forzado = True
        self.close()

    def _on_eliminar(self, _button: Gtk.Button) -> None:
        if self._tarea is None:
            return
        dialog = Gtk.AlertDialog()
        dialog.set_message(_("Eliminar tarea"))
        dialog.set_detail(
            _(
                "¿Seguro que quieres eliminar «{titulo}»? Sus subtareas y dependencias "
                "también se eliminarán. Esta acción no se puede deshacer."
            ).format(titulo=self._tarea.titulo)
        )
        dialog.set_buttons([_("Cancelar"), _("Eliminar")])
        dialog.set_cancel_button(0)
        dialog.set_default_button(0)
        dialog.choose(self, None, self._on_eliminar_respuesta)

    def _on_eliminar_respuesta(self, dialog: Gtk.AlertDialog, result) -> None:
        try:
            eleccion = dialog.choose_finish(result)
        except GLib.Error:
            return
        if eleccion != 1 or self._tarea is None:
            return
        GitHubSyncManager(self._store).eliminar_tarea(self._tarea.id)
        self._on_saved()
        self._cierre_forzado = True
        self.close()

    # ------------------------------------------------------------------ guardado

    def _dependencias_pendientes_al_completar(self) -> list:
        """Dependencias marcadas que no están al 100 %, si este guardado completa la tarea."""
        final = completado.id_columna_final(self._estados)
        estado_id = self._estados[self._estado_dropdown.get_selected()].id if self._estados else None
        completa_ahora = round(self._porcentaje_scale.get_value()) >= 100 or (
            final is not None and estado_id == final
        )
        ya_completa = self._tarea is not None and self._tarea.porcentaje_completado >= 100
        if not completa_ahora or ya_completa:
            return []
        marcadas = [i for i, check in self._dependencia_checks if check.get_active()]
        return completado.dependencias_sin_terminar(
            marcadas, self._store.listar_tareas(self._proyecto_id)
        )

    def _con_aviso_de_dependencias(self, continuar: Callable[[], None]) -> None:
        pendientes = self._dependencias_pendientes_al_completar()
        if pendientes:
            confirmar_completar(self, pendientes, continuar)
        else:
            continuar()

    def _on_save(self, _button: Gtk.Button) -> None:
        self._con_aviso_de_dependencias(self._guardar_y_cerrar)

    def _guardar_y_cerrar(self) -> None:
        if self._guardar():
            self._on_saved()
            self._cierre_forzado = True
            self.close()

    def _on_guardar_y_crear_otra(self, _button: Gtk.Button) -> None:
        self._con_aviso_de_dependencias(self._guardar_y_crear_otra)

    def _guardar_y_crear_otra(self) -> None:
        if not self._guardar():
            return
        self._on_saved()
        self._cierre_forzado = True
        self.close()
        TaskDialog(self._parent, self._store, self._proyecto_id, self._on_saved).present()

    def _guardar(self) -> bool:
        self._limpiar_errores()
        titulo = self._titulo_entry.get_text().strip()
        if not titulo:
            self._mostrar_error(
                _("El título no puede estar vacío."), self._titulo_entry, self._pagina_general
            )
            return False

        fecha = self._inicio.valor
        fecha_limite = self._limite.valor
        fecha_fin = self._fin.valor or fecha
        hito_indice = self._hito_dropdown.get_selected()
        hito_id = self._hitos[hito_indice - 1].id if hito_indice > 0 else None
        if fecha_fin and not fecha:
            self._mostrar_error(
                _("El final planificado necesita una fecha de inicio."),
                self._inicio.widget,
                self._pagina_fechas,
            )
            return False
        if fecha and fecha_fin and fecha_fin < fecha:
            self._mostrar_error(
                _("El final planificado no puede ser anterior al inicio."),
                self._fin.widget,
                self._pagina_fechas,
            )
            return False
        if fecha_fin and fecha_limite and fecha_limite < fecha_fin:
            self._mostrar_error(
                _("La fecha límite no puede ser anterior al final planificado."),
                self._limite.widget,
                self._pagina_fechas,
            )
            return False

        padre_indice = self._padre_dropdown.get_selected()
        padre_id = self._candidatas_padre[padre_indice - 1].id if padre_indice > 0 else None
        estado_id = (
            self._estados[self._estado_dropdown.get_selected()].id if self._estados else None
        )
        descripcion = self._descripcion_editor.obtener_texto().strip()
        if fecha and fecha_fin:
            duracion = self._duracion_entre(fecha, fecha_fin)
        else:
            duracion = int(self._duracion_spin.get_value())
        porcentaje = round(self._porcentaje_scale.get_value())
        fecha_fin_inicial = self._fin_inicial.valor or fecha_fin
        fecha_fin_real = completado.fecha_fin_real_para(porcentaje, self._fin_real.valor)
        if (
            self._tarea is None
            and estado_id is not None
            and estado_id == completado.id_columna_final(self._estados)
        ):
            porcentaje = 100  # una tarea nueva en la columna de completadas ya está completa

        if self._tarea is None:
            tarea = self._store.crear_tarea(
                self._proyecto_id,
                titulo,
                padre_id=padre_id,
                estado_id=estado_id,
                prioridad=self._prioridad_dropdown.get_selected(),
                descripcion=descripcion,
                fecha_inicio=fecha or None,
                fecha_fin_planificada=fecha_fin,
                fecha_fin_planificada_inicial=fecha_fin_inicial,
                fecha_limite=fecha_limite,
                fecha_fin_real=fecha_fin_real,
                duracion_dias=duracion,
                porcentaje_completado=porcentaje,
                hito_id=hito_id,
            )
        else:
            tarea = self._tarea
            estado_anterior_id = tarea.estado_id
            tarea.titulo = titulo
            tarea.padre_id = padre_id
            tarea.porcentaje_completado = porcentaje
            completado.al_cambiar_de_columna(tarea, estado_id, self._estados)
            porcentaje = tarea.porcentaje_completado
            tarea.estado_id = estado_id
            tarea.prioridad = self._prioridad_dropdown.get_selected()
            tarea.descripcion = descripcion
            tarea.fecha_inicio = fecha or None
            if tarea.fecha_fin_planificada_inicial is None or self._editar_planificacion_base.get_active():
                tarea.fecha_fin_planificada_inicial = fecha_fin_inicial
            tarea.fecha_fin_planificada = fecha_fin
            tarea.fecha_limite = fecha_limite
            tarea.fecha_fin_real = fecha_fin_real
            tarea.duracion_dias = duracion
            tarea.porcentaje_completado = porcentaje
            tarea.hito_id = hito_id
            self._store.actualizar_tarea(tarea)
            if estado_anterior_id is not None and estado_anterior_id != estado_id:
                self._store.purgar_estado_temporal_si_vacio(estado_anterior_id)

        if not self._sincronizar_dependencias(tarea.id):
            return False
        self._sincronizar_asignaciones(tarea.id)
        self._store.establecer_etiquetas_de_tarea(
            tarea.id,
            [self._store.asegurar_etiqueta(self._proyecto_id, n, c).id for n, c in self._etiquetas],
        )

        # Si el proyecto está vinculado con GitHub, enviar cambios en segundo plano
        proyecto = self._store.obtener_proyecto(self._proyecto_id)
        if proyecto and (proyecto.github_repo_name or proyecto.github_project_v2_id):
            def _push() -> None:
                try:
                    GitHubSyncManager(self._store).push_tarea(tarea.id)
                except Exception as e:  # noqa: BLE001 - la sincronización no debe bloquear el guardado
                    log.debug("Error enviando tarea a GitHub: %s", e)

            threading.Thread(target=_push, daemon=True).start()
        return True

    # ------------------------------------------------------------------ asignaciones

    def _sugerencias_etiquetas(self, texto: str) -> list[str]:
        puestas = {n.casefold() for n, _c in self._etiquetas}
        return [
            e.nombre
            for e in self._store.listar_etiquetas(self._proyecto_id)
            if e.nombre.casefold() not in puestas and (not texto or texto in e.nombre.casefold())
        ]

    def _on_etiqueta_escrita(self, _entry: Gtk.Entry) -> None:
        self._anadir_etiqueta(self._etiqueta_entry.get_text())

    def _anadir_etiqueta(self, nombre: str) -> None:
        nombre = nombre.strip()
        self._etiqueta_entry.set_text("")
        if not nombre or any(n.casefold() == nombre.casefold() for n, _c in self._etiquetas):
            return
        color = self._colores_etiquetas.get(nombre.casefold()) or color_automatico(nombre)
        # Las etiquetas existentes conservan su nombre tal cual está en el proyecto.
        existente = next(
            (e for e in self._store.listar_etiquetas(self._proyecto_id)
             if e.nombre.casefold() == nombre.casefold()),
            None,
        )
        self._etiquetas.append((existente.nombre if existente else nombre, color))
        self._refrescar_etiquetas()

    def _quitar_etiqueta(self, _boton: Gtk.Button, nombre: str) -> None:
        self._etiquetas = [(n, c) for n, c in self._etiquetas if n != nombre]
        self._refrescar_etiquetas()

    def _refrescar_etiquetas(self) -> None:
        vaciar_envoltura(self._etiquetas_box)
        if not self._etiquetas:
            vacio = Gtk.Label(label=_("Sin etiquetas"), xalign=0)
            vacio.add_css_class("dim-label")
            vacio.add_css_class("caption")
            self._etiquetas_box.append(vacio)
            return
        for nombre, color in self._etiquetas:
            chip = Gtk.Box(spacing=2)
            texto = GLib.markup_escape_text(nombre)
            etiqueta = Gtk.Label(use_markup=True, margin_start=2)
            etiqueta.set_markup(
                f'<span background="#{color}" foreground="#{color_de_texto(color)}"> {texto} </span>'
            )
            chip.append(etiqueta)
            quitar = Gtk.Button(icon_name="window-close-symbolic", tooltip_text=_("Quitar etiqueta"))
            quitar.add_css_class("flat")
            quitar.add_css_class("circular")
            quitar.connect("clicked", self._quitar_etiqueta, nombre)
            chip.append(quitar)
            self._etiquetas_box.append(chip)

    def _sugerencias_recursos(self, texto: str) -> list[str]:
        asignados = {r.id for r in self._asignados}
        return [
            r.nombre
            for r in self._store.listar_recursos(self._proyecto_id)
            if r.id not in asignados and (not texto or texto in r.nombre.casefold())
        ]

    def _on_recurso_sugerido(self, nombre: str) -> None:
        self._asignar_entry.set_text(nombre)
        self._on_asignar(self._asignar_entry)

    def _refrescar_asignados(self) -> None:
        while (hijo := self._asignados_box.get_first_child()) is not None:
            self._asignados_box.remove(hijo)
        if not self._asignados:
            vacio = Gtk.Label(label=_("Nadie asignado"), xalign=0)
            vacio.add_css_class("dim-label")
            vacio.add_css_class("caption")
            self._asignados_box.append(vacio)
            return
        for recurso in self._asignados:
            tarjeta = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            fila = Gtk.Box(spacing=8, valign=Gtk.Align.CENTER)
            fila.append(AvatarWidget(recurso, size=28))
            fila.append(Gtk.Label(label=recurso.nombre, xalign=0, hexpand=True))
            quitar = Gtk.Button(
                icon_name="list-remove-symbolic", tooltip_text=_("Quitar asignación")
            )
            quitar.add_css_class("flat")
            quitar.connect("clicked", self._on_quitar_asignado, recurso.id)
            fila.append(quitar)
            tarjeta.append(fila)

            ajuste = Gtk.Box(spacing=8, margin_start=36)
            dedicacion = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 5)
            dedicacion.set_value(self._dedicaciones.get(recurso.id, 100))
            dedicacion.set_digits(0)
            dedicacion.set_hexpand(True)
            dedicacion.set_tooltip_text(_("Porcentaje de dedicación"))
            dedicacion.connect("value-changed", self._on_dedicacion_changed, recurso.id)
            ajuste.append(dedicacion)
            porcentaje = Gtk.Label(label=f"{self._dedicaciones.get(recurso.id, 100)} %")
            porcentaje.set_width_chars(5)
            dedicacion.connect("value-changed", self._actualizar_etiqueta_dedicacion, porcentaje)
            ajuste.append(porcentaje)
            tarjeta.append(ajuste)

            rapidos = Gtk.Box(spacing=6, margin_start=36)
            for valor in _PORCENTAJES_RAPIDOS:
                boton = Gtk.Button(label=f"{valor} %")
                boton.connect("clicked", lambda _b, v=valor, e=dedicacion: e.set_value(v))
                rapidos.append(boton)
            tarjeta.append(rapidos)
            tarjeta.append(Gtk.Separator(margin_top=4, margin_bottom=4))
            self._asignados_box.append(tarjeta)

    def _on_asignar(self, _widget: Gtk.Widget) -> None:
        nombre = self._asignar_entry.get_text().strip()
        if not nombre:
            return
        if any(r.nombre.casefold() == nombre.casefold() for r in self._asignados):
            self._asignar_entry.set_text("")
            return
        recurso = self._store.asegurar_recurso(self._proyecto_id, nombre)
        self._asignados.append(recurso)
        self._dedicaciones[recurso.id] = 100
        self._asignar_entry.set_text("")
        self._refrescar_asignados()

    def _on_quitar_asignado(self, _button: Gtk.Button, recurso_id: int) -> None:
        self._asignados = [r for r in self._asignados if r.id != recurso_id]
        self._dedicaciones.pop(recurso_id, None)
        self._refrescar_asignados()

    def _on_dedicacion_changed(self, escala: Gtk.Scale, recurso_id: int) -> None:
        self._dedicaciones[recurso_id] = round(escala.get_value())

    def _actualizar_etiqueta_dedicacion(
        self, escala: Gtk.Scale, etiqueta: Gtk.Label
    ) -> None:
        etiqueta.set_text(f"{round(escala.get_value())} %")

    def _sincronizar_asignaciones(self, tarea_id: int) -> None:
        actuales = {a.recurso_id: a.id for a in self._store.listar_asignaciones(tarea_id)}
        deseados = {r.id for r in self._asignados}
        for recurso_id in deseados - actuales.keys():
            self._store.asignar_recurso(tarea_id, recurso_id, self._dedicaciones.get(recurso_id, 100))
        for recurso_id in deseados & actuales.keys():
            self._store.actualizar_dedicacion(tarea_id, recurso_id, self._dedicaciones.get(recurso_id, 100))
        for recurso_id in actuales.keys() - deseados:
            self._store.quitar_asignacion(actuales[recurso_id])

    def _sincronizar_dependencias(self, tarea_id: int) -> bool:
        existentes = {
            d.tarea_origen_id: d.id
            for d in self._store.listar_dependencias(self._proyecto_id)
            if d.tarea_destino_id == tarea_id
        }
        deseadas = {
            origen_id for origen_id, check in self._dependencia_checks if check.get_active()
        }
        for origen_id in deseadas - existentes.keys():
            try:
                self._store.crear_dependencia(origen_id, tarea_id)
            except CicloDependenciaError:
                self._mostrar_error(
                    _("Esa dependencia crearía un ciclo entre tareas."),
                    None,
                    self._pagina_dependencias,
                )
                return False
        for origen_id in existentes.keys() - deseadas:
            self._store.eliminar_dependencia(existentes[origen_id])
        return True

    # ------------------------------------------------------------------ errores

    def _limpiar_errores(self) -> None:
        for widget in self._marcados_error:
            widget.remove_css_class("error")
        self._marcados_error.clear()
        self._error_label.set_visible(False)

    def _mostrar_error(
        self, mensaje: str, campo: Gtk.Widget | None = None, pagina: Gtk.Widget | None = None
    ) -> None:
        """Muestra el mensaje, marca en rojo el campo que falla y lleva a su pestaña."""
        self._error_label.set_text(mensaje)
        self._error_label.set_visible(True)
        if campo is not None:
            campo.add_css_class("error")
            self._marcados_error.append(campo)
            campo.grab_focus()
        if pagina is not None:
            self._notebook.set_current_page(self._notebook.page_num(pagina.get_ancestor(Gtk.ScrolledWindow)))
