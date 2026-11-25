from unittest.mock import MagicMock

from gnomilestone.estado_issue import categoria_estado_issue, elegir_estado
from gnomilestone.github import GitHubClient
from gnomilestone.models import EstadoTablero, Tarea
from gnomilestone.store import Store
from gnomilestone.sync import GitHubSyncManager

ESTADOS_GITHUB = [
    {"id": "IS_bl", "name": "Backlog", "category": "Backlog"},
    {"id": "IS_td", "name": "Todo", "category": "Planned"},
    {"id": "IS_ip", "name": "In progress", "category": "Started"},
    {"id": "IS_rv", "name": "In review", "category": "Started"},
    {"id": "IS_dn", "name": "Done", "category": "Completed"},
    {"id": "IS_np", "name": "Not planned", "category": "Not planned"},
]


def _columnas():
    return [
        EstadoTablero(1, 1, "Pendiente", 0),
        EstadoTablero(2, 1, "En progreso", 1),
        EstadoTablero(3, 1, "Revisión", 2),
        EstadoTablero(4, 1, "Hecho", 3, es_final=True),
    ]


def _tarea(estado_id, porcentaje=0):
    return Tarea(id=1, proyecto_id=1, titulo="T", estado_id=estado_id, porcentaje_completado=porcentaje)


def test_la_categoria_sale_de_la_columna_y_del_progreso():
    columnas = _columnas()
    assert categoria_estado_issue(_tarea(1), columnas) == "Backlog"
    assert categoria_estado_issue(_tarea(1, 30), columnas) == "Started"  # con progreso
    assert categoria_estado_issue(_tarea(2), columnas) == "Started"  # fuera de la primera columna
    assert categoria_estado_issue(_tarea(3), columnas) == "review"
    assert categoria_estado_issue(_tarea(4), columnas) == "Completed"
    assert categoria_estado_issue(_tarea(1, 100), columnas) == "Completed"


def test_se_elige_el_estado_de_github_por_categoria_y_nombre():
    assert elegir_estado("Backlog", ESTADOS_GITHUB)["id"] == "IS_bl"
    assert elegir_estado("Started", ESTADOS_GITHUB)["id"] == "IS_ip"  # no «In review»
    assert elegir_estado("review", ESTADOS_GITHUB)["id"] == "IS_rv"
    assert elegir_estado("Completed", ESTADOS_GITHUB)["id"] == "IS_dn"
    assert elegir_estado("review", ESTADOS_GITHUB[:3]) is None  # el repositorio no lo ofrece


def test_el_envio_de_una_tarea_pone_el_estado_del_issue(tmp_path):
    store = Store(tmp_path / "t.db")
    p = store.crear_proyecto("P", github_repo_owner="u", github_repo_name="r")
    final = next(e for e in store.listar_estados(p.id) if e.es_final)
    t = store.crear_tarea(p.id, "Hecha", estado_id=final.id)
    t.github_issue_number = 7
    store.actualizar_tarea(t)

    cliente = MagicMock(spec=GitHubClient)
    cliente.obtener_issue.return_value = {
        "labels": [], "assignees": [], "node_id": "I_7", "status": {"name": "Backlog"},
    }
    cliente.estados_issue.return_value = ESTADOS_GITHUB
    GitHubSyncManager(store, cliente).push_tarea(t.id)
    cliente.fijar_estado_issue.assert_called_once_with("I_7", "IS_dn", None)

    # Si GitHub ya lo tiene en ese estado, no se vuelve a pedir el cambio.
    cliente.fijar_estado_issue.reset_mock()
    cliente.obtener_issue.return_value["status"] = {"name": "Done"}
    GitHubSyncManager(store, cliente).push_tarea(t.id)
    cliente.fijar_estado_issue.assert_not_called()


def test_el_flujo_de_github_reutiliza_crea_y_enlaza_las_columnas(tmp_path):
    store = Store(tmp_path / "f.db")
    p = store.crear_proyecto("P")
    antes = {e.nombre: e for e in store.listar_estados(p.id)}  # Pendiente, En progreso, Hecho...
    tarea = store.crear_tarea(p.id, "T", estado_id=antes["En progreso"].id) if "En progreso" in antes else None

    informe = store.aplicar_flujo_github(p.id)
    columnas = store.listar_estados(p.id)
    assert [c.nombre for c in columnas[:7]] == [
        "Backlog", "Todo", "In progress", "In review", "Done", "Not planned", "Duplicate",
    ]
    assert [c.estado_issue for c in columnas[:7]] == [
        "Backlog", "Planned", "Started", "review", "Completed", "Not planned", "Duplicate",
    ]
    assert next(c for c in columnas if c.nombre == "Done").es_final
    assert sum(c.es_final for c in columnas) == 1
    assert informe["creadas"] and {"In review", "Not planned", "Duplicate"} <= set(informe["creadas"])
    if tarea is not None:  # la tarea sigue en su columna, ahora renombrada
        assert store.obtener_tarea(tarea.id).estado_id == antes["En progreso"].id
    # Aplicarlo dos veces no duplica nada.
    assert store.aplicar_flujo_github(p.id)["creadas"] == []
    assert len(store.listar_estados(p.id)) == len(columnas)


def test_las_tareas_descartadas_no_cuentan_en_el_progreso(tmp_path):
    from gnomilestone.ganttcalc import progreso_proyecto, progreso_resumen

    store = Store(tmp_path / "d.db")
    p = store.crear_proyecto("P")
    store.aplicar_flujo_github(p.id)
    columnas = {c.nombre: c for c in store.listar_estados(p.id)}
    hecha = store.crear_tarea(p.id, "Hecha", estado_id=columnas["Done"].id)
    hecha.porcentaje_completado = 100
    store.actualizar_tarea(hecha)
    pendiente = store.crear_tarea(p.id, "Pendiente", estado_id=columnas["Backlog"].id)
    descartada = store.crear_tarea(p.id, "Descartada", estado_id=columnas["Not planned"].id)
    assert store.obtener_tarea(descartada.id).descartada
    assert not store.obtener_tarea(pendiente.id).descartada

    tareas = store.listar_tareas(p.id)
    assert progreso_proyecto(tareas) == 50  # hecha (100) y pendiente (0); la descartada no suma ni resta
    assert not progreso_resumen(tareas)


def test_una_columna_enlazada_manda_en_el_estado_del_issue():
    columnas = [
        EstadoTablero(1, 1, "Backlog", 0, estado_issue="Backlog"),
        EstadoTablero(2, 1, "Todo", 1, estado_issue="Planned"),
        EstadoTablero(3, 1, "Done", 2, es_final=True, estado_issue="Completed"),
        EstadoTablero(4, 1, "Duplicate", 3, estado_issue="Duplicate"),
    ]
    assert categoria_estado_issue(_tarea(2), columnas) == "Planned"
    assert categoria_estado_issue(_tarea(4, 40), columnas) == "Duplicate"  # cerrada sin completar
    assert elegir_estado("Planned", ESTADOS_GITHUB)["id"] == "IS_td"


def test_duplicate_envia_el_issue_original_y_sin_el_no_se_envia(tmp_path):
    store = Store(tmp_path / "dup.db")
    p = store.crear_proyecto("P", github_repo_owner="u", github_repo_name="r")
    store.aplicar_flujo_github(p.id)
    duplicate = next(c for c in store.listar_estados(p.id) if c.nombre == "Duplicate")
    original = store.crear_tarea(p.id, "Original")
    original.github_issue_number = 1
    store.actualizar_tarea(original)
    copia = store.crear_tarea(p.id, "Copia", estado_id=duplicate.id)
    copia.github_issue_number = 2
    store.actualizar_tarea(copia)

    cliente = MagicMock(spec=GitHubClient)
    cliente.estados_issue.return_value = ESTADOS_GITHUB + [
        {"id": "IS_du", "name": "Duplicate", "category": "Duplicate"}
    ]
    cliente.obtener_issue.side_effect = lambda _o, _r, n: {
        "labels": [], "assignees": [], "node_id": f"I_{n}", "status": {"name": "Backlog"},
    }
    GitHubSyncManager(store, cliente).push_tarea(copia.id)
    cliente.fijar_estado_issue.assert_not_called()  # sin original no se puede enviar

    copia = store.obtener_tarea(copia.id)
    copia.duplicado_de_id = original.id
    store.actualizar_tarea(copia)
    GitHubSyncManager(store, cliente).push_tarea(copia.id)
    cliente.fijar_estado_issue.assert_called_once_with("I_2", "IS_du", "I_1")


def test_el_flujo_de_github_da_descripcion_a_todas_las_columnas_sin_pisar_las_propias(tmp_path):
    store = Store(tmp_path / "desc.db")
    p = store.crear_proyecto("P")
    todo = next(e for e in store.listar_estados(p.id) if e.nombre in ("Todo", "Pendiente"))
    store.actualizar_descripcion_estado(todo.id, "Mi descripción")

    store.aplicar_flujo_github(p.id)
    columnas = {c.nombre: c for c in store.listar_estados(p.id)}
    assert next(c for c in columnas.values() if c.id == todo.id).descripcion == "Mi descripción"
    for nombre in ("Backlog", "In progress", "In review", "Done", "Not planned", "Duplicate"):
        assert columnas[nombre].descripcion, nombre
    assert all(c.descripcion for c in columnas.values() if c.estado_issue)
    assert columnas["Done"].descripcion == "This has been completed"
