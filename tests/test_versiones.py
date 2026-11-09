import pytest

from gnomilestone.diagrama import Diagrama
from gnomilestone.store import MAX_VERSIONES, Store
from gnomilestone.versiones import diferencias, formatear_fecha, hay_cambios, resumen_diagrama


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "g.db")


def test_actualizar_nota_guarda_la_version_anterior(store):
    p = store.crear_proyecto("P")
    nota = store.crear_nota_documentacion(p.id, "arquitectura", "T1", "uno")
    assert store.listar_versiones_nota(nota.id) == []
    nota.contenido = "dos"
    store.actualizar_nota_documentacion(nota)
    nota.titulo = "T2"
    nota.contenido = "tres"
    store.actualizar_nota_documentacion(nota)
    versiones = store.listar_versiones_nota(nota.id)
    assert [(v.titulo, v.contenido) for v in versiones] == [("T1", "dos"), ("T1", "uno")]


def test_guardar_sin_cambios_no_crea_version(store):
    p = store.crear_proyecto("P")
    nota = store.crear_nota_documentacion(p.id, "arquitectura", "T", "x")
    store.actualizar_nota_documentacion(nota)
    assert store.listar_versiones_nota(nota.id) == []


def test_se_conservan_solo_las_ultimas_versiones(store):
    p = store.crear_proyecto("P")
    nota = store.crear_nota_documentacion(p.id, "arquitectura", "T", "0")
    for i in range(1, MAX_VERSIONES + 6):
        nota.contenido = str(i)
        store.actualizar_nota_documentacion(nota)
    versiones = store.listar_versiones_nota(nota.id)
    assert len(versiones) == MAX_VERSIONES
    assert versiones[0].contenido == str(MAX_VERSIONES + 4)  # la más reciente


def test_versiones_de_diagrama_y_borrado_en_cascada(store):
    p = store.crear_proyecto("P")
    sub = store.crear_subseccion_documentacion(p.id, "arquitectura", "F", "diagramas")
    d = store.crear_diagrama_documentacion(p.id, sub.id, "D", "a")
    d.datos = "b"
    store.actualizar_diagrama_documentacion(d)
    assert [v.contenido for v in store.listar_versiones_diagrama(d.id)] == ["a"]
    store.eliminar_diagrama_documentacion(d.id)
    assert store.listar_versiones_diagrama(d.id) == []


def test_borrar_la_nota_borra_sus_versiones(store):
    p = store.crear_proyecto("P")
    nota = store.crear_nota_documentacion(p.id, "arquitectura", "T", "0")
    nota.contenido = "1"
    store.actualizar_nota_documentacion(nota)
    store.eliminar_nota_documentacion(nota.id)
    assert store.listar_versiones_nota(nota.id) == []


def test_diferencias_por_lineas():
    diff = diferencias("a\nb\nc", "a\nB\nc\nd")
    assert diff == [(" ", "a"), ("-", "b"), ("+", "B"), (" ", "c"), ("+", "d")]
    assert hay_cambios(diff)
    assert not hay_cambios(diferencias("x\ny", "x\ny"))


def test_resumen_de_diagramas():
    antes, ahora = Diagrama(), Diagrama()
    a = antes.nuevo_nodo("paso", "A", 0, 0)
    b = antes.nuevo_nodo("paso", "B", 0, 100)
    antes.conectar(a.id, b.id)
    ahora.nodos = [type(n)(n.id, n.tipo, n.texto, n.x, n.y) for n in antes.nodos]
    ahora.nodos[1].texto = "B2"
    ahora.nuevo_nodo("fin", "Fin", 0, 200)
    resumen = resumen_diagrama(antes, ahora)
    assert "1 elementos añadidos" in resumen
    assert "1 elementos con texto o tipo distinto" in resumen
    assert "1 flechas distintas" in resumen
    assert resumen_diagrama(antes, antes).startswith("Sin diferencias")


def test_contar_versiones_por_nota_y_diagrama(store):
    p = store.crear_proyecto("P")
    otro = store.crear_proyecto("Q")
    sub = store.crear_subseccion_documentacion(p.id, "arquitectura", "F", "diagramas")
    a = store.crear_nota_documentacion(p.id, "arquitectura", "A", "0")
    b = store.crear_nota_documentacion(p.id, "arquitectura", "B", "0")
    ajena = store.crear_nota_documentacion(otro.id, "arquitectura", "Z", "0")
    for i in (1, 2):
        a.contenido = str(i)
        store.actualizar_nota_documentacion(a)
    ajena.contenido = "1"
    store.actualizar_nota_documentacion(ajena)
    d = store.crear_diagrama_documentacion(p.id, sub.id, "D", "a")
    d.datos = "b"
    store.actualizar_diagrama_documentacion(d)
    assert store.contar_versiones_notas(p.id) == {a.id: 2}  # b sin versiones; ajena, de otro proyecto
    assert b.id not in store.contar_versiones_notas(p.id)
    assert store.contar_versiones_diagramas(p.id) == {d.id: 1}


def test_formatear_fecha():
    assert formatear_fecha("2026-11-09T14:32:05Z") == "2026-11-09 14:32"
    assert formatear_fecha("") == ""
