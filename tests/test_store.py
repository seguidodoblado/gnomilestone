import sqlite3

import pytest

from gnomilestone.store import CicloDependenciaError, ColumnaNoVaciaError, Store


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "gnomilestone.db")


def test_crear_proyecto_crea_tres_estados_por_defecto(store):
    proyecto = store.crear_proyecto("Migración web")
    estados = store.listar_estados(proyecto.id)
    assert [e.nombre for e in estados] == ["Todo", "In Progress", "Done"]
    # Mismo esquema que un Project V2 recién creado en GitHub: "Done" es la final desde
    # el alta, para no depender de que el usuario lo marque a mano (ver sync.py).
    assert [e.nombre for e in estados if e.es_final] == ["Done"]


def test_completar_tarea_la_mueve_al_primer_estado_final(store):
    proyecto = store.crear_proyecto("Cierre")
    estados = store.listar_estados(proyecto.id)
    store.establecer_estado_final(proyecto.id, estados[2].id)
    tarea = store.crear_tarea(proyecto.id, "Tarea", estado_id=estados[0].id)
    tarea.porcentaje_completado = 100
    store.actualizar_tarea(tarea)
    actualizada = store.obtener_tarea(tarea.id)
    assert actualizada is not None
    assert actualizada.estado_id == estados[2].id


def test_si_hay_varios_estados_finales_gana_el_primero(store):
    proyecto = store.crear_proyecto("Orden")
    estados = store.listar_estados(proyecto.id)
    store.establecer_estado_final(proyecto.id, estados[1].id)
    # Simula una base que contiene más de un cierre: se conserva la prioridad por orden.
    with store._connect() as db:
        db.execute("UPDATE estado_tablero SET es_final = 1 WHERE id = ?", (estados[2].id,))
    tarea = store.crear_tarea(proyecto.id, "Tarea", estado_id=estados[0].id)
    tarea.porcentaje_completado = 100
    store.actualizar_tarea(tarea)
    assert store.obtener_tarea(tarea.id).estado_id == estados[1].id


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
    hito = store.crear_hito(proyecto.id, "Hito")
    tarea.porcentaje_completado = 50
    tarea.hito_id = hito.id
    tarea.fecha_inicio = "2026-11-07"
    tarea.fecha_fin_planificada = "2026-11-09"
    tarea.fecha_limite = "2026-11-10"
    store.actualizar_tarea(tarea)
    actualizada = store.obtener_tarea(tarea.id)
    assert actualizada.porcentaje_completado == 50
    assert actualizada.hito_id == hito.id
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
    # "Done" ya nace como final (ver test_crear_proyecto_crea_tres_estados_por_defecto).
    assert [e.nombre for e in store.listar_estados(proyecto.id) if e.es_final] == ["Done"]

    store.establecer_estado_final(proyecto.id, pendiente.id)
    store.establecer_estado_final(proyecto.id, hecho.id)
    assert [e.nombre for e in store.listar_estados(proyecto.id) if e.es_final] == ["Done"]
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
    titulos = [n.titulo for n in store.listar_notas_documentacion(proyecto.id, "arquitectura")]
    assert {"Capas", "Datos", "Estructura del proyecto", "Pilas", "Empaquetado", "Pruebas"}.issubset(titulos)
    assert len(store.listar_notas_documentacion(proyecto.id)) == 12

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


def test_proyecto_nuevo_nace_con_subsecciones_por_defecto(store):
    proyecto = store.crear_proyecto("Docs")
    por_seccion = {}
    for sub in store.listar_subsecciones_documentacion(proyecto.id):
        por_seccion.setdefault(sub.seccion, []).append(sub.nombre)
    assert set(por_seccion) == {"vision_general", "arquitectura", "especificaciones", "decisiones_tecnicas"}
    assert "Modelo de datos" in por_seccion["especificaciones"]


def test_subsecciones_crud_y_notas_en_cascada(store):
    proyecto = store.crear_proyecto("Docs")
    sub = store.crear_subseccion_documentacion(proyecto.id, "arquitectura", "Despliegue")
    store.renombrar_subseccion_documentacion(sub.id, "Infraestructura")
    nombres = [s.nombre for s in store.listar_subsecciones_documentacion(proyecto.id, "arquitectura")]
    assert nombres[-1] == "Infraestructura"
    nota = store.crear_nota_documentacion(
        proyecto.id, "arquitectura", "Nube", subseccion_id=sub.id
    )
    assert [n.id for n in store.listar_notas_documentacion(proyecto.id, subseccion_id=sub.id)] == [
        nota.id
    ]
    store.eliminar_subseccion_documentacion(sub.id)
    assert store.obtener_nota_documentacion(nota.id) is None


def test_blueprint_no_admite_subsecciones_editables(store):
    proyecto = store.crear_proyecto("Docs")
    with pytest.raises(ValueError):
        store.crear_subseccion_documentacion(proyecto.id, "blueprint", "X")


def test_diagramas_nace_como_subseccion_de_diagramas(store):
    proyecto = store.crear_proyecto("Docs")
    tipos = {s.nombre: s.tipo for s in store.listar_subsecciones_documentacion(proyecto.id)}
    assert tipos["Diagramas"] == "diagramas"
    assert tipos["Diseño y estructura"] == "notas"
    assert tipos["Stack y empaquetado"] == "notas"
    assert tipos["Calidad y entrega"] == "notas"


def test_diagramas_crud_y_cascada(store):
    proyecto = store.crear_proyecto("Docs")
    sub = store.crear_subseccion_documentacion(proyecto.id, "arquitectura", "Despliegue", "diagramas")
    assert sub.tipo == "diagramas"
    d = store.crear_diagrama_documentacion(proyecto.id, sub.id, "Login", '{"nodos": []}')
    d2 = store.crear_diagrama_documentacion(proyecto.id, sub.id, "Alta")
    assert (d.orden, d2.orden) == (0, 1)
    d.titulo, d.datos = "Inicio de sesión", '{"nodos": [1]}'
    store.actualizar_diagrama_documentacion(d)
    assert store.obtener_diagrama_documentacion(d.id).titulo == "Inicio de sesión"
    assert [x.id for x in store.listar_diagramas_documentacion(proyecto.id, sub.id)] == [d.id, d2.id]
    store.eliminar_diagrama_documentacion(d2.id)
    assert store.obtener_diagrama_documentacion(d2.id) is None
    store.eliminar_subseccion_documentacion(sub.id)
    assert store.listar_diagramas_documentacion(proyecto.id) == []


def test_tipo_de_subseccion_desconocido_se_rechaza(store):
    proyecto = store.crear_proyecto("Docs")
    with pytest.raises(ValueError):
        store.crear_subseccion_documentacion(proyecto.id, "arquitectura", "X", "otra")


def test_estado_de_nota_se_guarda_y_valida(store):
    proyecto = store.crear_proyecto("Docs")
    nota = store.crear_nota_documentacion(proyecto.id, "arquitectura", "T", estado="borrador")
    assert store.obtener_nota_documentacion(nota.id).estado == "borrador"
    nota.estado = "vigente"
    store.actualizar_nota_documentacion(nota)
    assert store.obtener_nota_documentacion(nota.id).estado == "vigente"
    assert store.crear_nota_documentacion(proyecto.id, "arquitectura", "U").estado == ""
    with pytest.raises(ValueError):
        store.crear_nota_documentacion(proyecto.id, "arquitectura", "X", estado="otro")


def test_jerarquia_de_notas_y_validaciones(store):
    p = store.crear_proyecto("Docs")
    sub = store.crear_subseccion_documentacion(p.id, "arquitectura", "Capas")
    otra = store.crear_subseccion_documentacion(p.id, "arquitectura", "Otra")
    a = store.crear_nota_documentacion(p.id, "arquitectura", "A", subseccion_id=sub.id)
    b = store.crear_nota_documentacion(p.id, "arquitectura", "B", subseccion_id=sub.id, padre_id=a.id)
    c = store.crear_nota_documentacion(p.id, "arquitectura", "C", subseccion_id=sub.id, padre_id=b.id)
    assert store.obtener_nota_documentacion(c.id).padre_id == b.id
    # No puede ser su propio padre ni colgar de un descendiente (ciclo).
    a.padre_id = a.id
    with pytest.raises(ValueError):
        store.actualizar_nota_documentacion(a)
    a.padre_id = c.id
    with pytest.raises(ValueError):
        store.actualizar_nota_documentacion(a)
    # El padre debe ser de la misma subsección.
    fuera = store.crear_nota_documentacion(p.id, "arquitectura", "F", subseccion_id=otra.id)
    with pytest.raises(ValueError):
        store.crear_nota_documentacion(p.id, "arquitectura", "X", subseccion_id=sub.id, padre_id=fuera.id)
    # Mover una nota a otro padre válido funciona.
    c.padre_id = a.id
    store.actualizar_nota_documentacion(c)
    assert store.obtener_nota_documentacion(c.id).padre_id == a.id


def test_borrar_una_nota_sube_sus_subpaginas_a_su_abuela(store):
    p = store.crear_proyecto("Docs")
    sub = store.crear_subseccion_documentacion(p.id, "arquitectura", "Capas")
    a = store.crear_nota_documentacion(p.id, "arquitectura", "A", subseccion_id=sub.id)
    b = store.crear_nota_documentacion(p.id, "arquitectura", "B", subseccion_id=sub.id, padre_id=a.id)
    c = store.crear_nota_documentacion(p.id, "arquitectura", "C", subseccion_id=sub.id, padre_id=b.id)
    store.eliminar_nota_documentacion(b.id)
    assert store.obtener_nota_documentacion(c.id).padre_id == a.id
    store.eliminar_nota_documentacion(a.id)
    assert store.obtener_nota_documentacion(c.id).padre_id is None


def test_reordenar_tareas_renumera_el_orden(store):
    proyecto = store.crear_proyecto("Orden por arrastre")
    a = store.crear_tarea(proyecto.id, "A")
    b = store.crear_tarea(proyecto.id, "B")
    c = store.crear_tarea(proyecto.id, "C")
    store.reordenar_tareas([c.id, a.id, b.id])
    assert [t.titulo for t in store.listar_tareas(proyecto.id)] == ["C", "A", "B"]


def test_fila_de_tarea_expone_el_issue_de_github(store):
    from gnomilestone.ui.task_tree_view import TareaRow

    proyecto = store.crear_proyecto("Issues")
    tarea = store.crear_tarea(proyecto.id, "Con issue")
    assert TareaRow("x", [], tarea=tarea).issue == ""
    tarea.github_issue_number = 17
    tarea.github_url = "https://github.com/o/r/issues/17"
    fila = TareaRow("x", [], tarea=tarea)
    assert (fila.issue, fila.issue_url) == ("#17", "https://github.com/o/r/issues/17")


def test_una_copia_vieja_de_la_tarea_no_borra_su_issue_de_github(store):
    # Regresión: el diálogo guardaba una copia leída antes de terminar el primer envío (sin
    # número de issue) y borraba el vínculo; el siguiente envío creaba un issue duplicado.
    proyecto = store.crear_proyecto("Duplicados")
    tarea = store.crear_tarea(proyecto.id, "Vista de Lista")
    copia_vieja = store.obtener_tarea(tarea.id)
    store.vincular_issue_github(tarea.id, 39, "https://github.com/o/r/issues/39")

    copia_vieja.titulo = "Vista de Lista (editada)"
    store.actualizar_tarea(copia_vieja)

    actual = store.obtener_tarea(tarea.id)
    assert actual.titulo == "Vista de Lista (editada)"
    assert (actual.github_issue_number, actual.github_url) == (
        39,
        "https://github.com/o/r/issues/39",
    )


def test_vincular_issue_no_pisa_lo_editado_durante_el_envio(store):
    proyecto = store.crear_proyecto("Envio")
    tarea = store.crear_tarea(proyecto.id, "Original")
    editada = store.obtener_tarea(tarea.id)
    editada.titulo = "Editada mientras se enviaba"
    store.actualizar_tarea(editada)
    store.vincular_issue_github(tarea.id, 7, "https://github.com/o/r/issues/7")
    actual = store.obtener_tarea(tarea.id)
    assert (actual.titulo, actual.github_issue_number) == ("Editada mientras se enviaba", 7)


def test_hitos_crear_listar_actualizar_y_eliminar(store):
    proyecto = store.crear_proyecto("Proyecto")
    sin_fecha = store.crear_hito(proyecto.id, "Sin fecha")
    tardio = store.crear_hito(proyecto.id, "Tardío", "2026-12-01")
    temprano = store.crear_hito(proyecto.id, "Temprano", "2026-11-01", "Notas", True, 7)
    assert [h.titulo for h in store.listar_hitos(proyecto.id)] == ["Temprano", "Tardío", "Sin fecha"]
    assert temprano.conseguido is True and temprano.github_milestone_number == 7

    tardio.titulo, tardio.fecha = "Tardío 2", "2026-12-15"
    store.actualizar_hito(tardio)
    store.vincular_milestone_hito(tardio.id, 9)
    leido = store.obtener_hito(tardio.id)
    assert (leido.titulo, leido.fecha, leido.github_milestone_number) == ("Tardío 2", "2026-12-15", 9)

    tarea = store.crear_tarea(proyecto.id, "T", hito_id=sin_fecha.id)
    store.eliminar_hito(sin_fecha.id)
    assert store.obtener_hito(sin_fecha.id) is None
    assert store.obtener_tarea(tarea.id).hito_id is None  # la tarea se queda, sin Hito


def test_borrar_el_proyecto_borra_sus_hitos(store):
    proyecto = store.crear_proyecto("Proyecto")
    hito = store.crear_hito(proyecto.id, "H")
    store.eliminar_proyecto(proyecto.id)
    assert store.obtener_hito(hito.id) is None


def test_migracion_convierte_las_tareas_hito_en_hitos(tmp_path):
    import sqlite3

    from gnomilestone.store import Store

    ruta = tmp_path / "viejo.db"
    Store(ruta)  # esquema completo (versión actual)
    db = sqlite3.connect(ruta)
    db.execute("PRAGMA foreign_keys = ON")
    db.execute("INSERT INTO proyecto (id, nombre) VALUES (1, 'P')")

    def tarea(i, titulo, padre=None, hito=0, **extra):
        columnas = ["id", "proyecto_id", "titulo", "padre_id", "es_hito", *extra]
        db.execute(
            f"INSERT INTO tarea ({', '.join(columnas)}) VALUES ({', '.join('?' * len(columnas))})",
            [i, 1, titulo, padre, hito, *extra.values()],
        )

    tarea(1, "Previa A")
    tarea(2, "Previa B")
    tarea(3, "Hito", hito=1, fecha_inicio="2026-11-23", fecha_limite="2026-11-24",
          porcentaje_completado=100)
    tarea(4, "Hija del hito", padre=3)
    tarea(5, "Suelta")
    db.execute("INSERT INTO dependencia (tarea_origen_id, tarea_destino_id, tipo) VALUES (1, 3, 'fin_a_inicio')")
    db.execute("INSERT INTO dependencia (tarea_origen_id, tarea_destino_id, tipo) VALUES (2, 3, 'fin_a_inicio')")
    db.execute("PRAGMA user_version = 31")
    db.execute("DROP TABLE hito")
    db.commit()
    db.close()

    store = Store(ruta)
    hitos = store.listar_hitos(1)
    assert [(h.titulo, h.fecha, h.conseguido) for h in hitos] == [("Hito", "2026-11-24", True)]
    por_titulo = {t.titulo: t for t in store.listar_tareas(1)}
    assert set(por_titulo) == {"Previa A", "Previa B", "Hija del hito", "Suelta"}
    assert {por_titulo[n].hito_id for n in ("Previa A", "Previa B", "Hija del hito")} == {hitos[0].id}
    assert por_titulo["Suelta"].hito_id is None
    assert por_titulo["Hija del hito"].padre_id is None  # sube al padre del Hito (ninguno)
    assert (tmp_path / "viejo.db.copia-antes-de-hitos").exists()


def test_migracion_34_rellena_iconos_de_subsecciones(tmp_path):
    ruta = tmp_path / "iconos.db"
    Store(ruta)
    db = sqlite3.connect(ruta)
    db.execute("INSERT INTO proyecto (id, nombre) VALUES (1, 'P')")
    db.execute("DELETE FROM subseccion_documentacion")
    filas = [
        ("arquitectura", "A", 0, "notas", None),
        ("arquitectura", "Diag", 3, "diagramas", None),
        ("arquitectura", "Propia", 1, "notas", "folder-symbolic"),  # icono ya elegido
        ("arquitectura", "Creada", 7, "notas", None),  # no sembrada
    ]
    for seccion, nombre, orden, tipo, icono in filas:
        db.execute(
            "INSERT INTO subseccion_documentacion (proyecto_id, seccion, nombre, orden, tipo, icon_name) "
            "VALUES (1, ?, ?, ?, ?, ?)", (seccion, nombre, orden, tipo, icono),
        )
    db.execute("PRAGMA user_version = 33")  # base que ya pasó por la 33 sin relleno
    db.commit()
    db.close()

    Store(ruta)
    db = sqlite3.connect(ruta)
    iconos = dict(db.execute("SELECT nombre, icon_name FROM subseccion_documentacion"))
    assert iconos == {
        "A": "applications-graphics-symbolic",
        "Diag": "media-playlist-shuffle-symbolic",
        "Propia": "folder-symbolic",
        "Creada": None,
    }


def test_migracion_35_sustituye_iconos_antiguos_sin_pisar_los_elegidos(tmp_path):
    ruta = tmp_path / "antiguos.db"
    Store(ruta)
    db = sqlite3.connect(ruta)
    db.execute("INSERT INTO proyecto (id, nombre) VALUES (1, 'P')")
    db.execute("DELETE FROM subseccion_documentacion")
    filas = [
        ("especificaciones", "Modelo", 0, "accessories-database-symbolic"),  # no existe en el tema
        ("arquitectura", "Diseño", 0, "applications-engineering-symbolic"),  # repetía la sección
        ("arquitectura", "Stack", 1, "folder-symbolic"),  # elegido por el usuario
    ]
    for seccion, nombre, orden, icono in filas:
        db.execute(
            "INSERT INTO subseccion_documentacion (proyecto_id, seccion, nombre, orden, tipo, icon_name) "
            "VALUES (1, ?, ?, ?, 'notas', ?)", (seccion, nombre, orden, icono),
        )
    db.execute("PRAGMA user_version = 34")
    db.commit()
    db.close()

    Store(ruta)
    db = sqlite3.connect(ruta)
    iconos = dict(db.execute("SELECT nombre, icon_name FROM subseccion_documentacion"))
    assert iconos == {
        "Modelo": "drive-harddisk-symbolic",
        "Diseño": "applications-graphics-symbolic",
        "Stack": "folder-symbolic",
    }


def test_migracion_36_repara_iconos_repetidos_y_el_de_interfaz(tmp_path):
    ruta = tmp_path / "repetidos.db"
    Store(ruta)
    db = sqlite3.connect(ruta)
    db.execute("INSERT INTO proyecto (id, nombre) VALUES (1, 'P')")
    db.execute("DELETE FROM subseccion_documentacion")
    filas = [  # `orden` repetido en Arquitectura, como en una base real
        ("arquitectura", "Diseño y estructura", 0, "view-grid-symbolic"),
        ("arquitectura", "Stack y empaquetado", 0, "view-grid-symbolic"),
        ("arquitectura", "Quality and delivery", 0, "view-grid-symbolic"),
        ("arquitectura", "Mía", 0, "folder-symbolic"),
        ("especificaciones", "Interfaz", 2, "preferences-desktop-symbolic"),
    ]
    for seccion, nombre, orden, icono in filas:
        db.execute(
            "INSERT INTO subseccion_documentacion (proyecto_id, seccion, nombre, orden, tipo, icon_name) "
            "VALUES (1, ?, ?, ?, 'notas', ?)", (seccion, nombre, orden, icono),
        )
    db.execute("PRAGMA user_version = 35")
    db.commit()
    db.close()

    Store(ruta)
    db = sqlite3.connect(ruta)
    iconos = dict(db.execute("SELECT nombre, icon_name FROM subseccion_documentacion"))
    assert iconos == {
        "Diseño y estructura": "applications-graphics-symbolic",
        "Stack y empaquetado": "view-grid-symbolic",
        "Quality and delivery": "emblem-ok-symbolic",
        "Mía": "folder-symbolic",
        "Interfaz": "view-dual-symbolic",
    }


def test_subseccion_con_icono_elegido(tmp_path):
    store = Store(tmp_path / "icono.db")
    proyecto = store.crear_proyecto("P")
    sub = store.crear_subseccion_documentacion(proyecto.id, "arquitectura", "Propia", "notas", "folder-symbolic")
    assert sub.icon_name == "folder-symbolic"
    otra = store.crear_subseccion_documentacion(proyecto.id, "arquitectura", "Sin icono")
    assert otra.icon_name is None
    store.cambiar_icono_subseccion_documentacion(otra.id, "starred-symbolic")
    store.cambiar_icono_subseccion_documentacion(sub.id, None)
    iconos = {s.nombre: s.icon_name for s in store.listar_subsecciones_documentacion(proyecto.id, "arquitectura")}
    assert iconos["Sin icono"] == "starred-symbolic"
    assert iconos["Propia"] is None


def test_el_historial_registra_el_usuario_activo(store):
    proyecto = store.crear_proyecto("Autores")
    ana = store.crear_usuario("Ana")
    anonima = store.crear_tarea(proyecto.id, "Antes")
    store.usuario_actual_id = ana.id
    firmada = store.crear_tarea(proyecto.id, "Después")
    firmada.porcentaje_completado = 30
    store.actualizar_tarea(firmada)
    assert [e.usuario_id for e in store.listar_historial_tarea(anonima.id)] == [None]
    assert {e.usuario_id for e in store.listar_historial_tarea(firmada.id)} == {ana.id}
    store.eliminar_usuario(ana.id)
    assert store.usuario_actual_id is None
    assert {e.usuario_id for e in store.listar_historial_tarea(firmada.id)} == {None}


def test_usuarios_se_crean_renombran_y_no_se_repiten(store):
    ana = store.crear_usuario("  Ana ")
    assert ana.nombre == "Ana"
    store.renombrar_usuario(ana.id, "Ana B")
    assert [u.nombre for u in store.listar_usuarios()] == ["Ana B"]
    with pytest.raises(ValueError):
        store.crear_usuario("   ")
    with pytest.raises(sqlite3.IntegrityError):
        store.crear_usuario("ana b")


def test_historial_del_proyecto_junta_todas_las_tareas_en_orden(store):
    a, b = store.crear_proyecto("A"), store.crear_proyecto("B")
    t1, t2 = store.crear_tarea(a.id, "uno"), store.crear_tarea(a.id, "dos")
    store.crear_tarea(b.id, "ajena")
    historial = store.listar_historial_proyecto(a.id)
    assert [e.tarea_id for e in historial] == [t2.id, t1.id]


def test_la_migracion_39_convierte_los_recursos_firmantes_en_usuarios(tmp_path):
    ruta = tmp_path / "vieja.db"
    store = Store(ruta)
    proyecto = store.crear_proyecto("P")
    tarea = store.crear_tarea(proyecto.id, "T")
    recurso = store.crear_recurso(proyecto.id, "Ana")
    with sqlite3.connect(ruta) as db:
        db.execute("ALTER TABLE historial_tarea ADD COLUMN recurso_id INTEGER")
        db.execute("UPDATE historial_tarea SET recurso_id = ?", (recurso.id,))
        db.execute("PRAGMA user_version = 38")
    store = Store(ruta)
    usuarios = store.listar_usuarios()
    assert [u.nombre for u in usuarios] == ["Ana"]
    assert {e.usuario_id for e in store.listar_historial_tarea(tarea.id)} == {usuarios[0].id}


def test_atribuir_cambios_sin_autor_solo_toca_el_proyecto(store):
    a, b = store.crear_proyecto("A"), store.crear_proyecto("B")
    yo = store.crear_usuario("Yo")
    ta, tb = store.crear_tarea(a.id, "ta"), store.crear_tarea(b.id, "tb")
    assert store.atribuir_cambios_sin_autor(a.id, yo.id) == 1
    assert [e.usuario_id for e in store.listar_historial_tarea(ta.id)] == [yo.id]
    assert [e.usuario_id for e in store.listar_historial_tarea(tb.id)] == [None]


def test_el_historial_de_estado_conserva_los_nombres_de_columna(store):
    from gnomilestone.historial import detalle_evento

    proyecto = store.crear_proyecto("Columnas")
    temporal = store.crear_estado(proyecto.id, "Temporal")
    final = store.crear_estado(proyecto.id, "Final")
    tarea = store.crear_tarea(proyecto.id, "T", estado_id=temporal.id)
    tarea.estado_id = final.id
    store.actualizar_tarea(tarea)
    store.eliminar_estado(temporal.id)  # queda vacía y se borra
    evento = next(e for e in store.listar_historial_tarea(tarea.id) if e.tipo == "estado")
    estados = {e.id: e.nombre for e in store.listar_estados(proyecto.id)}
    assert detalle_evento(evento, estados) == "Temporal → Final"


def test_detalle_de_estado_sin_nombre_guardado_no_muestra_el_id():
    from gnomilestone.historial import detalle_evento
    from gnomilestone.models import HistorialTarea

    antiguo = HistorialTarea(1, 1, "2026-11-10 14:08", "estado", "estado_id", None, "39")
    assert detalle_evento(antiguo, {}) == "— → (columna eliminada)"


def test_recursos_de_persona(store) -> None:
    proyecto = store.crear_proyecto("P")
    ana = store.crear_recurso(proyecto.id, "Ana")
    luis = store.crear_recurso(proyecto.id, "Luis")
    portatil = store.crear_recurso(proyecto.id, "Portátil", categoria="equipos")
    oficina = store.crear_recurso(proyecto.id, "Oficina", categoria="lugares")
    store.fijar_recursos_de_persona(ana.id, [portatil.id, oficina.id, luis.id])
    assert [r.nombre for r in store.listar_recursos_de_persona(ana.id)] == ["Portátil", "Oficina"]
    # Un recurso pertenece como mucho a una persona: pasa a Luis y sale de Ana.
    store.fijar_recursos_de_persona(luis.id, [portatil.id])
    assert [r.nombre for r in store.listar_recursos_de_persona(ana.id)] == ["Oficina"]
    # Borrar la persona deja libres sus recursos.
    store.eliminar_recurso(luis.id)
    assert store.listar_recursos_de_persona(luis.id) == []
    assert next(r for r in store.listar_recursos(proyecto.id) if r.id == portatil.id).persona_id is None


def test_recurso_guarda_detalles_y_datos_de_persona(store) -> None:
    proyecto = store.crear_proyecto("P")
    ana = store.crear_recurso(proyecto.id, "Ana", cargo="Desarrolladora", telefono="600")
    equipo = store.crear_recurso(
        proyecto.id, "Portátil", categoria="equipos", detalles={"marca": "Lenovo", "modelo": "T14"}
    )
    equipo.detalles["estado"] = "En uso"
    store.actualizar_recurso(equipo)
    por_id = {r.id: r for r in store.listar_recursos(proyecto.id)}
    assert (por_id[ana.id].cargo, por_id[ana.id].telefono) == ("Desarrolladora", "600")
    assert por_id[equipo.id].detalles == {"marca": "Lenovo", "modelo": "T14", "estado": "En uso"}


def test_persona_guarda_usuario_de_github(store) -> None:
    proyecto = store.crear_proyecto("P")
    ana = store.crear_recurso(proyecto.id, "Ana García", github_login="anag")
    ana.github_login = "ana-g"
    store.actualizar_recurso(ana)
    assert store.listar_recursos(proyecto.id)[0].github_login == "ana-g"
