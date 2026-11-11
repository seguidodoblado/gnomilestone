"""Avance y estado de un Hito a partir de las tareas que contribuyen a él (lógica pura)."""

from __future__ import annotations

from datetime import date, datetime

from gnomilestone.models import Hito, Tarea


def tareas_por_hito(tareas: list[Tarea]) -> dict[int, list[Tarea]]:
    """Tareas agrupadas por el Hito al que contribuyen (las que no tienen Hito, fuera)."""
    agrupadas: dict[int, list[Tarea]] = {}
    for tarea in tareas:
        if tarea.hito_id is not None:
            agrupadas.setdefault(tarea.hito_id, []).append(tarea)
    return agrupadas


def hitos_con_estado(hitos: list[Hito], tareas: list[Tarea]) -> list[tuple[Hito, bool]]:
    """Cada Hito con si está conseguido (para dibujarlo relleno o hueco)."""
    por_hito = tareas_por_hito(tareas)
    return [(h, esta_conseguido(h, por_hito.get(h.id, []))) for h in hitos]


def avance_hito(hito: Hito, tareas: list[Tarea]) -> int:
    """Porcentaje 0-100: la media del avance de sus tareas, ponderada por su duración. Sin
    tareas, 100 si está marcado como conseguido y 0 si no."""
    if hito.conseguido:
        return 100
    if not tareas:
        return 0
    pesos = [max(t.duracion_dias, 1) for t in tareas]
    total = sum(p * min(t.porcentaje_completado, 100) for p, t in zip(pesos, tareas, strict=True))
    return round(total / sum(pesos))


def esta_conseguido(hito: Hito, tareas: list[Tarea]) -> bool:
    """Marcado a mano o con todas sus tareas completas (y al menos una)."""
    return hito.conseguido or (bool(tareas) and all(t.porcentaje_completado >= 100 for t in tareas))


def esta_vencido(hito: Hito, tareas: list[Tarea], hoy: date | None = None) -> bool:
    """Su fecha ya pasó y todavía no se ha conseguido."""
    if not hito.fecha or esta_conseguido(hito, tareas):
        return False
    try:
        fecha = date.fromisoformat(hito.fecha[:10])
    except ValueError:
        return False
    return fecha < (hoy or datetime.now().astimezone().date())
