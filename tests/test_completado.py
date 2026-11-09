from gnomilestone.completado import al_cambiar_de_columna, id_columna_final
from gnomilestone.models import EstadoTablero, Tarea

PENDIENTE, EN_CURSO, HECHO = 1, 2, 3


def _estados(final=True):
    return [
        EstadoTablero(id=PENDIENTE, proyecto_id=1, nombre="Pendiente", orden=0),
        EstadoTablero(id=EN_CURSO, proyecto_id=1, nombre="En curso", orden=1),
        EstadoTablero(id=HECHO, proyecto_id=1, nombre="Hecho", orden=2, es_final=final),
    ]


def _tarea(estado_id, porcentaje):
    return Tarea(id=1, proyecto_id=1, titulo="T", estado_id=estado_id, porcentaje_completado=porcentaje)


def test_entrar_en_la_columna_final_completa_y_recuerda_el_porcentaje():
    tarea = _tarea(EN_CURSO, 60)
    al_cambiar_de_columna(tarea, HECHO, _estados())
    assert (tarea.porcentaje_completado, tarea.porcentaje_previo) == (100, 60)


def test_salir_de_la_columna_final_restituye_el_porcentaje_previo():
    tarea = _tarea(EN_CURSO, 60)
    al_cambiar_de_columna(tarea, HECHO, _estados())
    tarea.estado_id = HECHO
    al_cambiar_de_columna(tarea, EN_CURSO, _estados())
    assert (tarea.porcentaje_completado, tarea.porcentaje_previo) == (60, None)


def test_salir_sin_porcentaje_previo_deja_a_cero():
    tarea = _tarea(HECHO, 100)
    al_cambiar_de_columna(tarea, PENDIENTE, _estados())
    assert tarea.porcentaje_completado == 0


def test_sin_columna_final_marcada_no_hace_nada():
    tarea = _tarea(EN_CURSO, 60)
    al_cambiar_de_columna(tarea, HECHO, _estados(final=False))
    assert tarea.porcentaje_completado == 60
    assert id_columna_final(_estados(final=False)) is None


def test_mover_entre_columnas_normales_no_toca_el_porcentaje():
    tarea = _tarea(PENDIENTE, 30)
    al_cambiar_de_columna(tarea, EN_CURSO, _estados())
    assert tarea.porcentaje_completado == 30


def test_salir_de_la_final_con_menos_de_100_conserva_lo_que_tenga():
    # El usuario ya bajó el % a mano: no se pisa.
    tarea = _tarea(HECHO, 80)
    al_cambiar_de_columna(tarea, EN_CURSO, _estados())
    assert tarea.porcentaje_completado == 80


def test_fecha_fin_real_segun_el_porcentaje():
    from datetime import date

    from gnomilestone.completado import fecha_fin_real_para

    hoy = date(2026, 11, 9)
    assert fecha_fin_real_para(100, None, hoy) == "2026-11-09"
    assert fecha_fin_real_para(100, "2026-11-01", hoy) == "2026-11-01"  # respeta la manual
    assert fecha_fin_real_para(60, "2026-11-01", hoy) is None
    assert fecha_fin_real_para(0, None, hoy) is None


def test_entrar_en_la_columna_final_pone_la_fecha_fin_real():
    tarea = _tarea(EN_CURSO, 60)
    al_cambiar_de_columna(tarea, HECHO, _estados())
    assert tarea.fecha_fin_real is not None


def test_entrar_con_fecha_fin_real_manual_la_conserva():
    tarea = _tarea(EN_CURSO, 60)
    tarea.fecha_fin_real = "2026-01-02"
    al_cambiar_de_columna(tarea, HECHO, _estados())
    assert tarea.fecha_fin_real == "2026-01-02"


def test_salir_de_la_columna_final_borra_la_fecha_fin_real():
    tarea = _tarea(HECHO, 100)
    tarea.porcentaje_previo = 60
    tarea.fecha_fin_real = "2026-01-02"
    al_cambiar_de_columna(tarea, EN_CURSO, _estados())
    assert (tarea.porcentaje_completado, tarea.fecha_fin_real) == (60, None)


def test_dependencias_sin_terminar_solo_cuenta_las_marcadas_incompletas_y_no_archivadas():
    from gnomilestone.completado import dependencias_sin_terminar

    def t(id_, pct, archivada=False):
        return Tarea(id=id_, proyecto_id=1, titulo=f"T{id_}", porcentaje_completado=pct, archivada=archivada)

    tareas = [t(1, 20), t(2, 100), t(3, 50, archivada=True), t(4, 0)]
    assert [x.id for x in dependencias_sin_terminar([1, 2, 3], tareas)] == [1]
    assert dependencias_sin_terminar([], tareas) == []
