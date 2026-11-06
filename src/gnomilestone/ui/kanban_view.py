from __future__ import annotations

from collections.abc import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, GObject, Gtk

from gnomilestone.i18n import _, formatear_fecha_local
from gnomilestone.models import Tarea
from gnomilestone.store import Store
from gnomilestone.ui.avatar_widget import fila_avatares

_TIPO_ARRASTRE_TAREA = GObject.TYPE_INT  # lleva el id de la tarea arrastrada

# Para distinguir las columnas de un vistazo (sin depender de que el usuario les asigne
# un color propio todavía): una franja de color arriba de cada una, ciclando esta paleta.
_PALETA_COLUMNAS = (
    "#3584e4",  # azul
    "#33d17a",  # verde
    "#f6d32d",  # amarillo
    "#ff7800",  # naranja
    "#e01b24",  # rojo
    "#9141ac",  # morado
    "#63452c",  # marrón
    "#26a269",  # verde oscuro
)
_CLASE_COLUMNA_PREFIJO = "gnomilestone-columna-"
_css_columnas_aplicado = False


def _asegurar_css_columnas() -> None:
    global _css_columnas_aplicado
    if _css_columnas_aplicado:
        return
    reglas_color = "\n".join(
        f".{_CLASE_COLUMNA_PREFIJO}{indice} {{ border-top: 3px solid {color}; }}\n"
        # Mismo color arriba de cada tarjeta: hoy hereda el de su columna; cuando haya
        # etiquetas de GitHub, esta franja pasará a reflejar el color de la etiqueta.
        f".card.gnomilestone-tarjeta.{_CLASE_COLUMNA_PREFIJO}{indice} "
        f"{{ border-top: 3px solid {color}; }}"
        for indice, color in enumerate(_PALETA_COLUMNAS)
    )
    # Columna: canaleta oscura plana + franja de color arriba (tableros distinguibles).
    # Tarjeta: mismo lenguaje que la columna, solo que un tono más clara que ella (sin
    # contorno ni sombra propios: se distingue por tonalidad, no por un marco), con la
    # misma franja de color arriba a juego con su columna.
    reglas = (
        ".gnomilestone-columna-fondo { "
        "background-color: alpha(black, 0.18); border-radius: 12px; }\n"
        # El viewport del ScrolledWindow pinta fondo opaco encima de la columna.
        ".gnomilestone-columna-fondo scrolledwindow, "
        ".gnomilestone-columna-fondo viewport { "
        "background-color: transparent; background-image: none; }\n"
        ".card.gnomilestone-tarjeta { "
        "padding: 8px 10px; "
        "background-color: alpha(@view_fg_color, 0.20); "
        "background-image: none; "
        "border: none; "
        "border-radius: 10px; "
        "box-shadow: none; }\n"
        ".card.gnomilestone-tarjeta:hover { "
        "background-color: alpha(@view_fg_color, 0.28); "
        "background-image: none; }\n"
        f"{reglas_color}"
    )
    proveedor = Gtk.CssProvider()
    proveedor.load_from_string(reglas)
    # USER (> THEME) para que transparent en scrolledwindow/viewport gane al fondo del tema.
    Gtk.StyleContext.add_provider_for_display(
        Gdk.Display.get_default(), proveedor, Gtk.STYLE_PROVIDER_PRIORITY_USER
    )
    _css_columnas_aplicado = True


class KanbanView(Gtk.Box):
    """Tablero: una columna por cada `estado_tablero` del proyecto (distinguidas por color),
    con tarjetas arrastrables entre columnas (actualiza `tarea.estado_id` al soltar)."""

    def __init__(
        self,
        store: Store,
        on_editar_tarea: Callable[[Tarea], None] | None = None,
        on_eliminar_tarea: Callable[[Tarea], None] | None = None,
        on_cambio: Callable[[], None] | None = None,
        on_abrir_ajustes: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        _asegurar_css_columnas()
        self._store = store
        self._proyecto_id: int | None = None
        self._on_editar_tarea = on_editar_tarea
        self._on_eliminar_tarea = on_eliminar_tarea
        # Arrastrar una tarjeta cambia tarea.estado_id directamente en el store (este
        # widget ya tiene acceso a él): on_cambio avisa al contenedor para que la Tabla y
        # el Gantt, que no se enteran solos, también se refresquen.
        self._on_cambio = on_cambio

        if on_abrir_ajustes is not None:
            cabecera = Gtk.Box(margin_top=6, margin_bottom=6, margin_start=6, margin_end=6)
            cabecera.append(Gtk.Label(hexpand=True))  # empuja el engranaje a la derecha
            ajustes_button = Gtk.Button(
                icon_name="emblem-system-symbolic", tooltip_text=_("Columnas del tablero")
            )
            ajustes_button.connect("clicked", lambda _b: on_abrir_ajustes())
            cabecera.append(ajustes_button)
            self.append(cabecera)

        self._columnas_box = Gtk.Box(
            spacing=12, margin_top=6, margin_bottom=12, margin_start=12, margin_end=12
        )
        scroller = Gtk.ScrolledWindow(hexpand=True, vexpand=True)
        scroller.set_child(self._columnas_box)
        self.append(scroller)

    def mostrar_proyecto(self, proyecto_id: int) -> None:
        self._proyecto_id = proyecto_id
        self.refrescar()

    def refrescar(self) -> None:
        hijo = self._columnas_box.get_first_child()
        while hijo is not None:
            siguiente = hijo.get_next_sibling()
            self._columnas_box.remove(hijo)
            hijo = siguiente
        if self._proyecto_id is None:
            return

        estados = self._store.listar_estados(self._proyecto_id)
        tareas_por_estado: dict[int | None, list[Tarea]] = {}
        for tarea in self._store.listar_tareas(self._proyecto_id):
            tareas_por_estado.setdefault(tarea.estado_id, []).append(tarea)

        for indice, estado in enumerate(estados):
            tareas = sorted(tareas_por_estado.get(estado.id, []), key=lambda t: t.orden)
            self._columnas_box.append(
                self._construir_columna(estado.id, estado.nombre, tareas, indice)
            )

    def _construir_columna(
        self, estado_id: int, nombre: str, tareas: list[Tarea], indice: int
    ) -> Gtk.Widget:
        columna = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL, spacing=6, width_request=220, vexpand=True
        )
        columna.add_css_class("gnomilestone-columna-fondo")
        columna.add_css_class(f"{_CLASE_COLUMNA_PREFIJO}{indice % len(_PALETA_COLUMNAS)}")

        cabecera = Gtk.Box(margin_top=8, margin_bottom=4, margin_start=10, margin_end=10)
        titulo = Gtk.Label(label=nombre, xalign=0, hexpand=True)
        titulo.add_css_class("heading")
        cabecera.append(titulo)
        contador = Gtk.Label(label=str(len(tareas)))
        contador.add_css_class("dim-label")
        cabecera.append(contador)
        columna.append(cabecera)

        lista = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=6,
            margin_start=8,
            margin_end=8,
            margin_bottom=8,
            vexpand=True,
        )
        for tarea in tareas:
            lista.append(self._construir_tarjeta(tarea, indice))
        scroller = Gtk.ScrolledWindow(vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
        scroller.set_child(lista)
        columna.append(scroller)

        objetivo = Gtk.DropTarget.new(_TIPO_ARRASTRE_TAREA, Gdk.DragAction.MOVE)
        objetivo.connect("drop", self._on_drop, estado_id)
        columna.add_controller(objetivo)
        return columna

    def _construir_tarjeta(self, tarea: Tarea, indice_columna: int) -> Gtk.Widget:
        tarjeta = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=4,
            margin_top=4,
            margin_bottom=6,
            margin_start=4,
            margin_end=4,
        )
        tarjeta.add_css_class("card")
        tarjeta.add_css_class("activatable")
        tarjeta.add_css_class("gnomilestone-tarjeta")
        tarjeta.add_css_class(f"{_CLASE_COLUMNA_PREFIJO}{indice_columna % len(_PALETA_COLUMNAS)}")

        fila_titulo = Gtk.Box(spacing=4)
        etiqueta = Gtk.Label(label=tarea.titulo, xalign=0, wrap=True, hexpand=True)
        fila_titulo.append(etiqueta)
        if self._on_eliminar_tarea is not None:
            borrar = Gtk.Button(
                icon_name="user-trash-symbolic",
                tooltip_text=_("Eliminar tarea"),
                has_frame=False,
            )
            borrar.connect("clicked", lambda _b, t=tarea: self._on_eliminar_tarea(t))
            fila_titulo.append(borrar)
        tarjeta.append(fila_titulo)

        if tarea.fecha_inicio:
            info = Gtk.Label(
                label=(
                    f"{formatear_fecha_local(tarea.fecha_inicio)} · "
                    f"{tarea.duracion_dias}d · {tarea.porcentaje_completado}%"
                ),
                xalign=0,
            )
            info.add_css_class("caption")
            info.add_css_class("dim-label")
            tarjeta.append(info)

        recursos = self._store.listar_recursos_de_tarea(tarea.id)
        if recursos:
            tarjeta.append(fila_avatares(recursos, size=22, maximo=4))

        if self._on_editar_tarea is not None:
            doble_clic = Gtk.GestureClick(button=1)
            doble_clic.connect("released", self._on_tarjeta_pulsada, tarea)
            tarjeta.add_controller(doble_clic)

        origen = Gtk.DragSource(actions=Gdk.DragAction.MOVE)
        origen.connect("prepare", self._on_preparar_arrastre, tarea.id)
        tarjeta.add_controller(origen)

        return tarjeta

    def _on_tarjeta_pulsada(
        self, gesture: Gtk.GestureClick, n_press: int, _x: float, _y: float, tarea: Tarea
    ) -> None:
        if n_press == 2 and self._on_editar_tarea is not None:
            self._on_editar_tarea(tarea)

    def _on_preparar_arrastre(
        self, _origen: Gtk.DragSource, _x: float, _y: float, tarea_id: int
    ) -> Gdk.ContentProvider:
        valor = GObject.Value(_TIPO_ARRASTRE_TAREA, tarea_id)
        return Gdk.ContentProvider.new_for_value(valor)

    def _on_drop(self, _objetivo: Gtk.DropTarget, tarea_id: int, _x: float, _y: float, estado_id: int) -> bool:
        tarea = self._store.obtener_tarea(tarea_id)
        if tarea is None or tarea.estado_id == estado_id:
            return False
        tarea.estado_id = estado_id
        self._store.actualizar_tarea(tarea)
        if self._on_cambio is not None:
            self._on_cambio()  # refresca también Tabla/Gantt, y de paso este tablero
        else:
            self.refrescar()
        return True
