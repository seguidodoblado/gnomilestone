"""Columna «de completadas» del tablero: entrar en ella completa la tarea (100 %) y salir
de ella deshace ese completado."""

from __future__ import annotations

from gnomilestone.models import EstadoTablero, Tarea


def id_columna_final(estados: list[EstadoTablero]) -> int | None:
    """Id de la columna marcada como «de completadas», o None si no hay ninguna."""
    return next((e.id for e in estados if e.es_final), None)


def al_cambiar_de_columna(
    tarea: Tarea, estado_nuevo_id: int | None, estados: list[EstadoTablero]
) -> None:
    """Ajusta el % de `tarea` por su paso a `estado_nuevo_id`. No cambia `tarea.estado_id`.

    - Entra en la columna final y no estaba al 100 %: pasa al 100 %, recordando el % que
      tenía en `porcentaje_previo`.
    - Sale de la columna final estando al 100 %: vuelve a ese % recordado (0 si no lo hay).
    Sin columna final marcada no hace nada.
    """
    final = id_columna_final(estados)
    if final is None or tarea.estado_id == estado_nuevo_id:
        return
    entra = estado_nuevo_id == final
    sale = tarea.estado_id == final
    if entra and tarea.porcentaje_completado < 100:
        tarea.porcentaje_previo = tarea.porcentaje_completado
        tarea.porcentaje_completado = 100
    elif sale and not entra and tarea.porcentaje_completado >= 100:
        previo = tarea.porcentaje_previo
        tarea.porcentaje_completado = previo if previo is not None and previo < 100 else 0
        tarea.porcentaje_previo = None
