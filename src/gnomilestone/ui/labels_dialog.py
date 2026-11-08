from __future__ import annotations

from collections.abc import Callable

import gi

gi.require_version("Gdk", "4.0")
gi.require_version("Gtk", "4.0")
from gi.repository import Gdk, GLib, Gtk

from gnomilestone.etiquetas import color_automatico
from gnomilestone.i18n import _
from gnomilestone.models import Etiqueta
from gnomilestone.store import EtiquetaDuplicadaError, Store
from gnomilestone.sync import GitHubSyncManager


def _muestra(color: str) -> Gtk.Label:
    etiqueta = Gtk.Label(use_markup=True)
    etiqueta.set_markup(f'<span background="#{color}">      </span>')
    return etiqueta


def _rgba_de_hex(color: str) -> Gdk.RGBA:
    rgba = Gdk.RGBA()
    if not rgba.parse(f"#{color.lstrip('#')}"):
        rgba.parse("#6e7781")
    return rgba


def _hex_de_rgba(rgba: Gdk.RGBA) -> str:
    return "".join(f"{round(c * 255):02x}" for c in (rgba.red, rgba.green, rgba.blue))


class _SelectorColor(Gtk.MenuButton):
    """Botón con la muestra del color; al pulsarlo se despliega el selector de color de GTK
    (paleta y editor «+» de colores personalizados) y se elige con «Aplicar».

    El selector va incrustado en un popover, no en el diálogo asíncrono de
    `Gtk.ColorDialogButton`, que provocó un cierre brusco al reconstruir la lista."""

    def __init__(self, color: str, on_elegido: Callable[[str], None]) -> None:
        super().__init__(tooltip_text=_("Color de la etiqueta"))
        self._on_elegido = on_elegido
        self._color = color
        self.set_child(_muestra(color))

        popover = Gtk.Popover()
        caja = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=8,
            margin_top=10,
            margin_bottom=10,
            margin_start=10,
            margin_end=10,
        )
        self._selector = Gtk.ColorChooserWidget(use_alpha=False, show_editor=False)
        self._selector.set_rgba(_rgba_de_hex(color))
        # Doble clic o Enter sobre un color: se aplica sin pulsar el botón.
        self._selector.connect("color-activated", lambda _s, rgba: self._elegir(rgba))
        caja.append(self._selector)
        aplicar = Gtk.Button(label=_("Aplicar"), halign=Gtk.Align.END)
        aplicar.add_css_class("suggested-action")
        aplicar.connect("clicked", lambda _b: self._elegir(self._selector.get_rgba()))
        caja.append(aplicar)
        popover.set_child(caja)
        self._popover = popover
        self.set_popover(popover)

    def _elegir(self, rgba: Gdk.RGBA) -> None:
        valor = _hex_de_rgba(rgba)
        self._popover.popdown()
        if valor == self._color:
            return
        self._color = valor
        self.set_child(_muestra(valor))
        self._on_elegido(valor)


class LabelsDialog(Gtk.Window):
    """Gestión de las etiquetas de un proyecto: alta, renombrado, color y borrado.

    Si el proyecto está vinculado con un repositorio de GitHub, renombrar, cambiar el color
    o borrar se aplica también allí (afecta a todos los issues que la lleven)."""

    def __init__(
        self, parent: Gtk.Window, store: Store, proyecto_id: int, on_changed: Callable[[], None]
    ) -> None:
        super().__init__(
            title=_("Etiquetas del proyecto"),
            transient_for=parent,
            modal=True,
            default_width=460,
            default_height=480,
        )
        self._store = store
        self._proyecto_id = proyecto_id
        self._on_changed = on_changed
        self._sync = GitHubSyncManager(store)

        raiz = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=10,
            margin_top=16,
            margin_bottom=16,
            margin_start=16,
            margin_end=16,
        )
        self.set_child(raiz)

        self._lista = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self._lista.add_css_class("boxed-list")
        scroller = Gtk.ScrolledWindow(vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
        scroller.set_child(self._lista)
        raiz.append(scroller)

        self._error = Gtk.Label(xalign=0, wrap=True, visible=False)
        self._error.add_css_class("error")
        raiz.append(self._error)

        alta = Gtk.Box(spacing=6)
        self._nueva_entry = Gtk.Entry(placeholder_text=_("Nueva etiqueta"), hexpand=True)
        self._nueva_entry.connect("activate", self._on_anadir)
        alta.append(self._nueva_entry)
        anadir = Gtk.Button(icon_name="list-add-symbolic", tooltip_text=_("Añadir etiqueta"))
        anadir.connect("clicked", self._on_anadir)
        alta.append(anadir)
        raiz.append(alta)

        self._refrescar()

    def _refrescar(self) -> None:
        self._lista.remove_all()
        etiquetas = self._store.listar_etiquetas(self._proyecto_id)
        usos = self._store.contar_tareas_por_etiqueta(self._proyecto_id)
        if not etiquetas:
            vacio = Gtk.Label(label=_("Este proyecto aún no tiene etiquetas."), margin_top=12,
                              margin_bottom=12)
            vacio.add_css_class("dim-label")
            self._lista.append(vacio)
            return
        for etiqueta in etiquetas:
            fila = Gtk.Box(spacing=8, margin_top=6, margin_bottom=6, margin_start=8, margin_end=8)
            fila.append(
                _SelectorColor(etiqueta.color, lambda c, e=etiqueta: self._on_color(c, e))
            )

            entrada = Gtk.Entry(text=etiqueta.nombre, hexpand=True)
            entrada.connect("activate", self._on_renombrar, etiqueta)
            foco = Gtk.EventControllerFocus()
            foco.connect("leave", lambda _c, e=entrada, t=etiqueta: self._on_renombrar(e, t))
            entrada.add_controller(foco)
            fila.append(entrada)

            n = usos.get(etiqueta.id, 0)
            cuenta = Gtk.Label(label=_("{n} tareas").format(n=n) if n != 1 else _("1 tarea"))
            cuenta.add_css_class("dim-label")
            cuenta.add_css_class("caption")
            fila.append(cuenta)

            borrar = Gtk.Button(icon_name="user-trash-symbolic", tooltip_text=_("Eliminar etiqueta"))
            borrar.add_css_class("flat")
            borrar.add_css_class("circular")
            borrar.connect("clicked", self._on_eliminar, etiqueta, n)
            fila.append(borrar)
            self._lista.append(fila)

    def _mostrar_error(self, mensaje: str | None) -> None:
        self._error.set_visible(bool(mensaje))
        self._error.set_text(mensaje or "")

    def _on_anadir(self, _widget: Gtk.Widget) -> None:
        nombre = self._nueva_entry.get_text().strip()
        if not nombre:
            return
        self._mostrar_error(None)
        self._store.asegurar_etiqueta(self._proyecto_id, nombre, color_automatico(nombre))
        self._nueva_entry.set_text("")
        self._refrescar()
        self._on_changed()

    def _on_renombrar(self, entrada: Gtk.Entry, etiqueta: Etiqueta) -> None:
        nombre = entrada.get_text().strip()
        if not nombre:
            entrada.set_text(etiqueta.nombre)
            return
        if nombre == etiqueta.nombre:
            return
        try:
            self._sync.renombrar_etiqueta(etiqueta.id, nombre)
        except EtiquetaDuplicadaError:
            self._mostrar_error(_("Ya existe otra etiqueta con ese nombre."))
            entrada.set_text(etiqueta.nombre)
            return
        self._mostrar_error(None)
        # Se reconstruye la lista fuera de este manejador: puede ser el de «perder el foco»
        # de una entrada que la propia reconstrucción destruye.
        GLib.idle_add(self._refrescar_y_avisar)

    def _refrescar_y_avisar(self) -> bool:
        self._refrescar()
        self._on_changed()
        return GLib.SOURCE_REMOVE

    def _on_color(self, color: str, etiqueta: Etiqueta) -> None:
        self._sync.cambiar_color_etiqueta(etiqueta.id, color)
        self._on_changed()

    def _on_eliminar(self, _boton: Gtk.Button, etiqueta: Etiqueta, usos: int) -> None:
        dialogo = Gtk.AlertDialog()
        dialogo.set_message(_("Eliminar etiqueta"))
        dialogo.set_detail(
            _(
                "¿Seguro que quieres eliminar «{nombre}»? Se quitará de las tareas que la "
                "llevan ({n}) y, si el proyecto está vinculado con GitHub, también del "
                "repositorio, de todos sus issues. No se puede deshacer."
            ).format(nombre=etiqueta.nombre, n=usos)
        )
        dialogo.set_buttons([_("Cancelar"), _("Eliminar")])
        dialogo.set_cancel_button(0)
        dialogo.set_default_button(0)
        dialogo.choose(self, None, self._on_eliminar_respuesta, etiqueta)

    def _on_eliminar_respuesta(self, dialogo: Gtk.AlertDialog, resultado, etiqueta: Etiqueta) -> None:
        try:
            eleccion = dialogo.choose_finish(resultado)
        except GLib.Error:
            return
        if eleccion == 1:
            self._sync.eliminar_etiqueta(etiqueta.id)
            self._refrescar()
            self._on_changed()
