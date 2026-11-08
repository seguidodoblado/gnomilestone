from datetime import date

from gnomilestone import ganttcalc
from gnomilestone.models import Dependencia, Tarea


def test_parse_fecha():
    assert ganttcalc.parse_fecha("2026-03-05") == date(2026, 3, 5)


def test_fecha_a_x():
    origen = date(2026, 3, 1)
    assert ganttcalc.fecha_a_x(date(2026, 3, 1), origen, 20.0) == 0
    assert ganttcalc.fecha_a_x(date(2026, 3, 6), origen, 20.0) == 100


def test_x_a_fecha_es_inversa_de_fecha_a_x():
    origen = date(2026, 3, 1)
    fecha = date(2026, 3, 10)
    x = ganttcalc.fecha_a_x(fecha, origen, 15.0)
    assert ganttcalc.x_a_fecha(x, origen, 15.0) == fecha


def test_ancho_duracion():
    assert ganttcalc.ancho_duracion(5, 10.0) == 50.0
    assert ganttcalc.ancho_duracion(0, 10.0) == 10.0  # mínimo de 1 día de ancho


def _tarea(id_, fecha_inicio, duracion_dias=1):
    return Tarea(id=id_, proyecto_id=1, titulo=f"T{id_}", fecha_inicio=fecha_inicio,
                 duracion_dias=duracion_dias)


def test_recalcular_dependientes_empuja_al_sucesor_si_se_solapa():
    tareas = [_tarea(1, "2026-03-01", 5), _tarea(2, "2026-03-03", 2)]
    deps = [Dependencia(id=1, tarea_origen_id=1, tarea_destino_id=2)]
    cambiadas = ganttcalc.recalcular_dependientes(tareas, deps, 1)
    assert len(cambiadas) == 1
    assert cambiadas[0].id == 2
    assert cambiadas[0].fecha_inicio == "2026-03-06"  # 1 termina el día 6 (01 + 5 días)


def test_recalcular_dependientes_no_toca_nada_si_no_hay_solape():
    tareas = [_tarea(1, "2026-03-01", 2), _tarea(2, "2026-03-10")]
    deps = [Dependencia(id=1, tarea_origen_id=1, tarea_destino_id=2)]
    assert ganttcalc.recalcular_dependientes(tareas, deps, 1) == []


def test_recalcular_dependientes_propaga_en_cascada():
    tareas = [_tarea(1, "2026-03-01", 5), _tarea(2, "2026-03-03", 2), _tarea(3, "2026-03-04", 3)]
    deps = [
        Dependencia(id=1, tarea_origen_id=1, tarea_destino_id=2),
        Dependencia(id=2, tarea_origen_id=2, tarea_destino_id=3),
    ]
    cambiadas = {t.id: t for t in ganttcalc.recalcular_dependientes(tareas, deps, 1)}
    assert cambiadas[2].fecha_inicio == "2026-03-06"
    assert cambiadas[3].fecha_inicio == "2026-03-08"  # 2 ahora termina el día 8 (06 + 2)


def test_recalcular_dependientes_ignora_tareas_sin_fecha():
    tareas = [_tarea(1, "2026-03-01", 5), _tarea(2, None)]
    deps = [Dependencia(id=1, tarea_origen_id=1, tarea_destino_id=2)]
    assert ganttcalc.recalcular_dependientes(tareas, deps, 1) == []


def test_limitar_hijo_a_padre_dentro_de_rango_no_cambia():
    inicio, duracion = ganttcalc.limitar_hijo_a_padre(
        date(2026, 3, 3), 2, date(2026, 3, 1), 10
    )
    assert (inicio, duracion) == (date(2026, 3, 3), 2)


def test_limitar_hijo_a_padre_recorta_inicio_anterior_al_padre():
    inicio, _duracion = ganttcalc.limitar_hijo_a_padre(
        date(2026, 2, 25), 2, date(2026, 3, 1), 10
    )
    assert inicio == date(2026, 3, 1)


def test_limitar_hijo_a_padre_recorta_duracion_que_se_sale_del_padre():
    inicio, duracion = ganttcalc.limitar_hijo_a_padre(
        date(2026, 3, 5), 20, date(2026, 3, 1), 10
    )
    assert inicio == date(2026, 3, 5)
    assert duracion == 6  # el padre termina el día 11 (01 + 10)


def test_limitar_hijo_a_padre_con_padre_muy_corto_deja_al_menos_un_dia():
    _inicio, duracion = ganttcalc.limitar_hijo_a_padre(
        date(2026, 3, 10), 5, date(2026, 3, 1), 1
    )
    assert duracion == 1


def test_trasladar_hijos_sin_delta_no_devuelve_nada():
    tareas = [_tarea(1, "2026-03-01", 5), _tarea(2, "2026-03-02", 2)]
    tareas[1].padre_id = 1
    assert ganttcalc.trasladar_hijos(tareas, 1, 0) == []


def test_trasladar_hijos_mueve_hijo_directo_el_mismo_delta():
    padre = _tarea(1, "2026-03-01", 5)
    hijo = _tarea(2, "2026-03-02", 2)
    hijo.padre_id = 1
    cambiadas = ganttcalc.trasladar_hijos([padre, hijo], 1, 3)
    assert len(cambiadas) == 1
    assert cambiadas[0].id == 2
    assert cambiadas[0].fecha_inicio == "2026-03-05"


def test_trasladar_hijos_mueve_nietos_en_cascada():
    padre = _tarea(1, "2026-03-01", 5)
    hijo = _tarea(2, "2026-03-02", 2)
    hijo.padre_id = 1
    nieto = _tarea(3, "2026-03-02", 1)
    nieto.padre_id = 2
    cambiadas = {t.id: t for t in ganttcalc.trasladar_hijos([padre, hijo, nieto], 1, -2)}
    assert cambiadas[2].fecha_inicio == "2026-02-28"
    assert cambiadas[3].fecha_inicio == "2026-02-28"


def test_trasladar_hijos_ignora_hijos_sin_fecha():
    padre = _tarea(1, "2026-03-01", 5)
    hijo = _tarea(2, None)
    hijo.padre_id = 1
    assert ganttcalc.trasladar_hijos([padre, hijo], 1, 3) == []


def test_limitar_hijos_tras_redimensionar_recorta_a_las_que_ya_no_caben():
    padre = _tarea(1, "2026-03-01", 10)
    dentro = _tarea(2, "2026-03-02", 2)
    dentro.padre_id = 1
    fuera = _tarea(3, "2026-03-05", 20)
    fuera.padre_id = 1
    cambiadas = {
        t.id: t
        for t in ganttcalc.limitar_hijos_tras_redimensionar(
            [padre, dentro, fuera], 1, date(2026, 3, 1), 10
        )
    }
    assert 2 not in cambiadas  # ya cabía, no se toca
    assert cambiadas[3].duracion_dias == 6  # recortada al nuevo fin del padre (11/03)


def test_limitar_hijos_tras_redimensionar_no_toca_nietos_que_ya_caben():
    padre = _tarea(1, "2026-03-01", 10)
    hijo = _tarea(2, "2026-03-01", 5)
    hijo.padre_id = 1
    nieto = _tarea(3, "2026-03-01", 2)  # cabe de sobra en su padre (la hija)
    nieto.padre_id = 2
    cambiadas = ganttcalc.limitar_hijos_tras_redimensionar([padre, hijo, nieto], 1, date(2026, 3, 1), 10)
    assert cambiadas == []


def test_limitar_hijos_tras_redimensionar_recorta_nietos_en_cascada():
    # Abuela (1) se encoge a 3 días; hija (2) se recorta con ella, y la nieta (3), que
    # cabía en la hija original pero no en la ya recortada, se recorta a su vez.
    padre = _tarea(1, "2026-03-01", 3)
    hijo = _tarea(2, "2026-03-01", 10)
    hijo.padre_id = 1
    nieto = _tarea(3, "2026-03-05", 2)  # dentro de la hija (01-11/03) pero no del nuevo padre
    nieto.padre_id = 2
    cambiadas = {
        t.id: t
        for t in ganttcalc.limitar_hijos_tras_redimensionar([padre, hijo, nieto], 1, date(2026, 3, 1), 3)
    }
    assert cambiadas[2].duracion_dias == 3  # la hija se recorta al rango del padre (01-04/03)

    assert cambiadas[3].fecha_inicio == "2026-03-03"  # la nieta se recorta al rango ya recortado


def _tarea_vencimiento(
    fecha_inicio=None,
    fecha_fin_planificada=None,
    fecha_limite=None,
    duracion_dias=1,
    porcentaje_completado=0,
):
    return Tarea(
        id=1,
        proyecto_id=1,
        titulo="T",
        fecha_inicio=fecha_inicio,
        fecha_fin_planificada=fecha_fin_planificada,
        fecha_limite=fecha_limite,
        duracion_dias=duracion_dias,
        porcentaje_completado=porcentaje_completado,
    )


def test_estado_vencimiento_sin_fechas_ni_porcentaje_no_aplica():
    assert ganttcalc.estado_vencimiento(_tarea_vencimiento(), hoy=date(2026, 3, 1)) is None


def test_estado_vencimiento_no_marca_tareas_completadas():
    tarea = _tarea_vencimiento("2026-01-01", "2026-01-01", "2026-01-02", porcentaje_completado=100)
    assert ganttcalc.estado_vencimiento(tarea, hoy=date(2026, 3, 1)) is None


def test_fecha_fin_planificada_usa_la_fecha_explicita():
    tarea = _tarea_vencimiento("2026-03-01", fecha_fin_planificada="2026-03-10", duracion_dias=20)
    assert ganttcalc.fecha_fin_planificada(tarea) == date(2026, 3, 10)


def test_fecha_fin_planificada_cae_al_ultimo_dia_de_la_duracion():
    tarea = _tarea_vencimiento("2026-03-01", duracion_dias=5)
    assert ganttcalc.fecha_fin_planificada(tarea) == date(2026, 3, 5)


def test_estado_vencimiento_naranja_al_llegar_al_final_planificado():
    tarea = _tarea_vencimiento("2026-03-01", fecha_fin_planificada="2026-03-05")
    assert ganttcalc.estado_vencimiento(tarea, hoy=date(2026, 3, 6)) == ganttcalc.PLANIFICADA_PASADA


def test_estado_vencimiento_marca_el_ultimo_dia_planificado():
    tarea = _tarea_vencimiento("2026-03-01", fecha_fin_planificada="2026-03-05")
    assert ganttcalc.estado_vencimiento(tarea, hoy=date(2026, 3, 5)) is None


def test_estado_vencimiento_rojo_al_llegar_a_la_fecha_limite():
    tarea = _tarea_vencimiento("2026-03-01", "2026-03-05", "2026-03-08")
    assert ganttcalc.estado_vencimiento(tarea, hoy=date(2026, 3, 9)) == ganttcalc.VENCIDA


def test_estado_vencimiento_no_marca_rojo_hasta_pasada_la_fecha_limite():
    tarea = _tarea_vencimiento("2026-03-01", "2026-03-05", "2026-03-08")
    assert ganttcalc.estado_vencimiento(tarea, hoy=date(2026, 3, 8)) == ganttcalc.VENCIDA


def test_estado_vencimiento_rojo_un_dia_antes_de_la_fecha_limite():
    tarea = _tarea_vencimiento("2026-03-01", "2026-03-05", "2026-03-08")
    assert ganttcalc.estado_vencimiento(tarea, hoy=date(2026, 3, 7)) == ganttcalc.VENCIDA


def test_estado_vencimiento_usa_una_ventana_configurable():
    tarea = _tarea_vencimiento(
        "2026-03-01", fecha_fin_planificada="2026-03-20", fecha_limite="2026-03-10"
    )
    assert ganttcalc.estado_vencimiento(tarea, hoy=date(2026, 3, 7), dias_alerta=2) is None
    assert ganttcalc.estado_vencimiento(tarea, hoy=date(2026, 3, 7), dias_alerta=3) == ganttcalc.VENCIDA


def test_estado_vencimiento_con_cero_dias_espera_al_dia_limite():
    tarea = _tarea_vencimiento(
        "2026-03-01", fecha_fin_planificada="2026-03-20", fecha_limite="2026-03-10"
    )
    assert ganttcalc.estado_vencimiento(tarea, hoy=date(2026, 3, 9), dias_alerta=0) is None
    assert ganttcalc.estado_vencimiento(tarea, hoy=date(2026, 3, 10), dias_alerta=0) == ganttcalc.VENCIDA


def test_estado_vencimiento_rojo_sin_fecha_de_inicio():
    tarea = _tarea_vencimiento(fecha_limite="2026-03-08")
    assert ganttcalc.estado_vencimiento(tarea, hoy=date(2026, 3, 9)) == ganttcalc.VENCIDA


def test_sincronizar_fin_planificado_usa_el_ultimo_dia_de_la_duracion():
    tarea = ganttcalc.sincronizar_fin_planificado(_tarea(1, "2026-03-01", 5))
    assert tarea.fecha_fin_planificada == "2026-03-05"


def test_sincronizar_fin_planificado_corrige_un_valor_obsoleto():
    tarea = _tarea(1, "2026-03-01", 5)
    tarea.fecha_fin_planificada = "2026-03-20"
    assert ganttcalc.sincronizar_fin_planificado(tarea).fecha_fin_planificada == "2026-03-05"


def test_sincronizar_fin_planificado_no_toca_tareas_sin_inicio():
    tarea = _tarea(1, None, 5)
    assert ganttcalc.sincronizar_fin_planificado(tarea) is tarea


def test_trasladar_hijos_actualiza_el_final_planificado():
    padre = _tarea(1, "2026-03-01", 5)
    hijo = _tarea(2, "2026-03-02", 2)
    hijo.padre_id = 1
    cambiadas = ganttcalc.trasladar_hijos([padre, hijo], 1, 3)
    assert cambiadas[0].fecha_inicio == "2026-03-05"
    assert cambiadas[0].fecha_fin_planificada == "2026-03-06"


def test_recalcular_dependientes_actualiza_el_final_planificado():
    tareas = [_tarea(1, "2026-03-01", 5), _tarea(2, "2026-03-03", 2)]
    deps = [Dependencia(id=1, tarea_origen_id=1, tarea_destino_id=2)]
    cambiadas = ganttcalc.recalcular_dependientes(tareas, deps, 1)
    assert cambiadas[0].fecha_inicio == "2026-03-06"
    assert cambiadas[0].fecha_fin_planificada == "2026-03-07"


def test_limitar_hijos_tras_redimensionar_actualiza_el_final_planificado():
    padre = _tarea(1, "2026-03-01", 10)
    fuera = _tarea(3, "2026-03-05", 20)
    fuera.padre_id = 1
    cambiadas = {
        t.id: t
        for t in ganttcalc.limitar_hijos_tras_redimensionar(
            [padre, fuera], 1, date(2026, 3, 1), 10
        )
    }
    assert cambiadas[3].duracion_dias == 6
    assert cambiadas[3].fecha_fin_planificada == "2026-03-10"


def test_marcas_regla_meses_a_zoom_bajo():
    from datetime import date

    from gnomilestone.ganttcalc import etiqueta_marca, marcas_regla

    origen = date(2026, 11, 8)
    marcas = marcas_regla(origen, 4.0, 400)  # Anual: ~100 días
    assert [(f, t) for f, t in marcas] == [
        (date(2026, 12, 1), "mes"),
        (date(2027, 1, 1), "mes"),
        (date(2027, 2, 1), "mes"),
    ]
    # Trimestral (8 px/día) también marca meses, igual en Gantt y en Uso.
    assert all(t == "mes" for _f, t in marcas_regla(origen, 8.0, 400))
    assert etiqueta_marca(date(2027, 1, 1), "mes").endswith("2027")
    assert "2026" in etiqueta_marca(date(2026, 12, 1), "mes", primera=True)
    assert "2026" not in etiqueta_marca(date(2026, 12, 1), "mes")


def test_marcas_regla_semanas_y_dias():
    from datetime import date

    from gnomilestone.ganttcalc import marcas_regla

    origen = date(2026, 11, 8)
    semanal = marcas_regla(origen, 18.0, 400)
    assert [f for f, _t in semanal][:3] == [date(2026, 11, 8), date(2026, 11, 15), date(2026, 11, 22)]
    assert all(t == "dia" for _f, t in semanal)
    diario = marcas_regla(origen, 80.0, 400)
    assert [f for f, _t in diario][:2] == [date(2026, 11, 8), date(2026, 11, 9)]
