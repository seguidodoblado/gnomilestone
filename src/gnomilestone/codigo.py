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
_CELDA_SEPARADORA = re.compile(r"^\s*(:?)-+(:?)\s*$")
_VALLA = re.compile(r"^(\s*)(`{3,})(.*)$")
_TITULO = re.compile(r'^(?:title\s*=\s*)?(?:"([^"]*)"|\'([^\']*)\'|(.+))$')


@dataclass(frozen=True)
class Texto:
    markdown: str


@dataclass(frozen=True)
class Separador:
    """Línea horizontal (`---`): se dibuja como un separador que ocupa todo el ancho."""


@dataclass(frozen=True)
class Tabla:
    """Tabla Markdown: la primera fila es la cabecera; `alineaciones` lleva «left», «center»
    o «right» por columna."""

    cabecera: tuple[str, ...]
    alineaciones: tuple[str, ...]
    filas: tuple[tuple[str, ...], ...]


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


def _celdas(linea: str) -> list[str]:
    """Celdas de una fila de tabla; respeta `\\|` y las barras dentro de `código`."""
    linea = linea.strip()
    linea = linea.removeprefix("|")
    if linea.endswith("|") and not linea.endswith("\\|"):
        linea = linea[:-1]
    celdas: list[str] = []
    actual: list[str] = []
    en_codigo = False
    i = 0
    while i < len(linea):
        c = linea[i]
        if c == "\\" and linea[i + 1 : i + 2] == "|":
            actual.append("|")
            i += 2
            continue
        if c == "`":
            en_codigo = not en_codigo
        if c == "|" and not en_codigo:
            celdas.append("".join(actual).strip())
            actual = []
        else:
            actual.append(c)
        i += 1
    celdas.append("".join(actual).strip())
    return celdas


def _alineaciones(linea: str) -> tuple[str, ...] | None:
    """Alineaciones de una fila separadora (`|---|:-:|--:|`); None si no lo es."""
    if "-" not in linea or "|" not in linea and not _CELDA_SEPARADORA.match(linea):
        return None
    resultado = []
    for celda in _celdas(linea):
        m = _CELDA_SEPARADORA.match(celda)
        if m is None:
            return None
        resultado.append("center" if m.group(1) and m.group(2) else "right" if m.group(2) else "left")
    return tuple(resultado)


def _trocear_tablas(lineas: list[str]) -> list[Texto | Tabla]:
    """Separa un tramo de líneas en texto y tablas (cabecera + separador + filas)."""
    resultado: list[Texto | Tabla] = []
    tramo: list[str] = []

    def cerrar() -> None:
        contenido = "\n".join(tramo).strip("\n")
        if contenido.strip():
            resultado.append(Texto(contenido))
        tramo.clear()

    i = 0
    while i < len(lineas):
        alineaciones = None
        if i + 1 < len(lineas) and "|" in lineas[i] and (
            alineaciones := _alineaciones(lineas[i + 1])
        ):
            cabecera = _celdas(lineas[i])
            if len(cabecera) != len(alineaciones):
                alineaciones = None
        if not alineaciones:
            tramo.append(lineas[i])
            i += 1
            continue
        n = len(alineaciones)
        filas: list[tuple[str, ...]] = []
        i += 2
        while i < len(lineas) and lineas[i].strip() and "|" in lineas[i]:
            fila = _celdas(lineas[i])[:n]
            filas.append(tuple(fila + [""] * (n - len(fila))))
            i += 1
        cerrar()
        resultado.append(Tabla(tuple(cabecera), alineaciones, tuple(filas)))
    cerrar()
    return resultado


def dividir_bloques(markdown: str) -> list[Texto | Codigo | Separador | Tabla]:
    """Separa el Markdown en tramos de texto, líneas horizontales (`---`) y bloques de
    código delimitados por ```. Un bloque sin cerrar llega hasta el final."""
    bloques: list[Texto | Codigo | Separador | Tabla] = []
    texto: list[str] = []
    codigo: list[str] = []
    apertura: tuple[int, str] | None = None  # (nº de comillas, info) del bloque abierto

    def volcar_texto() -> None:
        tramo: list[str] = []

        def cerrar_tramo() -> None:
            bloques.extend(_trocear_tablas(tramo))
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


_TAREA_MD = re.compile(r"^(\s*(?:[-*+]|\d+[.)])\s+\[)( |x|X)(\]\s+)")


def alternar_tarea(markdown: str, numero: int) -> str:
    """Marca o desmarca la casilla `numero` (contando desde 0, fuera de los bloques de código,
    en el orden en que las pinta el visor). Si no existe, devuelve el texto sin cambios."""
    lineas = markdown.split("\n")
    apertura: int | None = None
    contadas = 0
    for i, linea in enumerate(lineas):
        m = _VALLA.match(linea.rstrip("\r"))
        if apertura is None:
            if m:
                apertura = len(m.group(2))
                continue
        else:
            if m and len(m.group(2)) >= apertura and not m.group(3).strip():
                apertura = None
            continue
        t = _TAREA_MD.match(linea)
        if t is None:
            continue
        if contadas == numero:
            nuevo = " " if t.group(2) != " " else "x"
            lineas[i] = t.group(1) + nuevo + linea[t.end(2):]
            return "\n".join(lineas)
        contadas += 1
    return markdown


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
    bloques: list[Texto | Codigo | Separador | Tabla], max_lineas: int
) -> list[Texto | Codigo | Separador | Tabla]:
    """Comienzo de una nota para su tarjeta: los primeros `max_lineas` líneas con contenido
    (las de texto y las de código cuentan igual). Lo que se corta termina en «…»."""
    restantes = max_lineas
    resultado: list[Texto | Codigo | Separador | Tabla] = []
    for bloque in bloques:
        if restantes <= 0:
            break
        if isinstance(bloque, Tabla):
            # Cabecera y filas cuentan como líneas (el separador no).
            filas = bloque.filas[: max(restantes - 1, 0)]
            restantes -= 1 + len(filas)
            resultado.append(Tabla(bloque.cabecera, bloque.alineaciones, filas))
        elif isinstance(bloque, Separador):
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
