from __future__ import annotations

import shutil
from collections.abc import Callable
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gio, GLib, Gtk

from gnomilestone.i18n import _
from gnomilestone.models import Proyecto
from gnomilestone.store import DATA_DIR, Store

_ESTADOS = (
    ("pendiente", "Pendiente"),
    ("en_curso", "En curso"),
    ("pausado", "Pausado"),
    ("completado", "Completado"),
)

_ICONO_PROYECTO_POR_DEFECTO = "folder-symbolic"


class ProjectDialog(Gtk.Window):
    """Edición de los metadatos generales de un proyecto."""

    def __init__(
        self,
        parent: Gtk.Window,
        store: Store,
        proyecto: Proyecto,
        on_saved: Callable[[Proyecto], None],
    ) -> None:
        super().__init__(
            title=_("Editar proyecto"),
            transient_for=parent,
            modal=True,
            default_width=460,
        )
        self._store = store
        self._proyecto = proyecto
        self._on_saved = on_saved

        box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=10,
            margin_top=16,
            margin_bottom=16,
            margin_start=16,
            margin_end=16,
        )
        # Con scroll: si la ventana queda más baja que el contenido (p. ej. al reabrirla),
        # los campos siguen accesibles en vez de quedar recortados hasta redimensionar.
        scroll = Gtk.ScrolledWindow(
            hscrollbar_policy=Gtk.PolicyType.NEVER,
            propagate_natural_height=True,
        )
        scroll.set_child(box)
        self.set_child(scroll)

        box.append(Gtk.Label(label=_("Nombre"), xalign=0))
        self._nombre = Gtk.Entry(text=proyecto.nombre)
        box.append(self._nombre)

        box.append(Gtk.Label(label=_("Icono"), xalign=0))
        self._icon_name = _ICONO_PROYECTO_POR_DEFECTO
        self._icon_path = proyecto.icon_path
        imagen_row = Gtk.Box(spacing=10, valign=Gtk.Align.CENTER)
        self._icon_preview = Gtk.Image()
        self._icon_preview.set_pixel_size(32)
        self._actualizar_icono()
        imagen_row.append(self._icon_preview)
        elegir_imagen = Gtk.Button(label=_("Elegir imagen del equipo"))
        elegir_imagen.connect("clicked", self._on_elegir_imagen)
        imagen_row.append(elegir_imagen)
        quitar_imagen = Gtk.Button(label=_("Quitar imagen"))
        quitar_imagen.connect("clicked", self._on_quitar_imagen)
        imagen_row.append(quitar_imagen)
        box.append(imagen_row)

        box.append(Gtk.Label(label=_("Descripción"), xalign=0))
        self._descripcion = Gtk.TextBuffer(text=proyecto.descripcion)
        descripcion = Gtk.TextView(buffer=self._descripcion, wrap_mode=Gtk.WrapMode.WORD_CHAR)
        descripcion.set_top_margin(6)
        descripcion.set_bottom_margin(6)
        descripcion.set_left_margin(6)
        descripcion.set_right_margin(6)
        # Un TextView con ajuste de línea fuera de un ScrolledWindow da medidas erróneas
        # en GTK4 y el resto del formulario no llega a pintarse hasta redimensionar.
        descripcion_scroll = Gtk.ScrolledWindow(
            hscrollbar_policy=Gtk.PolicyType.NEVER,
            min_content_height=90,
            max_content_height=160,
            propagate_natural_height=True,
        )
        descripcion_scroll.add_css_class("card")
        descripcion_scroll.set_child(descripcion)
        box.append(descripcion_scroll)

        fechas = Gtk.Box(spacing=10)
        inicio_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, hexpand=True)
        inicio_box.append(Gtk.Label(label=_("Fecha de inicio"), xalign=0))
        self._fecha_inicio = self._build_fecha_selector(proyecto.fecha_inicio)
        inicio_box.append(self._fecha_inicio)
        fechas.append(inicio_box)
        fin_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, hexpand=True)
        fin_box.append(Gtk.Label(label=_("Fecha objetivo"), xalign=0))
        self._fecha_fin = self._build_fecha_selector(proyecto.fecha_fin_estimada)
        fin_box.append(self._fecha_fin)
        fechas.append(fin_box)
        box.append(fechas)

        box.append(Gtk.Label(label=_("Estado"), xalign=0))
        self._estado = Gtk.DropDown.new_from_strings(
            [_(etiqueta) for codigo, etiqueta in _ESTADOS]
        )
        estados = [codigo for codigo, etiqueta in _ESTADOS]
        self._estado.set_selected(estados.index(proyecto.estado) if proyecto.estado in estados else 0)
        box.append(self._estado)

        self._archivado = Gtk.CheckButton(label=_("Proyecto archivado"))
        self._archivado.set_active(proyecto.archivado)
        box.append(self._archivado)

        self._error = Gtk.Label(xalign=0, wrap=True)
        self._error.add_css_class("error")
        box.append(self._error)

        acciones = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8, halign=Gtk.Align.END)
        cancelar = Gtk.Button(label=_("Cancelar"))
        cancelar.connect("clicked", lambda _button: self.close())
        guardar = Gtk.Button(label=_("Guardar"))
        guardar.add_css_class("suggested-action")
        guardar.connect("clicked", self._guardar)
        acciones.append(cancelar)
        acciones.append(guardar)
        box.append(acciones)

    def _guardar(self, _button: Gtk.Button) -> None:
        nombre = self._nombre.get_text().strip()
        if not nombre:
            self._error.set_text(_("El nombre no puede estar vacío."))
            return

        inicio = self._fecha_inicio_iso
        fin = self._fecha_fin_iso
        if inicio and fin and fin < inicio:
            self._error.set_text(_("La fecha objetivo no puede ser anterior a la de inicio."))
            return

        estado = _ESTADOS[self._estado.get_selected()][0]
        inicio_iter = self._descripcion.get_start_iter()
        fin_iter = self._descripcion.get_end_iter()
        self._proyecto.nombre = nombre
        self._proyecto.icon_name = self._icon_name
        self._proyecto.icon_path = self._icon_path
        self._proyecto.descripcion = self._descripcion.get_text(inicio_iter, fin_iter, False)
        self._proyecto.fecha_inicio = inicio
        self._proyecto.fecha_fin_estimada = fin
        self._proyecto.estado = estado
        self._proyecto.archivado = self._archivado.get_active()
        self._store.actualizar_proyecto(self._proyecto)
        self._on_saved(self._proyecto)
        self.close()

    def _on_elegir_imagen(self, _button: Gtk.Button) -> None:
        dialog = Gtk.FileDialog(title=_("Elegir imagen del proyecto"))
        filtros = Gio.ListStore.new(Gtk.FileFilter)
        filtro = Gtk.FileFilter(name=_("Imágenes"))
        filtro.add_pixbuf_formats()
        filtros.append(filtro)
        dialog.set_filters(filtros)
        dialog.open(self, None, self._on_imagen_elegida)

    def _on_imagen_elegida(
        self, dialog: Gtk.FileDialog, result: Gio.AsyncResult
    ) -> None:
        try:
            archivo = dialog.open_finish(result)
        except GLib.Error:
            return
        origen = archivo.get_path() if archivo else None
        if not origen:
            return
        try:
            destino_dir = DATA_DIR / "project_icons"
            destino_dir.mkdir(parents=True, exist_ok=True)
            destino = destino_dir / f"project-{self._proyecto.id}{Path(origen).suffix.lower()}"
            shutil.copy2(origen, destino)
        except OSError:
            self._error.set_text(_("No se pudo copiar la imagen seleccionada."))
            return
        self._icon_path = str(destino)
        self._actualizar_icono()

    def _on_quitar_imagen(self, _button: Gtk.Button) -> None:
        self._icon_path = None
        self._actualizar_icono()

    def _actualizar_icono(self) -> None:
        if self._icon_path and Path(self._icon_path).is_file():
            self._icon_preview.set_from_file(self._icon_path)
        else:
            self._icon_preview.set_from_icon_name(self._icon_name)

    def _build_fecha_selector(self, fecha_inicial: str | None) -> Gtk.MenuButton:
        atributo = "_fecha_inicio_iso" if not hasattr(self, "_fecha_inicio_iso") else "_fecha_fin_iso"
        setattr(self, atributo, fecha_inicial)
        boton = Gtk.MenuButton()
        popover = Gtk.Popover()
        contenido = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=8,
            margin_top=10,
            margin_bottom=10,
            margin_start=10,
            margin_end=10,
        )
        calendario = Gtk.Calendar()
        if fecha_inicial:
            anio, mes, dia = (int(parte) for parte in fecha_inicial.split("-"))
            calendario.select_day(GLib.DateTime.new_local(anio, mes, dia, 0, 0, 0))
        calendario.connect("day-selected", self._on_fecha_seleccionada, atributo, boton)
        contenido.append(calendario)
        acciones = Gtk.Box(spacing=6)
        hoy = Gtk.Button(label=_("Hoy"))
        hoy.connect("clicked", self._on_fecha_hoy, atributo, calendario, boton)
        acciones.append(hoy)
        quitar = Gtk.Button(label=_("Sin fecha"))
        quitar.connect("clicked", self._on_fecha_quitada, atributo, boton)
        acciones.append(quitar)
        contenido.append(acciones)
        popover.set_child(contenido)
        boton.set_popover(popover)
        self._actualizar_etiqueta_fecha(boton, fecha_inicial)
        return boton

    @staticmethod
    def _actualizar_etiqueta_fecha(boton: Gtk.MenuButton, fecha: str | None) -> None:
        if fecha:
            anio, mes, dia = fecha.split("-")
            boton.set_label(f"{dia}/{mes}/{anio}")
        else:
            boton.set_label(_("Sin fecha"))

    def _on_fecha_seleccionada(
        self, calendario: Gtk.Calendar, atributo: str, boton: Gtk.MenuButton
    ) -> None:
        fecha = calendario.get_date()
        valor = f"{fecha.get_year():04d}-{fecha.get_month():02d}-{fecha.get_day_of_month():02d}"
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
        calendario.select_day(hoy)
        valor = f"{hoy.get_year():04d}-{hoy.get_month():02d}-{hoy.get_day_of_month():02d}"
        setattr(self, atributo, valor)
        self._actualizar_etiqueta_fecha(boton, valor)

    def _on_fecha_quitada(self, _button: Gtk.Button, atributo: str, boton: Gtk.MenuButton) -> None:
        setattr(self, atributo, None)
        self._actualizar_etiqueta_fecha(boton, None)
