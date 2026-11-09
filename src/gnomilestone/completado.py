"""Columna «de completadas» del tablero: entrar en ella completa la tarea (100 %) y salir
de ella deshace ese completado."""

from __future__ import annotations

from datetime import date, datetime

from gnomilestone.models import EstadoTablero, Tarea


def id_columna_final(estados: list[EstadoTablero]) -> int | None:
    """Id de la columna marcada como «de completadas», o None si no hay ninguna."""
    return next((e.id for e in estados if e.es_final), None)


def dependencias_sin_terminar(origenes_ids, tareas: list[Tarea]) -> list[Tarea]:
    """Tareas de `tareas` cuyo id está en `origenes_ids` (aquellas de las que depende la tarea
    que se quiere completar) y que no están al 100 %. Las archivadas no cuentan."""
    ids = set(origenes_ids)
    return [t for t in tareas if t.id in ids and not t.archivada and t.porcentaje_completado < 100]


def fecha_fin_real_para(
    porcentaje: int, actual: str | None, hoy: date | None = None
) -> str | None:
    """Fecha de fin real que corresponde a un % completado: al llegar al 100 % se pone la de
    hoy (si no había ya una), y por debajo del 100 % se borra. Respeta la que haya puesto
    el usuario mientras la tarea siga completada."""
    if porcentaje < 100:
        return None
    if actual:
        return actual
    return (hoy or datetime.now().astimezone().date()).isoformat()


def al_cambiar_de_columna(
    tarea: Tarea, estado_nuevo_id: int | None, estados: list[EstadoTablero]
) -> None:
    """Ajusta el % de `tarea` por su paso a `estado_nuevo_id`. No cambia `tarea.estado_id`.

    - Entra en la columna final y no estaba al 100 %: pasa al 100 %, recordando el % que
      tenía en `porcentaje_previo`, y se rellena la fecha de fin real (hoy) si estaba vacía.
    - Sale de la columna final estando al 100 %: vuelve a ese % recordado (0 si no lo hay) y
      se borra la fecha de fin real.
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
        tarea.fecha_fin_real = fecha_fin_real_para(100, tarea.fecha_fin_real)
    elif sale and not entra and tarea.porcentaje_completado >= 100:
        previo = tarea.porcentaje_previo
        tarea.porcentaje_completado = previo if previo is not None and previo < 100 else 0
        tarea.porcentaje_previo = None
        tarea.fecha_fin_real = fecha_fin_real_para(tarea.porcentaje_completado, tarea.fecha_fin_real)
