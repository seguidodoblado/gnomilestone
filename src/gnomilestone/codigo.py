"""Bloques de código de las notas (sin GTK): troceo del Markdown y coloreado de sintaxis.

El coloreado usa Pygments si está instalado; si no, el código se muestra sin colores.
"""

from __future__ import annotations

import functools
import re
from dataclasses import dataclass

try:
    from pygments.lexers import get_lexer_by_name
    from pygments.token import Token
    from pygments.util import ClassNotFound
except ImportError:  # sin Pygments: bloques de código sin colorear
    get_lexer_by_name = None

_SEPARADOR = re.compile(r"^\s*([-*_])(\s*\1){2,}\s*$")
_VALLA = re.compile(r"^(\s*)(`{3,})(.*)$")
_TITULO = re.compile(r'^(?:title\s*=\s*)?(?:"([^"]*)"|\'([^\']*)\'|(.+))$')


@dataclass(frozen=True)
class Texto:
    markdown: str


@dataclass(frozen=True)
class Separador:
    """Línea horizontal (`---`): se dibuja como un separador que ocupa todo el ancho."""


@dataclass(frozen=True)
class Codigo:
    lenguaje: str  # tal como se escribió tras las comillas (p. ej. «python»); "" si no hay
    titulo: str  # leyenda opcional del bloque
    codigo: str


def _info(resto: str) -> tuple[str, str]:
    """Lenguaje y título de la línea de apertura: `python`, `python "Título"`,
    `python title="Título"` o `python Título libre`."""
    partes = resto.strip().split(None, 1)
    if not partes:
        return "", ""
    lenguaje = partes[0].lower()
    if len(partes) == 1:
        return lenguaje, ""
    m = _TITULO.match(partes[1].strip())
    titulo = next((g for g in m.groups() if g), "") if m else ""
    return lenguaje, titulo.strip()


def dividir_bloques(markdown: str) -> list[Texto | Codigo | Separador]:
    """Separa el Markdown en tramos de texto, líneas horizontales (`---`) y bloques de
    código delimitados por ```. Un bloque sin cerrar llega hasta el final."""
    bloques: list[Texto | Codigo | Separador] = []
    texto: list[str] = []
    codigo: list[str] = []
    apertura: tuple[int, str] | None = None  # (nº de comillas, info) del bloque abierto

    def volcar_texto() -> None:
        tramo: list[str] = []

        def cerrar_tramo() -> None:
            contenido = "\n".join(tramo).strip("\n")
            if contenido.strip():
                bloques.append(Texto(contenido))
            tramo.clear()

        for linea in texto:
            if _SEPARADOR.match(linea):
                cerrar_tramo()
                bloques.append(Separador())
            else:
                tramo.append(linea)
        cerrar_tramo()
        texto.clear()

    for linea in markdown.replace("\r\n", "\n").split("\n"):
        m = _VALLA.match(linea)
        if apertura is None:
            if m:
                volcar_texto()
                apertura = (len(m.group(2)), m.group(3))
            else:
                texto.append(linea)
        elif m and len(m.group(2)) >= apertura[0] and not m.group(3).strip():
            lenguaje, titulo = _info(apertura[1])
            bloques.append(Codigo(lenguaje, titulo, "\n".join(codigo)))
            codigo.clear()
            apertura = None
        else:
            codigo.append(linea)
    if apertura is not None:
        lenguaje, titulo = _info(apertura[1])
        bloques.append(Codigo(lenguaje, titulo, "\n".join(codigo)))
    else:
        volcar_texto()
    return bloques


# Lenguajes que Pygments no conoce: buscar uno desconocido recorre todos los plugins
# instalados (decenas de ms por consulta), así que se descartan sin preguntar.
_SIN_LEXER = frozenset({"mermaid", "text", "txt", "plain", "plaintext"})


@functools.lru_cache(maxsize=64)
def _lexer(lenguaje: str):
    """Lexer de Pygments para el lenguaje (con caché, también de los que no existen)."""
    if get_lexer_by_name is None or not lenguaje or lenguaje in _SIN_LEXER:
        return None
    try:
        return get_lexer_by_name(lenguaje, stripnl=False, stripall=False)
    except ClassNotFound:
        return None


def nombre_lenguaje(lenguaje: str) -> str:
    """Nombre para mostrar («Python», «JavaScript»…); el texto tal cual si no se conoce."""
    lexer = _lexer(lenguaje)
    if lexer is not None:
        return lexer.name
    return lenguaje.capitalize() if lenguaje else ""


def _categoria(tipo) -> str:
    if tipo in Token.Comment:
        return "comentario"
    if tipo in Token.Literal.String:
        return "cadena"
    if tipo in Token.Literal.Number:
        return "numero"
    if tipo in Token.Keyword:
        return "palabra_clave"
    if tipo in Token.Name.Function or tipo in Token.Name.Class or tipo in Token.Name.Decorator:
        return "definicion"
    if tipo in Token.Name.Builtin or tipo in Token.Name.Exception:
        return "interno"
    if tipo in Token.Operator:
        return "operador"
    return ""


def colorear(codigo: str, lenguaje: str) -> list[list[tuple[str, str]]]:
    """Líneas del código como listas de (categoría, texto); la categoría es «» para el texto
    sin color. Sin lexer disponible, cada línea es un único tramo sin categoría."""
    lexer = _lexer(lenguaje)
    lineas: list[list[tuple[str, str]]] = [[]]
    fuente = (
        lexer.get_tokens(codigo) if lexer is not None else [(None, codigo)]  # type: ignore[list-item]
    )
    for tipo, valor in fuente:
        categoria = _categoria(tipo) if tipo is not None else ""
        trozos = valor.split("\n")
        for i, trozo in enumerate(trozos):
            if i > 0:
                lineas.append([])
            if trozo:
                lineas[-1].append((categoria, trozo))
    # Pygments añade un salto final que no es una línea de código.
    if len(lineas) > 1 and not lineas[-1] and codigo.endswith("\n") is False:
        lineas.pop()
    return lineas


def recortar_bloques(
    bloques: list[Texto | Codigo | Separador], max_lineas: int
) -> list[Texto | Codigo | Separador]:
    """Comienzo de una nota para su tarjeta: los primeros `max_lineas` líneas con contenido
    (las de texto y las de código cuentan igual). Lo que se corta termina en «…»."""
    restantes = max_lineas
    resultado: list[Texto | Codigo | Separador] = []
    for bloque in bloques:
        if restantes <= 0:
            break
        if isinstance(bloque, Separador):
            restantes -= 1
            resultado.append(bloque)
        elif isinstance(bloque, Codigo):
            lineas = bloque.codigo.split("\n")
            if len(lineas) > restantes:
                lineas = [*lineas[:restantes], "…"]
            restantes -= min(len(lineas), restantes)
            resultado.append(Codigo(bloque.lenguaje, bloque.titulo, "\n".join(lineas)))
        else:
            lineas = bloque.markdown.split("\n")
            utiles = [i for i, linea in enumerate(lineas) if linea.strip()]
            if len(utiles) > restantes:
                lineas = [*lineas[: utiles[restantes - 1] + 1], "…"]
                restantes = 0
            else:
                restantes -= len(utiles)
            resultado.append(Texto("\n".join(lineas)))
    return resultado
