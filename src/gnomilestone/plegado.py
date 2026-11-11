"""Plegado de tareas padre en la vista Lista: qué filas quedan ocultas y cuántas cuelgan de cada una.

Lógica pura (sin GTK) sobre el mapa `tarea_id -> padre_id`.
"""

from __future__ import annotations


def descendientes_por_tarea(padre_de: dict[int, int | None]) -> dict[int, int]:
    """Número de descendientes (hijas, nietas…) de cada tarea que tiene alguno."""
    cuenta: dict[int, int] = {}
    for tarea_id in padre_de:
        actual = padre_de.get(tarea_id)
        visitados = {tarea_id}
        while actual is not None and actual in padre_de and actual not in visitados:
            cuenta[actual] = cuenta.get(actual, 0) + 1
            visitados.add(actual)
            actual = padre_de.get(actual)
    return cuenta


def ocultas_por_plegado(padre_de: dict[int, int | None], plegadas: set[int]) -> set[int]:
    """Tareas ocultas porque alguno de sus ancestros está plegado."""
    ocultas: set[int] = set()
    for tarea_id in padre_de:
        actual = padre_de.get(tarea_id)
        visitados = {tarea_id}
        while actual is not None and actual not in visitados:
            if actual in plegadas:
                ocultas.add(tarea_id)
                break
            visitados.add(actual)
            actual = padre_de.get(actual)
    return ocultas
