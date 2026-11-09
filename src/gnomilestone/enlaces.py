"""Enlaces internos de la documentación (sin GTK).

En el Markdown de una nota:
  - `[[Título]]` o `[[Título|texto]]` enlaza con la nota, el diagrama o la tarea que se llame
    así (en ese orden de prioridad, sin distinguir mayúsculas ni acentos).
  - `#27` enlaza con la tarea vinculada al issue 27 de GitHub.
Los enlaces se convierten a `[texto](gnomilestone://tipo/id)` antes de pintar la nota; los
que no se resuelven se dejan tal cual, para que se vea que están rotos.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from gnomilestone.models import DiagramaDocumentacion, NotaDocumentacion, Tarea

ESQUEMA = "gnomilestone://"
_WIKI = re.compile(r"\[\[([^\[\]\n|]+)(?:\|([^\[\]\n]+))?\]\]")
_ISSUE = re.compile(r"(?<![\w&/#\[])#(\d+)\b")
_CODIGO = re.compile(r"(`[^`\n]*`)")


def normalizar(texto: str) -> str:
    """Minúsculas y sin acentos, carácter a carácter (conserva la longitud y los índices)."""
    return "".join(unicodedata.normalize("NFD", c)[0].lower() for c in texto)


@dataclass(frozen=True)
class Destino:
    tipo: str  # "nota" | "diagrama" | "tarea"
    id: int
    titulo: str

    @property
    def uri(self) -> str:
        return f"{ESQUEMA}{self.tipo}/{self.id}"


class Indice:
    """Resuelve títulos y números de issue a destinos dentro de un proyecto."""

    def __init__(
        self,
        notas: list[NotaDocumentacion],
        diagramas: list[DiagramaDocumentacion],
        tareas: list[Tarea],
    ) -> None:
        self._por_titulo: dict[str, Destino] = {}
        # Prioridad: notas, luego diagramas, luego tareas (el primero que llega, gana).
        for nota in notas:
            self._por_titulo.setdefault(normalizar(nota.titulo.strip()), Destino("nota", nota.id, nota.titulo))
        for diagrama in diagramas:
            self._por_titulo.setdefault(
                normalizar(diagrama.titulo.strip()), Destino("diagrama", diagrama.id, diagrama.titulo)
            )
        for tarea in tareas:
            self._por_titulo.setdefault(normalizar(tarea.titulo.strip()), Destino("tarea", tarea.id, tarea.titulo))
        self._por_issue = {
            t.github_issue_number: Destino("tarea", t.id, t.titulo)
            for t in tareas
            if t.github_issue_number is not None
        }

    def por_titulo(self, titulo: str) -> Destino | None:
        return self._por_titulo.get(normalizar(titulo.strip()))

    def por_issue(self, numero: int) -> Destino | None:
        return self._por_issue.get(numero)


def transformar_enlaces(texto: str, indice: Indice) -> str:
    """Convierte los enlaces internos resueltos en enlaces Markdown normales (`gnomilestone://`).
    No toca el código (bloques ni `en línea`)."""
    salida = []
    en_bloque = False
    for linea in texto.split("\n"):
        if linea.lstrip().startswith("```"):
            en_bloque = not en_bloque
            salida.append(linea)
        elif en_bloque:
            salida.append(linea)
        else:
            # Los tramos impares de la división son código en línea: se dejan igual.
            partes = _CODIGO.split(linea)
            salida.append(
                "".join(p if i % 2 else _transformar_linea(p, indice) for i, p in enumerate(partes))
            )
    return "\n".join(salida)


def _transformar_linea(texto: str, indice: Indice) -> str:
    def wiki(m: re.Match[str]) -> str:
        destino = indice.por_titulo(m.group(1))
        if destino is None:
            return m.group(0)
        return f"[{m.group(2) or m.group(1)}]({destino.uri})"

    def issue(m: re.Match[str]) -> str:
        destino = indice.por_issue(int(m.group(1)))
        return f"[{m.group(0)}]({destino.uri})" if destino else m.group(0)

    return _ISSUE.sub(issue, _WIKI.sub(wiki, texto))


def destino_de_uri(uri: str) -> tuple[str, int] | None:
    """('nota'|'diagrama'|'tarea', id) de un enlace `gnomilestone://tipo/id`; None si no lo es."""
    if not uri.startswith(ESQUEMA):
        return None
    tipo, _sep, resto = uri[len(ESQUEMA) :].partition("/")
    if tipo in ("nota", "diagrama", "tarea") and resto.isdigit():
        return tipo, int(resto)
    return None


def entrantes(
    destino: Destino, notas: list[NotaDocumentacion], indice: Indice
) -> list[NotaDocumentacion]:
    """Notas (distintas del propio destino) que enlazan con él."""
    resultado = []
    for nota in notas:
        if destino.tipo == "nota" and nota.id == destino.id:
            continue
        if _enlaza_con(nota.contenido, destino, indice):
            resultado.append(nota)
    return resultado


def _enlaza_con(contenido: str, destino: Destino, indice: Indice) -> bool:
    return any(
        d == destino
        for d in (
            *(indice.por_titulo(m.group(1)) for m in _WIKI.finditer(contenido)),
            *(indice.por_issue(int(m.group(1))) for m in _ISSUE.finditer(contenido)),
        )
    )
