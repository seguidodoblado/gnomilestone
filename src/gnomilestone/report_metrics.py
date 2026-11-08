"""Métricas de informes calculadas a partir del modelo actual.

Las funciones son deliberadamente independientes de GTK para que los informes puedan
probarse y reutilizarse en una futura vista global. Las métricas que requieren histórico
(burndown, CFD y tiempo por columna) no se estiman: el modelo actual no conserva esos
eventos.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date

from gnomilestone.ganttcalc import VENCIDA, estado_vencimiento, fecha_fin_planificada, parse_fecha
from gnomilestone.models import Asignacion, Dependencia, EstadoTablero, Proyecto, Recurso, Tarea
from gnomilestone.resource_usage import construir_filas_uso


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
    # El cálculo de camino por dependencias se conserva abajo como referencia para
    # una futura métrica distinta (holgura/ruta de dependencias), pero no debe usarse
    # para pintar la ruta crítica del informe.
    por_id = {t.id: t for t in tareas}
    prev: dict[int, int | None] = {}
    distancia: dict[int, int] = {}
    sucesores: dict[int, list[int]] = defaultdict(list)
    entrantes: dict[int, int] = {t.id: 0 for t in tareas}
    for dep in dependencias:
        if dep.tarea_origen_id in por_id and dep.tarea_destino_id in por_id:
            sucesores[dep.tarea_origen_id].append(dep.tarea_destino_id)
            entrantes[dep.tarea_destino_id] += 1
    def duracion(t: Tarea) -> int:
        return 1 if t.es_hito else max(t.duracion_dias, 1)
    pendientes = [t.id for t in tareas if entrantes[t.id] == 0]
    for t in pendientes:
        distancia[t] = duracion(por_id[t])
        prev[t] = None
    indice = 0
    while indice < len(pendientes):
        origen = pendientes[indice]
        indice += 1
        for destino in sucesores.get(origen, []):
            candidato = distancia[origen] + duracion(por_id[destino])
            if candidato > distancia.get(destino, 0):
                distancia[destino] = candidato
                prev[destino] = origen
            entrantes[destino] -= 1
            if entrantes[destino] == 0:
                pendientes.append(destino)
    if not distancia:
        return []
    actual = max(distancia, key=distancia.get)
    ids = []
    while actual is not None:
        ids.append(actual)
        actual = prev.get(actual)
    return [por_id[i] for i in reversed(ids)]


def proximos_hitos(tareas: list[Tarea], estados: list[EstadoTablero]) -> list[Tarea]:
    nombres = {e.id: e.nombre for e in estados}
    return sorted((t for t in tareas if t.es_hito and t.fecha_limite), key=lambda t: t.fecha_limite or "")


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
    vencidas = sum(bool(t.fecha_limite and t.porcentaje_completado < 100 and parse_fecha(t.fecha_limite) < date.today()) for t in activas)
    return {
        "proyectos": len([p for p in proyectos if not p.archivado]),
        "tareas": len(activas),
        "progreso_medio": sum(t.porcentaje_completado for t in activas) / len(activas) if activas else 0,
        "vencidas": vencidas,
    }
