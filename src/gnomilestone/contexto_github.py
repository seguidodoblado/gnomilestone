"""Rellena las notas de «Contexto del proyecto» con los ficheros del repositorio de GitHub.

Cada nota se corresponde con un documento habitual del repositorio (README, código de
conducta, guía de contribución, licencia y política de seguridad). Sin GTK: el cliente de
GitHub se pasa como parámetro para poder probarlo.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Protocol

from gnomilestone.html_markdown import html_a_markdown
from gnomilestone.models import NotaDocumentacion
from gnomilestone.store import Store

SECCION = "vision_general"

# Título de la nota (en castellano, como se crea) y rutas donde buscar su fichero, por orden.
DOCUMENTOS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("README", ("README.md", "README.markdown", "README", "README.rst", "docs/README.md")),
    (
        "Código de conducta",
        ("CODE_OF_CONDUCT.md", ".github/CODE_OF_CONDUCT.md", "docs/CODE_OF_CONDUCT.md"),
    ),
    (
        "Contribuyendo",
        ("CONTRIBUTING.md", ".github/CONTRIBUTING.md", "docs/CONTRIBUTING.md"),
    ),
    ("Licencia", ("LICENSE", "LICENSE.md", "LICENSE.txt", "COPYING", "COPYING.md")),
    ("Seguridad", ("SECURITY.md", ".github/SECURITY.md", "docs/SECURITY.md")),
)


class _Cliente(Protocol):
    def obtener_fichero_repo(self, owner: str, repo: str, ruta: str) -> str | None: ...


@dataclass(frozen=True)
class DocumentoRemoto:
    titulo: str
    ruta: str | None  # None: no está en el repositorio
    markdown: str | None


@dataclass(frozen=True)
class ResultadoPull:
    actualizadas: list[str]
    creadas: list[str]
    sin_cambios: list[str]
    no_encontradas: list[str]

    @property
    def hubo_cambios(self) -> bool:
        return bool(self.actualizadas or self.creadas)


def como_markdown(ruta: str, texto: str, repositorio: tuple[str, str] | None = None) -> str:
    """El Markdown se limpia de HTML (cabeceras centradas, badges, imágenes) y sus rutas
    relativas pasan a direcciones de GitHub si se conoce el `repositorio` (propietario,
    nombre); el texto plano (LICENSE…) va en un bloque de código para conservar su formato
    en vez de reflujarse como un párrafo."""
    if ruta.lower().endswith((".md", ".markdown")):
        return html_a_markdown(texto, repositorio, ruta)
    valla = "```"
    while valla in texto:
        valla += "`"
    return f"{valla}\n{texto.rstrip()}\n{valla}\n"


def traer_documentos(
    cliente: _Cliente,
    owner: str,
    repo: str,
    al_avanzar: Callable[[str], None] | None = None,
) -> list[DocumentoRemoto]:
    """Busca en el repositorio el primer fichero existente de cada documento."""
    resultado = []
    for titulo, rutas in DOCUMENTOS:
        if al_avanzar is not None:
            al_avanzar(titulo)
        encontrado = None
        for ruta in rutas:
            texto = cliente.obtener_fichero_repo(owner, repo, ruta)
            if isinstance(texto, str) and texto.strip():
                encontrado = DocumentoRemoto(titulo, ruta, como_markdown(ruta, texto, (owner, repo)))
                break
        resultado.append(encontrado or DocumentoRemoto(titulo, None, None))
    return resultado


def aplicar_documentos(
    store: Store, proyecto_id: int, subseccion_id: int, documentos: list[DocumentoRemoto]
) -> ResultadoPull:
    """Vuelca los documentos en las notas de la subsección. Una nota existente se
    sobrescribe (el Store guarda su versión anterior, recuperable desde «Versiones»); una
    ausente se crea; lo que el repositorio no tiene no se toca."""
    existentes: dict[str, NotaDocumentacion] = {}
    for nota in store.listar_notas_documentacion(proyecto_id, subseccion_id=subseccion_id):
        if nota.padre_id is None:
            existentes.setdefault(nota.titulo, nota)
    actualizadas, creadas, sin_cambios, no_encontradas = [], [], [], []
    for documento in documentos:
        if documento.markdown is None:
            no_encontradas.append(documento.titulo)
            continue
        nota = existentes.get(documento.titulo)
        if nota is None:
            store.crear_nota_documentacion(
                proyecto_id, SECCION, documento.titulo, documento.markdown, subseccion_id
            )
            creadas.append(documento.titulo)
        elif nota.contenido == documento.markdown:
            sin_cambios.append(documento.titulo)
        else:
            store.actualizar_nota_documentacion(replace(nota, contenido=documento.markdown))
            actualizadas.append(documento.titulo)
    return ResultadoPull(actualizadas, creadas, sin_cambios, no_encontradas)
