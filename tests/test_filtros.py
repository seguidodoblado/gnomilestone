from gnomilestone.filtros import ocultar_completadas
from gnomilestone.models import Tarea


def _tarea(id_, porcentaje=0, padre_id=None):
    return Tarea(
        id=id_,
        proyecto_id=1,
        titulo=f"T{id_}",
        padre_id=padre_id,
        porcentaje_completado=porcentaje,
    )


def test_sin_completadas_no_cambia_nada():
    tareas = [_tarea(1), _tarea(2, 50)]
    assert ocultar_completadas(tareas) == tareas


def test_oculta_una_tarea_completada_sin_subtareas():
    pendiente = _tarea(1)
    completada = _tarea(2, 100)
    assert ocultar_completadas([pendiente, completada]) == [pendiente]


def test_oculta_un_arbol_completo_completado():
    padre = _tarea(1, 100)
    hija = _tarea(2, 100, padre_id=1)
    nieta = _tarea(3, 100, padre_id=2)
    assert ocultar_completadas([padre, hija, nieta]) == []


def test_conserva_la_tarea_resumen_si_tiene_trabajo_pendiente():
    padre = _tarea(1, 100)
    hija_pendiente = _tarea(2, 40, padre_id=1)
    hija_completada = _tarea(3, 100, padre_id=1)
    assert ocultar_completadas([padre, hija_pendiente, hija_completada]) == [
        padre,
        hija_pendiente,
    ]


def test_conserva_la_cadena_hasta_una_nieta_pendiente():
    padre = _tarea(1, 100)
    hija = _tarea(2, 100, padre_id=1)
    nieta_pendiente = _tarea(3, 0, padre_id=2)
    assert ocultar_completadas([padre, hija, nieta_pendiente]) == [
        padre,
        hija,
        nieta_pendiente,
    ]


def test_lista_vacia():
    assert ocultar_completadas([]) == []
