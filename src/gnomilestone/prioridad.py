"""Prioridad de una tarea y su correspondencia con el campo «Priority» de un Project V2.

GitHub no tiene prioridad en los issues: solo existe si el proyecto define un campo de
selección (p. ej. «Priority» con High/Medium/Low o P0/P1/P2). Localmente es un nivel 0-3.
"""

from __future__ import annotations

import re

NINGUNA, BAJA, MEDIA, ALTA = 0, 1, 2, 3
NIVELES = (NINGUNA, BAJA, MEDIA, ALTA)

_PALABRAS: dict[int, frozenset[str]] = {
    ALTA: frozenset({"alta", "alto", "high", "urgent", "urgente", "critical", "critica", "p0"}),
    MEDIA: frozenset({"media", "medio", "medium", "normal", "p1"}),
    BAJA: frozenset({"baja", "bajo", "low", "minor", "p2", "p3"}),
}


def nivel_desde_opcion(nombre: str | None) -> int | None:
    """Nivel local de una opción de GitHub, o None si no se reconoce (no se toca)."""
    if not nombre:
        return None
    palabras = set(re.split(r"[^0-9a-záéíóúñ]+", nombre.casefold()))
    for nivel, conocidas in _PALABRAS.items():
        if palabras & conocidas:
            return nivel
    return None


def opcion_para_nivel(nivel: int, opciones: dict[str, str]) -> str | None:
    """Id de la opción de GitHub (`opciones`: nombre -> id) que corresponde al nivel."""
    if nivel == NINGUNA:
        return None
    for nombre, opcion_id in opciones.items():
        if nivel_desde_opcion(nombre) == nivel:
            return opcion_id
    return None
