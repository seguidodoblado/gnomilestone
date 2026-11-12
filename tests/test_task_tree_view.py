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


def test_construir_filas_lleva_etiquetas_y_prioridad():
    from gnomilestone.models import Etiqueta
    from gnomilestone.ui.task_tree_view import nombre_prioridad

    tareas = [_tarea(1), _tarea(2)]
    tareas[0].prioridad = 3
    bug = Etiqueta(id=1, proyecto_id=1, nombre="bug", color="d73a4a")
    raices = construir_filas(tareas, {}, etiquetas_por_tarea={1: [bug]})
    assert raices[0].etiquetas == [bug]
    assert raices[1].etiquetas == []
    assert raices[0].prioridad == nombre_prioridad(3) == "Alta"
    assert raices[1].prioridad == ""


def test_ordenar_archivadas_indenta_solo_por_ancestros_tambien_archivados():
    from gnomilestone.ui.archived_dialog import ordenar_archivadas

    padre = _tarea(1, orden=0)
    hija = _tarea(2, padre_id=1, orden=1)
    suelta = _tarea(3, padre_id=99, orden=2)  # su padre sigue a la vista
    assert [(t.id, n) for t, n in ordenar_archivadas([suelta, hija, padre])] == [
        (1, 0), (2, 1), (3, 0),
    ]


def test_porcentaje_texto_lleva_el_simbolo_y_las_filas_sin_tarea_van_vacias():
    from gnomilestone.ui.task_tree_view import TareaRow

    tarea = _tarea(1)
    tarea.porcentaje_completado = 60
    assert construir_filas([tarea], {})[0].porcentaje_texto == "60 %"
    assert TareaRow("Proyecto", []).porcentaje_texto == ""


def test_la_fila_lleva_el_tipo_traducido():
    from gnomilestone.ui.task_tree_view import TareaRow

    tarea = Tarea(1, 1, "T", tipo="error")
    assert TareaRow(tarea=tarea, titulo="T", hijos=[]).tipo == "Error"
    assert TareaRow(tarea=Tarea(2, 1, "U"), titulo="U", hijos=[]).tipo == ""
