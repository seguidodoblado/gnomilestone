from datetime import date, datetime, timedelta

from gnomilestone.models import Asignacion, Dependencia, HistorialTarea, Proyecto, Recurso, Tarea
from gnomilestone.report_metrics import (
    estado_github,
    eventos_con_fecha_de_finalizacion,
    fechas_planificadas_reales,
    flujo_acumulado,
    recursos_sin_tareas,
    reparto_por_recurso,
    resumen_desviacion,
    resumen_multi_proyecto,
    ruta_critica,
    tiempo_medio_por_columna,
    trayectoria_estados,
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




def planificada(i, inicio, fin_inicial, fin_actual=None, real=None, **kw):
    return tarea(
        i, fecha_inicio=inicio, fecha_fin_planificada_inicial=fin_inicial,
        fecha_fin_planificada=fin_actual or fin_inicial, fecha_fin_real=real, **kw,
    )


def test_desviacion_de_tareas_terminadas_y_en_curso():
    hoy = datetime.now().astimezone().date()
    ayer = (hoy - timedelta(days=3)).isoformat()
    tareas = [
        planificada(1, "2026-01-01", "2026-01-10", real="2026-01-13", porcentaje_completado=100),
        planificada(2, "2026-01-01", "2026-01-10", real="2026-01-09", porcentaje_completado=100),
        planificada(3, "2026-01-01", "2026-01-10", real="2026-01-10", porcentaje_completado=100),
        planificada(4, "2026-01-01", ayer, porcentaje_completado=20),
        planificada(5, "2026-01-01", (hoy + timedelta(days=9)).isoformat(), porcentaje_completado=20),
        tarea(6),  # sin fechas: no entra
    ]
    resumen = resumen_desviacion(tareas)
    assert (resumen.a_tiempo, resumen.adelantadas, resumen.con_retraso, resumen.sin_medir) == (1, 1, 2, 1)
    assert [f.tarea.id for f in resumen.peores] == [1, 4]
    assert resumen.retraso_medio == 3
    assert len(fechas_planificadas_reales(tareas)) == 5


def estado_evt(i, tarea_id, momento, antes, despues):
    return HistorialTarea(i, tarea_id, momento, "estado", "estado_id", str(antes), str(despues))


def test_trayectoria_y_tiempo_medio_por_columna():
    t = tarea(1, estado_id=3, creado="2026-11-01 00:00:00")
    hist = [estado_evt(1, 1, "2026-11-03 00:00:00", 1, 2), estado_evt(2, 1, "2026-11-04 12:00:00", 2, 3)]
    ahora = datetime.fromisoformat("2026-11-06T00:00:00")
    assert [e for _d, _h, e in trayectoria_estados(t, hist, ahora)] == [1, 2, 3]
    medios = tiempo_medio_por_columna([t], hist, ahora)
    assert medios[1] == (2.0, 1)
    assert medios[2] == (1.5, 1)
    assert medios[3] == (1.5, 1)


def test_tarea_sin_cambios_cuenta_en_su_estado_actual():
    t = tarea(1, estado_id=2, creado="2026-11-01 00:00:00")
    assert tiempo_medio_por_columna([t], [], datetime.fromisoformat("2026-11-03T00:00:00"))[2] == (2.0, 1)


def test_flujo_acumulado_cuenta_por_dia_y_estado():
    a = tarea(1, estado_id=2, creado="2026-11-01 08:00:00")
    b = tarea(2, estado_id=1, creado="2026-11-02 08:00:00")
    hist = [estado_evt(1, 1, "2026-11-02 10:00:00", 1, 2)]
    dias, conteos = flujo_acumulado([a, b], hist, hoy=date(2026, 11, 3))
    assert dias == [date(2026, 11, 1), date(2026, 11, 2), date(2026, 11, 3)]
    assert conteos[1] == [1, 1, 1]  # a el día 1; b desde el día 2
    assert conteos[2] == [0, 1, 1]
    assert flujo_acumulado([], [], hoy=date(2026, 11, 3)) == ([], {})


def test_las_finalizaciones_se_fechan_en_el_fin_real_de_la_tarea():
    hecha = tarea(1, porcentaje_completado=100, fecha_fin_real="2026-10-08", estado_id=9)
    abierta = tarea(2, porcentaje_completado=40)
    reabierta = tarea(3, porcentaje_completado=30, fecha_fin_real=None)
    eventos = [
        HistorialTarea(1, 1, "2026-11-10T09:00:00Z", "creacion"),
        HistorialTarea(2, 1, "2026-11-10T09:01:00Z", "progreso", "porcentaje_completado", "0", "100"),
        HistorialTarea(3, 1, "2026-11-10T09:01:00Z", "fin_real", "fecha_fin_real", None, "2026-11-10"),
        HistorialTarea(4, 1, "2026-11-10T09:01:00Z", "estado", "estado_id", "2", "9"),
        HistorialTarea(5, 2, "2026-11-10T09:02:00Z", "progreso", "porcentaje_completado", "0", "40"),
        HistorialTarea(6, 3, "2026-11-10T09:03:00Z", "progreso", "porcentaje_completado", "100", "30"),
    ]
    resultado = eventos_con_fecha_de_finalizacion([hecha, abierta, reabierta], eventos, id_estado_final=9)
    # Se conservan la creación y los avances que no son una finalización...
    assert sorted(e.id for e in resultado if e.id > 0) == [1, 5, 6]
    # ...y hay una sola finalización, en el fin real de la tarea y no en el día del alta.
    finales = [e for e in resultado if e.tipo == "fin_real"]
    assert [(e.tarea_id, e.creado[:10]) for e in finales] == [(1, "2026-10-08")]


def test_actividad_por_usuario_agrupa_y_deja_los_sin_autor_al_final():
    from gnomilestone.models import Usuario
    from gnomilestone.report_metrics import actividad_por_usuario

    usuarios = [Usuario(1, "Ana"), Usuario(2, "Luis"), Usuario(3, "Eva")]
    ev = lambda i, uid: HistorialTarea(i, 1, "2026-11-10 10:00:00", "estado", usuario_id=uid)
    filas = actividad_por_usuario(usuarios, [ev(1, 2), ev(2, 2), ev(3, 1), ev(4, None), ev(5, 99)])
    assert [(f.usuario.nombre if f.usuario else None, f.cambios) for f in filas] == [
        ("Luis", 2), ("Ana", 1), ("Eva", 0), (None, 2),
    ]


def test_resultados_por_recurso():
    from gnomilestone.report_metrics import resultados_por_recurso

    hoy = date(2026, 11, 12)
    recursos = [Recurso(1, 1, "Ana"), Recurso(2, 1, "Luis")]
    tareas = [
        tarea(1, porcentaje_completado=100, fecha_fin_real="2026-11-05", fecha_fin_planificada_inicial="2026-11-06"),
        tarea(2, porcentaje_completado=100, fecha_fin_real="2026-10-05", fecha_fin_planificada_inicial="2026-10-01"),
        tarea(3, porcentaje_completado=40, estado_id=2, fecha_limite="2000-01-01", prioridad=4),
        tarea(4, porcentaje_completado=0, estado_id=1, prioridad=3),
        tarea(5, porcentaje_completado=0, estado_id=2),
    ]
    asig = [Asignacion(i, i, 1) for i in range(1, 6)]
    eventos = [
        HistorialTarea(1, 3, "2026-10-01 10:00:00", "progreso"),
        HistorialTarea(2, 5, "2026-11-11 10:00:00", "estado"),
    ]
    filas = resultados_por_recurso(recursos, tareas, asig, eventos, 1, hoy, 14)
    ana = next(f for f in filas if f.recurso.nombre == "Ana")
    assert (ana.hechas, ana.en_curso, ana.pendientes) == (2, 2, 1)
    assert (ana.hechas_30d, ana.hechas_30d_previas) == (1, 1)
    assert ana.a_tiempo == 50
    assert ana.estancadas == 1  # la 3: sin cambios desde el 1-oct; la 5 se movió ayer
    assert (ana.urgentes, ana.vencidas) == (2, 1)
    luis = next(f for f in filas if f.recurso.nombre == "Luis")
    assert luis.a_tiempo is None and luis.en_curso == 0
    # Con un umbral enorme nada está estancado.
    assert resultados_por_recurso(recursos, tareas, asig, eventos, 1, hoy, 90)[0].estancadas == 0


def test_trabajo_por_tipo_atribuye_por_asignacion():
    from gnomilestone.report_metrics import trabajo_por_tipo

    hoy = date(2026, 11, 12)
    recursos = [Recurso(1, 1, "Ana"), Recurso(2, 1, "Luis")]
    tareas = [
        tarea(1, porcentaje_completado=100, fecha_fin_real="2026-11-10", tipo="error"),
        tarea(2, porcentaje_completado=100, fecha_fin_real="2026-11-11", tipo="error"),
        tarea(3, porcentaje_completado=100, fecha_fin_real="2026-11-01"),
        tarea(4, porcentaje_completado=100, fecha_fin_real="2026-08-01", tipo="trabajo"),  # fuera de 30 d
        tarea(5, porcentaje_completado=20, tipo="funcionalidad"),
    ]
    asig = [Asignacion(i, i, 1) for i in (1, 2, 3, 4, 5)]
    hechas = trabajo_por_tipo(recursos, tareas, asig, True, hoy)
    assert hechas[0].recurso.nombre == "Ana" and hechas[0].por_tipo == {"error": 2, "": 1}
    assert hechas[1].total == 0
    abiertas = trabajo_por_tipo(recursos, tareas, asig, False, hoy)
    assert abiertas[0].por_tipo == {"funcionalidad": 1}
