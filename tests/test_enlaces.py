from gnomilestone.documentacion import buscar
from gnomilestone.enlaces import (
    Indice,
    destino_de_uri,
    entrantes,
    normalizar,
    transformar_enlaces,
)
from gnomilestone.models import DiagramaDocumentacion, NotaDocumentacion, Tarea


def nota(i, titulo, contenido="", sub=1):
    return NotaDocumentacion(i, 1, "arquitectura", titulo, contenido, subseccion_id=sub)


def indice():
    notas = [nota(1, "Modelo de datos"), nota(2, "Visión general")]
    diagramas = [DiagramaDocumentacion(7, 1, 3, "Login")]
    tareas = [Tarea(10, 1, "Documentación", github_issue_number=27), Tarea(11, 1, "Modelo de datos")]
    return Indice(notas, diagramas, tareas)


def test_normalizar_conserva_la_longitud():
    assert normalizar("Visión Ñandú") == "vision nandu"
    assert len(normalizar("Árbol y Çedilla")) == len("Árbol y Çedilla")


def test_enlace_wiki_se_resuelve_sin_acentos_ni_mayusculas():
    texto = "Ver [[vision GENERAL]] y [[Login|el login]] y [[Roto]]"
    assert transformar_enlaces(texto, indice()) == (
        "Ver [vision GENERAL](gnomilestone://nota/2) y [el login](gnomilestone://diagrama/7) "
        "y [[Roto]]"
    )


def test_prioridad_nota_sobre_tarea_con_el_mismo_titulo():
    assert transformar_enlaces("[[Modelo de datos]]", indice()) == "[Modelo de datos](gnomilestone://nota/1)"


def test_issue_enlaza_con_la_tarea_vinculada():
    assert transformar_enlaces("Hecho en #27 y no #99", indice()) == (
        "Hecho en [#27](gnomilestone://tarea/10) y no #99"
    )


def test_no_toca_codigo_ni_titulos_markdown():
    texto = "`[[Login]]` y #27\n```\n[[Login]] #27\n```\n## Título\n[[Login]]"
    resultado = transformar_enlaces(texto, indice())
    assert resultado.split("\n")[0] == "`[[Login]]` y [#27](gnomilestone://tarea/10)"
    assert resultado.split("\n")[2] == "[[Login]] #27"
    assert resultado.split("\n")[4] == "## Título"
    assert resultado.split("\n")[5] == "[Login](gnomilestone://diagrama/7)"


def test_destino_de_uri():
    assert destino_de_uri("gnomilestone://nota/5") == ("nota", 5)
    assert destino_de_uri("gnomilestone://tarea/x") is None
    assert destino_de_uri("https://x.y") is None


def test_enlaces_entrantes():
    idx = indice()
    destino = idx.por_titulo("Modelo de datos")
    notas = [
        nota(1, "Modelo de datos", "yo mismo [[Modelo de datos]]"),
        nota(2, "Visión general", "mira [[modelo de datos]]"),
        nota(3, "Otra", "nada"),
    ]
    assert [n.id for n in entrantes(destino, notas, idx)] == [2]


def test_busqueda_y_orden_por_titulo():
    notas = [
        nota(1, "Capas", "La arquitectura de la aplicación usa capas"),
        nota(2, "Arquitectura general", "Texto"),
        nota(3, "Otra", "nada de esto"),
    ]
    diagramas = [DiagramaDocumentacion(9, 1, 3, "Flujo", '{"nodos":[{"id":1,"tipo":"paso","texto":"Validar arquitectura","x":0,"y":0}],"aristas":[]}')]
    res = buscar("ARQUITECTURA", notas, diagramas)
    assert [(r.tipo, r.id) for r in res] == [("nota", 2), ("nota", 1), ("diagrama", 9)]
    assert buscar("arquitectura capas", notas, diagramas)[0].id == 1  # todas las palabras
    assert buscar("", notas, diagramas) == []
    assert buscar("inexistente", notas, diagramas) == []


def test_extracto_resalta_la_coincidencia_con_acentos():
    notas = [nota(1, "T", "x" * 100 + " Visión del sistema " + "y" * 100)]
    r = buscar("vision", notas, [])[0]
    assert r.extracto[r.inicio : r.inicio + r.longitud] == "Visión"
    assert r.extracto.startswith("…") and r.extracto.endswith("…")
