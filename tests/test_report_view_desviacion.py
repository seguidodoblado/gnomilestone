from gnomilestone.ui.report_view import ReportView

tramos = ReportView._tramos_desviacion


def linea(*ys):
    return [(i * 10.0, float(y)) for i, y in enumerate(ys)]


def test_burnup_por_delante_es_verde_y_por_detras_es_rojo():
    ideal = linea(100, 80, 60)  # sube hacia arriba (y baja)
    assert [a for _p, a in tramos(ideal, linea(100, 50, 40), burndown=False)] == [True, True]
    assert [a for _p, a in tramos(ideal, linea(100, 90, 80), burndown=False)] == [False, False]


def test_burndown_invierte_el_sentido():
    ideal = linea(0, 20, 40)  # los pendientes bajan: y crece
    assert [a for _p, a in tramos(ideal, linea(0, 30, 60), burndown=True)] == [True, True]
    assert [a for _p, a in tramos(ideal, linea(0, 10, 20), burndown=True)] == [False, False]


def test_si_las_lineas_se_cruzan_el_tramo_se_parte_en_verde_y_rojo():
    resultado = tramos(linea(100, 60), linea(80, 80), burndown=False)  # delante y luego detrás
    assert [a for _p, a in resultado] == [True, False]
    cruce = resultado[0][0][1]
    assert cruce == resultado[1][0][0] and abs(cruce[1] - 80.0) < 1e-9  # se cruzan donde el ideal llega a la altura de lo real


def test_lineas_iguales_no_dibujan_area():
    assert tramos(linea(100, 50), linea(100, 50), burndown=False) == []
