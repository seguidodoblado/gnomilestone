from gnomilestone.documentacion import (
    eventos_roadmap,
    fecha_completada,
    historial_realizado,
    hitos_del_proyecto,
)
from gnomilestone.models import Hito, Tarea


def t(i, **kw):
    return Tarea(i, 1, f"T{i}", **kw)


def h(i, **kw):
    return Hito(i, 1, f"H{i}", **kw)


def test_historial_agrupa_completadas_por_dia_antiguo_primero():
    tareas = [
        t(1, porcentaje_completado=100, actualizado="2026-11-06T10:00:00Z"),
        t(2, porcentaje_completado=50, actualizado="2026-11-07T10:00:00Z"),
        t(3, porcentaje_completado=100, actualizado="2026-11-07T09:00:00Z"),
        t(4, porcentaje_completado=100, archivada=True, actualizado="2026-11-07T12:00:00Z"),
    ]
    historial = historial_realizado(tareas)
    assert [dia for dia, _g in historial] == ["2026-11-06", "2026-11-07"]
    assert [x.id for x in historial[1][1]] == [3, 4]


def test_hitos_ordenados_con_los_sin_fecha_al_final():
    hitos = [h(1), h(2, fecha="2026-12-01"), h(3, fecha="2026-11-01")]
    assert [x.id for x in hitos_del_proyecto(hitos)] == [3, 2, 1]


def test_roadmap_incluye_hitos_y_tareas_de_primer_nivel_con_fecha():
    tareas = [
        t(1, fecha_inicio="2026-11-10"),
        t(2, padre_id=1, fecha_inicio="2026-11-01"),  # subtarea: fuera
        t(4),  # sin fecha: fuera
        t(5, fecha_inicio="2026-11-01", fecha_limite="2026-11-20", porcentaje_completado=100),
    ]
    hitos = [h(7, fecha="2026-11-05"), h(8)]  # el Hito sin fecha no sale
    eventos = eventos_roadmap(tareas, hitos)
    assert [(e.id, e.fecha, e.es_hito) for e in eventos] == [
        (7, "2026-11-05", True), (1, "2026-11-10", False), (5, "2026-11-20", False),
    ]
    assert eventos[2].completado


def test_roadmap_marca_un_hito_conseguido_cuando_todas_sus_tareas_estan_completas():
    tareas = [t(1, hito_id=7, porcentaje_completado=100), t(2, hito_id=7, porcentaje_completado=100)]
    assert eventos_roadmap(tareas, [h(7, fecha="2026-11-05")])[0].completado is True
    tareas[1].porcentaje_completado = 50
    assert eventos_roadmap(tareas, [h(7, fecha="2026-11-05")])[0].completado is False


def test_secciones_por_titulo_ignora_titulos_dentro_de_codigo():
    from gnomilestone.documentacion import secciones_por_titulo

    texto = "intro\n\n# Uno\ntexto\n```\n# no es título\n```\n## Dos\nmás\n#### nivel 4\nfin"
    secciones = secciones_por_titulo(texto)
    assert [(s.nivel, s.titulo) for s in secciones] == [(None, None), (1, "Uno"), (2, "Dos")]
    assert secciones[1].markdown.startswith("# Uno") and "# no es título" in secciones[1].markdown
    assert "#### nivel 4" in secciones[2].markdown
    assert secciones_por_titulo("") == []
    assert [s.titulo for s in secciones_por_titulo("# Solo")] == ["Solo"]


def _arbol():
    from gnomilestone.models import NotaDocumentacion

    def n(i, titulo, padre=None):
        return NotaDocumentacion(i, 1, "arquitectura", titulo, subseccion_id=1, padre_id=padre)

    return [n(1, "Raíz A"), n(2, "Hija", 1), n(3, "Nieta", 2), n(4, "Raíz B"), n(5, "Hija B", 4)]


def test_hijas_ruta_y_descendientes():
    from gnomilestone.documentacion import descendientes, hijas, ruta_de

    notas = _arbol()
    assert [x.id for x in hijas(notas, None)] == [1, 4]
    assert [x.id for x in hijas(notas, 1)] == [2]
    assert [x.id for x in ruta_de(notas, 3)] == [1, 2, 3]
    assert ruta_de(notas, 99) == []
    assert descendientes(notas, 1) == {2, 3}
    assert descendientes(notas, 3) == set()


def test_candidatas_a_padre_excluye_la_nota_y_sus_descendientes_y_sangra():
    from gnomilestone.documentacion import candidatas_a_padre

    notas = _arbol()
    assert candidatas_a_padre(notas, 2) == [(1, "Raíz A"), (4, "Raíz B"), (5, "    Hija B")]
    assert [i for i, _t in candidatas_a_padre(notas, None)] == [1, 2, 3, 4, 5]


def test_el_historial_usa_la_fecha_de_fin_real_y_no_la_de_alta():
    # Dadas de alta el 10 de noviembre, pero terminadas antes: cuenta cuando se terminaron.
    tareas = [
        t(1, porcentaje_completado=100, fecha_fin_real="2026-10-08", actualizado="2026-11-10T09:00:00Z"),
        t(2, porcentaje_completado=100, fecha_fin_real="2026-10-08", actualizado="2026-11-10T09:05:00Z"),
        t(3, porcentaje_completado=100, fecha_fin_real="2026-10-20", actualizado="2026-11-10T09:10:00Z"),
        t(4, porcentaje_completado=100, actualizado="2026-11-12T10:00:00Z"),  # sin fin real: usa la modificación
        t(5, porcentaje_completado=60, fecha_fin_real="2026-10-01", actualizado="2026-11-10T09:00:00Z"),
    ]
    historial = historial_realizado(tareas)
    assert [(dia, [x.id for x in grupo]) for dia, grupo in historial] == [
        ("2026-10-08", [1, 2]),
        ("2026-10-20", [3]),
        ("2026-11-12", [4]),
    ]


def test_fecha_completada_es_none_si_la_tarea_no_esta_al_cien_por_cien():
    assert fecha_completada(t(1, porcentaje_completado=99, fecha_fin_real="2026-10-01")) is None
    assert fecha_completada(t(2, porcentaje_completado=100, fecha_fin_real="2026-10-01")) == "2026-10-01"


def test_eventos_pasados_cuenta_los_anteriores_a_hoy():
    from datetime import date

    from gnomilestone.documentacion import EventoRoadmap, eventos_pasados

    def e(fecha):
        return EventoRoadmap(1, "x", fecha, False, False)

    eventos = [e("2026-11-01"), e("2026-11-10"), e("2026-11-12"), e("2026-12-01")]
    assert eventos_pasados(eventos, date(2026, 11, 12)) == 2  # el de hoy no es pasado
    assert eventos_pasados(eventos, date(2026, 10, 1)) == 0
    assert eventos_pasados(eventos, date(2027, 1, 1)) == 4
    assert eventos_pasados([], date(2026, 11, 12)) == 0
