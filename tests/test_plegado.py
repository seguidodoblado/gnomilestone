from gnomilestone.plegado import descendientes_por_tarea, ocultas_por_plegado

# 1
# ├─ 2
# │  └─ 4
# └─ 3
# 5
ARBOL = {1: None, 2: 1, 3: 1, 4: 2, 5: None}


def test_descendientes_cuenta_hijas_y_nietas():
    assert descendientes_por_tarea(ARBOL) == {1: 3, 2: 1}


def test_sin_plegadas_no_hay_ocultas():
    assert ocultas_por_plegado(ARBOL, set()) == set()


def test_plegar_un_padre_oculta_todos_sus_descendientes():
    assert ocultas_por_plegado(ARBOL, {1}) == {2, 3, 4}


def test_plegar_una_hija_solo_oculta_lo_suyo():
    assert ocultas_por_plegado(ARBOL, {2}) == {4}


def test_ciclos_no_cuelgan_el_calculo():
    ciclo = {1: 2, 2: 1}
    assert ocultas_por_plegado(ciclo, {1}) == {2}
    assert descendientes_por_tarea(ciclo)


def test_el_porcentaje_de_una_tarea_con_subtareas_es_el_agregado_de_sus_hojas():
    from gnomilestone import ganttcalc
    from gnomilestone.models import Tarea
    from gnomilestone.ui.task_tree_view import construir_filas

    padre = Tarea(id=1, proyecto_id=1, titulo="Padre", porcentaje_completado=0, duracion_dias=1)
    hija_a = Tarea(id=2, proyecto_id=1, titulo="A", padre_id=1, porcentaje_completado=100, duracion_dias=1)
    hija_b = Tarea(id=3, proyecto_id=1, titulo="B", padre_id=1, porcentaje_completado=0, duracion_dias=1)
    tareas = [padre, hija_a, hija_b]
    filas = construir_filas(tareas, {}, progreso_resumen=ganttcalc.progreso_resumen(tareas))
    assert filas[0].porcentaje_texto == "50 %"  # el 0 % propio del padre no se muestra
    assert [h.porcentaje_texto for h in filas[0].hijos] == ["100 %", "0 %"]
