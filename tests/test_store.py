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


def test_eliminar_tarea_vinculada_a_github_se_recuerda_con_sus_subtareas(store):
    proyecto = store.crear_proyecto("P")
    padre = store.crear_tarea(proyecto.id, "Padre")
    hija = store.crear_tarea(proyecto.id, "Hija", padre_id=padre.id)
    for tarea, numero in ((padre, 7), (hija, 8)):
        tarea.github_issue_number = numero
        store.actualizar_tarea(tarea)
    otra = store.crear_tarea(proyecto.id, "Otra")
    otra.github_issue_number = 9
    store.actualizar_tarea(otra)

    store.eliminar_tarea(padre.id)

    assert store.github_descartado(proyecto.id, 7, None)
    assert store.github_descartado(proyecto.id, 8, None)
    assert not store.github_descartado(proyecto.id, 9, None)


def test_eliminar_tarea_sin_vinculo_github_no_deja_rastro(store):
    proyecto = store.crear_proyecto("P")
    tarea = store.crear_tarea(proyecto.id, "Local")
    store.eliminar_tarea(tarea.id)
    assert not store.github_descartado(proyecto.id, None, None)


def test_etiquetas_se_reutilizan_sin_distinguir_mayusculas_y_se_asignan(store):
    proyecto = store.crear_proyecto("P")
    tarea = store.crear_tarea(proyecto.id, "T")
    bug = store.asegurar_etiqueta(proyecto.id, "Bug", "d73a4a")
    otra = store.asegurar_etiqueta(proyecto.id, "bug")
    assert otra.id == bug.id
    mejora = store.asegurar_etiqueta(proyecto.id, "mejora", "#a2eeef")
    assert mejora.color == "a2eeef"

    store.establecer_etiquetas_de_tarea(tarea.id, [bug.id, mejora.id])
    assert [e.nombre for e in store.listar_etiquetas_de_tarea(tarea.id)] == ["Bug", "mejora"]
    store.establecer_etiquetas_de_tarea(tarea.id, [mejora.id])
    assert [e.nombre for e in store.listar_etiquetas_de_tarea(tarea.id)] == ["mejora"]

    # El color de GitHub manda al volver a sincronizar.
    assert store.asegurar_etiqueta(proyecto.id, "Bug", "ff0000").color == "ff0000"


def test_prioridad_se_guarda_en_la_tarea(store):
    proyecto = store.crear_proyecto("P")
    tarea = store.crear_tarea(proyecto.id, "T", prioridad=3)
    assert store.obtener_tarea(tarea.id).prioridad == 3
    tarea.prioridad = 1
    store.actualizar_tarea(tarea)
    assert store.obtener_tarea(tarea.id).prioridad == 1


def test_estado_final_es_unico_y_porcentaje_previo_se_guarda(store):
    proyecto = store.crear_proyecto("P")
    pendiente, _en_curso, hecho = store.listar_estados(proyecto.id)
    assert not any(e.es_final for e in store.listar_estados(proyecto.id))

    store.establecer_estado_final(proyecto.id, pendiente.id)
    store.establecer_estado_final(proyecto.id, hecho.id)
    assert [e.nombre for e in store.listar_estados(proyecto.id) if e.es_final] == ["Hecho"]
    store.establecer_estado_final(proyecto.id, None)
    assert not any(e.es_final for e in store.listar_estados(proyecto.id))

    tarea = store.crear_tarea(proyecto.id, "T")
    tarea.porcentaje_previo = 40
    store.actualizar_tarea(tarea)
    assert store.obtener_tarea(tarea.id).porcentaje_previo == 40


def _arbol_para_archivo(store):
    proyecto = store.crear_proyecto("P")
    padre = store.crear_tarea(proyecto.id, "Padre")
    hija = store.crear_tarea(proyecto.id, "Hija", padre_id=padre.id)
    nieta = store.crear_tarea(proyecto.id, "Nieta", padre_id=hija.id)
    otra = store.crear_tarea(proyecto.id, "Otra")
    return proyecto, padre, hija, nieta, otra


def test_archivar_oculta_la_tarea_y_su_rama_pero_no_las_borra(store):
    proyecto, _padre, hija, nieta, _otra = _arbol_para_archivo(store)
    store.archivar_tarea(hija.id)
    assert [t.titulo for t in store.listar_tareas(proyecto.id)] == ["Padre", "Otra"]
    assert [t.titulo for t in store.listar_tareas_archivadas(proyecto.id)] == ["Hija", "Nieta"]
    assert len(store.listar_tareas(proyecto.id, incluir_archivadas=True)) == 4
    assert store.obtener_tarea(nieta.id).archivada is True


def test_desarchivar_recupera_la_rama_y_los_ancestros(store):
    proyecto, padre, hija, _nieta, _otra = _arbol_para_archivo(store)
    store.archivar_tarea(padre.id)  # padre, hija y nieta
    store.desarchivar_tarea(hija.id)  # la hija vuelve con su nieta y con su padre
    assert sorted(t.titulo for t in store.listar_tareas(proyecto.id)) == [
        "Hija", "Nieta", "Otra", "Padre",
    ]
    assert store.listar_tareas_archivadas(proyecto.id) == []


def test_archivar_completadas_solo_ramas_enteras_al_100(store):
    proyecto, _padre, hija, nieta, otra = _arbol_para_archivo(store)
    for t in (hija, nieta, otra):
        t.porcentaje_completado = 100
        store.actualizar_tarea(t)
    # El padre no está completo: se archiva la rama de la hija (y su nieta) y «Otra».
    assert store.archivar_completadas(proyecto.id) == 3
    assert [t.titulo for t in store.listar_tareas(proyecto.id)] == ["Padre"]

    # Una rama con una subtarea sin completar no se archiva.
    p2 = store.crear_proyecto("Q")
    a = store.crear_tarea(p2.id, "A", porcentaje_completado=100)
    store.crear_tarea(p2.id, "A1", padre_id=a.id, porcentaje_completado=40)
    assert store.archivar_completadas(p2.id) == 0


def test_las_tareas_archivadas_no_salen_en_listar_tareas_de_proyectos(store):
    proyecto, padre, *_resto = _arbol_para_archivo(store)
    store.archivar_tarea(padre.id)
    assert [t.titulo for t in store.listar_tareas_de_proyectos([proyecto.id])] == ["Otra"]


def test_notas_de_documentacion_crud_y_orden(store):
    proyecto = store.crear_proyecto("Docs")
    a = store.crear_nota_documentacion(proyecto.id, "arquitectura", "Capas", "# Capas")
    b = store.crear_nota_documentacion(proyecto.id, "arquitectura", "Datos")
    c = store.crear_nota_documentacion(proyecto.id, "blueprint", "Roadmap")
    assert (a.orden, b.orden, c.orden) == (0, 1, 0)
    assert [n.titulo for n in store.listar_notas_documentacion(proyecto.id, "arquitectura")] == [
        "Capas", "Datos",
    ]
    assert len(store.listar_notas_documentacion(proyecto.id)) == 3

    b.titulo = "Modelo de datos"
    b.contenido = "Tablas"
    store.actualizar_nota_documentacion(b)
    guardada = store.obtener_nota_documentacion(b.id)
    assert (guardada.titulo, guardada.contenido) == ("Modelo de datos", "Tablas")

    store.eliminar_nota_documentacion(a.id)
    assert store.obtener_nota_documentacion(a.id) is None


def test_nota_de_documentacion_rechaza_seccion_desconocida(store):
    proyecto = store.crear_proyecto("Docs")
    with pytest.raises(ValueError):
        store.crear_nota_documentacion(proyecto.id, "otra", "X")


def test_eliminar_proyecto_borra_sus_notas_de_documentacion(store):
    proyecto = store.crear_proyecto("Docs")
    store.crear_nota_documentacion(proyecto.id, "blueprint", "Roadmap")
    store.eliminar_proyecto(proyecto.id)
    assert store.listar_notas_documentacion(proyecto.id) == []
