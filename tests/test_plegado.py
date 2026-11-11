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
