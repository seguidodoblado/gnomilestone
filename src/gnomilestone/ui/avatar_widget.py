from __future__ import annotations

import functools
import math
from pathlib import Path

import cairo
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, GdkPixbuf, GLib, Gtk, Pango, PangoCairo

from gnomilestone.models import Recurso

_COLOR_RESPALDO = (0.47, 0.46, 0.48)


def _hex_a_rgb(color_hex: str | None) -> tuple[float, float, float]:
    if not color_hex:
        return _COLOR_RESPALDO
    texto = color_hex.lstrip("#")
    if len(texto) != 6:
        return _COLOR_RESPALDO
    try:
        return (
            int(texto[0:2], 16) / 255.0,
            int(texto[2:4], 16) / 255.0,
            int(texto[4:6], 16) / 255.0,
        )
    except ValueError:
        return _COLOR_RESPALDO


def _inicial(nombre: str) -> str:
    partes = nombre.strip().split()
    if not partes:
        return "?"
    if len(partes) == 1:
        return partes[0][:1].upper()
    return (partes[0][:1] + partes[-1][:1]).upper()


@functools.lru_cache(maxsize=128)
def _cargar_escalado(ruta: str, size: int, _modificado: int) -> GdkPixbuf.Pixbuf | None:
    """Imagen escalada, con caché: cada refresco de un proyecto recrea todos los avatares y
    decodificar la misma imagen costaba ~15 ms por avatar. `_modificado` (la fecha del
    fichero) solo sirve para invalidar la caché cuando la imagen cambia."""
    try:
        return GdkPixbuf.Pixbuf.new_from_file_at_scale(ruta, size, size, True)
    except GLib.Error:
        return None


def _pixbuf_local(avatar_url: str | None, size: int) -> GdkPixbuf.Pixbuf | None:
    if not avatar_url or avatar_url.startswith(("http://", "https://")):
        return None
    ruta = Path(avatar_url)
    try:
        modificado = ruta.stat().st_mtime_ns
    except OSError:
        return None
    return _cargar_escalado(str(ruta), size, modificado) if ruta.is_file() else None


class AvatarWidget(Gtk.DrawingArea):
    """Avatar circular: imagen local o iniciales sobre el color del recurso."""

    def __init__(self, recurso: Recurso, size: int = 28) -> None:
        super().__init__()
        self._size = size
        self._recurso = recurso
        self._pixbuf: GdkPixbuf.Pixbuf | None = None
        # Cuadrado fijo: si la celda asigna width≠height, no deformamos el círculo.
        self.set_content_width(size)
        self.set_content_height(size)
        self.set_size_request(size, size)
        self.set_hexpand(False)
        self.set_vexpand(False)
        self.set_halign(Gtk.Align.CENTER)
        self.set_valign(Gtk.Align.CENTER)
        self.set_draw_func(self._dibujar)
        self.set_tooltip_text(recurso.nombre)
        self._cargar_pixbuf()

    def actualizar(self, recurso: Recurso) -> None:
        self._recurso = recurso
        self.set_tooltip_text(recurso.nombre)
        self._cargar_pixbuf()
        self.queue_draw()

    def _cargar_pixbuf(self) -> None:
        self._pixbuf = _pixbuf_local(self._recurso.avatar_url, self._size * 2)

    def _dibujar(
        self, _area: Gtk.DrawingArea, cr: cairo.Context, width: int, height: int
    ) -> None:
        lado = min(width, height)
        cx, cy = width / 2.0, height / 2.0
        radio = lado / 2.0
        cr.arc(cx, cy, radio, 0, 2 * math.pi)
        cr.clip()

        if self._pixbuf is not None:
            # object-fit: cover — una sola escala, centrado; el clip circular recorta el sobrante.
            pw = self._pixbuf.get_width()
            ph = self._pixbuf.get_height()
            escala = max(lado / pw, lado / ph)
            dw, dh = pw * escala, ph * escala
            cr.save()
            cr.translate(cx - dw / 2.0, cy - dh / 2.0)
            cr.scale(escala, escala)
            Gdk.cairo_set_source_pixbuf(cr, self._pixbuf, 0, 0)
            cr.paint()
            cr.restore()
            return

        r, g, b = _hex_a_rgb(self._recurso.color_hex)
        cr.set_source_rgb(r, g, b)
        cr.paint()

        layout = PangoCairo.create_layout(cr)
        layout.set_text(_inicial(self._recurso.nombre), -1)
        desc = Pango.FontDescription.from_string(f"Sans Bold {max(8, self._size // 2)}")
        layout.set_font_description(desc)
        texto_w, texto_h = layout.get_pixel_size()
        cr.set_source_rgb(1, 1, 1)
        cr.move_to(cx - texto_w / 2, cy - texto_h / 2)
        PangoCairo.show_layout(cr, layout)


def fila_avatares(
    recursos: list[Recurso], size: int = 22, maximo: int = 3, height_request: int | None = None
) -> Gtk.Widget:
    """Fila compacta de avatares (con «+N» si hay más de `maximo`)."""
    caja = Gtk.Box(spacing=2, valign=Gtk.Align.CENTER)
    if height_request is not None:
        caja.set_size_request(-1, height_request)
    if not recursos:
        vacio = Gtk.Label(label="—", xalign=0)
        vacio.add_css_class("dim-label")
        caja.append(vacio)
        return caja
    for recurso in recursos[:maximo]:
        caja.append(AvatarWidget(recurso, size=size))
    resto = len(recursos) - maximo
    if resto > 0:
        mas = Gtk.Label(label=f"+{resto}")
        mas.add_css_class("caption")
        mas.add_css_class("dim-label")
        caja.append(mas)
    return caja
