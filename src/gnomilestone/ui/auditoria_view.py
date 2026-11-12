"""Pestaña Auditoría: qué usuario de gestión hizo cada cambio y el registro cronológico."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gio, GLib, GObject, Gtk

from gnomilestone import usuarios as usuarios_activos
from gnomilestone.historial import detalle_evento, titulo_evento
from gnomilestone.i18n import _
from gnomilestone.models import HistorialTarea
from gnomilestone.report_metrics import actividad_por_usuario
from gnomilestone.store import Store

_TODOS = -1  # filtro: todos los usuarios
_SIN_AUTOR = -2  # filtro: cambios sin autor


def _fecha_local(creado: str) -> str:
    """Fecha y hora locales de un instante de SQLite (UTC, «AAAA-MM-DD HH:MM:SS»)."""
    try:
        instante = datetime.strptime(creado[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
    except ValueError:
        return creado
    return instante.astimezone().strftime("%Y-%m-%d %H:%M")


class FilaAuditoria(GObject.Object):
    def __init__(self, fecha: str, usuario: str, tarea: str, cambio: str, detalle: str) -> None:
        super().__init__()
        self.fecha, self.usuario, self.tarea, self.cambio, self.detalle = (
            fecha, usuario, tarea, cambio, detalle,
        )


def _pedir_nombre(padre: Gtk.Widget, titulo: str, valor: str, al_aceptar) -> None:
    """Pequeño diálogo modal con un campo de texto; llama a `al_aceptar(nombre)`."""
    ventana = Gtk.Window(
        title=titulo, modal=True, transient_for=padre.get_root(), default_width=340, resizable=False
    )
    caja = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
    for lado in ("top", "bottom", "start", "end"):
        getattr(caja, f"set_margin_{lado}")(18)
    entrada = Gtk.Entry(text=valor, activates_default=True)
    caja.append(Gtk.Label(label=_("Nombre"), xalign=0))
    caja.append(entrada)
    botones = Gtk.Box(spacing=8, halign=Gtk.Align.END)
    cancelar = Gtk.Button(label=_("Cancelar"))
    aceptar = Gtk.Button(label=_("Aceptar"))
    aceptar.add_css_class("suggested-action")
    botones.append(cancelar)
    botones.append(aceptar)
    caja.append(botones)
    ventana.set_child(caja)
    ventana.set_default_widget(aceptar)

    def _aceptar(*_args) -> None:
        nombre = entrada.get_text().strip()
        if nombre:
            ventana.close()
            al_aceptar(nombre)

    cancelar.connect("clicked", lambda _b: ventana.close())
    aceptar.connect("clicked", _aceptar)
    ventana.present()


def _confirmar(padre: Gtk.Widget, mensaje: str, detalle: str, accion: str, al_confirmar) -> None:
    dialogo = Gtk.AlertDialog(
        message=mensaje, detail=detalle, buttons=[_("Cancelar"), accion],
        cancel_button=0, default_button=0,
    )

    def terminado(d, resultado) -> None:
        try:
            if d.choose_finish(resultado) == 1:
                al_confirmar()
        except GLib.Error:
            return  # diálogo cerrado sin elegir

    dialogo.choose(padre.get_root(), None, terminado)


class AuditoriaView(Gtk.Box):
    """Usuario activo, cambios por usuario y registro cronológico del proyecto."""

    def __init__(self, store: Store, on_cambio=None) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self._store = store
        self._on_cambio = on_cambio
        self._proyecto_id: int | None = None
        self._historial: list[HistorialTarea] = []
        self._titulos: dict[int, str] = {}
        self._estados: dict[int, str] = {}
        self._usuarios = []
        self._poblando = False
        for lado in ("top", "bottom", "start", "end"):
            getattr(self, f"set_margin_{lado}")(12)

        gestion = Gtk.Box(spacing=8)
        gestion.append(Gtk.Label(label=_("Usuario activo:")))
        self._selector = Gtk.DropDown(
            tooltip_text=_("Los cambios que hagas en las tareas se firmarán con este usuario")
        )
        self._selector.connect("notify::selected", self._on_usuario_elegido)
        gestion.append(self._selector)
        for texto, accion in (
            (_("Nuevo…"), self._nuevo),
            (_("Renombrar…"), self._renombrar),
            (_("Eliminar"), self._eliminar),
        ):
            boton = Gtk.Button(label=texto)
            boton.connect("clicked", lambda _b, a=accion: a())
            gestion.append(boton)
        self._boton_atribuir = Gtk.Button(
            label=_("Atribuir cambios sin autor"), hexpand=True, halign=Gtk.Align.END,
            tooltip_text=_("Firma con el usuario activo todos los cambios anteriores sin autor"),
        )
        self._boton_atribuir.connect("clicked", lambda _b: self._atribuir())
        gestion.append(self._boton_atribuir)
        self.append(gestion)

        self.append(Gtk.Label(label=_("Cambios por usuario"), xalign=0, css_classes=["heading"]))
        self._barras = Gtk.DrawingArea(content_height=60)
        self._barras.set_draw_func(self._dibujar_barras)
        self.append(self._barras)

        filtro = Gtk.Box(spacing=8)
        filtro.append(Gtk.Label(label=_("Registro de cambios"), xalign=0, css_classes=["heading"]))
        filtro.append(Gtk.Label(label=_("Mostrar:"), hexpand=True, halign=Gtk.Align.END))
        self._filtro = Gtk.DropDown()
        self._ids_filtro: list[int] = [_TODOS]
        self._filtro.connect("notify::selected", lambda *_a: self._reconstruir_registro())
        filtro.append(self._filtro)
        self.append(filtro)

        self._modelo = Gio.ListStore(item_type=FilaAuditoria)
        vista = Gtk.ColumnView(model=Gtk.NoSelection(model=self._modelo), show_row_separators=True)
        for titulo, propiedad, expandir in (
            (_("Fecha"), "fecha", False), (_("Usuario"), "usuario", False),
            (_("Tarea"), "tarea", True), (_("Cambio"), "cambio", False),
            (_("Detalle"), "detalle", True),
        ):
            fabrica = Gtk.SignalListItemFactory()
            fabrica.connect("setup", lambda _f, item: item.set_child(Gtk.Label(xalign=0, ellipsize=3)))
            fabrica.connect(
                "bind", lambda _f, item, p=propiedad: item.get_child().set_text(getattr(item.get_item(), p))
            )
            columna = Gtk.ColumnViewColumn(title=titulo, factory=fabrica, resizable=True, expand=expandir)
            vista.append_column(columna)
        self._vacio = Gtk.Label(label=_("Aún no hay cambios registrados"), css_classes=["dim-label"])
        marco = Gtk.ScrolledWindow(vexpand=True, hexpand=True, child=vista)
        self.append(marco)
        self.append(self._vacio)

    # -- Datos ---------------------------------------------------------------

    def set_data(self, proyecto_id, historial, titulos_tareas, nombres_estado) -> None:
        self._proyecto_id = proyecto_id
        self._historial = historial
        self._titulos = titulos_tareas
        self._estados = nombres_estado
        self._usuarios = self._store.listar_usuarios()
        self._poblando = True
        ids = [u.id for u in self._usuarios]
        self._selector.set_model(Gtk.StringList.new([u.nombre for u in self._usuarios]))
        actual = self._store.usuario_actual_id
        if actual in ids:
            self._selector.set_selected(ids.index(actual))
        self._ids_filtro = [_TODOS, *ids, _SIN_AUTOR]
        seleccion = self._filtro.get_selected()
        self._filtro.set_model(Gtk.StringList.new(
            [_("Todos los usuarios"), *(u.nombre for u in self._usuarios), _("Sin autor")]
        ))
        self._filtro.set_selected(seleccion if seleccion < len(self._ids_filtro) else 0)
        self._poblando = False
        self._boton_atribuir.set_sensitive(actual in ids)
        self._barras.set_content_height(max(40, 30 * (len(self._usuarios) + 1)))
        self._barras.queue_draw()
        self._reconstruir_registro()

    def _reconstruir_registro(self) -> None:
        if self._poblando:
            return
        indice = self._filtro.get_selected()
        filtro = self._ids_filtro[indice] if indice < len(self._ids_filtro) else _TODOS
        nombres = {u.id: u.nombre for u in self._usuarios}
        filas = []
        for e in self._historial:
            if filtro == _SIN_AUTOR and e.usuario_id in nombres:
                continue
            if filtro >= 0 and e.usuario_id != filtro:
                continue
            filas.append(FilaAuditoria(
                _fecha_local(e.creado),
                nombres.get(e.usuario_id, _("Sin autor")),
                self._titulos.get(e.tarea_id, f"#{e.tarea_id}"),
                titulo_evento(e.tipo),
                detalle_evento(e, self._estados) or (e.detalle if e.tipo == "creacion" else ""),
            ))
        self._modelo.remove_all()
        self._modelo.splice(0, 0, filas)
        self._vacio.set_visible(not filas)

    # -- Barras --------------------------------------------------------------

    def _dibujar_barras(self, _area, cr, ancho, alto) -> None:
        color = self.get_color()
        filas = actividad_por_usuario(self._usuarios, self._historial)
        maximo = max([f.cambios for f in filas] + [1])
        cr.set_font_size(13)
        bx = min(130, ancho * 0.25)
        bw = max(40, ancho - bx - 8)
        for i, fila in enumerate(filas):
            y = 4 + i * 30
            cr.set_source_rgba(color.red, color.green, color.blue, color.alpha)
            cr.move_to(0, y + 15)
            cr.show_text((fila.usuario.nombre if fila.usuario else _("Sin autor"))[:16])
            cr.set_source_rgba(0.12, 0.22, 0.38, 0.75)
            self._redondeado(cr, bx, y, bw, 20, 10)
            cr.fill()
            if fila.cambios:
                cr.set_source_rgb(*((0.24, 0.52, 0.86) if fila.usuario else (0.45, 0.47, 0.52)))
                self._redondeado(cr, bx, y, max(20, bw * fila.cambios / maximo), 20, 10)
                cr.fill()
            cr.set_source_rgb(0.96, 0.98, 1.0)
            texto = _("{n} cambios").format(n=fila.cambios)
            cr.move_to(bx + (bw - cr.text_extents(texto).width) / 2, y + 15)
            cr.show_text(texto)

    @staticmethod
    def _redondeado(cr, x, y, w, h, r) -> None:
        r = min(r, w / 2, h / 2)
        cr.new_sub_path()
        cr.arc(x + w - r, y + r, r, -1.5708, 0)
        cr.arc(x + w - r, y + h - r, r, 0, 1.5708)
        cr.arc(x + r, y + h - r, r, 1.5708, 3.1416)
        cr.arc(x + r, y + r, r, 3.1416, 4.7124)
        cr.close_path()

    # -- Gestión de usuarios --------------------------------------------------

    def _usuario_seleccionado(self):
        i = self._selector.get_selected()
        return self._usuarios[i] if 0 <= i < len(self._usuarios) else None

    def _on_usuario_elegido(self, *_args) -> None:
        if self._poblando:
            return
        usuario = self._usuario_seleccionado()
        if usuario is not None:
            usuarios_activos.establecer_usuario_actual(self._store, usuario.id)
            self._boton_atribuir.set_sensitive(True)

    def _refrescar(self) -> None:
        if self._on_cambio:
            self._on_cambio()

    def _nuevo(self) -> None:
        def crear(nombre: str) -> None:
            try:
                usuario = self._store.crear_usuario(nombre)
            except (sqlite3.IntegrityError, ValueError):
                return  # nombre repetido o vacío
            usuarios_activos.establecer_usuario_actual(self._store, usuario.id)
            self._refrescar()

        _pedir_nombre(self, _("Nuevo usuario"), "", crear)

    def _renombrar(self) -> None:
        usuario = self._usuario_seleccionado()
        if usuario is None:
            return

        def renombrar(nombre: str) -> None:
            try:
                self._store.renombrar_usuario(usuario.id, nombre)
            except (sqlite3.IntegrityError, ValueError):
                return  # nombre repetido o vacío
            self._refrescar()

        _pedir_nombre(self, _("Renombrar usuario"), usuario.nombre, renombrar)

    def _eliminar(self) -> None:
        usuario = self._usuario_seleccionado()
        if usuario is None:
            return

        def eliminar() -> None:
            self._store.eliminar_usuario(usuario.id)
            if self._store.usuario_actual_id is None:
                usuarios_activos.inicializar_usuario_actual(self._store)
            self._refrescar()

        _confirmar(
            self, _("¿Eliminar a {nombre}?").format(nombre=usuario.nombre),
            _("Sus cambios del historial se quedarán sin autor."), _("Eliminar"), eliminar,
        )

    def _atribuir(self) -> None:
        usuario = self._usuario_seleccionado()
        if usuario is None or self._proyecto_id is None:
            return

        def atribuir() -> None:
            self._store.atribuir_cambios_sin_autor(self._proyecto_id, usuario.id)
            self._refrescar()

        _confirmar(
            self, _("¿Atribuir a {nombre} los cambios sin autor?").format(nombre=usuario.nombre),
            _("Todos los cambios anteriores de este proyecto sin autor se firmarán con ese usuario. "
              "No se puede deshacer."),
            _("Atribuir"), atribuir,
        )
