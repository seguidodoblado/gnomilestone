from gnomilestone.models import Tarea
from gnomilestone.ui.table_view import coincide_con_filtro
from gnomilestone.ui.task_tree_view import TareaRow


def _fila(titulo="Tarea", estado_id=None):
    tarea = Tarea(id=1, proyecto_id=1, titulo=titulo, estado_id=estado_id)
    return TareaRow(titulo, [], tarea=tarea, estado_nombre="")


def test_sin_texto_ni_estado_coincide_con_todo():
    assert coincide_con_filtro(_fila("Lo que sea"), "", None) is True


def test_texto_coincide_sin_distinguir_mayusculas():
    assert coincide_con_filtro(_fila("Diseñar portada"), "PORTADA", None) is True


def test_texto_no_coincide():
    assert coincide_con_filtro(_fila("Diseñar portada"), "maqueta", None) is False


def test_filtro_de_estado_coincide():
    assert coincide_con_filtro(_fila("T", estado_id=3), "", 3) is True


def test_filtro_de_estado_no_coincide():
    assert coincide_con_filtro(_fila("T", estado_id=3), "", 5) is False


def test_filtro_de_texto_y_estado_combinados():
    fila = _fila("Diseñar portada", estado_id=3)
    assert coincide_con_filtro(fila, "portada", 3) is True
    assert coincide_con_filtro(fila, "portada", 5) is False
    assert coincide_con_filtro(fila, "maqueta", 3) is False


def test_fila_sin_tarea_no_coincide_con_filtro_de_estado():
    fila_proyecto = TareaRow("Proyecto X", [])  # nodo raíz de la vista global, sin tarea
    assert coincide_con_filtro(fila_proyecto, "", 3) is False
    assert coincide_con_filtro(fila_proyecto, "", None) is True
