from datetime import date

from gnomilestone.hitos import avance_hito, esta_conseguido, esta_vencido, tareas_por_hito
from gnomilestone.models import Hito, Tarea


def t(i, pct=0, dur=1, hito_id=None):
    return Tarea(i, 1, f"T{i}", porcentaje_completado=pct, duracion_dias=dur, hito_id=hito_id)


def h(**kw):
    return Hito(1, 1, "H", **kw)


def test_tareas_por_hito_ignora_las_que_no_tienen_hito():
    grupos = tareas_por_hito([t(1, hito_id=5), t(2), t(3, hito_id=5), t(4, hito_id=6)])
    assert {k: [x.id for x in v] for k, v in grupos.items()} == {5: [1, 3], 6: [4]}


def test_avance_es_la_media_ponderada_por_duracion():
    tareas = [t(1, pct=100, dur=1), t(2, pct=0, dur=3)]
    assert avance_hito(h(), tareas) == 25


def test_avance_sin_tareas_depende_de_si_esta_conseguido():
    assert avance_hito(h(), []) == 0
    assert avance_hito(h(conseguido=True), []) == 100


def test_conseguido_a_mano_o_con_todas_las_tareas_completas():
    assert esta_conseguido(h(conseguido=True), [t(1)]) is True
    assert esta_conseguido(h(), [t(1, pct=100), t(2, pct=100)]) is True
    assert esta_conseguido(h(), [t(1, pct=100), t(2, pct=99)]) is False
    assert esta_conseguido(h(), []) is False


def test_vencido_solo_si_la_fecha_paso_y_no_esta_conseguido():
    hoy = date(2026, 11, 20)
    assert esta_vencido(h(fecha="2026-11-19"), [], hoy) is True
    assert esta_vencido(h(fecha="2026-11-20"), [], hoy) is False
    assert esta_vencido(h(fecha="2026-11-19", conseguido=True), [], hoy) is False
    assert esta_vencido(h(), [], hoy) is False


def test_asignar_tareas_a_hito_pone_y_quita_el_hito(tmp_path):
    from gnomilestone.store import Store
    from gnomilestone.ui.asignar_hito import asignar_tareas_a_hito

    store = Store(tmp_path / "t.db")
    p = store.crear_proyecto("P")  # sin repo: no se envía nada a GitHub
    hito = store.crear_hito(p.id, "H")
    a = store.crear_tarea(p.id, "A")
    b = store.crear_tarea(p.id, "B", hito_id=hito.id)

    asignar_tareas_a_hito(store, [a.id], hito.id)
    assert store.obtener_tarea(a.id).hito_id == hito.id
    asignar_tareas_a_hito(store, [a.id, b.id], None)
    assert store.obtener_tarea(a.id).hito_id is None
    assert store.obtener_tarea(b.id).hito_id is None
