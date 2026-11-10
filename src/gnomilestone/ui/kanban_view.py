from __future__ import annotations

import logging
import threading
from collections.abc import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, GLib, GObject, Gtk, Pango

from gnomilestone import completado
from gnomilestone.etiquetas import color_de_texto
from gnomilestone.filtros import ocultar_completadas
from gnomilestone.ganttcalc import VENCIDA
from gnomilestone.i18n import _, formatear_fecha_local
from gnomilestone.models import Tarea
from gnomilestone.ordenacion import mover_tarea
from gnomilestone.store import Store
from gnomilestone.ui.avatar_widget import fila_avatares
from gnomilestone.ui.aviso_dependencias import confirmar_completar
from gnomilestone.ui.prioridad_icono import crear_icono_prioridad
from gnomilestone.ui.vencimiento import (
    aplicar_estilo_vencimiento,
    asegurar_css_vencimientos,
    texto_vencimiento,
)

log = logging.getLogger(__name__)

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


def colores_de_estados(estados: list) -> dict[int, str]:
    """Color de cada columna del tablero (por su posición), el mismo del Tablero, del selector
    de columna del diálogo y de la columna «Columna» de las listas."""
    return {e.id: _PALETA_COLUMNAS[i % len(_PALETA_COLUMNAS)] for i, e in enumerate(estados)}



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
        f"{{ border-top: 3px solid {color}; background-color: alpha({color}, 0.16); }}\n"
        f".card.gnomilestone-tarjeta.{_CLASE_COLUMNA_PREFIJO}{indice}:hover "
        f"{{ background-color: alpha({color}, 0.26); }}"
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
        # Línea que marca dónde caerá la tarjeta arrastrada.
        ".gnomilestone-indicador-drop { "
        "min-height: 4px; border-radius: 2px; background-color: @accent_color; }\n"
        # Sin el resalte «de selección» que GTK pone a todo destino de arrastre activo.
        ".gnomilestone-columna-fondo:drop(active), "
        ".card.gnomilestone-tarjeta:drop(active) { "
        "outline: none; box-shadow: none; }\n"
        # Chip con la tarea padre, encima del título de la subtarea.
        ".gnomilestone-padre { "
        "background-color: alpha(@accent_color, 0.25); color: @accent_color; "
        "border-radius: 6px; padding: 1px 6px; font-weight: bold; }\n"
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
        on_archivar_tarea: Callable[[Tarea], None] | None = None,
    ) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        _asegurar_css_columnas()
        asegurar_css_vencimientos()
        self._store = store
        self._proyecto_id: int | None = None
        self._mostrar_completadas = True
        self._on_editar_tarea = on_editar_tarea
        self._on_eliminar_tarea = on_eliminar_tarea
        self._on_archivar_tarea = on_archivar_tarea
        # Arrastrar una tarjeta cambia tarea.estado_id directamente en el store (este
        # widget ya tiene acceso a él): on_cambio avisa al contenedor para que la Tabla y
        # el Gantt, que no se enteran solos, también se refresquen.
        self._on_cambio = on_cambio
        self._tareas_por_id: dict[int, Tarea] = {}
        self._hijas_de: dict[int, list[Tarea]] = {}
        self._indicador: Gtk.Box | None = None  # línea de destino del arrastre
        self._movimiento_en_tarjeta = False  # la tarjeta ya gestionó este movimiento
        self._n_movimientos = 0

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

    def mostrar_proyecto(self, proyecto_id: int, mostrar_completadas: bool = True) -> None:
        self._proyecto_id = proyecto_id
        self._mostrar_completadas = mostrar_completadas
        self.refrescar()

    def refrescar(self) -> None:
        self._indicador = None  # sus widgets se destruyen con las columnas
        hijo = self._columnas_box.get_first_child()
        while hijo is not None:
            siguiente = hijo.get_next_sibling()
            self._columnas_box.remove(hijo)
            hijo = siguiente
        if self._proyecto_id is None:
            return

        estados = self._store.listar_estados(self._proyecto_id)
        tareas = self._store.listar_tareas(self._proyecto_id)
        # Relación padre-hijo sobre todas las tareas (aunque se oculten las completadas).
        self._tareas_por_id = {t.id: t for t in tareas}
        self._hijas_de = {}
        for t in tareas:
            if t.padre_id in self._tareas_por_id:
                self._hijas_de.setdefault(t.padre_id, []).append(t)
        if not self._mostrar_completadas:
            tareas = ocultar_completadas(tareas)
        tareas_por_estado: dict[int | None, list[Tarea]] = {}
        for tarea in tareas:
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
        objetivo.connect("motion", self._on_movimiento_sobre_columna, lista)
        objetivo.connect("leave", lambda _o: self._al_salir_de_columna())
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

        recursos = self._store.listar_recursos_de_tarea(tarea.id)

        fila_titulo = Gtk.Box(spacing=4)
        icono_prioridad = crear_icono_prioridad(tarea.prioridad)
        if icono_prioridad is not None:
            icono_prioridad.set_valign(Gtk.Align.START)
            icono_prioridad.set_margin_top(2)
            fila_titulo.append(icono_prioridad)
        etiqueta = Gtk.Label(label=tarea.titulo, xalign=0, wrap=True, hexpand=True)
        estado = aplicar_estilo_vencimiento(etiqueta, tarea)
        aviso = texto_vencimiento(estado)
        if aviso:
            etiqueta.set_tooltip_text(aviso)
        fila_titulo.append(etiqueta)
        if recursos:
            fila_titulo.append(fila_avatares(recursos, size=22, maximo=3))
        if self._on_archivar_tarea is not None:
            archivar = Gtk.Button(
                icon_name="archivar-symbolic",
                tooltip_text=_("Archivar tarea"),
                has_frame=False,
            )
            archivar.connect("clicked", lambda _b, t=tarea: self._on_archivar_tarea(t))
            fila_titulo.append(archivar)
        if self._on_eliminar_tarea is not None:
            borrar = Gtk.Button(
                icon_name="user-trash-symbolic",
                tooltip_text=_("Eliminar tarea"),
                has_frame=False,
            )
            borrar.connect("clicked", lambda _b, t=tarea: self._on_eliminar_tarea(t))
            fila_titulo.append(borrar)
        tarjeta.append(fila_titulo)

        padre = self._tareas_por_id.get(tarea.padre_id) if tarea.padre_id else None
        if padre is not None:
            fila_padre = Gtk.Box(spacing=4, halign=Gtk.Align.START)
            fila_padre.add_css_class("gnomilestone-padre")
            fila_padre.add_css_class("caption")
            fila_padre.append(Gtk.Image.new_from_icon_name("go-up-symbolic"))
            fila_padre.append(
                Gtk.Label(
                    label=padre.titulo, xalign=0, ellipsize=Pango.EllipsizeMode.END,
                    max_width_chars=28,
                )
            )
            fila_padre.set_tooltip_text(_("Subtarea de: {titulo}").format(titulo=padre.titulo))
            tarjeta.prepend(fila_padre)
        hijas = self._hijas_de.get(tarea.id, [])
        if hijas:
            hechas = sum(1 for h in hijas if h.porcentaje_completado >= 100)
            resumen = Gtk.Label(
                label=_("Subtareas: {hechas}/{total}").format(hechas=hechas, total=len(hijas)),
                xalign=0,
            )
            resumen.add_css_class("caption")
            resumen.add_css_class("dim-label")
            tarjeta.append(resumen)
            tarjeta.append(Gtk.ProgressBar(fraction=hechas / len(hijas)))

        if tarea.fecha_inicio:
            info = Gtk.Label(
                label=(
                    f"{formatear_fecha_local(tarea.fecha_inicio)} · "
                    f"{tarea.duracion_dias}d · {tarea.porcentaje_completado}%"
                    + (_(" · vencida") if estado == VENCIDA else "")
                ),
                xalign=0,
            )
            info.add_css_class("caption")
            info.add_css_class("error" if estado == VENCIDA else "dim-label")
            tarjeta.append(info)

        etiquetas = self._store.listar_etiquetas_de_tarea(tarea.id)
        if etiquetas:
            fila_marcas = Gtk.FlowBox(
                selection_mode=Gtk.SelectionMode.NONE,
                column_spacing=4,
                row_spacing=2,
                max_children_per_line=6,
            )
            for e in etiquetas:
                chip = Gtk.Label(use_markup=True)
                chip.set_markup(
                    f'<span size="small" background="#{e.color}" '
                    f'foreground="#{color_de_texto(e.color)}"> '
                    f"{GLib.markup_escape_text(e.nombre)} </span>"
                )
                fila_marcas.append(chip)
            tarjeta.append(fila_marcas)

        if self._on_editar_tarea is not None:
            doble_clic = Gtk.GestureClick(button=1)
            doble_clic.connect("released", self._on_tarjeta_pulsada, tarea)
            tarjeta.add_controller(doble_clic)

        origen = Gtk.DragSource(actions=Gdk.DragAction.MOVE)
        origen.connect("prepare", self._on_preparar_arrastre, tarea.id)
        origen.connect("drag-begin", self._on_arrastre_iniciado, tarjeta)
        origen.connect("drag-end", lambda *_a: self._quitar_indicador())
        tarjeta.add_controller(origen)

        # Soltar sobre una tarjeta la coloca antes o después de ella (mitad superior/inferior).
        objetivo = Gtk.DropTarget.new(_TIPO_ARRASTRE_TAREA, Gdk.DragAction.MOVE)
        objetivo.connect("motion", self._on_movimiento_sobre_tarjeta, tarjeta)
        objetivo.connect("drop", self._on_drop_sobre_tarjeta, tarjeta, tarea)
        tarjeta.add_controller(objetivo)

        return tarjeta

    def _al_salir_de_columna(self) -> None:
        # GTK avisa de «salida» también al pasar de la columna a una de sus tarjetas (que
        # tienen su propio destino): solo se borra la línea si no sigue el movimiento.
        n = self._n_movimientos

        def _borrar() -> bool:
            if self._n_movimientos == n:
                self._quitar_indicador()
            return GLib.SOURCE_REMOVE

        GLib.timeout_add(150, _borrar)

    def _quitar_indicador(self) -> None:
        if self._indicador is not None and self._indicador.get_parent() is not None:
            self._indicador.get_parent().remove(self._indicador)

    def _poner_indicador(self, lista: Gtk.Box, despues_de: Gtk.Widget | None) -> None:
        """Coloca la línea de destino en `lista`, tras `despues_de` (None = al principio)."""
        if self._indicador is None:
            self._indicador = Gtk.Box()
            self._indicador.add_css_class("gnomilestone-indicador-drop")
        self._quitar_indicador()
        lista.insert_child_after(self._indicador, despues_de)

    @staticmethod
    def _es_mitad_inferior(tarjeta: Gtk.Widget, y: float) -> bool:
        return y > tarjeta.get_height() / 2

    def _on_movimiento_sobre_tarjeta(
        self, _objetivo: Gtk.DropTarget, _x: float, y: float, tarjeta: Gtk.Widget
    ) -> Gdk.DragAction:
        self._n_movimientos += 1
        self._movimiento_en_tarjeta = True  # la columna, que también lo recibe, no debe repetirlo
        lista = tarjeta.get_parent()
        if lista is None:
            return Gdk.DragAction.MOVE
        despues = self._es_mitad_inferior(tarjeta, y)
        vecina = tarjeta.get_next_sibling() if despues else tarjeta.get_prev_sibling()
        if vecina is not None and vecina is self._indicador:
            return Gdk.DragAction.MOVE  # ya está en su sitio: evita recolocarla en cada movimiento
        if despues:
            self._poner_indicador(lista, tarjeta)
        else:
            self._quitar_indicador()  # al quitarla cambian las hermanas: se pregunta después
            self._poner_indicador(lista, tarjeta.get_prev_sibling())
        return Gdk.DragAction.MOVE

    def _on_movimiento_sobre_columna(
        self, _objetivo: Gtk.DropTarget, _x: float, _y: float, lista: Gtk.Box
    ) -> Gdk.DragAction:
        self._n_movimientos += 1
        if self._movimiento_en_tarjeta:
            self._movimiento_en_tarjeta = False
            return Gdk.DragAction.MOVE
        # Hueco libre de la columna (o columna vacía): la tarjeta irá al final.
        ultima = lista.get_last_child()
        if ultima is not None and ultima is self._indicador:
            return Gdk.DragAction.MOVE
        self._poner_indicador(lista, ultima)
        return Gdk.DragAction.MOVE

    def _on_drop_sobre_tarjeta(
        self, _objetivo: Gtk.DropTarget, tarea_id: int, _x: float, y: float,
        tarjeta: Gtk.Widget, destino: Tarea,
    ) -> bool:
        despues = self._es_mitad_inferior(tarjeta, y)
        self._quitar_indicador()
        return self._soltar(tarea_id, destino.estado_id, destino.id, despues)

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


    @staticmethod
    def _on_arrastre_iniciado(origen: Gtk.DragSource, _drag: Gdk.Drag, tarjeta: Gtk.Widget) -> None:
        # El icono del arrastre es la propia tarjeta (no el icono genérico de documento).
        # El puntero queda centrado horizontalmente y cerca del borde superior de la tarjeta.
        icono = Gtk.WidgetPaintable.new(tarjeta)
        origen.set_icon(icono, int(tarjeta.get_width() / 2), 12)

    def _on_drop(self, _objetivo: Gtk.DropTarget, tarea_id: int, _x: float, _y: float, estado_id: int) -> bool:
        # Soltar en el hueco de la columna: la tarjeta pasa al final de ella.
        self._quitar_indicador()
        tareas = self._store.listar_tareas(self._proyecto_id) if self._proyecto_id else []
        de_la_columna = [t for t in tareas if t.estado_id == estado_id and t.id != tarea_id]
        ultima = de_la_columna[-1].id if de_la_columna else None
        return self._soltar(tarea_id, estado_id, ultima, True)

    def _soltar(
        self,
        tarea_id: int,
        estado_id: int,
        referencia_id: int | None,
        despues: bool,
        confirmado: bool = False,
    ) -> bool:
        tarea = self._store.obtener_tarea(tarea_id)
        if tarea is None:
            return False
        if not confirmado and self._avisar_dependencias(tarea, estado_id, referencia_id, despues):
            return True  # el soltar queda en espera de la respuesta del usuario
        cambia_columna = tarea.estado_id != estado_id
        if cambia_columna:
            completado.al_cambiar_de_columna(
                tarea, estado_id, self._store.listar_estados(tarea.proyecto_id)
            )
            tarea.estado_id = estado_id
            self._store.actualizar_tarea(tarea)
            self._push_a_github(tarea_id)
        todas = self._store.listar_tareas(tarea.proyecto_id, incluir_archivadas=True)
        ids = [t.id for t in todas]
        nuevo = mover_tarea(ids, tarea_id, referencia_id, despues)
        cambia_orden = nuevo != ids
        if cambia_orden:
            self._store.reordenar_tareas(nuevo)
        if not (cambia_columna or cambia_orden):
            return False
        if self._on_cambio is not None:
            self._on_cambio()  # refresca también Tabla/Gantt, y de paso este tablero
        else:
            self.refrescar()
        return True

    def _avisar_dependencias(
        self, tarea: Tarea, estado_id: int, referencia_id: int | None, despues: bool
    ) -> bool:
        """Si soltar la tarjeta la completa y sus dependencias no están terminadas, pregunta
        antes y devuelve True (el movimiento se repite al confirmar)."""
        final = completado.id_columna_final(self._store.listar_estados(tarea.proyecto_id))
        if final is None or estado_id != final or tarea.estado_id == final:
            return False
        if tarea.porcentaje_completado >= 100:
            return False
        origenes = [
            d.tarea_origen_id
            for d in self._store.listar_dependencias(tarea.proyecto_id)
            if d.tarea_destino_id == tarea.id
        ]
        pendientes = completado.dependencias_sin_terminar(
            origenes, self._store.listar_tareas(tarea.proyecto_id)
        )
        if not pendientes:
            return False
        confirmar_completar(
            self.get_root(),
            pendientes,
            lambda: self._soltar(tarea.id, estado_id, referencia_id, despues, confirmado=True),
        )
        return True

    def _push_a_github(self, tarea_id: int) -> None:
        # Cambiar de columna en el Tablero es, para GitHub, cambiar el Status: debe
        # sincronizarse igual que guardar el diálogo de tarea o arrastrar en el Gantt.
        if self._proyecto_id is None:
            return
        proyecto = self._store.obtener_proyecto(self._proyecto_id)
        if not proyecto or not (proyecto.github_repo_name or proyecto.github_project_v2_id):
            return

        def _push() -> None:
            from gnomilestone.sync import GitHubSyncManager

            try:
                GitHubSyncManager(self._store).push_tarea(tarea_id)
            except Exception:
                log.debug("Error enviando tarea %s a GitHub", tarea_id, exc_info=True)

        threading.Thread(target=_push, daemon=True).start()
