"""Separa de un texto Markdown los párrafos formados solo por imágenes (la fila de badges de
un README, su logotipo) para dibujarlos como imágenes; el resto sigue siendo texto.

Sin GTK. Una imagen mezclada con texto no se separa: el visor de texto muestra su alt.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_TITULO = r'(?:\s+"[^"]*")?'
# `[![alt](src)](href)` (imagen con enlace) o `![alt](src)` (imagen suelta).
_IMAGEN = re.compile(
    rf"\[!\[([^\]]*)\]\(([^)\s]+){_TITULO}\)\]\(([^)\s]+){_TITULO}\)"
    rf"|!\[([^\]]*)\]\(([^)\s]+){_TITULO}\)"
)
_PARRAFOS = re.compile(r"\n[ \t]*\n")


@dataclass(frozen=True)
class Imagen:
    alt: str
    src: str
    enlace: str | None = None


@dataclass(frozen=True)
class SegmentoTexto:
    markdown: str


@dataclass(frozen=True)
class SegmentoImagenes:
    imagenes: list[Imagen]


def _imagenes_de(parrafo: str) -> list[Imagen] | None:
    """Las imágenes del párrafo si no contiene nada más que imágenes; si no, None."""
    encontradas: list[Imagen] = []
    posicion = 0
    for m in _IMAGEN.finditer(parrafo):
        if parrafo[posicion:m.start()].strip():
            return None
        if m.group(2) is not None:
            encontradas.append(Imagen(m.group(1), m.group(2), m.group(3)))
        else:
            encontradas.append(Imagen(m.group(4), m.group(5)))
        posicion = m.end()
    if parrafo[posicion:].strip() or not encontradas:
        return None
    return encontradas


def segmentar(markdown: str) -> list[SegmentoTexto | SegmentoImagenes]:
    """Divide el texto en segmentos de texto y de filas de imágenes, en su orden."""
    segmentos: list[SegmentoTexto | SegmentoImagenes] = []
    texto: list[str] = []

    def vaciar() -> None:
        if texto:
            segmentos.append(SegmentoTexto("\n\n".join(texto)))
            texto.clear()

    for parrafo in _PARRAFOS.split(markdown):
        imagenes = _imagenes_de(parrafo)
        if imagenes is None:
            if parrafo.strip():
                texto.append(parrafo)
        else:
            vaciar()
            segmentos.append(SegmentoImagenes(imagenes))
    vaciar()
    return segmentos
