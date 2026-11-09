from __future__ import annotations

from collections.abc import Callable

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk

from gnomilestone.i18n import _


def pedir_texto(
    parent: Gtk.Window | None,
    titulo: str,
    valor: str,
    al_aceptar: Callable[[str], None],
    extra: Gtk.Widget | None = None,
    permitir_vacio: bool = False,
) -> None:
    """Ventana modal con una línea de texto (y, opcionalmente, un widget extra debajo)."""
    ventana = Gtk.Window(title=titulo, transient_for=parent, modal=True, default_width=340)
    caja = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
    for margen in ("top", "bottom", "start", "end"):
        getattr(caja, f"set_margin_{margen}")(18)
    ventana.set_child(caja)
    entrada = Gtk.Entry(text=valor, activates_default=True)
    caja.append(entrada)
    if extra is not None:
        caja.append(extra)
    botones = Gtk.Box(spacing=8, halign=Gtk.Align.END)
    cancelar = Gtk.Button(label=_("Cancelar"))
    aceptar = Gtk.Button(label=_("Aceptar"))
    aceptar.add_css_class("suggested-action")
    botones.append(cancelar)
    botones.append(aceptar)
    caja.append(botones)
    ventana.set_default_widget(aceptar)

    def confirmar(_b: Gtk.Widget) -> None:
        texto = entrada.get_text().strip()
        if not texto and not permitir_vacio:
            return
        ventana.close()
        al_aceptar(texto)

    cancelar.connect("clicked", lambda _b: ventana.close())
    aceptar.connect("clicked", confirmar)
    entrada.connect("activate", confirmar)
    ventana.present()
    entrada.grab_focus()


def boton_con_icono(texto: str, icono: str, **propiedades) -> Gtk.Button:
    """Botón con icono y texto. (`Gtk.Button(label=…, icon_name=…)` solo muestra el icono.)"""
    contenido = Gtk.Box(spacing=6)
    contenido.append(Gtk.Image.new_from_icon_name(icono))
    contenido.append(Gtk.Label(label=texto))
    return Gtk.Button(child=contenido, **propiedades)


def dato_con_icono(
    icono: str, texto: str, tooltip: str | None = None, pequeno: bool = True, **propiedades
) -> Gtk.Box:
    """Dato corto con un icono simbólico delante (fecha, versión…), en tono atenuado."""
    caja = Gtk.Box(spacing=5, tooltip_text=tooltip, **propiedades)
    imagen = Gtk.Image.new_from_icon_name(icono)
    imagen.set_pixel_size(14)
    imagen.add_css_class("dim-label")
    etiqueta = Gtk.Label(label=texto, xalign=0)
    if pequeno:
        etiqueta.add_css_class("caption")
    caja.append(imagen)
    caja.append(etiqueta)
    return caja
