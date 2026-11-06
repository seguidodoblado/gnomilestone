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
from gnomilestone.models import Recurso
from gnomilestone.store import DATA_DIR, PALETA_RECURSOS, Store
from gnomilestone.ui.avatar_widget import AvatarWidget

log = logging.getLogger(__name__)

_AVATARS_DIR = DATA_DIR / "avatars"
_css_swatch_aplicado = False


def _asegurar_css_swatch() -> None:
    global _css_swatch_aplicado
    if _css_swatch_aplicado:
        return
    proveedor = Gtk.CssProvider()
    proveedor.load_from_string(
        ".gnomilestone-color-swatch { "
        "min-width: 24px; min-height: 24px; border-radius: 9999px; padding: 0; }\n"
        ".gnomilestone-avatar-boton { padding: 0; min-width: 0; min-height: 0; }\n"
    )
    Gtk.StyleContext.add_provider_for_display(
        Gdk.Display.get_default(), proveedor, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
    )
    _css_swatch_aplicado = True


def _es_ruta_local(avatar_url: str) -> bool:
    return not avatar_url.startswith(("http://", "https://"))


class ResourceView(Gtk.Box):
    """Vista de personas del proyecto (rail Recursos): carga, avatar editable y alta manual
    secundaria. El alta normal sigue siendo asignar desde una tarea."""

    def __init__(self, store: Store, on_changed: Callable[[], None]) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.set_margin_top(16)
        self.set_margin_bottom(16)
        self.set_margin_start(16)
        self.set_margin_end(16)
        _asegurar_css_swatch()
        self._store = store
        self._proyecto_id: int | None = None
        self._on_changed = on_changed

        intro = Gtk.Label(
            label=_(
                "Las personas se añaden al asignarlas en una tarea. "
                "Pulsa el avatar para cambiar el color o la imagen "
                "(más adelante se podrá tomar del usuario de GitHub)."
            ),
            xalign=0,
            wrap=True,
        )
        intro.add_css_class("dim-label")
        self.append(intro)

        scroller = Gtk.ScrolledWindow(vexpand=True, hexpand=True)
        self._list_box = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self._list_box.add_css_class("boxed-list")
        scroller.set_child(self._list_box)
        self.append(scroller)

        self._vacio = Gtk.Label(
            label=_("Aún no hay recursos. Asígalos al crear o editar una tarea."),
            wrap=True,
            xalign=0,
        )
        self._vacio.add_css_class("dim-label")
        self.append(self._vacio)

        manual = Gtk.Expander(label=_("Añadir manualmente"))
        manual_box = Gtk.Box(spacing=6, margin_top=6)
        self._name_entry = Gtk.Entry(placeholder_text=_("Nombre"), hexpand=True)
        self._name_entry.connect("activate", self._on_add_manual)
        manual_box.append(self._name_entry)
        add_button = Gtk.Button(icon_name="list-add-symbolic", tooltip_text=_("Añadir"))
        add_button.connect("clicked", self._on_add_manual)
        manual_box.append(add_button)
        manual.set_child(manual_box)
        self.append(manual)

    def mostrar_proyecto(self, proyecto_id: int) -> None:
        self._proyecto_id = proyecto_id
        self.refrescar()

    def refrescar(self) -> None:
        self._list_box.remove_all()
        if self._proyecto_id is None:
            self._vacio.set_visible(True)
            self._list_box.set_visible(False)
            return
        recursos = self._store.listar_recursos(self._proyecto_id)
        self._vacio.set_visible(not recursos)
        self._list_box.set_visible(bool(recursos))
        for recurso in recursos:
            self._list_box.append(self._fila_recurso(recurso))

    def _fila_recurso(self, recurso: Recurso) -> Gtk.ListBoxRow:
        n_tareas = self._store.contar_asignaciones_recurso(recurso.id)
        titulos = self._store.listar_titulos_asignados(recurso.id)

        row = Gtk.ListBoxRow(activatable=False)
        fila = Gtk.Box(spacing=10, margin_top=8, margin_bottom=8, margin_start=8, margin_end=8)

        fila.append(self._boton_avatar(recurso))

        textos = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, hexpand=True)
        textos.append(Gtk.Label(label=recurso.nombre, xalign=0))
        if recurso.email:
            email = Gtk.Label(label=recurso.email, xalign=0)
            email.add_css_class("caption")
            email.add_css_class("dim-label")
            textos.append(email)
        if n_tareas == 0:
            detalle = _("Sin tareas asignadas")
        elif n_tareas == 1:
            detalle = _("1 tarea: {titulo}").format(titulo=titulos[0])
        else:
            detalle = _("{n} tareas: {lista}").format(
                n=n_tareas, lista=", ".join(titulos[:3]) + ("…" if n_tareas > 3 else "")
            )
        meta = Gtk.Label(label=detalle, xalign=0, wrap=True)
        meta.add_css_class("caption")
        meta.add_css_class("dim-label")
        textos.append(meta)
        fila.append(textos)

        delete_button = Gtk.Button(
            icon_name="user-trash-symbolic", tooltip_text=_("Eliminar recurso")
        )
        delete_button.add_css_class("flat")
        delete_button.connect("clicked", self._on_delete, recurso)
        fila.append(delete_button)

        row.set_child(fila)
        return row

    def _boton_avatar(self, recurso: Recurso) -> Gtk.MenuButton:
        boton = Gtk.MenuButton(tooltip_text=_("Cambiar avatar"))
        boton.add_css_class("flat")
        boton.add_css_class("gnomilestone-avatar-boton")
        avatar = AvatarWidget(recurso, size=32)
        boton.set_child(avatar)
        boton.avatar_widget = avatar
        boton.set_popover(self._popover_avatar(recurso, boton))
        return boton

    def _pintar_avatar(self, boton: Gtk.MenuButton, recurso: Recurso) -> None:
        avatar = getattr(boton, "avatar_widget", None)
        if isinstance(avatar, AvatarWidget):
            avatar.actualizar(recurso)
        else:
            nuevo = AvatarWidget(recurso, size=32)
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

    def _on_add_manual(self, _widget: Gtk.Widget) -> None:
        if self._proyecto_id is None:
            return
        nombre = self._name_entry.get_text().strip()
        if not nombre:
            return
        self._store.asegurar_recurso(self._proyecto_id, nombre)
        self._name_entry.set_text("")
        self.refrescar()
        self._on_changed()

    def _on_delete(self, _button: Gtk.Button, recurso: Recurso) -> None:
        if recurso.avatar_url and _es_ruta_local(recurso.avatar_url):
            Path(recurso.avatar_url).unlink(missing_ok=True)
        self._store.eliminar_recurso(recurso.id)
        self.refrescar()
        self._on_changed()
