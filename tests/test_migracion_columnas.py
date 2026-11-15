from gnomilestone.store import Store


def test_reasignar_estados_solo_a_tareas_sin_columna(tmp_path):
    store = Store(tmp_path / "t.db")
    p = store.crear_proyecto("P")
    haz = store.crear_estado(p.id, "Por hacer")
    hecho = store.crear_estado(p.id, "Hecho")
    t1 = store.crear_tarea(p.id, "a", estado_id=haz.id)
    t2 = store.crear_tarea(p.id, "b", estado_id=hecho.id)

    previo = store.estados_de_tareas(p.id)
    assert previo == {t1.id: haz.id, t2.id: hecho.id}
    store.limpiar_estado_de_tareas(p.id)
    store.eliminar_estados_de_proyecto(p.id)
    nuevo = store.crear_estado(p.id, "Todo", github_option_id="x")

    store.reasignar_estados({t1.id: nuevo.id})
    tareas = {t.id: t for t in store.listar_tareas(p.id)}
    assert tareas[t1.id].estado_id == nuevo.id
    assert tareas[t2.id].estado_id is None


class _ClienteFalso:
    def obtener_detalles_proyecto_v2(self, owner, num):
        from gnomilestone.github import GitHubStatusOption

        return {}, [GitHubStatusOption("o1", "Todo"), GitHubStatusOption("o2", "Done")], []


def test_columnas_sin_equivalente_ignora_las_que_coinciden_o_estan_vacias(tmp_path):
    from gnomilestone.sync import GitHubSyncManager

    store = Store(tmp_path / "t.db")
    p = store.crear_proyecto("P")
    p.github_repo_owner, p.github_project_v2_id = "yo", "7"
    store.actualizar_proyecto(p)
    todo = store.crear_estado(p.id, "todo")  # coincide por nombre
    curso = store.crear_estado(p.id, "En curso")  # sin equivalente, con tareas
    store.crear_estado(p.id, "Vacía")  # sin equivalente, sin tareas
    store.crear_tarea(p.id, "a", estado_id=todo.id)
    store.crear_tarea(p.id, "b", estado_id=curso.id)

    pendientes, opciones = GitHubSyncManager(store, _ClienteFalso()).columnas_sin_equivalente(p.id)

    assert [(e.nombre, n) for e, n in pendientes] == [("En curso", 1)]
    assert [o.name for o in opciones] == ["Todo", "Done"]
