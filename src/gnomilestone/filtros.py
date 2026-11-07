from __future__ import annotations

from gnomilestone.models import Tarea


def ocultar_completadas(tareas: list[Tarea]) -> list[Tarea]:
    """Tareas que quedan visibles al ocultar las completadas, conservando el orden.

    Una tarea al 100 % se oculta solo si todas sus descendientes también lo están: así
    una tarea resumen que aún tiene trabajo pendiente debajo sigue visible (y con ella
    su jerarquía), en vez de desaparecer y dejar huérfanas a sus subtareas.
    """
    hijos_por_padre: dict[int | None, list[Tarea]] = {}
    for tarea in tareas:
        hijos_por_padre.setdefault(tarea.padre_id, []).append(tarea)

    ramas_completadas: dict[int, bool] = {}

    def _rama_completada(tarea: Tarea) -> bool:
        if tarea.id not in ramas_completadas:
            ramas_completadas[tarea.id] = tarea.porcentaje_completado >= 100 and all(
                _rama_completada(hijo) for hijo in hijos_por_padre.get(tarea.id, [])
            )
        return ramas_completadas[tarea.id]

    return [tarea for tarea in tareas if not _rama_completada(tarea)]
