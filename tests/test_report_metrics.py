from gnomilestone.models import Asignacion, Dependencia, EstadoTablero, Proyecto, Recurso, Tarea
from gnomilestone.report_metrics import (
    estado_github,
    reparto_por_recurso,
    recursos_sin_tareas,
    resumen_multi_proyecto,
    ruta_critica,
)


def tarea(i, **kwargs):
    return Tarea(i, 1, f"T{i}", duracion_dias=kwargs.pop("duracion_dias", 1), **kwargs)


def test_ruta_critica_elige_la_rama_mas_larga():
    tareas = [
        tarea(1, duracion_dias=2, fecha_limite="2000-01-01"),
        tarea(2, duracion_dias=5),
        tarea(3, duracion_dias=1, fecha_limite="2000-01-01"),
    ]
    deps = [Dependencia(1, 1, 3), Dependencia(2, 2, 3)]
    assert [t.id for t in ruta_critica(tareas, deps)] == [1, 3]


def test_reparto_y_recursos_sin_asignar():
    recursos = [Recurso(1, 1, "Ana"), Recurso(2, 1, "Luis")]
    tareas = [tarea(1, porcentaje_completado=50)]
    reparto = reparto_por_recurso(recursos, tareas, [Asignacion(1, 1, 1)])
    assert reparto[0].tareas == 1
    assert reparto[0].progreso_medio == 50
    assert [r.nombre for r in recursos_sin_tareas(reparto)] == ["Luis"]


def test_estado_github_y_resumen_global():
    vinculada = tarea(1, github_issue_number=3, porcentaje_completado=40)
    local = tarea(2, porcentaje_completado=80)
    assert estado_github([vinculada, local], conflictos=2).locales == 1
    resumen = resumen_multi_proyecto([Proyecto(1, "P")], [vinculada, local])
    assert resumen["tareas"] == 2
    assert resumen["progreso_medio"] == 60
