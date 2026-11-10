"""Reordenación de tareas por arrastre (sin interfaz)."""

from __future__ import annotations


def mover_tarea(
    ids_en_orden: list[int], mover_id: int, referencia_id: int | None, despues: bool
) -> list[int]:
    """Devuelve `ids_en_orden` con `mover_id` colocado justo antes (o, con `despues`, justo
    después) de `referencia_id`. Sin referencia o con una referencia desconocida, la tarea no
    se mueve. Soltar una tarea sobre sí misma tampoco cambia nada."""
    if mover_id not in ids_en_orden or referencia_id is None or referencia_id == mover_id:
        return list(ids_en_orden)
    if referencia_id not in ids_en_orden:
        return list(ids_en_orden)
    resto = [i for i in ids_en_orden if i != mover_id]
    posicion = resto.index(referencia_id) + (1 if despues else 0)
    resto.insert(posicion, mover_id)
    return resto
