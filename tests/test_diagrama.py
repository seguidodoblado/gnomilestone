import math

from gnomilestone.diagrama import Diagrama, punto_borde


def _flujo() -> Diagrama:
    d = Diagrama()
    a = d.nuevo_nodo("inicio", "Inicio", 0, 0)
    b = d.nuevo_nodo("decision", "¿Ok?", 300, 0)
    c = d.nuevo_nodo("fin", "Fin", 600, 0)
    d.conectar(a.id, b.id)
    d.conectar(b.id, c.id, "sí")
    return d


def test_json_ida_y_vuelta():
    d = _flujo()
    copia = Diagrama.de_json(d.a_json())
    assert [(n.id, n.tipo, n.texto) for n in copia.nodos] == [(1, "inicio", "Inicio"), (2, "decision", "¿Ok?"), (3, "fin", "Fin")]
    assert [(a.desde, a.hasta, a.etiqueta) for a in copia.aristas] == [(1, 2, ""), (2, 3, "sí")]


def test_json_corrupto_o_vacio_da_diagrama_vacio():
    assert Diagrama.de_json("no es json").nodos == []
    assert Diagrama.de_json("").aristas == []
    assert Diagrama.de_json('{"nodos": [{"id": 1}]}').nodos == []


def test_aristas_huerfanas_se_descartan_al_cargar():
    d = Diagrama.de_json('{"nodos":[{"id":1,"tipo":"paso","texto":"a","x":0,"y":0}],"aristas":[{"desde":1,"hasta":9}]}')
    assert d.aristas == []


def test_conectar_rechaza_bucles_duplicados_y_nodos_inexistentes():
    d = _flujo()
    assert d.conectar(1, 1) is None
    assert d.conectar(1, 2) is None  # ya existe
    assert d.conectar(1, 99) is None
    assert d.conectar(2, 1) is not None  # el sentido contrario sí


def test_eliminar_nodo_quita_sus_flechas():
    d = _flujo()
    d.eliminar_nodo(2)
    assert [n.id for n in d.nodos] == [1, 3]
    assert d.aristas == []
    assert d.nuevo_nodo("paso", "x", 0, 0).id == 4


def test_nodo_en_respeta_la_forma_del_rombo():
    d = _flujo()
    rombo = d.nodo(2)
    assert d.nodo_en(rombo.x, rombo.y).id == 2
    # Esquina del rectángulo envolvente: fuera del rombo.
    assert d.nodo_en(rombo.x + rombo.w / 2 - 2, rombo.y + rombo.h / 2 - 2) is None
    assert d.nodo_en(5000, 5000) is None


def test_punto_borde_rectangulo_y_rombo():
    d = _flujo()
    x, y = punto_borde(d.nodo(1), 1000, 0)
    assert (round(x), round(y)) == (75, 0)
    x, y = punto_borde(d.nodo(2), 1000, 0)
    assert (round(x), round(y)) == (395, 0)
    x, y = punto_borde(d.nodo(2), 300, 1000)
    assert (round(x), round(y)) == (300, 50)
    assert math.isclose(punto_borde(d.nodo(1), 0, 0)[0], 0)


def test_arista_en_y_limites():
    d = _flujo()
    arista = d.aristas[0]
    assert d.arista_en(190, 3, 8) is arista
    assert d.arista_en(190, 100, 8) is None
    minx, _miny, maxx, _maxy = d.limites()
    assert (minx, maxx) == (-75, 675)
    assert Diagrama().limites() is None


def test_estilo_y_punta_de_las_flechas_y_tamano_propio_se_guardan_en_json():
    d = Diagrama()
    a = d.nuevo_nodo("paso", "A", 0, 0)
    a.ancho, a.alto = 220.0, 90.0
    b = d.nuevo_nodo("paso", "B", 0, 200)
    d.conectar(a.id, b.id, "x", estilo="discontinua", punta=False)
    copia = Diagrama.de_json(d.a_json())
    assert (copia.nodos[0].w, copia.nodos[0].h) == (220.0, 90.0)
    assert copia.nodos[1].w == 170.0  # el de su tipo
    assert (copia.aristas[0].estilo, copia.aristas[0].punta) == ("discontinua", False)


def test_json_antiguo_sin_estilo_ni_tamano_sigue_cargando():
    d = Diagrama.de_json(
        '{"nodos":[{"id":1,"tipo":"paso","texto":"a","x":0,"y":0},{"id":2,"tipo":"paso","texto":"b","x":0,"y":9}],'
        '"aristas":[{"desde":1,"hasta":2}]}'
    )
    assert (d.aristas[0].estilo, d.aristas[0].punta, d.nodos[0].ancho) == ("solida", True, 0.0)
