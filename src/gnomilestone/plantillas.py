"""Plantillas con las que se puede empezar una nota de documentación (sin GTK).

Son funciones y no constantes para que los textos se traduzcan con el idioma ya instalado.
"""

from __future__ import annotations

from dataclasses import dataclass

from gnomilestone.i18n import _


@dataclass(frozen=True)
class Plantilla:
    clave: str
    nombre: str
    descripcion: str
    titulo: str  # título inicial de la nota
    contenido: str  # Markdown inicial


def plantillas_para(seccion: str) -> list[Plantilla]:
    """Plantillas disponibles en una sección; la nota en blanco va siempre primera."""
    plantillas = [Plantilla("en_blanco", _("Nota en blanco"), _("Empezar desde cero"), "", "")]
    if seccion == "decisiones_tecnicas":
        plantillas.append(
            Plantilla(
                "adr",
                _("Decisión técnica (ADR)"),
                _("Contexto, decisión, alternativas y consecuencias"),
                _("Decisión: "),
                _(
                    "## Contexto\n¿Qué problema o necesidad motiva la decisión?\n\n"
                    "## Decisión\nQué se ha decidido y por qué.\n\n"
                    "## Alternativas consideradas\n- Alternativa A:\n- Alternativa B:\n\n"
                    "## Consecuencias\n- Positivas:\n- Negativas:\n"
                ),
            )
        )
    if seccion == "especificaciones":
        plantillas.append(
            Plantilla(
                "especificacion",
                _("Especificación"),
                _("Objetivo, requisitos y criterios de aceptación"),
                _("Especificación: "),
                _(
                    "## Objetivo\nQué debe conseguir.\n\n"
                    "## Requisitos\n- [ ] \n- [ ] \n\n"
                    "## Criterios de aceptación\n- \n\n"
                    "## Fuera de alcance\n- \n"
                ),
            )
        )
    if seccion == "arquitectura":
        plantillas.append(
            Plantilla(
                "componente",
                _("Componente"),
                _("Responsabilidad, interfaz y dependencias"),
                _("Componente: "),
                _(
                    "## Responsabilidad\nQué hace y qué no.\n\n"
                    "## Interfaz pública\n- \n\n"
                    "## Dependencias\n- \n\n"
                    "## Notas de diseño\n"
                ),
            )
        )
    return plantillas
