"""Intérprete de diagramas de flujo de Mermaid (`graph` / `flowchart`), sin GTK.

Cubre lo básico: nodos con forma (`A[rect]`, `A(redondo)`, `A([píldora])`, `A((círculo))`,
`A{decisión}`…), flechas (`-->`, `---`, `-.->`, `==>`) con texto (`-->|texto|` o
`-- texto -->`), cadenas (`A --> B --> C`) y grupos (`A & B --> C`). Se ignoran `style`,
`classDef`, `class`, `linkStyle`, `click` y los `subgraph` (sus nodos se dibujan sueltos).
Cualquier otro tipo de diagrama (secuencia, clases…) lanza `MermaidNoSoportado`.
"""

from __future__ import annotations

import re

from gnomilestone.diagrama import Diagrama, Nodo
from gnomilestone.diagrama_layout import DIRECCIONES, colocar_por_capas


class MermaidNoSoportado(Exception):
    """El texto no es un diagrama de flujo que sepamos dibujar."""


_CABECERA = re.compile(r"^(graph|flowchart)(?:\s+(TD|TB|BT|RL|LR))?$", re.IGNORECASE)
_IGNORADAS = ("style", "classdef", "class", "linkstyle", "click", "subgraph", "end", "direction", "acctitle", "accdescr")
_ID = re.compile(r"[^\s\-=.\[\](){}|&<>\"';:~]+")
# (apertura, cierre, tipo de nodo): se prueban de más larga a más corta.
_FORMAS = (
    ("[[", "]]", "paso"),
    ("[(", ")]", "paso"),
    ("[/", "/]", "paso"),
    ("[\\", "\\]", "paso"),
    ("[/", "\\]", "paso"),
    ("[\\", "/]", "paso"),
    ("((", "))", "inicio"),
    ("([", "])", "inicio"),
    ("{{", "}}", "paso"),
    ("[", "]", "paso"),
    ("(", ")", "paso"),
    ("{", "}", "decision"),
    (">", "]", "paso"),
)
_ENLACE_SIMPLE = re.compile(r"(?P<cuerpo><?(?:-{2,}|={2,}|-\.+-))(?P<punta>>)?")
_ENLACE_CON_TEXTO = re.compile(
    r"(?P<ini>--|==|-\.)\s*(?P<texto>[^\-=>|\n][^\n]*?)\s*(?P<fin>-->|---|==>|===|\.->|\.-)"
)
_ETIQUETA = re.compile(r"\s*\|([^|]*)\|")


def interpretar(texto: str) -> Diagrama:
    """Convierte un diagrama de flujo de Mermaid en un `Diagrama` ya colocado."""
    sentencias = _sentencias(texto)
    if not sentencias:
        raise MermaidNoSoportado("vacío")
    cabecera = _CABECERA.match(sentencias[0])
    if cabecera is None:
        raise MermaidNoSoportado(sentencias[0].split()[0])
    direccion = (cabecera.group(2) or "TD").upper()
    if direccion not in DIRECCIONES:
        direccion = "TD"
    construccion = _Construccion()
    for sentencia in sentencias[1:]:
        if sentencia.split()[0].lower() in _IGNORADAS:
            continue
        _interpretar_sentencia(sentencia, construccion)
    diagrama = construccion.diagrama
    for nodo in diagrama.nodos:
        _ajustar_tamano(nodo)
    colocar_por_capas(diagrama, direccion)
    return diagrama


def _sentencias(texto: str) -> list[str]:
    """Líneas sin comentarios (`%%`) ni vacías, partidas también por `;` fuera de textos."""
    resultado = []
    for linea in texto.replace("\r\n", "\n").split("\n"):
        linea = linea.split("%%", 1)[0]
        actual, profundidad, comillas = [], 0, False
        for caracter in linea:
            if caracter == '"':
                comillas = not comillas
            elif not comillas and caracter in "[({":
                profundidad += 1
            elif not comillas and caracter in "])}":
                profundidad = max(0, profundidad - 1)
            if caracter == ";" and profundidad == 0 and not comillas:
                resultado.append("".join(actual).strip())
                actual = []
            else:
                actual.append(caracter)
        resultado.append("".join(actual).strip())
    return [s for s in resultado if s]


class _Construccion:
    def __init__(self) -> None:
        self.diagrama = Diagrama()
        self.por_nombre: dict[str, Nodo] = {}

    def nodo(self, nombre: str, tipo: str | None, texto: str | None) -> Nodo:
        existente = self.por_nombre.get(nombre)
        if existente is None:
            existente = self.diagrama.nuevo_nodo(tipo or "paso", texto if texto is not None else nombre, 0, 0)
            self.por_nombre[nombre] = existente
        elif tipo is not None:  # una nueva mención con forma redefine el nodo
            existente.tipo = tipo
            existente.texto = texto if texto is not None else existente.texto
        return existente


def _interpretar_sentencia(sentencia: str, construccion: _Construccion) -> None:
    posicion = 0
    anteriores: list[Nodo] | None = None
    enlace = None
    while True:
        grupo, posicion = _grupo_de_nodos(sentencia, posicion, construccion)
        if not grupo:
            return
        if anteriores is not None and enlace is not None:
            for origen in anteriores:
                for destino in grupo:
                    construccion.diagrama.conectar(origen.id, destino.id, *enlace)
        anteriores = grupo
        enlace, posicion = _enlace(sentencia, posicion)
        if enlace is None:
            return


def _saltar_espacios(texto: str, posicion: int) -> int:
    while posicion < len(texto) and texto[posicion].isspace():
        posicion += 1
    return posicion


def _grupo_de_nodos(
    texto: str, posicion: int, construccion: _Construccion
) -> tuple[list[Nodo], int]:
    """Uno o varios nodos unidos por `&`."""
    nodos: list[Nodo] = []
    while True:
        posicion = _saltar_espacios(texto, posicion)
        coincidencia = _ID.match(texto, posicion)
        if coincidencia is None:
            return nodos, posicion
        posicion = coincidencia.end()
        tipo, contenido, posicion = _forma(texto, posicion)
        nodos.append(construccion.nodo(coincidencia.group(), tipo, contenido))
        despues = _saltar_espacios(texto, posicion)
        if despues < len(texto) and texto[despues] == "&":
            posicion = despues + 1
            continue
        return nodos, posicion


def _forma(texto: str, posicion: int) -> tuple[str | None, str | None, int]:
    """Forma opcional pegada al identificador: `[texto]`, `{texto}`, `([texto])`…"""
    for apertura, cierre, tipo in _FORMAS:
        if not texto.startswith(apertura, posicion):
            continue
        inicio = posicion + len(apertura)
        if texto.startswith('"', inicio):
            fin_texto = texto.find('"', inicio + 1)
            if fin_texto == -1:
                continue
            contenido = texto[inicio + 1 : fin_texto]
            fin = texto.find(cierre, fin_texto + 1)
        else:
            fin = texto.find(cierre, inicio)
            contenido = texto[inicio:fin] if fin != -1 else ""
        if fin == -1:
            continue
        return tipo, _limpiar_texto(contenido), fin + len(cierre)
    return None, None, posicion


def _limpiar_texto(texto: str) -> str:
    texto = re.sub(r"<br\s*/?>", "\n", texto.strip(), flags=re.IGNORECASE)
    return texto.strip("`").strip()


def _enlace(texto: str, posicion: int) -> tuple[tuple[str, str, bool] | None, int]:
    """Flecha que sigue a un nodo: (etiqueta, estilo, con punta) y la posición tras ella."""
    posicion = _saltar_espacios(texto, posicion)
    # Primero la forma con texto en medio («-- texto -->»): la simple también encajaría en «--».
    con_texto = _ENLACE_CON_TEXTO.match(texto, posicion)
    if con_texto is not None:
        fin_enlace = con_texto.group("fin")
        estilo = _estilo(con_texto.group("ini") + fin_enlace)
        etiqueta = _limpiar_texto(con_texto.group("texto"))
        return (etiqueta, estilo, fin_enlace.endswith(">")), con_texto.end()
    simple = _ENLACE_SIMPLE.match(texto, posicion)
    if simple is not None:
        cuerpo = simple.group("cuerpo").lstrip("<")
        etiqueta = _ETIQUETA.match(texto, simple.end())
        fin = etiqueta.end() if etiqueta else simple.end()
        texto_etiqueta = etiqueta.group(1).strip() if etiqueta else ""
        return (texto_etiqueta, _estilo(cuerpo), bool(simple.group("punta"))), fin
    return None, posicion


def _estilo(cuerpo: str) -> str:
    if "=" in cuerpo:
        return "gruesa"
    return "discontinua" if "." in cuerpo else "solida"


def _ajustar_tamano(nodo: Nodo) -> None:
    """Tamaño aproximado según el texto (≈ 7,5 px por carácter, líneas de 22 px)."""
    lineas = nodo.texto.split("\n") or [""]
    ancho_texto = max((len(linea) for linea in lineas), default=0) * 7.5
    if nodo.tipo == "decision":
        nodo.ancho = max(110.0, min(300.0, ancho_texto * 1.6 + 40))
        nodo.alto = max(70.0, 26.0 * len(lineas) * 1.5 + 30)
        return
    nodo.ancho = max(90.0, min(280.0, ancho_texto + 40))
    nodo.alto = max(44.0, 22.0 * len(lineas) + 24)
