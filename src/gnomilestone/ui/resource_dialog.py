from __future__ import annotations

import logging
import shutil
from collections.abc import Callable
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, Gio, GLib, Gtk

from gnomilestone.i18n import _
from gnomilestone.models import CATEGORIAS_RECURSO, Recurso
from gnomilestone.store import DATA_DIR, PALETA_RECURSOS, Store
from gnomilestone.ui.avatar_widget import AvatarWidget

log = logging.getLogger(__name__)

_AVATARS_DIR = DATA_DIR / "avatars"
_css_aplicado = False
_GLOBE_ICON = Path(__file__).resolve().parent.parent / "assets" / "globe-symbolic.svg"


def _globe_icon_path() -> Path:
    settings = Gtk.Settings.get_default()
    dark = bool(settings and "dark" in (settings.get_property("gtk-theme-name") or "").lower())
    return _GLOBE_ICON.with_name("globe-symbolic-dark.svg" if dark else "globe-symbolic-light.svg")

# (categoría, etiqueta, icono): el orden es el que se usa en el filtro y en la ordenación
# de tarjetas (que ya llega agrupada por categoría desde `Store.listar_recursos`).
_CATEGORIAS = (
    ("personas", _("Personas"), "avatar-default-symbolic"),
    ("medios", _("Medios"), "image-x-generic-symbolic"),
    ("equipos", _("Equipos"), "computer-symbolic"),
    ("lugares", _("Lugares"), "mark-location-symbolic"),
)
_ICONO_POR_CATEGORIA = {valor: icono for valor, _etq, icono in _CATEGORIAS}
_ETIQUETA_POR_CATEGORIA = {valor: etq for valor, etq, _ic in _CATEGORIAS}


def _asegurar_css() -> None:
    global _css_aplicado
    if _css_aplicado:
        return
    proveedor = Gtk.CssProvider()
    proveedor.load_from_string(
        ".gnomilestone-color-swatch { "
        "min-width: 24px; min-height: 24px; border-radius: 9999px; padding: 0; }\n"
        ".gnomilestone-avatar-boton { padding: 0; min-width: 0; min-height: 0; }\n"
        ".gnomilestone-tarjeta-recurso { "
        "padding: 20px 16px; min-width: 220px; min-height: 220px; }\n"
    )
    Gtk.StyleContext.add_provider_for_display(
        Gdk.Display.get_default(), proveedor, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
    )
    _css_aplicado = True


def _es_ruta_local(avatar_url: str) -> bool:
    return not avatar_url.startswith(("http://", "https://"))


class ResourceView(Gtk.Box):
    """Vista de recursos del proyecto (rail Recursos): tarjetas agrupadas por categoría
    (Personas, Medios, Equipos, Lugares), con alta rápida y un recurso global opcional
    que aparece en todos los proyectos. El alta normal sigue siendo asignar desde una
    tarea; esta vista es para gestionarlos (avatar, categoría, alcance, baja)."""

    def __init__(self, store: Store, on_changed: Callable[[], None]) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.set_margin_top(16)
        self.set_margin_bottom(16)
        self.set_margin_start(16)
        self.set_margin_end(16)
        _asegurar_css()
        self._store = store
        self._proyecto_id: int | None = None
        self._on_changed = on_changed
        self._filtro_categoria: str | None = None  # None = todas

        # Se crean antes que el filtro: activar su primer botón dispara refrescar(), que
        # ya necesita _flujo/_vacio existentes.
        self._flujo = Gtk.FlowBox(
            selection_mode=Gtk.SelectionMode.NONE,
            homogeneous=True,
            row_spacing=12,
            column_spacing=12,
            margin_top=6,
        )
        self._vacio = Gtk.Label(
            label=_("Aún no hay recursos. Añade uno arriba o asígnalo al crear una tarea."),
            wrap=True,
            xalign=0,
        )
        self._vacio.add_css_class("dim-label")

        self.append(self._build_filtro())
        self.append(self._build_alta_rapida())

        scroller = Gtk.ScrolledWindow(vexpand=True, hexpand=True)
        scroller.set_child(self._flujo)
        self.append(scroller)
        self.append(self._vacio)

    # -- Construcción de la cabecera -----------------------------------------

    def _build_filtro(self) -> Gtk.Widget:
        fila = Gtk.Box(spacing=6)
        primero: Gtk.ToggleButton | None = None
        for valor, etiqueta_icono, boton in self._botones_filtro():
            if primero is None:
                primero = boton
                boton.set_active(True)
            fila.append(boton)
        return fila

    def _botones_filtro(self):
        opciones = [(None, _("Todas"), None)] + [(v, e, i) for v, e, i in _CATEGORIAS]
        primero: Gtk.ToggleButton | None = None
        for valor, etiqueta, icono in opciones:
            contenido = Gtk.Box(spacing=4)
            if icono:
                contenido.append(Gtk.Image.new_from_icon_name(icono))
            contenido.append(Gtk.Label(label=etiqueta))
            boton = Gtk.ToggleButton(child=contenido, group=primero)
            boton.connect("toggled", self._on_filtro_toggled, valor)
            if primero is None:
                primero = boton
            yield valor, etiqueta, boton

    def _on_filtro_toggled(self, boton: Gtk.ToggleButton, valor: str | None) -> None:
        if boton.get_active():
            self._filtro_categoria = valor
            self.refrescar()

    def _build_alta_rapida(self) -> Gtk.Widget:
        fila = Gtk.Box(spacing=6, orientation=Gtk.Orientation.VERTICAL)
        controles = Gtk.Box(spacing=6)
        self._name_entry = Gtk.Entry(placeholder_text=_("Nombre del nuevo recurso"), hexpand=True)
        self._name_entry.connect("activate", self._on_add_manual)
        controles.append(self._name_entry)

        self._categoria_dropdown = Gtk.DropDown.new_from_strings(
            [etiqueta for _v, etiqueta, _i in _CATEGORIAS]
        )
        controles.append(self._categoria_dropdown)

        add_button = Gtk.Button(icon_name="list-add-symbolic", tooltip_text=_("Añadir recurso"))
        add_button.add_css_class("suggested-action")
        add_button.connect("clicked", self._on_add_manual)
        controles.append(add_button)
        fila.append(controles)

        self._global_check = Gtk.CheckButton(
            label=_("Recurso global (disponible en todos los proyectos)")
        )
        fila.append(self._global_check)
        return fila

    # -- Listado ---------------------------------------------------------------

    def mostrar_proyecto(self, proyecto_id: int) -> None:
        self._proyecto_id = proyecto_id
        self.refrescar()

    def refrescar(self) -> None:
        while (hijo := self._flujo.get_first_child()) is not None:
            self._flujo.remove(hijo)
        if self._proyecto_id is None:
            self._vacio.set_visible(True)
            self._flujo.set_visible(False)
            return
        recursos = self._store.listar_recursos(self._proyecto_id)
        if self._filtro_categoria is not None:
            recursos = [r for r in recursos if r.categoria == self._filtro_categoria]
        self._vacio.set_visible(not recursos)
        self._flujo.set_visible(bool(recursos))
        for recurso in recursos:
            self._flujo.append(self._tarjeta_recurso(recurso))

    # -- Tarjeta -----------------------------------------------------------

    def _tarjeta_recurso(self, recurso: Recurso) -> Gtk.Widget:
        n_tareas = self._store.contar_asignaciones_recurso(recurso.id)
        titulos = self._store.listar_titulos_asignados(recurso.id)

        tarjeta = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        tarjeta.add_css_class("card")
        tarjeta.add_css_class("gnomilestone-tarjeta-recurso")

        cabecera = Gtk.Box(halign=Gtk.Align.CENTER)
        cabecera.append(self._boton_avatar(recurso))
        tarjeta.append(cabecera)

        nombre = Gtk.Label(label=recurso.nombre, xalign=0.5, halign=Gtk.Align.CENTER, wrap=True)
        nombre.add_css_class("heading")
        tarjeta.append(nombre)

        if recurso.email:
            email = Gtk.Label(label=recurso.email, xalign=0.5, halign=Gtk.Align.CENTER)
            email.add_css_class("caption")
            email.add_css_class("dim-label")
            tarjeta.append(email)

        etiquetas = Gtk.Box(spacing=4, halign=Gtk.Align.CENTER)
        categoria_box = Gtk.Box(spacing=4)
        categoria_box.append(
            Gtk.Image.new_from_icon_name(_ICONO_POR_CATEGORIA[recurso.categoria])
        )
        categoria_label = Gtk.Label(label=_ETIQUETA_POR_CATEGORIA[recurso.categoria])
        categoria_label.add_css_class("caption")
        categoria_box.append(categoria_label)
        etiquetas.append(categoria_box)
        if recurso.es_global:
            global_box = Gtk.Box(spacing=4, tooltip_text=_("Disponible en todos los proyectos"))
            global_box.append(Gtk.Image.new_from_file(str(_globe_icon_path())))
            etiqueta_global = Gtk.Label(label=_("Global"))
            etiqueta_global.add_css_class("caption")
            global_box.append(etiqueta_global)
            etiquetas.append(global_box)
        tarjeta.append(etiquetas)

        if n_tareas == 0:
            detalle = _("Sin tareas asignadas")
        elif n_tareas == 1:
            detalle = _("1 tarea: {titulo}").format(titulo=titulos[0])
        else:
            detalle = _("{n} tareas: {lista}").format(
                n=n_tareas, lista=", ".join(titulos[:3]) + ("…" if n_tareas > 3 else "")
            )
        meta = Gtk.Label(label=detalle, xalign=0.5, halign=Gtk.Align.CENTER, wrap=True)
        meta.add_css_class("caption")
        meta.add_css_class("dim-label")
        tarjeta.append(meta)

        acciones = Gtk.Box(spacing=6, halign=Gtk.Align.CENTER, margin_top=4)
        edit_button = Gtk.Button(icon_name="document-edit-symbolic", tooltip_text=_("Editar recurso"))
        edit_button.add_css_class("flat")
        edit_button.connect("clicked", self._on_editar_clicked, recurso)
        acciones.append(edit_button)
        delete_button = Gtk.Button(icon_name="user-trash-symbolic", tooltip_text=_("Eliminar recurso"))
        delete_button.add_css_class("flat")
        delete_button.connect("clicked", self._on_delete, recurso)
        acciones.append(delete_button)
        tarjeta.append(acciones)

        return tarjeta

    # -- Avatar (color/imagen) ----------------------------------------------

    def _boton_avatar(self, recurso: Recurso) -> Gtk.MenuButton:
        boton = Gtk.MenuButton(tooltip_text=_("Cambiar avatar"))
        boton.add_css_class("flat")
        boton.add_css_class("gnomilestone-avatar-boton")
        avatar = AvatarWidget(recurso, size=56)
        boton.set_child(avatar)
        boton.avatar_widget = avatar
        boton.set_popover(self._popover_avatar(recurso, boton))
        return boton

    def _pintar_avatar(self, boton: Gtk.MenuButton, recurso: Recurso) -> None:
        avatar = getattr(boton, "avatar_widget", None)
        if isinstance(avatar, AvatarWidget):
            avatar.actualizar(recurso)
        else:
            nuevo = AvatarWidget(recurso, size=56)
            boton.set_child(nuevo)
            boton.avatar_widget = nuevo

    def _popover_avatar(self, recurso: Recurso, boton: Gtk.MenuButton) -> Gtk.Popover:
        popover = Gtk.Popover()
        caja = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=8,
            margin_top=10,
            margin_bottom=10,
            margin_start=10,
            margin_end=10,
        )
        caja.append(Gtk.Label(label=_("Color"), xalign=0))

        paleta = Gtk.Box(spacing=4)
        for color in PALETA_RECURSOS:
            swatch = Gtk.Button()
            swatch.add_css_class("gnomilestone-color-swatch")
            swatch.add_css_class("flat")
            css = Gtk.CssProvider()
            clase = f"swatch-{color.lstrip('#')}"
            swatch.add_css_class(clase)
            css.load_from_string(f".{clase} {{ background-color: {color}; }}")
            Gtk.StyleContext.add_provider_for_display(
                Gdk.Display.get_default(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
            )
            swatch.connect("clicked", self._on_color, recurso, color, boton, popover)
            paleta.append(swatch)
        caja.append(paleta)

        imagen_button = Gtk.Button(label=_("Elegir imagen…"))
        imagen_button.connect("clicked", self._on_elegir_imagen, recurso, boton, popover)
        caja.append(imagen_button)

        quitar = Gtk.Button(label=_("Quitar imagen"))
        quitar.set_sensitive(bool(recurso.avatar_url))
        quitar.connect("clicked", self._on_quitar_imagen, recurso, boton, popover)
        caja.append(quitar)

        nota = Gtk.Label(
            label=_("Al conectar GitHub se podrá usar el avatar de la cuenta."),
            wrap=True,
            xalign=0,
        )
        nota.add_css_class("caption")
        nota.add_css_class("dim-label")
        caja.append(nota)

        popover.set_child(caja)
        return popover

    def _ventana(self) -> Gtk.Window | None:
        raiz = self.get_root()
        return raiz if isinstance(raiz, Gtk.Window) else None

    def _on_color(
        self,
        _button: Gtk.Button,
        recurso: Recurso,
        color: str,
        avatar_button: Gtk.MenuButton,
        popover: Gtk.Popover,
    ) -> None:
        recurso.color_hex = color
        self._store.actualizar_recurso(recurso)
        self._pintar_avatar(avatar_button, recurso)
        popover.popdown()
        self._on_changed()

    def _on_elegir_imagen(
        self,
        _button: Gtk.Button,
        recurso: Recurso,
        avatar_button: Gtk.MenuButton,
        popover: Gtk.Popover,
    ) -> None:
        popover.popdown()
        dialog = Gtk.FileDialog(title=_("Elegir imagen de avatar"))
        filtros = Gio.ListStore.new(Gtk.FileFilter)
        filtro = Gtk.FileFilter(name=_("Imágenes"))
        filtro.add_pixbuf_formats()
        filtros.append(filtro)
        dialog.set_filters(filtros)
        dialog.open(self._ventana(), None, self._on_imagen_elegida, recurso, avatar_button)

    def _on_imagen_elegida(
        self,
        dialog: Gtk.FileDialog,
        result: Gio.AsyncResult,
        recurso: Recurso,
        avatar_button: Gtk.MenuButton,
    ) -> None:
        try:
            archivo = dialog.open_finish(result)
        except GLib.Error:
            return
        if archivo is None:
            return
        origen = archivo.get_path()
        if not origen:
            return
        try:
            destino = self._copiar_avatar(recurso.id, Path(origen))
        except OSError:
            log.exception("No se pudo guardar el avatar de recurso %s", recurso.id)
            return
        recurso.avatar_url = str(destino)
        self._store.actualizar_recurso(recurso)
        self._pintar_avatar(avatar_button, recurso)
        self.refrescar()
        self._on_changed()

    def _on_quitar_imagen(
        self,
        _button: Gtk.Button,
        recurso: Recurso,
        avatar_button: Gtk.MenuButton,
        popover: Gtk.Popover,
    ) -> None:
        anterior = recurso.avatar_url
        recurso.avatar_url = None
        self._store.actualizar_recurso(recurso)
        if anterior and _es_ruta_local(anterior):
            Path(anterior).unlink(missing_ok=True)
        self._pintar_avatar(avatar_button, recurso)
        popover.popdown()
        self.refrescar()
        self._on_changed()

    def _copiar_avatar(self, recurso_id: int, origen: Path) -> Path:
        _AVATARS_DIR.mkdir(parents=True, exist_ok=True)
        destino = _AVATARS_DIR / f"{recurso_id}{origen.suffix.lower() or '.png'}"
        shutil.copy2(origen, destino)
        return destino

    # -- Edición (nombre, email, categoría, alcance) ------------------------

    def _on_editar_clicked(self, _button: Gtk.Button, recurso: Recurso) -> None:
        dialog = Gtk.Window(
            title=_("Editar recurso"), transient_for=self._ventana(), modal=True, default_width=360
        )
        box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=10,
            margin_top=16,
            margin_bottom=16,
            margin_start=16,
            margin_end=16,
        )
        dialog.set_child(box)

        box.append(Gtk.Label(label=_("Nombre"), xalign=0))
        nombre_entry = Gtk.Entry(text=recurso.nombre)
        box.append(nombre_entry)

        box.append(Gtk.Label(label=_("Email"), xalign=0))
        email_entry = Gtk.Entry(text=recurso.email or "")
        box.append(email_entry)

        box.append(Gtk.Label(label=_("Categoría"), xalign=0))
        categoria_dropdown = Gtk.DropDown.new_from_strings(
            [etiqueta for _v, etiqueta, _i in _CATEGORIAS]
        )
        valores_categoria = [valor for valor, _e, _i in _CATEGORIAS]
        if recurso.categoria in valores_categoria:
            categoria_dropdown.set_selected(valores_categoria.index(recurso.categoria))
        box.append(categoria_dropdown)

        global_check = Gtk.CheckButton(
            label=_("Recurso global (disponible y asignable en todos los proyectos)")
        )
        global_check.set_active(recurso.es_global)
        box.append(global_check)

        error_label = Gtk.Label(xalign=0, wrap=True)
        error_label.add_css_class("error")
        box.append(error_label)

        acciones = Gtk.Box(spacing=8, halign=Gtk.Align.END, margin_top=8)
        cancelar = Gtk.Button(label=_("Cancelar"))
        cancelar.connect("clicked", lambda _b: dialog.close())
        acciones.append(cancelar)
        guardar = Gtk.Button(label=_("Guardar"))
        guardar.add_css_class("suggested-action")
        guardar.connect(
            "clicked",
            self._on_guardar_edicion,
            recurso,
            nombre_entry,
            email_entry,
            categoria_dropdown,
            valores_categoria,
            global_check,
            error_label,
            dialog,
        )
        acciones.append(guardar)
        box.append(acciones)

        dialog.present()

    def _on_guardar_edicion(
        self,
        _button: Gtk.Button,
        recurso: Recurso,
        nombre_entry: Gtk.Entry,
        email_entry: Gtk.Entry,
        categoria_dropdown: Gtk.DropDown,
        valores_categoria: list[str],
        global_check: Gtk.CheckButton,
        error_label: Gtk.Label,
        dialog: Gtk.Window,
    ) -> None:
        nombre = nombre_entry.get_text().strip()
        if not nombre:
            error_label.set_text(_("El nombre no puede estar vacío."))
            return
        recurso.nombre = nombre
        recurso.email = email_entry.get_text().strip() or None
        recurso.categoria = valores_categoria[categoria_dropdown.get_selected()]
        recurso.es_global = global_check.get_active()
        self._store.actualizar_recurso(recurso)
        dialog.close()
        self.refrescar()
        self._on_changed()

    # -- Alta rápida y baja --------------------------------------------------

    def _on_add_manual(self, _widget: Gtk.Widget) -> None:
        if self._proyecto_id is None:
            return
        nombre = self._name_entry.get_text().strip()
        if not nombre:
            return
        categoria = CATEGORIAS_RECURSO[self._categoria_dropdown.get_selected()]
        existente = self._store.obtener_recurso_por_nombre(self._proyecto_id, nombre)
        if existente is None:
            color = PALETA_RECURSOS[
                len(self._store.listar_recursos(self._proyecto_id)) % len(PALETA_RECURSOS)
            ]
            self._store.crear_recurso(
                self._proyecto_id,
                nombre.strip(),
                color_hex=color,
                categoria=categoria,
                es_global=self._global_check.get_active(),
            )
        self._name_entry.set_text("")
        self._global_check.set_active(False)
        self.refrescar()
        self._on_changed()

    def _on_delete(self, _button: Gtk.Button, recurso: Recurso) -> None:
        if recurso.avatar_url and _es_ruta_local(recurso.avatar_url):
            Path(recurso.avatar_url).unlink(missing_ok=True)
        self._store.eliminar_recurso(recurso.id)
        self.refrescar()
        self._on_changed()
