from contextlib import closing
from unittest.mock import MagicMock

from gnomilestone.github import GitHubClient, GitHubError, GitHubItem, GitHubStatusOption
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
    # Del 1 al 3 de noviembre, ambos inclusive: 3 días.
    assert t.duracion_dias == 3
    assert t.fecha_fin_planificada == "2026-11-03"

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
    rec = store.crear_recurso(p.id, "testuser", github_login="testuser")
    store.asignar_recurso(t.id, rec.id)
    # Un recurso sin login de GitHub (nombre completo) no se envía: daría un 422.
    sin_login = store.crear_recurso(p.id, "José Antonio Seguido Doblado")
    store.asignar_recurso(t.id, sin_login.id)

    client = MagicMock(spec=GitHubClient)
    client.obtener_issue.return_value = {"labels": []}
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
        labels=[],
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
    sync._push_tarea = lambda _tid, **_kw: False  # el envío previo falla: sigue pendiente
    res = sync.pull_proyecto(p.id)

    assert res.tareas_actualizadas == 0
    assert len(res.conflictos) == 1
    assert len(res.errores) == 1  # y se avisa de que no se pudo enviar
    assert store.obtener_tarea(t.id).titulo == "Título original"


def test_sync_pull_actualiza_duracion_y_final_planificado(tmp_path):
    db_file = tmp_path / "test.db"
    store = Store(db_file)
    p = store.crear_proyecto("Bloguero", github_repo_owner="testuser", github_project_v2_id="11")
    t = store.crear_tarea(p.id, "Diseñar UI", fecha_inicio="2026-11-01", duracion_dias=1)
    t.github_item_id = "ITEM_1"
    store.actualizar_tarea(t)

    client = MagicMock(spec=GitHubClient)
    client.obtener_detalles_proyecto_v2.return_value = (
        {"id": "PVT_11", "fields": {}, "status_field_id": None},
        [],
        [
            GitHubItem(
                id="ITEM_1",
                title="Diseñar UI",
                issue_number=1,
                url="https://github.com/testuser/bloguero/issues/1",
                start_date="2026-11-01",
                target_date="2026-11-03",
            )
        ],
    )

    sync = GitHubSyncManager(store, client)
    sync.pull_proyecto(p.id)

    actualizada = store.obtener_tarea(t.id)
    assert actualizada.duracion_dias == 3
    assert actualizada.fecha_fin_planificada == "2026-11-03"


class _ClienteBorrado:
    def __init__(self, falla_borrado=False):
        self.llamadas = []
        self.falla_borrado = falla_borrado

    def eliminar_issue(self, owner, repo, number):
        self.llamadas.append(("issue", owner, repo, number))
        return "eliminado"

    def eliminar_item_v2(self, project_id, item_id):
        self.llamadas.append(("item", project_id, item_id))


def test_eliminar_tarea_borra_tambien_en_github(tmp_path):
    from gnomilestone.store import Store
    from gnomilestone.sync import GitHubSyncManager

    store = Store(tmp_path / "db.sqlite")
    proyecto = store.crear_proyecto("P", github_repo_owner="yo", github_repo_name="repo")
    padre = store.crear_tarea(proyecto.id, "Padre")
    hija = store.crear_tarea(proyecto.id, "Hija", padre_id=padre.id)
    for tarea, n in ((padre, 1), (hija, 2)):
        tarea.github_issue_number = n
        store.actualizar_tarea(tarea)
    local = store.crear_tarea(proyecto.id, "Solo local")

    cliente = _ClienteBorrado()
    GitHubSyncManager(store, cliente).eliminar_tarea(padre.id, en_segundo_plano=False)

    assert sorted(c[3] for c in cliente.llamadas) == [1, 2]
    assert [t.id for t in store.listar_tareas(proyecto.id)] == [local.id]


def test_eliminar_tarea_sin_vinculo_no_llama_a_github(tmp_path):
    from gnomilestone.store import Store
    from gnomilestone.sync import GitHubSyncManager

    store = Store(tmp_path / "db.sqlite")
    proyecto = store.crear_proyecto("P", github_repo_owner="yo", github_repo_name="repo")
    tarea = store.crear_tarea(proyecto.id, "Local")
    cliente = _ClienteBorrado()
    GitHubSyncManager(store, cliente).eliminar_tarea(tarea.id, en_segundo_plano=False)
    assert cliente.llamadas == []


class _ClienteComentarios:
    def __init__(self, remotos=None):
        self.remotos = remotos or []
        self.creados = []
        self.borrados = []

    def listar_comentarios_repo(self, owner, repo):
        return self.remotos

    def crear_comentario(self, owner, repo, number, cuerpo):
        self.creados.append((number, cuerpo))
        return {"id": 900 + len(self.creados), "user": {"login": "yo"}}

    def eliminar_comentario(self, owner, repo, comment_id):
        self.borrados.append(comment_id)


def _proyecto_con_issue(tmp_path):
    from gnomilestone.store import Store

    store = Store(tmp_path / "db.sqlite")
    proyecto = store.crear_proyecto("P", github_repo_owner="yo", github_repo_name="repo")
    tarea = store.crear_tarea(proyecto.id, "T")
    tarea.github_issue_number = 5
    store.actualizar_tarea(tarea)
    return store, proyecto, tarea


def test_pull_comentarios_trae_actualiza_y_borra(tmp_path):
    from gnomilestone.sync import GitHubSyncManager, SyncResult

    store, proyecto, tarea = _proyecto_con_issue(tmp_path)
    remoto = {
        "id": 1, "body": "hola", "user": {"login": "ana"},
        "created_at": "2026-11-07T10:00:00Z", "issue_url": "https://api.github.com/repos/yo/repo/issues/5",
    }
    cliente = _ClienteComentarios([remoto])
    gestor = GitHubSyncManager(store, cliente)
    gestor._pull_comentarios(proyecto.id, "yo", "repo", SyncResult(errores=[]))
    comentarios = store.listar_comentarios(tarea.id)
    assert [(c.autor, c.cuerpo, c.github_comment_id) for c in comentarios] == [("ana", "hola", 1)]

    remoto["body"] = "editado"
    gestor._pull_comentarios(proyecto.id, "yo", "repo", SyncResult(errores=[]))
    assert store.listar_comentarios(tarea.id)[0].cuerpo == "editado"

    cliente.remotos = []
    gestor._pull_comentarios(proyecto.id, "yo", "repo", SyncResult(errores=[]))
    assert store.listar_comentarios(tarea.id) == []


def test_comentario_local_se_publica_y_se_borra_en_remoto(tmp_path):
    from gnomilestone.sync import GitHubSyncManager

    store, _proyecto, tarea = _proyecto_con_issue(tmp_path)
    cliente = _ClienteComentarios()
    gestor = GitHubSyncManager(store, cliente)
    comentario = store.crear_comentario(tarea.id, "mi nota")

    assert gestor.push_comentario(comentario.id)
    publicado = store.obtener_comentario(comentario.id)
    assert (publicado.github_comment_id, publicado.autor) == (901, "yo")
    assert cliente.creados == [(5, "mi nota")]
    assert not gestor.push_comentario(comentario.id)  # ya publicado: no se duplica

    gestor.eliminar_comentario(comentario.id, en_segundo_plano=False)
    assert cliente.borrados == [901]
    assert store.listar_comentarios(tarea.id) == []


def test_comentarios_pendientes_se_envian_en_el_sync(tmp_path):
    from gnomilestone.sync import GitHubSyncManager, SyncResult

    store, proyecto, tarea = _proyecto_con_issue(tmp_path)
    cliente = _ClienteComentarios()
    store.crear_comentario(tarea.id, "pendiente")
    GitHubSyncManager(store, cliente)._pull_comentarios(
        proyecto.id, "yo", "repo", SyncResult(errores=[])
    )
    assert cliente.creados == [(5, "pendiente")]


def test_editar_comentario_publicado_lo_envia_y_el_pull_no_lo_pisa(tmp_path):
    from gnomilestone.sync import GitHubSyncManager, SyncResult

    store, proyecto, tarea = _proyecto_con_issue(tmp_path)
    cliente = _ClienteComentarios()
    enviados = []
    cliente.actualizar_comentario = lambda o, r, cid, cuerpo: enviados.append((cid, cuerpo))
    gestor = GitHubSyncManager(store, cliente)
    local = store.crear_comentario(tarea.id, "v1", github_comment_id=7)

    # Edición sin red: queda pendiente y el pull no la pisa con la versión remota.
    def _falla(o, r, cid, cuerpo):
        raise RuntimeError("sin red")

    cliente.actualizar_comentario = _falla
    gestor.editar_comentario(local.id, "v2", en_segundo_plano=False)
    assert store.obtener_comentario(local.id).pendiente_envio

    cliente.actualizar_comentario = lambda o, r, cid, cuerpo: enviados.append((cid, cuerpo))
    cliente.remotos = [{
        "id": 7, "body": "remoto", "user": {"login": "ana"}, "created_at": "2026-11-07T10:00:00Z",
        "issue_url": "https://api.github.com/repos/yo/repo/issues/5",
    }]
    resultado = SyncResult(errores=[], conflictos=[])
    gestor._pull_comentarios(proyecto.id, "yo", "repo", resultado)

    assert len(resultado.conflictos) == 1
    assert enviados == [(7, "v2")]
    final = store.obtener_comentario(local.id)
    assert (final.cuerpo, final.pendiente_envio) == ("v2", False)


class _ClienteEtiquetas:
    def __init__(self, remotas):
        self.remotas = remotas
        self.actualizado = None
        self.etiquetas_creadas = []

    def obtener_issue(self, owner, repo, number):
        return {"labels": [{"name": n} for n in self.remotas]}

    def crear_etiqueta(self, owner, repo, nombre, color, descripcion=""):
        self.etiquetas_creadas.append((nombre, color))

    def actualizar_issue(self, **kwargs):
        self.actualizado = kwargs["labels"]
        return {}


def test_push_fusiona_etiquetas_sin_borrar_las_ajenas(tmp_path):
    from gnomilestone.sync import GitHubSyncManager

    store, proyecto, tarea = _proyecto_con_issue(tmp_path)
    # Último sync: el issue tenía «bug». En local se quita «bug» y se añade «mejora»;
    # mientras tanto alguien puso «urgente» en GitHub.
    store.guardar_etiquetas_base_github(tarea.id, ["bug"])
    mejora = store.asegurar_etiqueta(proyecto.id, "mejora", "a2eeef")
    store.establecer_etiquetas_de_tarea(tarea.id, [mejora.id])
    cliente = _ClienteEtiquetas(["bug", "urgente"])

    assert GitHubSyncManager(store, cliente).push_tarea(tarea.id)

    assert sorted(cliente.actualizado) == ["mejora", "urgente"]
    assert cliente.etiquetas_creadas == [("mejora", "a2eeef")]
    assert sorted(store.etiquetas_base_github(tarea.id)) == ["mejora", "urgente"]


def test_push_sin_base_conserva_las_etiquetas_remotas(tmp_path):
    from gnomilestone.sync import GitHubSyncManager

    store, _proyecto, tarea = _proyecto_con_issue(tmp_path)
    cliente = _ClienteEtiquetas(["bug"])
    GitHubSyncManager(store, cliente).push_tarea(tarea.id)
    assert cliente.actualizado == ["bug"]  # nunca sincronizada: no se borra nada


def test_aplicar_etiquetas_del_pull_reemplaza_y_fija_la_base(tmp_path):
    from gnomilestone.sync import GitHubSyncManager

    store, proyecto, tarea = _proyecto_con_issue(tmp_path)
    gestor = GitHubSyncManager(store, _ClienteEtiquetas([]))
    gestor._aplicar_etiquetas(proyecto.id, tarea.id, ["bug", "docs"], {"bug": "d73a4a"})
    assert [e.nombre for e in store.listar_etiquetas_de_tarea(tarea.id)] == ["bug", "docs"]
    gestor._aplicar_etiquetas(proyecto.id, tarea.id, ["docs"], {})
    assert [e.nombre for e in store.listar_etiquetas_de_tarea(tarea.id)] == ["docs"]
    assert store.etiquetas_base_github(tarea.id) == ["docs"]


class _ClienteGestionEtiquetas:
    def __init__(self):
        self.llamadas = []

    def actualizar_etiqueta(self, owner, repo, nombre, nuevo_nombre=None, color=None):
        self.llamadas.append(("patch", nombre, nuevo_nombre, color))

    def eliminar_etiqueta(self, owner, repo, nombre):
        self.llamadas.append(("delete", nombre))


def test_gestion_de_etiquetas_se_propaga_a_github_y_a_las_bases(tmp_path):
    import pytest

    from gnomilestone.store import EtiquetaDuplicadaError
    from gnomilestone.sync import GitHubSyncManager

    store, proyecto, tarea = _proyecto_con_issue(tmp_path)
    bug = store.asegurar_etiqueta(proyecto.id, "bug", "d73a4a")
    otra = store.asegurar_etiqueta(proyecto.id, "docs")
    store.establecer_etiquetas_de_tarea(tarea.id, [bug.id, otra.id])
    store.guardar_etiquetas_base_github(tarea.id, ["bug", "docs"])
    cliente = _ClienteGestionEtiquetas()
    gestor = GitHubSyncManager(store, cliente)

    gestor.renombrar_etiqueta(bug.id, "defecto", en_segundo_plano=False)
    gestor.cambiar_color_etiqueta(bug.id, "#00ff00", en_segundo_plano=False)
    assert cliente.llamadas == [("patch", "bug", "defecto", None), ("patch", "defecto", None, "#00ff00")]
    assert sorted(store.etiquetas_base_github(tarea.id)) == ["defecto", "docs"]
    assert store.obtener_etiqueta(bug.id).color == "00ff00"

    with pytest.raises(EtiquetaDuplicadaError):
        gestor.renombrar_etiqueta(bug.id, "DOCS", en_segundo_plano=False)

    gestor.eliminar_etiqueta(otra.id, en_segundo_plano=False)
    assert cliente.llamadas[-1] == ("delete", "docs")
    assert store.etiquetas_base_github(tarea.id) == ["defecto"]
    assert [e.nombre for e in store.listar_etiquetas_de_tarea(tarea.id)] == ["defecto"]
    assert store.contar_tareas_por_etiqueta(proyecto.id) == {bug.id: 1}


class _ClienteColumnas:
    def __init__(self, antes, despues):
        self.respuestas = [({"id": "PVT", "status_field_id": "F_STATUS"}, antes, []),
                           ({"id": "PVT", "status_field_id": "F_STATUS"}, despues, [])]
        self.enviadas = None
        self.estados_item = []

    def obtener_detalles_proyecto_v2(self, owner, num):
        return self.respuestas.pop(0)

    def reemplazar_opciones_status(self, field_id, opciones):
        self.enviadas = [(o.name, o.color) for o in opciones]

    def actualizar_status_item_v2(self, project_id, item_id, status_field_id, single_select_option_id):
        self.estados_item.append((item_id, single_select_option_id))


def test_push_columnas_envia_nombres_orden_y_restituye_estados(tmp_path):
    from gnomilestone.github import GitHubStatusOption as Op
    from gnomilestone.store import Store
    from gnomilestone.sync import GitHubSyncManager

    store = Store(tmp_path / "db.sqlite")
    proyecto = store.crear_proyecto(
        "P", github_repo_owner="yo", github_repo_name="repo", github_project_v2_id="3"
    )
    pendiente, en_curso, _hecho = store.listar_estados(proyecto.id)
    store.asociar_github_option_estado(pendiente.id, "old1")
    store.asociar_github_option_estado(en_curso.id, "old2")
    store.renombrar_estado(en_curso.id, "Haciendo")
    store.crear_estado(proyecto.id, "Revisión")
    tarea = store.crear_tarea(proyecto.id, "T", estado_id=en_curso.id)
    tarea.github_item_id = "ITEM"
    store.actualizar_tarea(tarea)

    antes = [Op("old1", "Todo", "RED", "d"), Op("old2", "In Progress", "BLUE")]
    despues = [Op("n1", "Todo"), Op("n2", "Haciendo"), Op("n3", "Done"), Op("n4", "Revisión")]
    cliente = _ClienteColumnas(antes, despues)
    # El item de la tarea sigue en el proyecto, pero GitHub no le conoce estado.
    from gnomilestone.github import GitHubItem

    cliente.respuestas[0] = (cliente.respuestas[0][0], antes, [GitHubItem(id="ITEM", title="T")])

    GitHubSyncManager(store, cliente).push_columnas(proyecto.id, en_segundo_plano=False)

    assert [n for n, _c in cliente.enviadas] == ["Todo", "Haciendo", "Done", "Revisión"]
    assert dict(cliente.enviadas)["Todo"] == "RED"  # conserva el color previo
    asociados = {e.nombre: e.github_option_id for e in store.listar_estados(proyecto.id)}
    assert asociados == {"Todo": "n1", "Haciendo": "n2", "Done": "n3", "Revisión": "n4"}
    assert cliente.estados_item == [("ITEM", "n2")]


def test_push_columnas_sin_project_v2_no_hace_nada(tmp_path):
    from gnomilestone.store import Store
    from gnomilestone.sync import GitHubSyncManager

    store = Store(tmp_path / "db.sqlite")
    proyecto = store.crear_proyecto("P", github_repo_owner="yo", github_repo_name="repo")
    cliente = _ClienteColumnas([], [])
    GitHubSyncManager(store, cliente).push_columnas(proyecto.id, en_segundo_plano=False)
    assert cliente.enviadas is None


def test_push_columnas_restituye_el_estado_remoto_de_todos_los_items(tmp_path):
    from gnomilestone.github import GitHubItem
    from gnomilestone.github import GitHubStatusOption as Op
    from gnomilestone.store import Store
    from gnomilestone.sync import GitHubSyncManager

    store = Store(tmp_path / "db.sqlite")
    proyecto = store.crear_proyecto(
        "P", github_repo_owner="yo", github_repo_name="repo", github_project_v2_id="3"
    )
    pendiente, en_curso, _hecho = store.listar_estados(proyecto.id)
    store.asociar_github_option_estado(pendiente.id, "old1")
    store.asociar_github_option_estado(en_curso.id, "old2")
    store.renombrar_estado(en_curso.id, "Haciendo")

    antes = [Op("old1", "Todo"), Op("old2", "In Progress")]
    items = [
        GitHubItem(id="A", title="a", status_option_id="old2"),  # solo existe en GitHub
        GitHubItem(id="B", title="b", status_option_id="old1"),
        GitHubItem(id="C", title="c", status_option_id=None),
    ]
    cliente = _ClienteColumnas(antes, [Op("n1", "Todo"), Op("n2", "Haciendo"), Op("n3", "Done")])
    cliente.respuestas[0] = (cliente.respuestas[0][0], antes, items)

    GitHubSyncManager(store, cliente).push_columnas(proyecto.id, en_segundo_plano=False)

    assert sorted(cliente.estados_item) == [("A", "n2"), ("B", "n1")]  # C no tenía estado


def test_push_columnas_ignora_items_locales_que_ya_no_existen_en_el_proyecto(tmp_path):
    from gnomilestone.github import GitHubStatusOption as Op
    from gnomilestone.store import Store
    from gnomilestone.sync import GitHubSyncManager

    store = Store(tmp_path / "db.sqlite")
    proyecto = store.crear_proyecto(
        "P", github_repo_owner="yo", github_repo_name="repo", github_project_v2_id="3"
    )
    pendiente = store.listar_estados(proyecto.id)[0]
    tarea = store.crear_tarea(proyecto.id, "T", estado_id=pendiente.id)
    tarea.github_item_id = "ITEM_BORRADO"
    store.actualizar_tarea(tarea)
    cliente = _ClienteColumnas([Op("o", "Pendiente")], [Op("n1", "Pendiente")])

    GitHubSyncManager(store, cliente).push_columnas(proyecto.id, en_segundo_plano=False)

    assert cliente.estados_item == []  # no se intenta fijar el estado de un item inexistente


def test_gestion_de_etiquetas_tolera_que_no_exista_en_github(tmp_path):
    from gnomilestone.github import GitHubNotFoundError
    from gnomilestone.sync import GitHubSyncManager

    class _Cliente:
        def __init__(self):
            self.creadas = []

        def actualizar_etiqueta(self, *args, **kwargs):
            raise GitHubNotFoundError("404")

        def eliminar_etiqueta(self, *args):
            raise GitHubNotFoundError("404")

        def crear_etiqueta(self, owner, repo, nombre, color, descripcion=""):
            self.creadas.append((nombre, color))

    store, proyecto, _tarea = _proyecto_con_issue(tmp_path)
    solo_local = store.asegurar_etiqueta(proyecto.id, "funcionalidad", "0e8a16")
    cliente = _Cliente()
    gestor = GitHubSyncManager(store, cliente)

    gestor.cambiar_color_etiqueta(solo_local.id, "d73a4a", en_segundo_plano=False)
    assert cliente.creadas == [("funcionalidad", "d73a4a")]  # se crea ya con su color

    gestor.renombrar_etiqueta(solo_local.id, "feature", en_segundo_plano=False)  # sin error
    gestor.eliminar_etiqueta(solo_local.id, en_segundo_plano=False)  # sin error
    assert store.listar_etiquetas(proyecto.id) == []


def test_push_sigue_enviando_la_tarea_aunque_no_se_puedan_leer_las_etiquetas(tmp_path):
    from gnomilestone.github import GitHubError
    from gnomilestone.sync import GitHubSyncManager

    store, proyecto, tarea = _proyecto_con_issue(tmp_path)
    bug = store.asegurar_etiqueta(proyecto.id, "bug")
    store.establecer_etiquetas_de_tarea(tarea.id, [bug.id])
    store.guardar_etiquetas_base_github(tarea.id, ["x"])
    cliente = _ClienteEtiquetas([])
    enviado = {}

    def _falla(*_a, **_k):
        raise GitHubError("tiempo agotado")

    cliente.obtener_issue = _falla
    cliente.actualizar_issue = lambda **kw: enviado.update(kw) or {}

    assert GitHubSyncManager(store, cliente).push_tarea(tarea.id)

    assert enviado["titulo"] == tarea.titulo
    assert enviado["labels"] is None  # etiquetas sin tocar
    assert store.etiquetas_base_github(tarea.id) == ["x"]  # la base no cambia


def test_renombrar_en_local_y_sincronizar_no_duplica_la_tarea(tmp_path):
    """Issue #28: renombrar en local y volver a sincronizar (pull y push) no crea copias."""
    store = Store(tmp_path / "test.db")
    p = store.crear_proyecto(
        "Bloguero",
        github_repo_owner="testuser",
        github_repo_name="bloguero",
        github_project_v2_id="11",
    )
    t = store.crear_tarea(p.id, "Título original")
    t.github_issue_number = 1
    t.github_item_id = "ITEM_1"
    store.actualizar_tarea(t)
    with closing(store._connect()) as db, db:
        db.execute("UPDATE tarea SET github_synced_at = '2026-01-01 00:00:00' WHERE id = ?", (t.id,))

    t = store.obtener_tarea(t.id)
    t.titulo = "Título renombrado en local"
    store.actualizar_tarea(t)

    item = GitHubItem(
        id="ITEM_1",
        title="Título original",
        issue_number=1,
        url="https://github.com/testuser/bloguero/issues/1",
    )
    client = MagicMock(spec=GitHubClient)
    client.obtener_detalles_proyecto_v2.return_value = (
        {"id": "PVT_11", "fields": {}, "status_field_id": None},
        [],
        [item],
    )
    client.listar_issues.return_value = [{"number": 1, "title": "Título original", "state": "open"}]
    client.obtener_issue.return_value = {"labels": []}

    sync = GitHubSyncManager(store, client)
    push_real = sync._push_tarea
    sync._push_tarea = lambda _tid, **_kw: False
    res = sync.pull_proyecto(p.id)
    sync._push_tarea = push_real
    assert res.tareas_creadas == 0
    assert len(res.conflictos) == 1
    assert [x.titulo for x in store.listar_tareas(p.id)] == ["Título renombrado en local"]

    assert sync.push_tarea(t.id) is True
    assert client.actualizar_issue.call_args.kwargs["titulo"] == "Título renombrado en local"
    client.crear_issue.assert_not_called()

    # GitHub ya tiene el título nuevo: otro pull sigue sin duplicar ni dar conflicto.
    item.title = "Título renombrado en local"
    client.listar_issues.return_value = [
        {"number": 1, "title": item.title, "state": "open"}
    ]
    res = sync.pull_proyecto(p.id)
    assert res.tareas_creadas == 0
    assert res.conflictos == []
    assert [x.titulo for x in store.listar_tareas(p.id)] == ["Título renombrado en local"]


def test_pull_trae_los_ficheros_de_contexto_del_repositorio(tmp_path):
    store = Store(tmp_path / "test.db")
    p = store.crear_proyecto("Demo", github_repo_owner="yo", github_repo_name="demo")
    client = MagicMock(spec=GitHubClient)
    client.listar_issues.return_value = []
    ficheros = {"README.md": "# Demo\n", "LICENSE": "GPL\n"}
    client.obtener_fichero_repo.side_effect = lambda _o, _r, ruta: ficheros.get(ruta)

    res = GitHubSyncManager(store, client).pull_proyecto(p.id)

    assert not res.errores
    assert res.documentos_actualizados == 2
    sub = store.listar_subsecciones_documentacion(p.id, "vision_general")[0]
    notas = {n.titulo: n.contenido for n in store.listar_notas_documentacion(p.id, subseccion_id=sub.id)}
    assert notas["README"] == "# Demo\n"
    assert notas["Licencia"] == "```\nGPL\n```\n"
    assert notas.get("Seguridad", "") == ""  # no está en el repositorio: no se toca

    # Una segunda sincronización sin cambios en GitHub no vuelve a escribir nada.
    assert GitHubSyncManager(store, client).pull_proyecto(p.id).documentos_actualizados == 0


def test_pull_sin_repositorio_no_busca_ficheros_de_contexto(tmp_path):
    store = Store(tmp_path / "test.db")
    p = store.crear_proyecto("Demo", github_repo_owner="yo")  # solo tablero, sin repo
    client = MagicMock(spec=GitHubClient)
    GitHubSyncManager(store, client).pull_proyecto(p.id)
    client.obtener_fichero_repo.assert_not_called()


def test_push_envia_prioridad_y_fechas_a_los_campos_de_issue(tmp_path):
    store = Store(tmp_path / "test.db")
    p = store.crear_proyecto("Bloguero", github_repo_owner="testuser", github_repo_name="bloguero")
    t = store.crear_tarea(p.id, "Tarea", fecha_inicio="2026-11-01", prioridad=4)
    t.github_issue_number = 105
    store.actualizar_tarea(t)

    client = MagicMock(spec=GitHubClient)
    client.obtener_issue.return_value = {"labels": [], "node_id": "ISSUE_NODE"}
    client.listar_campos_issue.return_value = {
        "priority": {"id": "F_PRI", "options": {"Urgent": "O_U", "High": "O_H"}},
        "start date": {"id": "F_START", "options": {}},
    }

    assert GitHubSyncManager(store, client).push_tarea(t.id) is True

    client.establecer_campos_issue.assert_called_once_with(
        "ISSUE_NODE",
        [
            {"fieldId": "F_PRI", "singleSelectOptionId": "O_U"},
            {"fieldId": "F_START", "dateValue": "2026-11-01"},
        ],
    )


def test_push_ignora_el_rechazo_de_fechas_que_son_campos_de_issue(tmp_path):
    from gnomilestone.github import GitHubError

    store = Store(tmp_path / "test.db")
    p = store.crear_proyecto(
        "B", github_repo_owner="u", github_repo_name="b", github_project_v2_id="11"
    )
    t = store.crear_tarea(p.id, "T", fecha_inicio="2026-11-01")
    t.github_issue_number = 5
    t.github_item_id = "ITEM"
    store.actualizar_tarea(t)

    client = MagicMock(spec=GitHubClient)
    client.obtener_issue.return_value = {"labels": [], "node_id": "N"}
    client.obtener_detalles_proyecto_v2.return_value = (
        {"id": "PVT", "fields": {"Start date": "F_S"}},
        [],
        [],
    )
    client.actualizar_fecha_item_v2.side_effect = GitHubError(
        "GraphQL error: Issue field values cannot be updated using the updateProjectV2ItemFieldValue mutation"
    )
    client.listar_campos_issue.return_value = {"start date": {"id": "IF_S", "options": {}}}

    assert GitHubSyncManager(store, client).push_tarea(t.id) is True
    client.establecer_campos_issue.assert_called_once_with(
        "N", [{"fieldId": "IF_S", "dateValue": "2026-11-01"}]
    )


def test_push_vincula_la_tarea_como_subissue_de_su_padre_y_a_sus_hijas(tmp_path):
    store = Store(tmp_path / "test.db")
    p = store.crear_proyecto("B", github_repo_owner="u", github_repo_name="b")
    padre = store.crear_tarea(p.id, "Padre")
    medio = store.crear_tarea(p.id, "Medio", padre_id=padre.id)
    hija = store.crear_tarea(p.id, "Hija", padre_id=medio.id)
    for t, n in ((padre, 1), (medio, 2), (hija, 3)):
        t.github_issue_number = n
        store.actualizar_tarea(t)

    client = MagicMock(spec=GitHubClient)
    client.obtener_issue.side_effect = lambda o, r, n: {"labels": [], "id": 1000 + n}
    client.listar_campos_issue.return_value = {}

    assert GitHubSyncManager(store, client).push_tarea(medio.id) is True
    llamadas = [c.args for c in client.vincular_subissue.call_args_list]
    assert llamadas == [("u", "b", 1, 1002), ("u", "b", 2, 1003)]


def _proyecto_con_repo(store):
    return store.crear_proyecto("B", github_repo_owner="u", github_repo_name="b")


def test_push_de_un_hito_crea_su_milestone_y_mete_en_el_a_sus_tareas(tmp_path):
    store = Store(tmp_path / "test.db")
    p = _proyecto_con_repo(store)
    hito = store.crear_hito(p.id, "Release 1.0", "2026-12-01", "Notas")
    con_issue = store.crear_tarea(p.id, "Con issue", hito_id=hito.id)
    store.crear_tarea(p.id, "Sin issue", hito_id=hito.id)
    con_issue.github_issue_number = 7
    store.actualizar_tarea(con_issue)

    client = MagicMock(spec=GitHubClient)
    client.crear_milestone.return_value = {"number": 3}

    assert GitHubSyncManager(store, client).push_hito(hito.id) is True

    client.crear_milestone.assert_called_once_with("u", "b", "Release 1.0", "2026-12-01", "Notas", False)
    assert store.obtener_hito(hito.id).github_milestone_number == 3
    client.actualizar_issue.assert_called_once_with("u", "b", 7, milestone=3)
    client.crear_issue.assert_not_called()  # un Hito no es un issue


def test_push_de_un_hito_ya_vinculado_lo_actualiza_y_lo_cierra_si_esta_conseguido(tmp_path):
    store = Store(tmp_path / "test.db")
    p = _proyecto_con_repo(store)
    hito = store.crear_hito(p.id, "R", "2026-12-01", github_milestone_number=4)
    store.crear_tarea(p.id, "T", hito_id=hito.id, porcentaje_completado=100)

    client = MagicMock(spec=GitHubClient)
    assert GitHubSyncManager(store, client).push_hito(hito.id) is True
    client.actualizar_milestone.assert_called_once_with("u", "b", 4, "R", "2026-12-01", "", True)
    client.crear_milestone.assert_not_called()


def test_hito_de_proyecto_sin_repo_no_envia_nada(tmp_path):
    store = Store(tmp_path / "test.db")
    p = store.crear_proyecto("Local")
    hito = store.crear_hito(p.id, "H")
    client = MagicMock(spec=GitHubClient)
    assert GitHubSyncManager(store, client).push_hito(hito.id) is True
    client.crear_milestone.assert_not_called()


def test_push_de_una_tarea_la_mete_en_el_milestone_de_su_hito(tmp_path):
    store = Store(tmp_path / "test.db")
    p = _proyecto_con_repo(store)
    hito = store.crear_hito(p.id, "R", github_milestone_number=9)
    tarea = store.crear_tarea(p.id, "T", hito_id=hito.id)
    tarea.github_issue_number = 12
    store.actualizar_tarea(tarea)

    client = MagicMock(spec=GitHubClient)
    client.obtener_issue.return_value = {"labels": []}
    client.listar_campos_issue.return_value = {}

    assert GitHubSyncManager(store, client).push_tarea(tarea.id) is True
    client.actualizar_issue.assert_any_call("u", "b", 12, milestone=9)


def test_push_de_una_tarea_crea_el_milestone_de_su_hito_si_falta(tmp_path):
    store = Store(tmp_path / "test.db")
    p = _proyecto_con_repo(store)
    hito = store.crear_hito(p.id, "R", "2026-12-01")
    tarea = store.crear_tarea(p.id, "T", hito_id=hito.id)
    tarea.github_issue_number = 12
    store.actualizar_tarea(tarea)

    client = MagicMock(spec=GitHubClient)
    client.obtener_issue.return_value = {"labels": []}
    client.listar_campos_issue.return_value = {}
    client.crear_milestone.return_value = {"number": 5}

    assert GitHubSyncManager(store, client).push_tarea(tarea.id) is True
    client.actualizar_issue.assert_any_call("u", "b", 12, milestone=5)
    assert store.obtener_hito(hito.id).github_milestone_number == 5


def test_tarea_sin_hito_sale_del_milestone_de_un_hito_local(tmp_path):
    store = Store(tmp_path / "test.db")
    p = _proyecto_con_repo(store)
    store.crear_hito(p.id, "R", github_milestone_number=9)
    suelta = store.crear_tarea(p.id, "Suelta")
    suelta.github_issue_number = 21
    store.actualizar_tarea(suelta)

    client = MagicMock(spec=GitHubClient)
    client.obtener_issue.return_value = {"labels": [], "milestone": {"number": 9}}
    client.listar_campos_issue.return_value = {}

    assert GitHubSyncManager(store, client).push_tarea(suelta.id) is True
    client.quitar_milestone_issue.assert_called_once_with("u", "b", 21)


def test_no_se_saca_de_un_milestone_que_no_es_de_ningun_hito(tmp_path):
    store = Store(tmp_path / "test.db")
    p = _proyecto_con_repo(store)
    suelta = store.crear_tarea(p.id, "Suelta")
    suelta.github_issue_number = 21
    store.actualizar_tarea(suelta)

    client = MagicMock(spec=GitHubClient)
    client.obtener_issue.return_value = {"labels": [], "milestone": {"number": 77}}
    client.listar_campos_issue.return_value = {}

    assert GitHubSyncManager(store, client).push_tarea(suelta.id) is True
    client.quitar_milestone_issue.assert_not_called()


def test_pull_crea_un_hito_por_milestone_y_empareja_por_titulo(tmp_path):
    from gnomilestone.sync import SyncResult

    store = Store(tmp_path / "test.db")
    p = _proyecto_con_repo(store)
    local = store.crear_hito(p.id, "Distribución")  # aún sin Milestone
    vinculado = store.crear_hito(p.id, "Viejo título", github_milestone_number=2)
    store.marcar_hito_sincronizado(vinculado.id)

    client = MagicMock(spec=GitHubClient)
    client.listar_milestones.return_value = [
        {"number": 1, "title": "distribución", "due_on": "2026-11-24T00:00:00Z", "state": "open"},
        {"number": 2, "title": "Nuevo título", "due_on": None, "state": "closed"},
        {"number": 3, "title": "v1.0", "due_on": "2026-12-01T00:00:00Z", "state": "open",
         "description": "Notas"},
    ]
    resultado = SyncResult()
    GitHubSyncManager(store, client)._pull_milestones(p.id, "u", "b", resultado)

    assert resultado.errores == []
    hitos = {h.github_milestone_number: h for h in store.listar_hitos(p.id)}
    assert hitos[1].id == local.id and hitos[1].fecha == "2026-11-24"  # emparejado, sin duplicar
    assert hitos[2].titulo == "Nuevo título" and hitos[2].conseguido is True
    assert (hitos[3].titulo, hitos[3].fecha, hitos[3].descripcion) == ("v1.0", "2026-12-01", "Notas")
    assert len(hitos) == 3


def test_pull_no_pisa_un_hito_editado_en_local_despues_del_ultimo_sync(tmp_path):
    from gnomilestone.sync import SyncResult

    store = Store(tmp_path / "test.db")
    p = _proyecto_con_repo(store)
    hito = store.crear_hito(p.id, "Mi título", github_milestone_number=2)
    with store._connect() as db:  # editado (actualizado) después del último sync
        db.execute(
            "UPDATE hito SET github_synced_at = '2000-01-01 00:00:00', "
            "actualizado = '2000-01-02 00:00:00' WHERE id = ?",
            (hito.id,),
        )
    client = MagicMock(spec=GitHubClient)
    client.listar_milestones.return_value = [{"number": 2, "title": "Remoto", "state": "open"}]
    GitHubSyncManager(store, client)._pull_milestones(p.id, "u", "b", SyncResult())
    assert store.obtener_hito(hito.id).titulo == "Mi título"


def test_eliminar_hito_borra_tambien_su_milestone(tmp_path):
    store = Store(tmp_path / "test.db")
    p = _proyecto_con_repo(store)
    hito = store.crear_hito(p.id, "R", github_milestone_number=6)
    tarea = store.crear_tarea(p.id, "T", hito_id=hito.id)

    client = MagicMock(spec=GitHubClient)
    GitHubSyncManager(store, client).eliminar_hito(hito.id, en_segundo_plano=False)

    client.eliminar_milestone.assert_called_once_with("u", "b", 6)
    assert store.obtener_hito(hito.id) is None
    assert store.obtener_tarea(tarea.id).hito_id is None


def test_enlazar_hito_une_la_tarea_con_el_hito_de_su_milestone(tmp_path):
    store = Store(tmp_path / "test.db")
    p = _proyecto_con_repo(store)
    hito = store.crear_hito(p.id, "Release", github_milestone_number=4)
    tarea = store.crear_tarea(p.id, "T")
    sync = GitHubSyncManager(store, MagicMock(spec=GitHubClient))
    hitos = {4: hito.id, "release": hito.id}

    sync._enlazar_hito(tarea.id, hitos, 4, "Release", False)
    assert store.obtener_tarea(tarea.id).hito_id == hito.id
    sync._enlazar_hito(tarea.id, hitos, None, None, True)  # editada en local: no se toca
    assert store.obtener_tarea(tarea.id).hito_id == hito.id
    sync._enlazar_hito(tarea.id, hitos, None, None, False)  # el issue ya no está en un Milestone
    assert store.obtener_tarea(tarea.id).hito_id is None


def test_push_de_un_hito_se_vincula_al_milestone_que_ya_existia_con_ese_titulo(tmp_path):
    store = Store(tmp_path / "test.db")
    p = _proyecto_con_repo(store)
    hito = store.crear_hito(p.id, "Distribución", "2026-11-24")

    client = MagicMock(spec=GitHubClient)
    client.crear_milestone.side_effect = GitHubError(
        'Error de GitHub API (HTTP 422): {"errors":[{"code":"already_exists","field":"title"}]}'
    )
    client.listar_milestones.return_value = [
        {"number": 1, "title": "Otro"}, {"number": 5, "title": "distribución"},
    ]

    assert GitHubSyncManager(store, client).push_hito(hito.id) is True
    assert store.obtener_hito(hito.id).github_milestone_number == 5
    client.actualizar_milestone.assert_called_once_with(
        "u", "b", 5, "Distribución", "2026-11-24", "", False
    )


def test_un_error_de_github_distinto_no_se_confunde_con_milestone_existente(tmp_path):
    store = Store(tmp_path / "test.db")
    p = _proyecto_con_repo(store)
    hito = store.crear_hito(p.id, "H")
    client = MagicMock(spec=GitHubClient)
    client.crear_milestone.side_effect = GitHubError("HTTP 500")
    assert GitHubSyncManager(store, client).push_hito(hito.id) is False
    client.listar_milestones.assert_not_called()


def test_tipo_para_issue_usa_el_nombre_del_repositorio_y_omite_si_no_existe():
    from unittest.mock import MagicMock

    from gnomilestone.models import Tarea
    from gnomilestone.sync import GitHubSyncManager

    cliente = MagicMock()
    cliente.listar_tipos_issue.return_value = ["Tarea", "Error", "Funcionalidad"]
    sync = GitHubSyncManager(MagicMock(), cliente)
    assert sync._tipo_para_issue("o", "r", Tarea(1, 1, "T", tipo="error")) == {"tipo": "Error"}
    assert sync._tipo_para_issue("o", "r", Tarea(2, 1, "T")) == {}
    cliente.listar_tipos_issue.return_value = ["Epic"]
    sync = GitHubSyncManager(MagicMock(), cliente)
    assert sync._tipo_para_issue("o", "r", Tarea(3, 1, "T", tipo="error")) == {}


def test_enviar_jerarquia_ignora_los_subissues_ya_enlazados_y_sigue_con_el_resto():
    from unittest.mock import MagicMock

    from gnomilestone.github import GitHubError
    from gnomilestone.models import Tarea

    tareas = [
        Tarea(1, 1, "padre", github_issue_number=10),
        Tarea(2, 1, "hija ya enlazada", padre_id=1, github_issue_number=11),
        Tarea(3, 1, "hija nueva", padre_id=1, github_issue_number=12),
    ]
    store = MagicMock()
    store.listar_tareas.return_value = tareas
    cliente = MagicMock()
    cliente.obtener_issue.side_effect = lambda o, r, n: {"id": 1000 + n}
    cliente.vincular_subissue.side_effect = [
        GitHubError("422: Issue may not contain duplicate sub-issues"), None,
    ]
    GitHubSyncManager(store, cliente)._enviar_jerarquia("o", "r", tareas[0])
    assert cliente.vincular_subissue.call_count == 2


def test_push_reutiliza_el_item_si_github_dice_que_el_contenido_ya_existe(tmp_path):
    store = Store(tmp_path / "test.db")
    p = store.crear_proyecto(
        "Bloguero",
        github_repo_owner="testuser",
        github_repo_name="bloguero",
        github_project_v2_id="11",
    )
    t = store.crear_tarea(p.id, "Ya en el proyecto")
    t.github_issue_number = 23
    store.actualizar_tarea(t)

    client = MagicMock(spec=GitHubClient)
    client.obtener_issue.return_value = {"labels": [], "node_id": "I_23"}
    client.obtener_detalles_proyecto_v2.return_value = (
        {"id": "PVT_11", "fields": {}},
        [],
        [GitHubItem(id="ITEM_23", title="Ya en el proyecto", issue_number=23)],
    )
    client.anadir_item_v2.side_effect = GitHubError(
        "GraphQL error: Content already exists in this project"
    )

    GitHubSyncManager(store, client).push_tarea(t.id)

    assert store.obtener_tarea(t.id).github_item_id == "ITEM_23"


def test_push_vuelve_a_anadir_el_item_que_ya_no_existe_en_el_project(tmp_path):
    store = Store(tmp_path / "test.db")
    p = store.crear_proyecto(
        "Bloguero",
        github_repo_owner="testuser",
        github_repo_name="bloguero",
        github_project_v2_id="11",
    )
    estado = store.crear_estado(p.id, "Hecho", github_option_id="OPT_DONE")
    t = store.crear_tarea(p.id, "Con item caducado", estado_id=estado.id)
    t.github_issue_number = 6
    t.github_item_id = "ITEM_VIEJO"
    store.actualizar_tarea(t)

    client = MagicMock(spec=GitHubClient)
    client.obtener_issue.return_value = {"labels": [], "node_id": "I_6"}
    client.obtener_detalles_proyecto_v2.return_value = (
        {"id": "PVT_11", "fields": {}, "status_field_id": "FIELD_STATUS"},
        [],
        [],
    )
    client.anadir_item_v2.return_value = "ITEM_NUEVO"

    def actualizar(project_id, item_id, status_field_id, single_select_option_id):
        if item_id == "ITEM_VIEJO":
            raise GitHubError("GraphQL error: The item does not exist in the project")

    client.actualizar_status_item_v2.side_effect = actualizar

    assert GitHubSyncManager(store, client).push_tarea(t.id) is True

    assert store.obtener_tarea(t.id).github_item_id == "ITEM_NUEVO"
    client.actualizar_status_item_v2.assert_called_with(
        project_id="PVT_11",
        item_id="ITEM_NUEVO",
        status_field_id="FIELD_STATUS",
        single_select_option_id="OPT_DONE",
    )


def test_tareas_pendientes_de_envio_y_enviar_pendientes(tmp_path):
    store = Store(tmp_path / "test.db")
    p = store.crear_proyecto("P", github_repo_owner="u", github_repo_name="r")
    sincronizada = store.crear_tarea(p.id, "Sincronizada", github_issue_number=1)
    store.marcar_sincronizada_github(sincronizada.id)
    editada = store.crear_tarea(p.id, "Editada", github_issue_number=2)
    store.marcar_sincronizada_github(editada.id)
    with closing(store._connect()) as db, db:
        db.execute(
            "UPDATE tarea SET actualizado = '2999-01-01 00:00:00' WHERE id = ?", (editada.id,)
        )
    nueva = store.crear_tarea(p.id, "Nueva")

    sync = GitHubSyncManager(store, MagicMock(spec=GitHubClient))
    ids = {t.id for t in sync.tareas_pendientes_de_envio(p.id)}
    assert ids == {editada.id, nueva.id}

    enviadas = []
    sync._push_tarea = lambda tid, **_kw: enviadas.append(tid) or tid != nueva.id
    fallos = sync.enviar_pendientes(p.id)
    assert set(enviadas) == {editada.id, nueva.id}
    assert len(fallos) == 1 and "Nueva" in fallos[0]


def test_push_de_subtarea_movida_por_su_padre_envia_sus_fechas_nuevas(tmp_path):
    from gnomilestone import ganttcalc

    store = Store(tmp_path / "test.db")
    p = store.crear_proyecto(
        "P", github_repo_owner="u", github_repo_name="r", github_project_v2_id="11"
    )
    padre = store.crear_tarea(
        p.id, "Padre", fecha_inicio="2026-11-01", fecha_fin_planificada="2026-11-10",
        duracion_dias=10,
    )
    hijo = store.crear_tarea(
        p.id, "Hijo", padre_id=padre.id, fecha_inicio="2026-11-02",
        fecha_fin_planificada="2026-11-04", duracion_dias=3,
    )
    for t, n in ((padre, 1), (hijo, 2)):
        t.github_issue_number, t.github_item_id = n, f"ITEM_{n}"
        store.actualizar_tarea(t)

    # Lo mismo que hace el Gantt al mover el padre 5 días.
    for h in ganttcalc.trasladar_hijos(store.listar_tareas(p.id), padre.id, 5):
        store.actualizar_tarea(h)

    client = MagicMock(spec=GitHubClient)
    client.obtener_issue.return_value = {"labels": []}
    client.obtener_detalles_proyecto_v2.return_value = (
        {"id": "PVT", "fields": {"Start date": "F_S", "Target date": "F_T"}}, [], [],
    )
    sync = GitHubSyncManager(store, client)
    assert sync.push_tarea(hijo.id) is True
    client.actualizar_fecha_item_v2.assert_any_call(
        project_id="PVT", item_id="ITEM_2", field_id="F_S", fecha_iso="2026-11-07"
    )
    client.actualizar_fecha_item_v2.assert_any_call(
        project_id="PVT", item_id="ITEM_2", field_id="F_T", fecha_iso="2026-11-09"
    )


def test_varios_401_se_resumen_en_un_solo_aviso():
    from gnomilestone.sync import SyncResult

    res = SyncResult()
    res.errores = [
        "Error sincronizando issues: Error de autenticación con GitHub (HTTP 401): {}",
        "Error trayendo los Milestones: Error de autenticación con GitHub (HTTP 401): {}",
        "No se pudo enviar a GitHub la tarea «X»; sigue pendiente.",
    ]
    res = GitHubSyncManager._resumir_errores_401(res)
    assert len(res.errores) == 2
    assert "HTTP 401" in res.errores[1] and "token" in res.errores[1]
    assert "sigue pendiente" in res.errores[0]


def _proyecto_con_asignado(tmp_path):
    store = Store(tmp_path / "test.db")
    p = store.crear_proyecto(
        "P", github_repo_owner="u", github_repo_name="r", github_project_v2_id="11"
    )
    t = store.crear_tarea(p.id, "T")
    t.github_issue_number, t.github_item_id = 1, "ITEM_1"
    store.actualizar_tarea(t)
    ana = store.crear_recurso(p.id, "Ana", github_login="ana")
    bea = store.crear_recurso(p.id, "Bea", github_login="bea")
    store.asignar_recurso(t.id, ana.id)
    store.asignar_recurso(t.id, bea.id)
    store.guardar_asignados_base_github(t.id, ["ana", "bea"])
    store.marcar_sincronizada_github(t.id)
    return store, p, t


def test_pull_quita_el_asignado_que_se_quito_en_github(tmp_path):
    store, p, t = _proyecto_con_asignado(tmp_path)
    client = MagicMock(spec=GitHubClient)
    client.obtener_detalles_proyecto_v2.return_value = (
        {"id": "PVT_11", "fields": {}, "status_field_id": None},
        [],
        [GitHubItem(id="ITEM_1", title="T", issue_number=1, assignees=["ana"])],
    )
    GitHubSyncManager(store, client).pull_proyecto(p.id)
    assert [r.github_login for r in store.listar_recursos_de_tarea(t.id)] == ["ana"]
    assert store.asignados_base_github(t.id) == {"ana"}


def test_pull_no_quita_un_asignado_anadido_en_local_sin_enviar(tmp_path):
    store, p, t = _proyecto_con_asignado(tmp_path)
    cai = store.crear_recurso(p.id, "Cai", github_login="cai")
    store.asignar_recurso(t.id, cai.id)  # local, aún no enviado: no está en la base
    client = MagicMock(spec=GitHubClient)
    client.obtener_detalles_proyecto_v2.return_value = (
        {"id": "PVT_11", "fields": {}, "status_field_id": None},
        [],
        [GitHubItem(id="ITEM_1", title="T", issue_number=1, assignees=["ana", "bea"])],
    )
    GitHubSyncManager(store, client).pull_proyecto(p.id)
    logins = {r.github_login for r in store.listar_recursos_de_tarea(t.id)}
    assert logins == {"ana", "bea", "cai"}


def test_push_propaga_la_desasignacion_local_y_respeta_lo_puesto_en_github(tmp_path):
    store, _p, t = _proyecto_con_asignado(tmp_path)
    bea = next(r for r in store.listar_recursos_de_tarea(t.id) if r.github_login == "bea")
    store.quitar_asignacion_tarea_recurso(t.id, bea.id)
    client = MagicMock(spec=GitHubClient)
    # En GitHub, además, alguien asignó a «dan» desde el último sync.
    client.obtener_issue.return_value = {
        "labels": [],
        "assignees": [{"login": "ana"}, {"login": "bea"}, {"login": "dan"}],
    }
    client.obtener_detalles_proyecto_v2.return_value = ({"id": "PVT", "fields": {}}, [], [])
    assert GitHubSyncManager(store, client).push_tarea(t.id) is True
    assert client.actualizar_issue.call_args.kwargs["assignees"] == ["ana", "dan"]
    assert store.asignados_base_github(t.id) == {"ana"}


def _proyecto_con_dos_issues(tmp_path):
    store = Store(tmp_path / "test.db")
    p = store.crear_proyecto("P", github_repo_owner="u", github_repo_name="r")
    viva = store.crear_tarea(p.id, "Viva", github_issue_number=1)
    borrada = store.crear_tarea(p.id, "Borrada", github_issue_number=2)
    for t in (viva, borrada):
        store.marcar_sincronizada_github(t.id)
    return store, p, viva, borrada


def test_pull_archiva_la_tarea_cuyo_issue_se_borro_en_github(tmp_path):
    from gnomilestone.github import GitHubNotFoundError

    store, p, viva, borrada = _proyecto_con_dos_issues(tmp_path)
    client = MagicMock(spec=GitHubClient)
    client.listar_issues.return_value = [{"number": 1, "title": "Viva", "state": "open"}]
    client.obtener_issue.side_effect = GitHubNotFoundError("404")
    res = GitHubSyncManager(store, client).pull_proyecto(p.id)
    assert store.obtener_tarea(borrada.id).archivada is True
    assert store.obtener_tarea(viva.id).archivada is False
    assert any("#2" in a and "Borrada" in a for a in res.avisos)


def test_pull_no_archiva_si_el_listado_esta_truncado_ni_si_hay_cambios_locales(tmp_path):
    from gnomilestone.github import GitHubNotFoundError

    store, p, _viva, borrada = _proyecto_con_dos_issues(tmp_path)
    client = MagicMock(spec=GitHubClient)
    client.obtener_issue.side_effect = GitHubNotFoundError("404")
    # Listado de 100 issues: puede haber más páginas, que falte uno no prueba nada.
    client.listar_issues.return_value = [
        {"number": n, "title": f"I{n}", "state": "open"} for n in range(10, 110)
    ]
    GitHubSyncManager(store, client).pull_proyecto(p.id)
    assert store.obtener_tarea(borrada.id).archivada is False

    # Listado completo, pero la tarea tiene una edición local sin enviar.
    client.listar_issues.return_value = [{"number": 1, "title": "Viva", "state": "open"}]
    with closing(store._connect()) as db, db:
        db.execute(
            "UPDATE tarea SET actualizado = '2999-01-01 00:00:00' WHERE id = ?", (borrada.id,)
        )
    GitHubSyncManager(store, client).pull_proyecto(p.id)
    assert store.obtener_tarea(borrada.id).archivada is False


def test_un_envio_suelto_que_falla_avisa_a_los_oyentes_y_el_de_pendientes_no(tmp_path):
    from gnomilestone import sync as sync_mod

    store = Store(tmp_path / "test.db")
    p = store.crear_proyecto("P", github_repo_owner="u", github_repo_name="r")
    t = store.crear_tarea(p.id, "Tarea rota")
    client = MagicMock(spec=GitHubClient)
    client.crear_issue.side_effect = GitHubError("boom")
    avisos: list[str] = []
    sync_mod.al_fallar_envio(avisos.append)
    try:
        manager = GitHubSyncManager(store, client)
        assert manager.push_tarea(t.id) is False
        assert avisos == ["Tarea rota"]
        assert len(manager.enviar_pendientes(p.id)) == 1  # lo avisa el diálogo del sync
        assert avisos == ["Tarea rota"]
    finally:
        sync_mod._oyentes_fallo_envio.remove(avisos.append)


def _tarea_sincronizada_y_editada(tmp_path, **cambios_locales):
    store = Store(tmp_path / "test.db")
    p = store.crear_proyecto(
        "P", github_repo_owner="u", github_repo_name="r", github_project_v2_id="11"
    )
    t = store.crear_tarea(p.id, "Título base", descripcion="Desc base")
    t.github_issue_number, t.github_item_id = 1, "ITEM_1"
    store.actualizar_tarea(t)
    store.marcar_sincronizada_github(t.id)  # guarda la base de campos
    with closing(store._connect()) as db, db:
        db.execute(
            "UPDATE tarea SET github_synced_at = '2026-01-01 00:00:00' WHERE id = ?", (t.id,)
        )
    t = store.obtener_tarea(t.id)
    for campo, valor in cambios_locales.items():
        setattr(t, campo, valor)
    store.actualizar_tarea(t)  # edición local posterior al sync
    return store, p, t


def _pull_con_item(store, p, **item):
    client = MagicMock(spec=GitHubClient)
    client.obtener_detalles_proyecto_v2.return_value = (
        {"id": "PVT_11", "fields": {}, "status_field_id": None},
        [],
        [GitHubItem(id="ITEM_1", issue_number=1, **item)],
    )
    sync = GitHubSyncManager(store, client)
    sync._push_tarea = lambda _tid, **_kw: False  # el envío previo falla: sigue pendiente
    return sync.pull_proyecto(p.id)


def test_fusion_por_campo_trae_lo_remoto_y_conserva_lo_local(tmp_path):
    # Local cambió el título; GitHub cambió la descripción: se quedan los dos cambios.
    store, p, t = _tarea_sincronizada_y_editada(tmp_path, titulo="Título local")
    res = _pull_con_item(store, p, title="Título base", body="Desc remota")
    final = store.obtener_tarea(t.id)
    assert final.titulo == "Título local"
    assert final.descripcion == "Desc remota"
    assert res.conflictos == []
    # Sigue pendiente de envío (no se marcó como sincronizada).
    assert final.actualizado > final.github_synced_at


def test_fusion_por_campo_avisa_solo_del_campo_cambiado_en_ambos_lados(tmp_path):
    store, p, t = _tarea_sincronizada_y_editada(tmp_path, titulo="Título local")
    res = _pull_con_item(store, p, title="Título remoto", body="Desc remota")
    final = store.obtener_tarea(t.id)
    assert final.titulo == "Título local"  # gana lo local
    assert final.descripcion == "Desc remota"  # lo otro sí se trae
    assert len(res.conflictos) == 1 and "título" in res.conflictos[0]
    assert "descripción" not in res.conflictos[0]


def _repo_con_tres_tareas(tmp_path):
    store = Store(tmp_path / "test.db")
    p = store.crear_proyecto("P", github_repo_owner="u", github_repo_name="r")
    tareas = [store.crear_tarea(p.id, f"T{n}", github_issue_number=n) for n in (1, 2, 3)]
    for t in tareas:
        store.marcar_sincronizada_github(t.id)
    return store, p, tareas


def _issue(n, **extra):
    return {"number": n, "title": f"T{n}", "state": "open", **extra}


def test_pull_trae_el_padre_de_un_subissue_y_no_cierra_ciclos(tmp_path):
    store, p, (t1, t2, _t3) = _repo_con_tres_tareas(tmp_path)
    api = "https://api.github.com/repos/u/r/issues/"
    client = MagicMock(spec=GitHubClient)
    client.listar_issues.return_value = [
        _issue(1),
        _issue(2, parent_issue_url=api + "1"),  # 2 es subissue de 1
        _issue(3),
    ]
    GitHubSyncManager(store, client).pull_proyecto(p.id)
    assert store.obtener_tarea(t2.id).padre_id == t1.id
    assert store.obtener_tarea(t1.id).padre_id is None

    # Ahora GitHub dice que 1 es subissue de 2: cerraría un ciclo, se ignora.
    client.listar_issues.return_value = [_issue(1, parent_issue_url=api + "2"), _issue(2), _issue(3)]
    GitHubSyncManager(store, client).pull_proyecto(p.id)
    assert store.obtener_tarea(t1.id).padre_id is None


def test_pull_trae_las_dependencias_blocked_by(tmp_path):
    store, p, (t1, t2, _t3) = _repo_con_tres_tareas(tmp_path)
    client = MagicMock(spec=GitHubClient)
    client.listar_issues.return_value = [
        _issue(1),
        _issue(2, issue_dependencies_summary={"total_blocked_by": 1}),
    ]
    client.listar_bloqueos.return_value = [
        {"number": 1, "url": "https://api.github.com/repos/u/r/issues/1"},
        {"number": 9, "url": "https://api.github.com/repos/otro/repo/issues/9"},  # otro repo
    ]
    GitHubSyncManager(store, client).pull_proyecto(p.id)
    deps = store.listar_dependencias(p.id)
    assert [(d.tarea_origen_id, d.tarea_destino_id) for d in deps] == [(t1.id, t2.id)]
    # Una segunda sincronización no la duplica.
    GitHubSyncManager(store, client).pull_proyecto(p.id)
    assert len(store.listar_dependencias(p.id)) == 1


def test_push_envia_las_dependencias_locales_que_faltan_en_github(tmp_path):
    store, _p, (t1, t2, _t3) = _repo_con_tres_tareas(tmp_path)
    store.crear_dependencia(t1.id, t2.id)  # T2 queda bloqueada por T1
    client = MagicMock(spec=GitHubClient)
    client.obtener_issue.return_value = {"labels": [], "id": 111}
    client.listar_bloqueos.return_value = []
    GitHubSyncManager(store, client).push_tarea(t2.id)
    client.anadir_bloqueo.assert_called_once_with("u", "r", 2, 111)
    # Si GitHub ya la tiene, no se vuelve a enviar.
    client.anadir_bloqueo.reset_mock()
    client.listar_bloqueos.return_value = [{"number": 1}]
    GitHubSyncManager(store, client).push_tarea(t2.id)
    client.anadir_bloqueo.assert_not_called()


def test_el_pull_ignora_los_items_redacted_del_project(tmp_path):
    store = Store(tmp_path / "t.db")
    p = store.crear_proyecto("P", github_repo_owner="u", github_project_v2_id="11")
    client = MagicMock(spec=GitHubClient)
    client.obtener_detalles_proyecto_v2.return_value = (
        {"id": "PVT_11", "title": "P", "fields": {}, "status_field_id": None},
        [],
        [
            GitHubItem(id="PVTI_redacted", title="", item_type="REDACTED"),
            GitHubItem(id="PVTI_1", title="Real", issue_number=1, item_type="ISSUE"),
        ],
    )
    GitHubSyncManager(store, client).pull_proyecto(p.id)
    assert [t.titulo for t in store.listar_tareas(p.id)] == ["Real"]


def test_push_columnas_no_envia_la_columna_temporal_no_status(tmp_path):
    from gnomilestone.github import GitHubStatusOption as Op
    from gnomilestone.store import Store
    from gnomilestone.sync import GitHubSyncManager

    store = Store(tmp_path / "db.sqlite")
    proyecto = store.crear_proyecto(
        "P", github_repo_owner="yo", github_repo_name="repo", github_project_v2_id="3"
    )
    store.obtener_o_crear_estado_temporal(proyecto.id)  # «No Status»: solo existe en local
    nombres = [e.nombre for e in store.listar_estados(proyecto.id)]
    assert "No Status" in nombres

    remotas = [Op(f"o{i}", n) for i, n in enumerate(n for n in nombres if n != "No Status")]
    cliente = _ClienteColumnas(remotas, remotas)
    GitHubSyncManager(store, cliente).push_columnas(proyecto.id, en_segundo_plano=False)

    assert "No Status" not in [n for n, _c in cliente.enviadas]
    assert [n for n, _c in cliente.enviadas] == [n for n in nombres if n != "No Status"]
