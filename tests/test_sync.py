from contextlib import closing
from unittest.mock import MagicMock

from gnomilestone.github import GitHubClient, GitHubItem, GitHubStatusOption
from gnomilestone.store import Store
from gnomilestone.sync import GitHubSyncManager


def test_sync_pull_project_v2(tmp_path):
    db_file = tmp_path / "test.db"
    store = Store(db_file)
    p = store.crear_proyecto("Bloguero", github_repo_owner="testuser", github_project_v2_id="11")

    client = MagicMock(spec=GitHubClient)
    meta = {
        "id": "PVT_11",
        "title": "Bloguero",
        "fields": {"Status": "FIELD_STATUS"},
        "status_field_id": "FIELD_STATUS",
    }
    status_options = [
        GitHubStatusOption(id="OPT_TODO", name="Todo"),
        GitHubStatusOption(id="OPT_DONE", name="Done"),
    ]
    items = [
        GitHubItem(
            id="ITEM_1",
            title="Diseñar UI",
            body="Crear mockups",
            issue_number=1,
            status_name="Todo",
            status_option_id="OPT_TODO",
            url="https://github.com/testuser/bloguero/issues/1",
            start_date="2026-11-01",
            target_date="2026-11-03",
            assignees=["testuser"],
        )
    ]
    client.obtener_detalles_proyecto_v2.return_value = (meta, status_options, items)

    sync = GitHubSyncManager(store, client)
    res = sync.pull_proyecto(p.id)

    assert res.tareas_creadas == 1
    assert res.estados_creados == 2  # 'Todo' y 'Done'
    assert res.recursos_creados == 1

    tareas = store.listar_tareas(p.id)
    assert len(tareas) == 1
    t = tareas[0]
    assert t.titulo == "Diseñar UI"
    assert t.github_issue_number == 1
    assert t.github_item_id == "ITEM_1"
    assert t.fecha_inicio == "2026-11-01"
    assert t.duracion_dias == 2

    # Verificar asignación
    recursos = store.listar_recursos_de_tarea(t.id)
    assert len(recursos) == 1
    assert recursos[0].nombre == "testuser"


def test_sync_push_tarea(tmp_path):
    db_file = tmp_path / "test.db"
    store = Store(db_file)
    p = store.crear_proyecto("Bloguero", github_repo_owner="testuser", github_repo_name="bloguero")
    t = store.crear_tarea(p.id, "Nueva tarea")

    client = MagicMock(spec=GitHubClient)
    client.crear_issue.return_value = {"number": 105, "html_url": "https://github.com/testuser/bloguero/issues/105"}

    sync = GitHubSyncManager(store, client)
    ok = sync.push_tarea(t.id)

    assert ok is True
    client.crear_issue.assert_called_once_with(
        owner="testuser",
        repo="bloguero",
        titulo="Nueva tarea",
        body="",
        assignees=None,
    )
    t_actualizada = store.obtener_tarea(t.id)
    assert t_actualizada.github_issue_number == 105


def test_sync_push_tarea_envia_asignados_y_fechas_a_project_v2(tmp_path):
    db_file = tmp_path / "test.db"
    store = Store(db_file)
    p = store.crear_proyecto(
        "Bloguero",
        github_repo_owner="testuser",
        github_repo_name="bloguero",
        github_project_v2_id="11",
    )
    t = store.crear_tarea(
        p.id, "Nueva tarea", fecha_inicio="2026-11-01", fecha_fin_planificada="2026-11-05"
    )
    t.github_issue_number = 105
    t.github_item_id = "ITEM_1"
    store.actualizar_tarea(t)
    rec = store.crear_recurso(p.id, "testuser")
    store.asignar_recurso(t.id, rec.id)

    client = MagicMock(spec=GitHubClient)
    client.obtener_detalles_proyecto_v2.return_value = (
        {
            "id": "PVT_11",
            "fields": {"Start Date": "FIELD_START", "Target Date": "FIELD_TARGET"},
        },
        [],
        [],
    )

    sync = GitHubSyncManager(store, client)
    assert sync.push_tarea(t.id) is True

    client.actualizar_issue.assert_called_once_with(
        owner="testuser",
        repo="bloguero",
        number=105,
        titulo="Nueva tarea",
        body="",
        state="open",
        assignees=["testuser"],
    )
    client.actualizar_fecha_item_v2.assert_any_call(
        project_id="PVT_11", item_id="ITEM_1", field_id="FIELD_START", fecha_iso="2026-11-01"
    )
    client.actualizar_fecha_item_v2.assert_any_call(
        project_id="PVT_11", item_id="ITEM_1", field_id="FIELD_TARGET", fecha_iso="2026-11-05"
    )
    # Tras un push correcto, queda marcada como sincronizada (para que un pull
    # posterior no la trate como en conflicto si nadie la ha tocado desde entonces).
    assert store.obtener_tarea(t.id).github_synced_at is not None


def test_sync_pull_no_sobrescribe_tarea_editada_tras_el_ultimo_sync(tmp_path):
    """Si la tarea local cambió después del último sync, el pull no debe pisarla."""
    db_file = tmp_path / "test.db"
    store = Store(db_file)
    p = store.crear_proyecto("Bloguero", github_repo_owner="testuser", github_project_v2_id="11")
    t = store.crear_tarea(p.id, "Título original")
    t.github_item_id = "ITEM_1"
    store.actualizar_tarea(t)

    with closing(store._connect()) as db, db:
        db.execute(
            "UPDATE tarea SET github_synced_at = '2026-01-01 00:00:00', "
            "actualizado = '2026-01-02 00:00:00' WHERE id = ?",
            (t.id,),
        )

    client = MagicMock(spec=GitHubClient)
    client.obtener_detalles_proyecto_v2.return_value = (
        {"id": "PVT_11", "fields": {}, "status_field_id": None},
        [],
        [
            GitHubItem(
                id="ITEM_1",
                title="Título cambiado en GitHub",
                issue_number=1,
                url="https://github.com/testuser/bloguero/issues/1",
            )
        ],
    )

    sync = GitHubSyncManager(store, client)
    res = sync.pull_proyecto(p.id)

    assert res.tareas_actualizadas == 0
    assert len(res.conflictos) == 1
    assert store.obtener_tarea(t.id).titulo == "Título original"
