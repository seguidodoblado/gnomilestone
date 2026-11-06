from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta

from gnomilestone.models import Dependencia, Tarea


def parse_fecha(fecha_iso: str) -> date:
    anio, mes, dia = (int(parte) for parte in fecha_iso.split("-"))
    return date(anio, mes, dia)


def formatear_fecha(fecha: date) -> str:
    return fecha.isoformat()


def fecha_a_x(fecha: date, fecha_origen: date, px_por_dia: float) -> float:
    return (fecha - fecha_origen).days * px_por_dia


def x_a_fecha(x: float, fecha_origen: date, px_por_dia: float) -> date:
    return fecha_origen + timedelta(days=round(x / px_por_dia))


def ancho_duracion(duracion_dias: int, px_por_dia: float) -> float:
    return max(duracion_dias, 1) * px_por_dia


def recalcular_dependientes(
    tareas: list[Tarea], dependencias: list[Dependencia], tarea_id: int
) -> list[Tarea]:
    """Tareas cuya fecha_inicio cambia en cascada para no empezar antes de que termine su
    predecesora, a partir de un cambio en `tarea_id`. No modifica las tareas recibidas:
    devuelve copias (con `dataclasses.replace`) de las que necesitan guardarse.

    El grafo de dependencias no puede tener ciclos (se impide al crearlas en `store.py`),
    así que un simple recorrido en anchura/profundidad desde `tarea_id` basta.
    """
    por_id = {tarea.id: tarea for tarea in tareas}
    sucesores: dict[int, list[int]] = {}
    for dependencia in dependencias:
        sucesores.setdefault(dependencia.tarea_origen_id, []).append(dependencia.tarea_destino_id)

    cambiadas: dict[int, Tarea] = {}
    pendientes = [tarea_id]
    while pendientes:
        origen_id = pendientes.pop()
        origen = cambiadas.get(origen_id, por_id.get(origen_id))
        if origen is None or not origen.fecha_inicio:
            continue
        fin_origen = parse_fecha(origen.fecha_inicio) + timedelta(days=max(origen.duracion_dias, 1))
        for destino_id in sucesores.get(origen_id, []):
            destino = cambiadas.get(destino_id, por_id.get(destino_id))
            if destino is None or not destino.fecha_inicio:
                continue
            if parse_fecha(destino.fecha_inicio) < fin_origen:
                cambiadas[destino_id] = replace(destino, fecha_inicio=formatear_fecha(fin_origen))
                pendientes.append(destino_id)

    return list(cambiadas.values())


def limitar_hijo_a_padre(
    fecha_inicio: date, duracion_dias: int, fecha_inicio_padre: date, duracion_padre_dias: int
) -> tuple[date, int]:
    """Recorta el rango de una subtarea para que quede dentro del de su tarea padre."""
    fin_padre = fecha_inicio_padre + timedelta(days=max(duracion_padre_dias, 1))
    ultimo_inicio_posible = fin_padre - timedelta(days=1)
    fecha_inicio = min(max(fecha_inicio, fecha_inicio_padre), ultimo_inicio_posible)
    duracion_maxima = (fin_padre - fecha_inicio).days
    duracion_dias = max(1, min(duracion_dias, duracion_maxima))
    return fecha_inicio, duracion_dias


def trasladar_hijos(tareas: list[Tarea], tarea_id: int, delta_dias: int) -> list[Tarea]:
    """Al MOVER una tarea padre, sus descendientes (hijos, nietos...) se mueven con ella,
    el mismo número de días, para conservar su posición relativa. Copias (con
    `dataclasses.replace`) de las tareas que hay que guardar; no modifica las recibidas."""
    if delta_dias == 0:
        return []
    hijos_por_padre: dict[int | None, list[Tarea]] = {}
    for tarea in tareas:
        hijos_por_padre.setdefault(tarea.padre_id, []).append(tarea)

    resultado: list[Tarea] = []
    pendientes = [tarea_id]
    while pendientes:
        actual_id = pendientes.pop()
        for hijo in hijos_por_padre.get(actual_id, []):
            if hijo.fecha_inicio:
                nueva_fecha = parse_fecha(hijo.fecha_inicio) + timedelta(days=delta_dias)
                resultado.append(replace(hijo, fecha_inicio=formatear_fecha(nueva_fecha)))
            pendientes.append(hijo.id)
    return resultado


def limitar_hijos_tras_redimensionar(
    tareas: list[Tarea], tarea_id: int, fecha_inicio_padre: date, duracion_padre_dias: int
) -> list[Tarea]:
    """Al REDIMENSIONAR una tarea, sus descendientes (hijas, nietas, bisnietas...) que ya
    no quepan se recortan en cascada con `limitar_hijo_a_padre` (el padre manda en toda la
    rama, nunca al revés). Si recortar a una hija también desplaza su propio rango, sus
    hijas se recortan a su vez a ese rango ya recortado, y así sucesivamente. Copias de las
    tareas que hay que guardar; no modifica las recibidas."""
    cambiadas: dict[int, Tarea] = {}
    pendientes = [(tarea_id, fecha_inicio_padre, duracion_padre_dias)]
    while pendientes:
        padre_id, fecha_padre, duracion_padre = pendientes.pop()
        for tarea in tareas:
            if tarea.padre_id != padre_id or not tarea.fecha_inicio:
                continue
            actual = cambiadas.get(tarea.id, tarea)
            fecha_actual = parse_fecha(actual.fecha_inicio)
            nueva_fecha, nueva_duracion = limitar_hijo_a_padre(
                fecha_actual, actual.duracion_dias, fecha_padre, duracion_padre
            )
            if nueva_fecha != fecha_actual or nueva_duracion != actual.duracion_dias:
                cambiadas[tarea.id] = replace(
                    actual, fecha_inicio=formatear_fecha(nueva_fecha), duracion_dias=nueva_duracion
                )
            # Se sigue bajando con el rango de esta tarea (ya recortado si hizo falta),
            # para que sus propias hijas se ajusten a él.
            pendientes.append((tarea.id, nueva_fecha, nueva_duracion))
    return list(cambiadas.values())
