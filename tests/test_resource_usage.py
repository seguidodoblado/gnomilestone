from datetime import date

from gnomilestone.models import Asignacion, Recurso, Tarea
from gnomilestone.resource_usage import (
    carga_por_dia,
    construir_filas_uso,
    duracion_efectiva,
    rango_fechas,
)


def _tarea(
    id_: int,
    titulo: str,
    fecha_inicio: str | None,
    duracion_dias: int = 1,
    *,
    es_hito: bool = False,
    padre_id: int | None = None,
) -> Tarea:
    return Tarea(
        id=id_,
        proyecto_id=1,
        titulo=titulo,
        padre_id=padre_id,
        fecha_inicio=fecha_inicio,
        duracion_dias=duracion_dias,
        es_hito=es_hito,
    )


def _recurso(id_: int, nombre: str, color: str = "#3584e4") -> Recurso:
    return Recurso(id=id_, proyecto_id=1, nombre=nombre, color_hex=color)


def test_duracion_efectiva_hito_y_cero():
    assert duracion_efectiva(_tarea(1, "Hito", "2026-11-01", 0, es_hito=True)) == 1
    assert duracion_efectiva(_tarea(2, "Cero", "2026-11-01", 0)) == 1
    assert duracion_efectiva(_tarea(3, "Normal", "2026-11-01", 3)) == 3


def test_sin_fecha_no_genera_segmento():
    ana = _recurso(1, "Ana")
    tarea = _tarea(10, "Sin fecha", None, 5)
    filas = construir_filas_uso(
        [ana], [tarea], [Asignacion(id=1, tarea_id=10, recurso_id=1, porcentaje_dedicacion=100)]
    )
    assert filas[0].segmentos == ()
    assert filas[0].carga_maxima == 0
    assert rango_fechas(filas) is None


def test_solape_al_100_sobrecarga():
    ana = _recurso(1, "Ana")
    t1 = _tarea(1, "Uno", "2026-11-01", 3)
    t2 = _tarea(2, "Dos", "2026-11-02", 3)
    filas = construir_filas_uso(
        [ana],
        [t1, t2],
        [
            Asignacion(id=1, tarea_id=1, recurso_id=1, porcentaje_dedicacion=100),
            Asignacion(id=2, tarea_id=2, recurso_id=1, porcentaje_dedicacion=100),
        ],
    )
    fila = filas[0]
    assert len(fila.segmentos) == 2
    assert fila.carga_maxima == 200
    assert fila.dias_sobrecarga == 2  # 2 y 3 de noviembre
    assert fila.sobrecargado
    carga = carga_por_dia(fila.segmentos)
    assert carga[date(2026, 11, 1)] == 100
    assert carga[date(2026, 11, 2)] == 200
    assert carga[date(2026, 11, 4)] == 100


def test_dedicacion_parcial_sin_sobrecarga():
    ana = _recurso(1, "Ana")
    t1 = _tarea(1, "Uno", "2026-11-01", 2)
    t2 = _tarea(2, "Dos", "2026-11-01", 2)
    filas = construir_filas_uso(
        [ana],
        [t1, t2],
        [
            Asignacion(id=1, tarea_id=1, recurso_id=1, porcentaje_dedicacion=40),
            Asignacion(id=2, tarea_id=2, recurso_id=1, porcentaje_dedicacion=50),
        ],
    )
    assert filas[0].carga_maxima == 90
    assert filas[0].dias_sobrecarga == 0
    assert not filas[0].sobrecargado


def test_varias_personas_y_rango():
    ana = _recurso(1, "Ana")
    luis = _recurso(2, "Luis")
    t1 = _tarea(1, "Uno", "2026-11-05", 2)
    t2 = _tarea(2, "Dos", "2026-11-10", 1)
    filas = construir_filas_uso(
        [ana, luis],
        [t1, t2],
        [
            Asignacion(id=1, tarea_id=1, recurso_id=1),
            Asignacion(id=2, tarea_id=2, recurso_id=2),
        ],
    )
    assert [f.recurso.nombre for f in filas] == ["Ana", "Luis"]
    assert rango_fechas(filas) == (date(2026, 11, 5), date(2026, 11, 11))


def test_hija_no_suma_si_el_mismo_recurso_esta_en_el_padre():
    ana = _recurso(1, "Ana")
    padre = _tarea(1, "Padre", "2026-11-01", 5)
    hija = _tarea(2, "Hija", "2026-11-02", 2, padre_id=1)
    filas = construir_filas_uso(
        [ana],
        [padre, hija],
        [
            Asignacion(id=1, tarea_id=1, recurso_id=1, porcentaje_dedicacion=100),
            Asignacion(id=2, tarea_id=2, recurso_id=1, porcentaje_dedicacion=100),
        ],
    )
    assert [s.tarea_id for s in filas[0].segmentos] == [1]
    assert filas[0].carga_maxima == 100
    assert filas[0].dias_sobrecarga == 0


def test_hija_si_suma_si_solo_ella_esta_asignada():
    ana = _recurso(1, "Ana")
    padre = _tarea(1, "Padre", "2026-11-01", 5)
    hija = _tarea(2, "Hija", "2026-11-02", 2, padre_id=1)
    filas = construir_filas_uso(
        [ana],
        [padre, hija],
        [Asignacion(id=1, tarea_id=2, recurso_id=1, porcentaje_dedicacion=100)],
    )
    assert [s.tarea_id for s in filas[0].segmentos] == [2]
    assert filas[0].carga_maxima == 100


def test_hermanas_si_pueden_sobrecargar():
    ana = _recurso(1, "Ana")
    padre = _tarea(1, "Padre", "2026-11-01", 5)
    a = _tarea(2, "A", "2026-11-01", 3, padre_id=1)
    b = _tarea(3, "B", "2026-11-02", 3, padre_id=1)
    filas = construir_filas_uso(
        [ana],
        [padre, a, b],
        [
            Asignacion(id=1, tarea_id=2, recurso_id=1, porcentaje_dedicacion=100),
            Asignacion(id=2, tarea_id=3, recurso_id=1, porcentaje_dedicacion=100),
        ],
    )
    assert {s.tarea_id for s in filas[0].segmentos} == {2, 3}
    assert filas[0].carga_maxima == 200
    assert filas[0].sobrecargado
