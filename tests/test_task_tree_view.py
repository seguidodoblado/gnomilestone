from gnomilestone.models import Tarea
from gnomilestone.ui.task_tree_view import construir_filas, ordenar_jerarquicamente


def _tarea(id_, padre_id=None, orden=0, titulo=None):
    return Tarea(id=id_, proyecto_id=1, titulo=titulo or f"T{id_}", padre_id=padre_id, orden=orden)


def test_construir_filas_jerarquia_simple():
    tareas = [
        _tarea(1, orden=0),
        _tarea(2, orden=1),
        _tarea(11, padre_id=1, orden=0),
        _tarea(12, padre_id=1, orden=1),
    ]
    raices = construir_filas(tareas, estados_por_id={})
    assert [r.titulo for r in raices] == ["T1", "T2"]
    assert [h.titulo for h in raices[0].hijos] == ["T11", "T12"]
    assert raices[1].hijos == []


def test_construir_filas_respeta_el_orden_de_hermanos():
    tareas = [_tarea(1, orden=5), _tarea(2, orden=1), _tarea(3, orden=3)]
    raices = construir_filas(tareas, estados_por_id={})
    assert [r.titulo for r in raices] == ["T2", "T3", "T1"]


def test_construir_filas_asocia_el_nombre_del_estado():
    tareas = [_tarea(1)]
    tareas[0].estado_id = 7
    raices = construir_filas(tareas, estados_por_id={7: "En curso"})
    assert raices[0].estado == "En curso"


def test_ordenar_jerarquicamente_raices_sin_prefijo():
    tareas = [_tarea(1), _tarea(2, orden=1)]
    resultado = [(t.id, prefijo) for t, prefijo in ordenar_jerarquicamente(tareas)]
    assert resultado == [(1, ""), (2, "")]


def test_ordenar_jerarquicamente_conectores_de_subtareas():
    tareas = [
        _tarea(1),
        _tarea(2, orden=1),
        _tarea(11, padre_id=1, orden=0),
        _tarea(12, padre_id=1, orden=1),
        _tarea(111, padre_id=11, orden=0),
    ]
    resultado = [(t.id, prefijo) for t, prefijo in ordenar_jerarquicamente(tareas)]
    assert resultado == [
        (1, ""),
        (11, "├─ "),
        (111, "│  └─ "),
        (12, "└─ "),
        (2, ""),

    ]
