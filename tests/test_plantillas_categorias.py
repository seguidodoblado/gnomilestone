from gnomilestone.plantillas import plantillas_para


def claves(seccion):
    return [p.clave for p in plantillas_para(seccion)]


def test_arquitectura_y_especificaciones_ofrecen_varias_plantillas():
    assert len(claves("arquitectura")) > 4
    assert len(claves("especificaciones")) > 4
    assert {"capas", "pila", "pruebas", "integracion_continua"} <= set(claves("arquitectura"))
    assert {"modelo_datos", "interfaz", "funcionalidad"} <= set(claves("especificaciones"))


def test_decisiones_tecnicas_conserva_su_unica_plantilla_y_la_en_blanco_va_primera():
    assert claves("decisiones_tecnicas") == ["en_blanco", "adr"]
    for seccion in ("vision_general", "arquitectura", "especificaciones"):
        assert claves(seccion)[0] == "en_blanco"


def test_las_claves_no_se_repiten_y_todas_traen_contenido():
    for seccion in ("vision_general", "arquitectura", "especificaciones", "decisiones_tecnicas"):
        plantillas = plantillas_para(seccion)
        assert len({p.clave for p in plantillas}) == len(plantillas)
        assert all(p.contenido.startswith("## ") for p in plantillas[1:])
