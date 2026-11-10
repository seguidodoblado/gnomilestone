"""Fila de imágenes remotas de una nota (badges, logotipo), cargadas en segundo plano.

Mientras llega cada imagen se muestra su texto alternativo; si no llega (sin red, formato
raro) se queda ese texto. Los SVG se rasterizan al doble de tamaño para verse nítidos en
pantallas de alta densidad.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

import gi

gi.require_version("Gdk", "4.0")
gi.require_version("GdkPixbuf", "2.0")
gi.require_version("Graphene", "1.0")
gi.require_version("Gsk", "4.0")
gi.require_version("Gtk", "4.0")
from gi.repository import Gdk, GdkPixbuf, Gio, GLib, Graphene, Gsk, Gtk

from gnomilestone import imagenes_remotas, settings
from gnomilestone.markdown_imagenes import Imagen

log = logging.getLogger(__name__)

ANCHO_MAXIMO = 760
ALTO_COMPACTO = 24  # en las tarjetas las imágenes se reducen a este alto
LADO_MAXIMO_PIXELES = 4000  # una imagen mayor se descarta: no merece la memoria

_hilos = ThreadPoolExecutor(max_workers=4, thread_name_prefix="gnomilestone-img")
# Imágenes ya decodificadas por dirección: al alternar editar/vista previa no se repite.
_decodificadas: dict[str, tuple[GdkPixbuf.Pixbuf, int, int]] = {}


def _decodificar(url: str) -> tuple[GdkPixbuf.Pixbuf, int, int] | None:
    """Descarga (o toma de la caché) y decodifica; se ejecuta en un hilo."""
    datos = imagenes_remotas.obtener(url)
    if not datos:
        return None
    try:
        origen = GLib.Bytes.new(datos)
        pixbuf = GdkPixbuf.Pixbuf.new_from_stream(Gio.MemoryInputStream.new_from_bytes(origen), None)
        ancho, alto = pixbuf.get_width(), pixbuf.get_height()
        if not (0 < ancho <= LADO_MAXIMO_PIXELES and 0 < alto <= LADO_MAXIMO_PIXELES):
            return None
        if b"<svg" in datos[:1024].lower():
            pixbuf = GdkPixbuf.Pixbuf.new_from_stream_at_scale(
                Gio.MemoryInputStream.new_from_bytes(origen), ancho * 2, alto * 2, True, None
            )
        return pixbuf, ancho, alto
    except Exception as e:  # noqa: BLE001 - un formato no soportado no debe romper la nota
        log.debug("No se pudo decodificar la imagen %s: %s", url, e)
        return None


def imagenes_habilitadas() -> bool:
    """Ajuste oculto `imagenes_remotas` (por defecto activo) para quien no quiera que las
    notas hagan peticiones de red al abrirse."""
    return bool(settings.read_settings().get("imagenes_remotas", True))


ESPACIO = 6  # hueco entre imágenes y entre líneas


class _Ajuste(Gtk.LayoutManager):
    """Coloca los hijos de izquierda a derecha y pasa a otra línea cuando no caben."""

    def do_get_request_mode(self, _widget):
        return Gtk.SizeRequestMode.HEIGHT_FOR_WIDTH

    @staticmethod
    def _hijos(widget):
        hijo = widget.get_first_child()
        while hijo is not None:
            if hijo.should_layout():
                yield hijo
            hijo = hijo.get_next_sibling()

    @staticmethod
    def _tamanos(widget):
        """(ancho, alto) natural de cada hijo."""
        resultado = []
        for hijo in _Ajuste._hijos(widget):
            ancho = hijo.measure(Gtk.Orientation.HORIZONTAL, -1)[1]
            alto = hijo.measure(Gtk.Orientation.VERTICAL, ancho)[1]
            resultado.append((hijo, ancho, alto))
        return resultado

    @staticmethod
    def _lineas(tamanos, ancho_disponible):
        """Reparte los hijos en líneas: lista de [(hijo, ancho, alto), …]."""
        lineas: list[list] = [[]]
        x = 0
        for elemento in tamanos:
            ancho = elemento[1]
            if lineas[-1] and x + ancho > ancho_disponible:
                lineas.append([])
                x = 0
            lineas[-1].append(elemento)
            x += ancho + ESPACIO
        return [linea for linea in lineas if linea]

    @staticmethod
    def _alto_de(linea) -> int:
        return max(alto for _h, _a, alto in linea)

    def do_measure(self, widget, orientacion, para_tamano):
        tamanos = self._tamanos(widget)
        if not tamanos:
            return 0, 0, -1, -1
        if orientacion == Gtk.Orientation.HORIZONTAL:
            minimo = max(ancho for _h, ancho, _a in tamanos)
            natural = sum(ancho for _h, ancho, _a in tamanos) + ESPACIO * (len(tamanos) - 1)
            return minimo, natural, -1, -1
        ancho = para_tamano if para_tamano >= 0 else 10**6
        lineas = self._lineas(tamanos, ancho)
        alto = sum(self._alto_de(linea) for linea in lineas) + ESPACIO * (len(lineas) - 1)
        return alto, alto, -1, -1

    def do_allocate(self, widget, ancho, _alto, baseline):
        y = 0
        for linea in self._lineas(self._tamanos(widget), ancho):
            x = 0
            alto_linea = self._alto_de(linea)
            for hijo, ancho_hijo, alto_hijo in linea:
                posicion = Gsk.Transform().translate(Graphene.Point().init(x, y + (alto_linea - alto_hijo) // 2))
                hijo.allocate(ancho_hijo, alto_hijo, -1, posicion)
                x += ancho_hijo + ESPACIO
            y += alto_linea + ESPACIO


class FilaImagenes(Gtk.Box):
    """Imágenes (badges, logotipo) que se ajustan a líneas como palabras."""

    def __init__(
        self,
        imagenes: list[Imagen],
        al_enlace: Callable[[str], bool] | None = None,
        compacto: bool = False,
    ) -> None:
        super().__init__(hexpand=True)
        self.set_layout_manager(_Ajuste())
        self._al_enlace = al_enlace
        self._compacto = compacto
        for imagen in imagenes:
            self.append(self._hueco(imagen))

    def _hueco(self, imagen: Imagen) -> Gtk.Widget:
        hueco = Gtk.Box(valign=Gtk.Align.CENTER)
        etiqueta = Gtk.Label(label=imagen.alt, xalign=0)
        etiqueta.add_css_class("dim-label")
        etiqueta.add_css_class("caption")
        hueco.append(etiqueta)
        if imagen.enlace and not self._compacto:  # en una tarjeta el clic es de la tarjeta
            hueco.set_cursor_from_name("pointer")
            hueco.set_tooltip_text(imagen.enlace)
            gesto = Gtk.GestureClick()
            gesto.connect("released", lambda *_a, url=imagen.enlace: self._abrir(url))
            hueco.add_controller(gesto)
        if not imagenes_habilitadas() or not imagenes_remotas.es_descargable(imagen.src):
            return hueco
        if (en_memoria := _decodificadas.get(imagen.src)) is not None:
            self._poner(hueco, etiqueta, *en_memoria)
            return hueco

        def terminado(futuro) -> None:
            try:
                resultado = futuro.result()
            except Exception:  # noqa: BLE001
                return
            if resultado is not None:
                GLib.idle_add(self._llego, hueco, etiqueta, imagen.src, resultado)

        _hilos.submit(_decodificar, imagen.src).add_done_callback(terminado)
        return hueco

    def _llego(self, hueco, etiqueta, src, resultado) -> bool:
        # Referencia fuerte a propósito: una débil se pierde, porque PyGObject libera el
        # envoltorio de Python de un widget aunque GTK lo siga teniendo.
        if hueco.get_root() is None:  # la nota ya se cerró o se rehízo
            return False
        _decodificadas[src] = resultado
        self._poner(hueco, etiqueta, *resultado)
        return False

    def _poner(self, hueco: Gtk.Box, etiqueta: Gtk.Label, pixbuf: GdkPixbuf.Pixbuf, ancho: int, alto: int) -> None:
        if self._compacto and alto > ALTO_COMPACTO:
            ancho, alto = max(1, round(ancho * ALTO_COMPACTO / alto)), ALTO_COMPACTO
        if ancho > ANCHO_MAXIMO:
            alto, ancho = round(alto * ANCHO_MAXIMO / ancho), ANCHO_MAXIMO
        # Un DrawingArea de tamaño exacto: una Gtk.Picture pediría el tamaño de su textura
        # (el doble en los SVG rasterizados a 2x) y el texto desbordaría las imágenes.
        area = Gtk.DrawingArea(content_width=ancho, content_height=alto)
        area.set_draw_func(lambda _a, cr, w, h: self._dibujar(cr, w, h, pixbuf))
        hueco.remove(etiqueta)
        hueco.append(area)

    @staticmethod
    def _dibujar(cr, ancho: int, alto: int, pixbuf: GdkPixbuf.Pixbuf) -> None:
        cr.scale(ancho / pixbuf.get_width(), alto / pixbuf.get_height())
        Gdk.cairo_set_source_pixbuf(cr, pixbuf, 0, 0)
        cr.paint()

    def _abrir(self, url: str) -> None:
        if self._al_enlace is not None and self._al_enlace(url):
            return
        Gtk.UriLauncher.new(url).launch(self.get_root(), None, lambda *_args: None)
