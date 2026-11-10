"""Métricas de informes calculadas a partir del modelo actual.

Las funciones son deliberadamente independientes de GTK para que los informes puedan
probarse y reutilizarse en una futura vista global.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from gnomilestone.documentacion import fecha_completada
from gnomilestone.ganttcalc import VENCIDA, estado_vencimiento, fecha_fin_planificada, parse_fecha
from gnomilestone.models import Asignacion, Dependencia, HistorialTarea, Proyecto, Recurso, Tarea


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


# ----------------------------------------------------------------------
# Planificación: fechas previstas frente a reales
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class FechasTarea:
    """Previsto y real de una tarea. `fin_real` es None si aún no ha terminado."""

    tarea: Tarea
    inicio: date
    fin_inicial: date
    fin_actual: date
    fin_real: date | None

    @property
    def desviacion_dias(self) -> int | None:
        """Días de retraso (+) o adelanto (−) respecto al plan inicial.

        Terminada: fin real − fin inicial. Sin terminar y ya pasada de plazo:
        hoy − fin inicial, es decir, lo que lleva de retraso. Sin terminar y en
        plazo no hay desviación todavía (None).
        """
        if self.fin_real is not None:
            return (self.fin_real - self.fin_inicial).days
        hoy = datetime.now().astimezone().date()
        if self.tarea.porcentaje_completado < 100 and hoy > self.fin_inicial:
            return (hoy - self.fin_inicial).days
        return None

    @property
    def movimientos(self) -> int:
        """Cuánto se ha movido el final respecto al plan inicial (días, con signo)."""
        return (self.fin_actual - self.fin_inicial).days


def fechas_planificadas_reales(tareas: list[Tarea]) -> list[FechasTarea]:
    """Tareas con inicio y fin planificado, ordenadas por inicio."""
    filas = []
    for tarea in tareas:
        if not tarea.fecha_inicio:
            continue
        actual = tarea.fecha_fin_planificada or tarea.fecha_fin_planificada_inicial
        inicial = tarea.fecha_fin_planificada_inicial or tarea.fecha_fin_planificada
        if not actual or not inicial:
            continue
        filas.append(FechasTarea(
            tarea,
            parse_fecha(tarea.fecha_inicio),
            parse_fecha(inicial),
            parse_fecha(actual),
            parse_fecha(tarea.fecha_fin_real) if tarea.fecha_fin_real else None,
        ))
    return sorted(filas, key=lambda f: (f.inicio, f.tarea.id))


@dataclass(frozen=True)
class ResumenDesviacion:
    a_tiempo: int
    con_retraso: int
    adelantadas: int
    sin_medir: int
    retraso_medio: float  # días, solo sobre las que van con retraso
    peores: list[FechasTarea]  # mayores retrasos, de más a menos


def resumen_desviacion(tareas: list[Tarea], maximo_peores: int = 5) -> ResumenDesviacion:
    filas = fechas_planificadas_reales(tareas)
    a_tiempo = con_retraso = adelantadas = sin_medir = 0
    retrasadas = []
    for fila in filas:
        dias = fila.desviacion_dias
        if dias is None:
            sin_medir += 1
        elif dias > 0:
            con_retraso += 1
            retrasadas.append(fila)
        elif dias < 0:
            adelantadas += 1
        else:
            a_tiempo += 1
    retrasadas.sort(key=lambda f: (-f.desviacion_dias, f.tarea.titulo.casefold()))
    medio = sum(f.desviacion_dias for f in retrasadas) / len(retrasadas) if retrasadas else 0.0
    return ResumenDesviacion(a_tiempo, con_retraso, adelantadas, sin_medir, medio, retrasadas[:maximo_peores])


# ----------------------------------------------------------------------
# Flujo de trabajo: tiempo por columna y diagrama de flujo acumulado (CFD)
# ----------------------------------------------------------------------


def _instante(texto: str | None) -> datetime | None:
    """Interpreta las marcas de SQLite ("2026-11-09 06:08:48" o con T/Z); sin zona."""
    if not texto:
        return None
    try:
        return datetime.fromisoformat(texto.strip().replace("Z", "").replace(" ", "T"))
    except ValueError:
        return None


def _id_estado(valor: str | None) -> int | None:
    try:
        return int(valor) if valor not in (None, "", "None") else None
    except ValueError:
        return None


def trayectoria_estados(
    tarea: Tarea, historial: list, ahora: datetime
) -> list[tuple[datetime, datetime, int | None]]:
    """Tramos (desde, hasta, estado_id) por los que ha pasado la tarea.

    Parte de la creación en el estado anterior al primer cambio registrado y sigue
    cada cambio de estado hasta `ahora`. Sin cambios registrados es un único tramo
    en el estado actual.
    """
    cambios = sorted(
        (
            (_instante(e.creado), e)
            for e in historial
            if e.tarea_id == tarea.id and e.tipo == "estado" and _instante(e.creado)
        ),
        key=lambda par: (par[0], par[1].id),
    )
    inicio = _instante(tarea.creado) or (cambios[0][0] if cambios else ahora)
    if not cambios:
        return [(inicio, max(inicio, ahora), tarea.estado_id)]
    tramos = []
    estado = _id_estado(cambios[0][1].valor_anterior)
    desde = min(inicio, cambios[0][0])
    for momento, evento in cambios:
        tramos.append((desde, momento, estado))
        desde, estado = momento, _id_estado(evento.valor_nuevo)
    tramos.append((desde, max(desde, ahora), estado))
    return tramos


def tiempo_medio_por_columna(
    tareas: list[Tarea], historial: list, ahora: datetime | None = None
) -> dict[int, tuple[float, int]]:
    """Por estado_id: (días medios que una tarea pasa en esa columna, tareas medidas).

    Se promedia por tarea (suma de sus estancias en la columna), no por visita.
    """
    # SQLite guarda las marcas en UTC y sin zona; se compara en esa misma referencia.
    ahora = ahora or datetime.now(UTC).replace(tzinfo=None)
    acumulado: dict[int, list[float]] = defaultdict(list)
    for tarea in tareas:
        por_estado: dict[int, float] = defaultdict(float)
        for desde, hasta, estado in trayectoria_estados(tarea, historial, ahora):
            if estado is not None:
                por_estado[estado] += (hasta - desde).total_seconds() / 86400
        for estado, dias in por_estado.items():
            acumulado[estado].append(dias)
    return {e: (sum(v) / len(v), len(v)) for e, v in acumulado.items()}


def flujo_acumulado(
    tareas: list[Tarea], historial: list, hoy: date | None = None, maximo_dias: int = 120
) -> tuple[list[date], dict[int, list[int]]]:
    """CFD: para cada día, cuántas tareas había en cada estado al terminar ese día.

    Devuelve (días, {estado_id: [conteo por día]}). Cubre desde la primera creación
    hasta hoy, recortado a los últimos `maximo_dias`. Una tarea cuenta desde el día
    en que se creó.
    """
    hoy = hoy or datetime.now(UTC).date()
    ahora = datetime.combine(hoy, datetime.max.time())
    trayectorias = [trayectoria_estados(t, historial, ahora) for t in tareas]
    inicios = [tramos[0][0].date() for tramos in trayectorias if tramos]
    if not inicios:
        return [], {}
    primero = max(min(inicios), hoy - timedelta(days=maximo_dias - 1))
    dias = [primero + timedelta(days=i) for i in range((hoy - primero).days + 1)]
    conteos: dict[int, list[int]] = defaultdict(lambda: [0] * len(dias))
    for tramos in trayectorias:
        for indice, dia in enumerate(dias):
            fin_dia = datetime.combine(dia, datetime.max.time())
            if tramos[0][0] > fin_dia:
                continue
            estado = next((e for desde, hasta, e in reversed(tramos) if desde <= fin_dia), None)
            if estado is not None:
                conteos[estado][indice] += 1
    return dias, dict(conteos)


def eventos_con_fecha_de_finalizacion(
    tareas: list[Tarea], eventos: list[HistorialTarea], id_estado_final: int | None = None
) -> list[HistorialTarea]:
    """Historial en el que cada finalización cae en la fecha de fin real de su tarea.

    Quita los eventos que marcaban una finalización en el momento de guardar el cambio (pasar
    al 100 %, fijar el fin real, entrar en la columna final) y añade uno por cada tarea
    completada, fechado en su `fecha_completada`. Así una tarea dada de alta con retraso
    cuenta el día en que se terminó, y una reabierta deja de contar como completada.
    """
    resultado = [
        e for e in eventos
        if e.tipo != "fin_real"
        and not (e.tipo == "progreso" and e.valor_nuevo == "100")
        and not (e.tipo == "estado" and id_estado_final is not None and e.valor_nuevo == str(id_estado_final))
    ]
    for tarea in tareas:
        if (dia := fecha_completada(tarea)) is not None:
            resultado.append(HistorialTarea(
                id=-tarea.id, tarea_id=tarea.id, creado=f"{dia}T12:00:00Z",
                tipo="fin_real", campo="fecha_fin_real", valor_nuevo=dia,
            ))
    return resultado
