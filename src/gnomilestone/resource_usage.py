"""Cálculo de ocupación de recursos en el tiempo (vista Uso).

Por cada persona suma el `porcentaje_dedicacion` de las tareas que caen en un mismo
día; por encima de 100 % se considera sobrecarga (solape).

Si la misma persona está asignada a una tarea y a un ancestro suyo, solo cuenta el
ancestro: la hija pertenece al padre y no debe sumar otra vez.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from gnomilestone.ganttcalc import parse_fecha
from gnomilestone.models import Asignacion, Recurso, Tarea


@dataclass(frozen=True)
class SegmentoUso:
    """Una asignación proyectada sobre el calendario."""

    tarea_id: int
    titulo: str
    fecha_inicio: date
    duracion_dias: int
    porcentaje_dedicacion: int

    @property
    def fecha_fin(self) -> date:
        return self.fecha_inicio + timedelta(days=self.duracion_dias)


@dataclass(frozen=True)
class FilaUso:
    recurso: Recurso
    segmentos: tuple[SegmentoUso, ...]
    carga_maxima: int
    dias_sobrecarga: int

    @property
    def sobrecargado(self) -> bool:
        return self.dias_sobrecarga > 0


def duracion_efectiva(tarea: Tarea) -> int:
    """Días que ocupa en el calendario (hitos y duraciones 0 cuentan un día)."""
    return 1 if tarea.es_hito else max(tarea.duracion_dias, 1)


def carga_por_dia(segmentos: list[SegmentoUso] | tuple[SegmentoUso, ...]) -> dict[date, int]:
    """Suma de dedicaciones por día calendario cubierto por algún segmento."""
    carga: dict[date, int] = {}
    for segmento in segmentos:
        for offset in range(segmento.duracion_dias):
            dia = segmento.fecha_inicio + timedelta(days=offset)
            carga[dia] = carga.get(dia, 0) + segmento.porcentaje_dedicacion
    return carga


def _cubierta_por_ancestro(
    tarea: Tarea, tareas_por_id: dict[int, Tarea], tareas_asignadas: set[int]
) -> bool:
    """True si algún ancestro de `tarea` también está en `tareas_asignadas` (mismo recurso)."""
    padre_id = tarea.padre_id
    while padre_id is not None:
        if padre_id in tareas_asignadas:
            return True
        padre = tareas_por_id.get(padre_id)
        if padre is None:
            return False
        padre_id = padre.padre_id
    return False


def construir_filas_uso(
    recursos: list[Recurso],
    tareas: list[Tarea],
    asignaciones: list[Asignacion],
) -> list[FilaUso]:
    """Una fila por recurso (orden de `recursos`), con segmentos datados y métricas de carga.

    Las hijas no suman si el mismo recurso ya está asignado a un ancestro.
    Dos hermanas (o tareas sin ancestro común asignado) sí pueden solaparse y sobrecargar.
    """
    tareas_por_id = {tarea.id: tarea for tarea in tareas}
    asignaciones_por_recurso: dict[int, list[Asignacion]] = {}
    for asignacion in asignaciones:
        asignaciones_por_recurso.setdefault(asignacion.recurso_id, []).append(asignacion)

    filas: list[FilaUso] = []
    for recurso in recursos:
        asignaciones_recurso = asignaciones_por_recurso.get(recurso.id, [])
        tareas_asignadas = {asignacion.tarea_id for asignacion in asignaciones_recurso}
        segmentos: list[SegmentoUso] = []
        for asignacion in asignaciones_recurso:
            tarea = tareas_por_id.get(asignacion.tarea_id)
            if tarea is None or not tarea.fecha_inicio:
                continue
            if _cubierta_por_ancestro(tarea, tareas_por_id, tareas_asignadas):
                continue
            segmentos.append(
                SegmentoUso(
                    tarea_id=tarea.id,
                    titulo=tarea.titulo,
                    fecha_inicio=parse_fecha(tarea.fecha_inicio),
                    duracion_dias=duracion_efectiva(tarea),
                    porcentaje_dedicacion=asignacion.porcentaje_dedicacion,
                )
            )
        segmentos.sort(key=lambda s: (s.fecha_inicio, s.titulo, s.tarea_id))
        carga = carga_por_dia(segmentos)
        carga_maxima = max(carga.values()) if carga else 0
        dias_sobrecarga = sum(1 for valor in carga.values() if valor > 100)
        filas.append(
            FilaUso(
                recurso=recurso,
                segmentos=tuple(segmentos),
                carga_maxima=carga_maxima,
                dias_sobrecarga=dias_sobrecarga,
            )
        )
    return filas


def carga_equipo_por_dia(filas: list[FilaUso]) -> dict[date, int]:
    """Carga del equipo por día, en % sobre su capacidad ese día.

    La capacidad del equipo ese día es el número de personas con algo asignado × 100
    (cada persona aporta 100 de capacidad "normal", tenga lo que tenga asignado). Por
    debajo de 100 hay margen: alguien asignado solo al 50 % ese día, sin nadie más,
    sale al 50 % (poca carga), no se infla a 100 solo por no estar sobrecargado. Por
    encima de 100, lo asignado supera la capacidad normal del equipo ese día, ya sea
    por solapes entre varias personas o porque una sola está individualmente
    sobrecargada. Quien dibuja la franja decide los cortes entre "poca carga", "carga
    normal" y "sobrecarga" (ver `_UMBRAL_CARGA_NORMAL` en `resource_usage_view.py`).
    """
    carga_total: dict[date, int] = {}
    capacidad_total: dict[date, int] = {}
    for fila in filas:
        carga_persona = carga_por_dia(fila.segmentos)
        for dia, valor in carga_persona.items():
            carga_total[dia] = carga_total.get(dia, 0) + valor
            capacidad_total[dia] = capacidad_total.get(dia, 0) + 100
    return {dia: round(100 * carga_total[dia] / capacidad_total[dia]) for dia in carga_total}


def rango_fechas(filas: list[FilaUso]) -> tuple[date, date] | None:
    """Inicio (inclusive) y fin (exclusive) del calendario cubierto, o None si no hay fechas."""
    inicios: list[date] = []
    fines: list[date] = []
    for fila in filas:
        for segmento in fila.segmentos:
            inicios.append(segmento.fecha_inicio)
            fines.append(segmento.fecha_fin)
    if not inicios:
        return None
    return min(inicios), max(fines)
