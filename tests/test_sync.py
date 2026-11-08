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
    rec = store.crear_recurso(p.id, "testuser")
    store.asignar_recurso(t.id, rec.id)

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
    res = sync.pull_proyecto(p.id)

    assert res.tareas_actualizadas == 0
    assert len(res.conflictos) == 1
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

    def crear_etiqueta(self, owner, repo, nombre, color):
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

    antes = [Op("old1", "Pendiente", "RED", "d"), Op("old2", "En curso", "BLUE")]
    despues = [Op("n1", "Pendiente"), Op("n2", "Haciendo"), Op("n3", "Hecho"), Op("n4", "Revisión")]
    cliente = _ClienteColumnas(antes, despues)
    # El item de la tarea sigue en el proyecto, pero GitHub no le conoce estado.
    from gnomilestone.github import GitHubItem

    cliente.respuestas[0] = (cliente.respuestas[0][0], antes, [GitHubItem(id="ITEM", title="T")])

    GitHubSyncManager(store, cliente).push_columnas(proyecto.id, en_segundo_plano=False)

    assert [n for n, _c in cliente.enviadas] == ["Pendiente", "Haciendo", "Hecho", "Revisión"]
    assert dict(cliente.enviadas)["Pendiente"] == "RED"  # conserva el color previo
    asociados = {e.nombre: e.github_option_id for e in store.listar_estados(proyecto.id)}
    assert asociados == {"Pendiente": "n1", "Haciendo": "n2", "Hecho": "n3", "Revisión": "n4"}
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

    antes = [Op("old1", "Pendiente"), Op("old2", "En curso")]
    items = [
        GitHubItem(id="A", title="a", status_option_id="old2"),  # solo existe en GitHub
        GitHubItem(id="B", title="b", status_option_id="old1"),
        GitHubItem(id="C", title="c", status_option_id=None),
    ]
    cliente = _ClienteColumnas(antes, [Op("n1", "Pendiente"), Op("n2", "Haciendo"), Op("n3", "Hecho")])
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

        def crear_etiqueta(self, owner, repo, nombre, color):
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
    res = sync.pull_proyecto(p.id)
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
