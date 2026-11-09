"""Métricas de informes calculadas a partir del modelo actual.

Las funciones son deliberadamente independientes de GTK para que los informes puedan
probarse y reutilizarse en una futura vista global.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime

from gnomilestone.ganttcalc import VENCIDA, estado_vencimiento, fecha_fin_planificada, parse_fecha
from gnomilestone.models import Asignacion, Dependencia, Proyecto, Recurso, Tarea


@dataclass(frozen=True)
class Desviacion:
    tarea: Tarea
    fin_planificado: date
    fin_estimado: date
    dias: int


@dataclass(frozen=True)
class RepartoRecurso:
    recurso: Recurso
    tareas: int
    progreso_medio: float


@dataclass(frozen=True)
class EstadoGithub:
    vinculadas: int
    locales: int
    conflictos: int = 0


def desviaciones_planificacion(tareas: list[Tarea]) -> list[Desviacion]:
    """Tareas cuyo fin estimado (fin de duración) difiere del fin planificado."""
    resultado = []
    for tarea in tareas:
        plan = fecha_fin_planificada(tarea)
        if plan is None or not tarea.fecha_inicio:
            continue
        estimado = parse_fecha(tarea.fecha_inicio)
        from datetime import timedelta
        estimado += timedelta(days=max(tarea.duracion_dias, 1) - 1)
        if estimado != plan:
            resultado.append(Desviacion(tarea, plan, estimado, (estimado - plan).days))
    return sorted(resultado, key=lambda x: (-abs(x.dias), x.tarea.titulo.lower()))


def ruta_critica(tareas: list[Tarea], dependencias: list[Dependencia]) -> list[Tarea]:
    """Devuelve las tareas que el Gantt marca con bandera roja.

    El Gantt considera crítica una tarea incompleta cuya fecha límite está vencida o
    dentro del umbral de alerta configurado. Se conserva ``dependencias`` en la firma
    para que las vistas puedan compartir la misma API de informe.
    """
    return [t for t in tareas if estado_vencimiento(t) == VENCIDA]
def reparto_por_recurso(
    recursos: list[Recurso], tareas: list[Tarea], asignaciones: list[Asignacion]
) -> list[RepartoRecurso]:
    por_tarea = {t.id: t for t in tareas}
    ids: dict[int, set[int]] = defaultdict(set)
    for a in asignaciones:
        if a.tarea_id in por_tarea:
            ids[a.recurso_id].add(a.tarea_id)
    resultado = []
    for recurso in recursos:
        ts = [por_tarea[i] for i in ids.get(recurso.id, set())]
        resultado.append(RepartoRecurso(recurso, len(ts), sum(t.porcentaje_completado for t in ts) / len(ts) if ts else 0))
    return resultado


def recursos_sin_tareas(reparto: list[RepartoRecurso]) -> list[Recurso]:
    return [fila.recurso for fila in reparto if fila.tareas == 0]


def estado_github(tareas: list[Tarea], conflictos: int = 0) -> EstadoGithub:
    vinculadas = sum(t.github_issue_number is not None or t.github_item_id is not None for t in tareas)
    return EstadoGithub(vinculadas, len(tareas) - vinculadas, conflictos)


def resumen_multi_proyecto(
    proyectos: list[Proyecto], tareas: list[Tarea]
) -> dict[str, float | int]:
    activas = [t for t in tareas if not t.archivada]
    hoy = datetime.now().astimezone().date()
    vencidas = sum(
        bool(
            t.fecha_limite
            and t.porcentaje_completado < 100
            and parse_fecha(t.fecha_limite) < hoy
        )
        for t in activas
    )
    return {
        "proyectos": len([p for p in proyectos if not p.archivado]),
        "tareas": len(activas),
        "progreso_medio": sum(t.porcentaje_completado for t in activas) / len(activas) if activas else 0,
        "vencidas": vencidas,
    }
