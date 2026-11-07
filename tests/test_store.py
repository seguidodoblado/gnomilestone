import pytest

from gnomilestone.store import CicloDependenciaError, ColumnaNoVaciaError, Store


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "gnomilestone.db")


def test_crear_proyecto_crea_tres_estados_por_defecto(store):
    proyecto = store.crear_proyecto("Migración web")
    estados = store.listar_estados(proyecto.id)
    assert [e.nombre for e in estados] == ["Pendiente", "En curso", "Hecho"]


def test_listar_proyectos_devuelve_los_creados(store):
    store.crear_proyecto("B")
    store.crear_proyecto("A")
    assert [p.nombre for p in store.listar_proyectos()] == ["A", "B"]


def test_actualizar_proyecto(store):
    proyecto = store.crear_proyecto("Original")
    proyecto.nombre = "Renombrado"
    proyecto.descripcion = "Descripción del proyecto"
    proyecto.fecha_inicio = "2026-11-07"
    proyecto.fecha_fin_estimada = "2026-12-01"
    proyecto.estado = "en_curso"
    proyecto.archivado = True
    proyecto.icon_name = "starred-symbolic"
    proyecto.icon_path = "/tmp/icono-proyecto.png"
    store.actualizar_proyecto(proyecto)
    actual = store.obtener_proyecto(proyecto.id)
    assert actual.nombre == "Renombrado"
    assert actual.descripcion == "Descripción del proyecto"
    assert actual.fecha_inicio == "2026-11-07"
    assert actual.fecha_fin_estimada == "2026-12-01"
    assert actual.estado == "en_curso"
    assert actual.archivado is True
    assert actual.icon_name == "starred-symbolic"
    assert actual.icon_path == "/tmp/icono-proyecto.png"


def test_eliminar_proyecto_borra_en_cascada_tareas_y_estados(store):
    proyecto = store.crear_proyecto("Temporal")
    estado = store.listar_estados(proyecto.id)[0]
    store.crear_tarea(proyecto.id, "Tarea", estado_id=estado.id)
    store.eliminar_proyecto(proyecto.id)
    assert store.obtener_proyecto(proyecto.id) is None
    assert store.listar_estados(proyecto.id) == []


def test_crear_tarea_y_subtarea(store):
    proyecto = store.crear_proyecto("Proyecto")
    raiz = store.crear_tarea(proyecto.id, "Raíz")
    hija = store.crear_tarea(proyecto.id, "Hija", padre_id=raiz.id)
    assert hija.padre_id == raiz.id
    assert [t.titulo for t in store.listar_tareas(proyecto.id)] == ["Raíz", "Hija"]


def test_actualizar_tarea(store):
    proyecto = store.crear_proyecto("Proyecto")
    tarea = store.crear_tarea(proyecto.id, "Tarea")
    tarea.porcentaje_completado = 50
    tarea.es_hito = True
    tarea.fecha_inicio = "2026-11-07"
    tarea.fecha_fin_planificada = "2026-11-09"
    tarea.fecha_limite = "2026-11-10"
    store.actualizar_tarea(tarea)
    actualizada = store.obtener_tarea(tarea.id)
    assert actualizada.porcentaje_completado == 50
    assert actualizada.es_hito is True
    assert actualizada.fecha_fin_planificada == "2026-11-09"
    assert actualizada.fecha_limite == "2026-11-10"


def test_eliminar_tarea(store):
    proyecto = store.crear_proyecto("Proyecto")
    tarea = store.crear_tarea(proyecto.id, "Tarea")
    store.eliminar_tarea(tarea.id)
    assert store.obtener_tarea(tarea.id) is None


def test_crear_dependencia_simple(store):
    proyecto = store.crear_proyecto("Proyecto")
    a = store.crear_tarea(proyecto.id, "A")
    b = store.crear_tarea(proyecto.id, "B")
    dependencia = store.crear_dependencia(a.id, b.id)
    assert dependencia.tarea_origen_id == a.id
    assert dependencia.tarea_destino_id == b.id


def test_crear_dependencia_detecta_ciclo_directo(store):
    proyecto = store.crear_proyecto("Proyecto")
    a = store.crear_tarea(proyecto.id, "A")
    b = store.crear_tarea(proyecto.id, "B")
    store.crear_dependencia(a.id, b.id)
    with pytest.raises(CicloDependenciaError):
        store.crear_dependencia(b.id, a.id)


def test_crear_dependencia_detecta_ciclo_indirecto(store):
    proyecto = store.crear_proyecto("Proyecto")
    a = store.crear_tarea(proyecto.id, "A")
    b = store.crear_tarea(proyecto.id, "B")
    c = store.crear_tarea(proyecto.id, "C")
    store.crear_dependencia(a.id, b.id)
    store.crear_dependencia(b.id, c.id)
    with pytest.raises(CicloDependenciaError):
        store.crear_dependencia(c.id, a.id)


def test_crear_dependencia_entre_proyectos_distintos_falla(store):
    proyecto1 = store.crear_proyecto("Proyecto 1")
    proyecto2 = store.crear_proyecto("Proyecto 2")
    a = store.crear_tarea(proyecto1.id, "A")
    b = store.crear_tarea(proyecto2.id, "B")
    with pytest.raises(ValueError):
        store.crear_dependencia(a.id, b.id)


def test_eliminar_estado_con_tareas_falla(store):
    proyecto = store.crear_proyecto("Proyecto")
    estado = store.listar_estados(proyecto.id)[0]
    store.crear_tarea(proyecto.id, "Tarea", estado_id=estado.id)
    with pytest.raises(ColumnaNoVaciaError):
        store.eliminar_estado(estado.id)


def test_mover_tareas_y_luego_eliminar_estado(store):
    proyecto = store.crear_proyecto("Proyecto")
    origen, destino, _ = store.listar_estados(proyecto.id)
    store.crear_tarea(proyecto.id, "Tarea", estado_id=origen.id)
    store.mover_tareas_a_estado(origen.id, destino.id)
    store.eliminar_estado(origen.id)
    assert origen.id not in [e.id for e in store.listar_estados(proyecto.id)]


def test_crear_recurso_y_asignarlo_a_una_tarea(store):
    proyecto = store.crear_proyecto("Proyecto")
    tarea = store.crear_tarea(proyecto.id, "Tarea")
    recurso = store.crear_recurso(proyecto.id, "Ana")
    store.asignar_recurso(tarea.id, recurso.id, porcentaje_dedicacion=50)
    asignaciones = store.listar_asignaciones(tarea.id)
    assert len(asignaciones) == 1
    assert asignaciones[0].recurso_id == recurso.id
    assert asignaciones[0].porcentaje_dedicacion == 50


def test_asegurar_recurso_no_duplica_por_mayusculas(store):
    proyecto = store.crear_proyecto("Proyecto")
    primero = store.asegurar_recurso(proyecto.id, "Ana")
    segundo = store.asegurar_recurso(proyecto.id, "ana")
    assert primero.id == segundo.id
    assert len(store.listar_recursos(proyecto.id)) == 1
    assert primero.color_hex  # color de paleta al crear


def test_asignar_recurso_es_idempotente(store):
    proyecto = store.crear_proyecto("Proyecto")
    tarea = store.crear_tarea(proyecto.id, "Tarea")
    recurso = store.asegurar_recurso(proyecto.id, "Luis")
    a1 = store.asignar_recurso(tarea.id, recurso.id)
    a2 = store.asignar_recurso(tarea.id, recurso.id)
    assert a1.id == a2.id
    assert len(store.listar_asignaciones(tarea.id)) == 1


def test_contar_y_listar_titulos_asignados(store):
    proyecto = store.crear_proyecto("Proyecto")
    r = store.asegurar_recurso(proyecto.id, "Ana")
    t1 = store.crear_tarea(proyecto.id, "Uno")
    t2 = store.crear_tarea(proyecto.id, "Dos")
    store.asignar_recurso(t1.id, r.id)
    store.asignar_recurso(t2.id, r.id)
    assert store.contar_asignaciones_recurso(r.id) == 2
    assert store.listar_titulos_asignados(r.id) == ["Uno", "Dos"]
    assert [x.nombre for x in store.listar_recursos_de_tarea(t1.id)] == ["Ana"]


def test_recurso_global_aparece_en_otro_proyecto(store):
    p1 = store.crear_proyecto("Proyecto 1")
    p2 = store.crear_proyecto("Proyecto 2")
    ana = store.crear_recurso(p1.id, "Ana", categoria="personas", es_global=True)
    luis = store.crear_recurso(p1.id, "Luis")  # no global: solo en p1

    nombres_p2 = {r.nombre for r in store.listar_recursos(p2.id)}
    assert "Ana" in nombres_p2
    assert "Luis" not in nombres_p2

    recursos_p1 = store.listar_recursos(p1.id)
    assert {r.id for r in recursos_p1} == {ana.id, luis.id}


def test_actualizar_recurso_guarda_categoria_y_global(store):
    proyecto = store.crear_proyecto("Proyecto")
    recurso = store.crear_recurso(proyecto.id, "Sala A", categoria="lugares")
    recurso.categoria = "equipos"
    recurso.es_global = True
    store.actualizar_recurso(recurso)

    actualizado = next(r for r in store.listar_recursos(proyecto.id) if r.id == recurso.id)
    assert actualizado.categoria == "equipos"
    assert actualizado.es_global is True


def test_listar_recursos_por_tarea(store):
    proyecto = store.crear_proyecto("Proyecto")
    ana = store.asegurar_recurso(proyecto.id, "Ana")
    luis = store.asegurar_recurso(proyecto.id, "Luis")
    t1 = store.crear_tarea(proyecto.id, "Uno")
    t2 = store.crear_tarea(proyecto.id, "Dos")
    store.asignar_recurso(t1.id, ana.id)
    store.asignar_recurso(t1.id, luis.id)
    store.asignar_recurso(t2.id, ana.id)
    por_tarea = store.listar_recursos_por_tarea(proyecto.id)
    assert {r.nombre for r in por_tarea[t1.id]} == {"Ana", "Luis"}
    assert [r.nombre for r in por_tarea[t2.id]] == ["Ana"]
    assert t1.id in por_tarea and t2.id in por_tarea


def test_listar_asignaciones_del_proyecto(store):
    proyecto = store.crear_proyecto("Proyecto")
    otro = store.crear_proyecto("Otro")
    ana = store.asegurar_recurso(proyecto.id, "Ana")
    t1 = store.crear_tarea(proyecto.id, "Uno")
    t2 = store.crear_tarea(proyecto.id, "Dos")
    t_otro = store.crear_tarea(otro.id, "Ajena")
    r_otro = store.asegurar_recurso(otro.id, "Luis")
    store.asignar_recurso(t1.id, ana.id, porcentaje_dedicacion=50)
    store.asignar_recurso(t2.id, ana.id)
    store.asignar_recurso(t_otro.id, r_otro.id)
    asignaciones = store.listar_asignaciones_del_proyecto(proyecto.id)
    assert len(asignaciones) == 2
    assert {a.tarea_id for a in asignaciones} == {t1.id, t2.id}
    assert next(a for a in asignaciones if a.tarea_id == t1.id).porcentaje_dedicacion == 50


def test_actualizar_avatar_url_y_color(store):
    proyecto = store.crear_proyecto("Proyecto")
    recurso = store.asegurar_recurso(proyecto.id, "Ana")
    recurso.color_hex = "#e01b24"
    recurso.avatar_url = "https://avatars.githubusercontent.com/u/1?v=4"
    store.actualizar_recurso(recurso)
    leido = store.obtener_recurso_por_nombre(proyecto.id, "Ana")
    assert leido is not None
    assert leido.color_hex == "#e01b24"
    assert leido.avatar_url.startswith("https://")


def test_migracion_v2_anade_avatar_url(tmp_path):
    from gnomilestone.store import Store

    db = tmp_path / "old.db"
    store = Store(db)
    assert store._connect().execute("PRAGMA user_version").fetchone()[0] >= 2
    cols = {fila[1] for fila in store._connect().execute("PRAGMA table_info(recurso)")}
    assert "avatar_url" in cols
