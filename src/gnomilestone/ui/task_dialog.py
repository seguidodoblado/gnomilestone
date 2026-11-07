from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from datetime import date, timedelta

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import GLib, Gtk

from gnomilestone.i18n import _
from gnomilestone.models import Recurso, Tarea
from gnomilestone.store import CicloDependenciaError, Store
from gnomilestone.sync import GitHubSyncManager
from gnomilestone.ui.avatar_widget import AvatarWidget

log = logging.getLogger(__name__)


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
            transient_for=parent,
            modal=True,
            default_width=560,
            default_height=720,
        )
        self.set_resizable(True)
        self._store = store
        self._proyecto_id = proyecto_id
        self._on_saved = on_saved
        self._tarea = tarea

        todas = store.listar_tareas(proyecto_id)
        excluidas = {tarea.id} | _descendientes(todas, tarea.id) if tarea else set()
        self._candidatas_padre = [t for t in todas if t.id not in excluidas]
        self._candidatas_dependencia = [t for t in todas if t.id not in excluidas]
        self._estados = store.listar_estados(proyecto_id)

        dependencias_actuales = {
            d.tarea_origen_id
            for d in store.listar_dependencias(proyecto_id)
            if tarea and d.tarea_destino_id == tarea.id
        }

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.set_child(root)

        box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=10,
            margin_top=16,
            margin_bottom=16,
            margin_start=16,
            margin_end=16,
        )
        contenido_scroller = Gtk.ScrolledWindow(
            vexpand=True,
            hscrollbar_policy=Gtk.PolicyType.NEVER,
            kinetic_scrolling=True,
        )
        contenido_scroller.set_child(box)
        root.append(contenido_scroller)

        box.append(Gtk.Label(label=_("Título"), xalign=0))
        self._titulo_entry = Gtk.Entry(text=tarea.titulo if tarea else "")
        box.append(self._titulo_entry)

        box.append(Gtk.Label(label=_("Descripción"), xalign=0))
        self._descripcion_buffer = Gtk.TextBuffer(text=tarea.descripcion if tarea else "")
        descripcion_view = Gtk.TextView(
            buffer=self._descripcion_buffer,
            wrap_mode=Gtk.WrapMode.WORD_CHAR,
            top_margin=6,
            bottom_margin=6,
            left_margin=6,
            right_margin=6,
        )
        descripcion_scroller = Gtk.ScrolledWindow(
            height_request=90, hscrollbar_policy=Gtk.PolicyType.NEVER
        )
        descripcion_scroller.add_css_class("card")  # mismo marco visual que un Entry/SpinButton
        descripcion_scroller.set_child(descripcion_view)
        box.append(descripcion_scroller)

        box.append(Gtk.Label(label=_("Tarea padre"), xalign=0))
        padre_labels = [_("Ninguna")] + [t.titulo for t in self._candidatas_padre]
        self._padre_dropdown = Gtk.DropDown.new_from_strings(padre_labels)
        if tarea and tarea.padre_id is not None:
            ids = [t.id for t in self._candidatas_padre]
            if tarea.padre_id in ids:
                self._padre_dropdown.set_selected(ids.index(tarea.padre_id) + 1)
        box.append(self._padre_dropdown)

        box.append(Gtk.Label(label=_("Columna"), xalign=0))
        self._estado_dropdown = Gtk.DropDown.new_from_strings([e.nombre for e in self._estados])
        if tarea and tarea.estado_id is not None:
            ids = [e.id for e in self._estados]
            if tarea.estado_id in ids:
                self._estado_dropdown.set_selected(ids.index(tarea.estado_id))
        box.append(self._estado_dropdown)

        box.append(Gtk.Label(label=_("Fecha de inicio"), xalign=0))
        box.append(self._build_fecha_selector(tarea.fecha_inicio if tarea else None))

        fecha_fin = tarea.fecha_fin_planificada if tarea else None
        if not fecha_fin and tarea and tarea.fecha_inicio:
            fecha_fin = (
                date.fromisoformat(tarea.fecha_inicio)
                + timedelta(days=max(tarea.duracion_dias, 1) - 1)
            ).isoformat()
        box.append(Gtk.Label(label=_("Final planificado"), xalign=0))
        box.append(self._build_fecha_selector(fecha_fin, "_fecha_fin_planificada_iso"))
        box.append(Gtk.Label(label=_("Fecha límite"), xalign=0))
        box.append(self._build_fecha_selector(tarea.fecha_limite if tarea else None, "_fecha_limite_iso"))

        box.append(Gtk.Label(label=_("Porcentaje completado"), xalign=0))
        self._porcentaje_spin = Gtk.SpinButton.new_with_range(0, 100, 5)
        self._porcentaje_spin.set_value(tarea.porcentaje_completado if tarea else 0)
        box.append(self._porcentaje_spin)

        self._hito_check = Gtk.CheckButton(label=_("Es un hito"))
        self._hito_check.set_active(bool(tarea and tarea.es_hito))
        box.append(self._hito_check)

        box.append(Gtk.Label(label=_("Asignado a"), xalign=0))
        self._asignados: list[Recurso] = (
            list(store.listar_recursos_de_tarea(tarea.id)) if tarea else []
        )
        self._dedicaciones: dict[int, int] = {
            asignacion.recurso_id: asignacion.porcentaje_dedicacion
            for asignacion in (store.listar_asignaciones(tarea.id) if tarea else [])
        }
        self._asignados_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.append(self._asignados_box)
        asignar_fila = Gtk.Box(spacing=6)
        self._asignar_entry = Gtk.Entry(
            placeholder_text=_("Nombre (se crea al asignar)"), hexpand=True
        )
        self._asignar_entry.connect("activate", self._on_asignar)
        self._configurar_autocompletado_recursos()
        asignar_fila.append(self._asignar_entry)
        asignar_button = Gtk.Button(icon_name="list-add-symbolic", tooltip_text=_("Asignar"))
        asignar_button.connect("clicked", self._on_asignar)
        asignar_fila.append(asignar_button)
        box.append(asignar_fila)
        self._refrescar_asignados()

        if self._candidatas_dependencia:
            box.append(Gtk.Label(label=_("Depende de"), xalign=0))
            self._dependencia_checks: list[tuple[int, Gtk.CheckButton]] = []
            dependencias_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            for candidata in self._candidatas_dependencia:
                check = Gtk.CheckButton(label=candidata.titulo)
                check.set_active(candidata.id in dependencias_actuales)
                dependencias_box.append(check)
                self._dependencia_checks.append((candidata.id, check))
            box.append(dependencias_box)
        else:
            self._dependencia_checks = []

        self._error_label = Gtk.Label(xalign=0, wrap=True)
        self._error_label.add_css_class("error")
        self._error_label.set_visible(False)
        box.append(self._error_label)

        if self._tarea and (self._tarea.github_url or self._tarea.github_issue_number):
            texto_gh = _("Ver en GitHub (#{num})").format(num=self._tarea.github_issue_number or "")
            gh_link = Gtk.LinkButton(uri=self._tarea.github_url or "", label=texto_gh)
            gh_link.set_halign(Gtk.Align.START)
            box.append(gh_link)

        acciones = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=8,
            margin_top=8,
            margin_bottom=10,
            margin_start=16,
            margin_end=16,
            halign=Gtk.Align.END,
        )
        cancelar_button = Gtk.Button(label=_("Cancelar"))
        cancelar_button.connect("clicked", lambda _button: self.close())
        acciones.append(cancelar_button)
        save_button = Gtk.Button(label=_("Guardar"))
        save_button.add_css_class("suggested-action")
        save_button.connect("clicked", self._on_save)
        acciones.append(save_button)
        root.append(acciones)

    def _build_fecha_selector(
        self, fecha_inicial: str | None, atributo: str = "_fecha_iso"
    ) -> Gtk.Widget:
        setattr(self, atributo, fecha_inicial)

        self._fecha_button = Gtk.MenuButton()
        popover = Gtk.Popover()
        popover_box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=8,
            margin_top=10,
            margin_bottom=10,
            margin_start=10,
            margin_end=10,
        )

        self._calendar = Gtk.Calendar()
        if fecha_inicial:
            anio, mes, dia = (int(parte) for parte in fecha_inicial.split("-"))
            self._calendar.select_day(GLib.DateTime.new_local(anio, mes, dia, 0, 0, 0))
        self._calendar.connect("day-selected", self._on_fecha_seleccionada, atributo, self._fecha_button)
        popover_box.append(self._calendar)

        botones_rapidos = Gtk.Box(spacing=6)
        hoy_button = Gtk.Button(label=_("Hoy"))
        hoy_button.connect("clicked", self._on_fecha_hoy, atributo, self._calendar, self._fecha_button)
        botones_rapidos.append(hoy_button)
        quitar_button = Gtk.Button(label=_("Sin fecha"))
        quitar_button.connect("clicked", self._on_fecha_quitada, atributo, self._fecha_button)
        botones_rapidos.append(quitar_button)
        popover_box.append(botones_rapidos)

        popover.set_child(popover_box)
        self._fecha_button.set_popover(popover)
        self._actualizar_etiqueta_fecha(self._fecha_button, fecha_inicial)
        return self._fecha_button

    def _on_fecha_seleccionada(
        self, calendario: Gtk.Calendar, atributo: str, boton: Gtk.MenuButton
    ) -> None:
        fecha = calendario.get_date()
        valor = (
            f"{fecha.get_year():04d}-{fecha.get_month():02d}-{fecha.get_day_of_month():02d}"
        )
        setattr(self, atributo, valor)
        self._actualizar_etiqueta_fecha(boton, valor)

    def _on_fecha_hoy(
        self,
        _button: Gtk.Button,
        atributo: str,
        calendario: Gtk.Calendar,
        boton: Gtk.MenuButton,
    ) -> None:
        hoy = GLib.DateTime.new_now_local()
        # select_day no dispara "day-selected" si el calendario ya mostraba ese día
        # (p. ej. al reabrir el diálogo): se actualiza el estado a mano, no solo por la señal.
        calendario.select_day(hoy)
        valor = f"{hoy.get_year():04d}-{hoy.get_month():02d}-{hoy.get_day_of_month():02d}"
        setattr(self, atributo, valor)
        self._actualizar_etiqueta_fecha(boton, valor)

    def _on_fecha_quitada(
        self, _button: Gtk.Button, atributo: str, boton: Gtk.MenuButton
    ) -> None:
        setattr(self, atributo, None)
        self._actualizar_etiqueta_fecha(boton, None)

    @staticmethod
    def _actualizar_etiqueta_fecha(boton: Gtk.MenuButton, fecha: str | None) -> None:
        if fecha:
            anio, mes, dia = fecha.split("-")
            boton.set_label(f"{dia}/{mes}/{anio}")
        else:
            boton.set_label(_("Sin fecha"))

    def _on_save(self, _button: Gtk.Button) -> None:
        titulo = self._titulo_entry.get_text().strip()
        if not titulo:
            self._mostrar_error(_("El título no puede estar vacío."))
            return

        fecha = self._fecha_iso
        fecha_fin = self._fecha_fin_planificada_iso
        fecha_limite = self._fecha_limite_iso
        if self._hito_check.get_active() and not fecha:
            self._mostrar_error(_("Un hito necesita una fecha: no se puede situar en el Gantt sin ella."))
            return

        padre_indice = self._padre_dropdown.get_selected()
        padre_id = self._candidatas_padre[padre_indice - 1].id if padre_indice > 0 else None
        estado_id = (
            self._estados[self._estado_dropdown.get_selected()].id if self._estados else None
        )
        inicio, fin = self._descripcion_buffer.get_bounds()
        descripcion = self._descripcion_buffer.get_text(inicio, fin, False).strip()
        if fecha and not fecha_fin:
            fecha_fin = (
                date.fromisoformat(fecha) + timedelta(days=0)
            ).isoformat()
        if fecha and fecha_fin and fecha_fin < fecha:
            self._mostrar_error(_("El final planificado no puede ser anterior al inicio."))
            return
        if fecha_fin and not fecha:
            self._mostrar_error(_("El final planificado necesita una fecha de inicio."))
            return
        if fecha_fin and fecha_limite and fecha_limite < fecha_fin:
            self._mostrar_error(_("La fecha límite no puede ser anterior al final planificado."))
            return
        duracion = (date.fromisoformat(fecha_fin) - date.fromisoformat(fecha)).days + 1 if fecha and fecha_fin else 1
        porcentaje = int(self._porcentaje_spin.get_value())
        es_hito = self._hito_check.get_active()

        if self._tarea is None:
            tarea = self._store.crear_tarea(
                self._proyecto_id,
                titulo,
                padre_id=padre_id,
                estado_id=estado_id,
                descripcion=descripcion,
                fecha_inicio=fecha or None,
                fecha_fin_planificada=fecha_fin,
                fecha_limite=fecha_limite,
                duracion_dias=duracion,
                porcentaje_completado=porcentaje,
                es_hito=es_hito,
            )
        else:
            tarea = self._tarea
            tarea.titulo = titulo
            tarea.padre_id = padre_id
            tarea.estado_id = estado_id
            tarea.descripcion = descripcion
            tarea.fecha_inicio = fecha or None
            tarea.fecha_fin_planificada = fecha_fin
            tarea.fecha_limite = fecha_limite
            tarea.duracion_dias = duracion
            tarea.porcentaje_completado = porcentaje
            tarea.es_hito = es_hito
            self._store.actualizar_tarea(tarea)

        if not self._sincronizar_dependencias(tarea.id):
            return
        self._sincronizar_asignaciones(tarea.id)

        # Si el proyecto está vinculado con GitHub, enviar cambios en segundo plano
        proyecto = self._store.obtener_proyecto(self._proyecto_id)
        if proyecto and (proyecto.github_repo_name or proyecto.github_project_v2_id):
            def _push() -> None:
                try:
                    GitHubSyncManager(self._store).push_tarea(tarea.id)
                except Exception as e:  # noqa: BLE001 - la sincronización no debe bloquear el guardado
                    log.debug("Error enviando tarea a GitHub: %s", e)

            threading.Thread(target=_push, daemon=True).start()

        self._on_saved()
        self.close()

    def _configurar_autocompletado_recursos(self) -> None:
        nombres = [r.nombre for r in self._store.listar_recursos(self._proyecto_id)]
        modelo = Gtk.ListStore(str)
        for nombre in nombres:
            modelo.append([nombre])
        completion = Gtk.EntryCompletion()
        completion.set_model(modelo)
        completion.set_text_column(0)
        completion.set_inline_completion(True)
        self._asignar_entry.set_completion(completion)

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
            fila = Gtk.Box(spacing=8, valign=Gtk.Align.CENTER)
            fila.append(AvatarWidget(recurso, size=28))
            fila.append(Gtk.Label(label=recurso.nombre, xalign=0, hexpand=True))
            dedicacion = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 5)
            dedicacion.set_value(self._dedicaciones.get(recurso.id, 100))
            dedicacion.set_digits(0)
            dedicacion.set_size_request(150, -1)
            dedicacion.set_hexpand(False)
            dedicacion.set_tooltip_text(_("Porcentaje de dedicación"))
            dedicacion.connect("value-changed", self._on_dedicacion_changed, recurso.id)
            fila.append(dedicacion)
            porcentaje = Gtk.Label(label=f"{self._dedicaciones.get(recurso.id, 100)} %")
            porcentaje.set_width_chars(5)
            dedicacion.connect("value-changed", self._actualizar_etiqueta_dedicacion, porcentaje)
            fila.append(porcentaje)
            quitar = Gtk.Button(
                icon_name="list-remove-symbolic", tooltip_text=_("Quitar asignación")
            )
            quitar.add_css_class("flat")
            quitar.connect("clicked", self._on_quitar_asignado, recurso.id)
            fila.append(quitar)
            self._asignados_box.append(fila)

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
        self._configurar_autocompletado_recursos()
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
                self._mostrar_error(_("Esa dependencia crearía un ciclo entre tareas."))
                return False
        for origen_id in existentes.keys() - deseadas:
            self._store.eliminar_dependencia(existentes[origen_id])
        return True

    def _mostrar_error(self, mensaje: str) -> None:
        self._error_label.set_text(mensaje)
        self._error_label.set_visible(True)
