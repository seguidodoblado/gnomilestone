from gnomilestone.plantillas import plantillas_para


def test_la_nota_en_blanco_va_siempre_primera_y_vacia():
    for seccion in ("arquitectura", "especificaciones", "decisiones_tecnicas", "blueprint"):
        primera = plantillas_para(seccion)[0]
        assert (primera.clave, primera.titulo, primera.contenido) == ("en_blanco", "", "")


def test_plantillas_propias_de_cada_seccion():
    assert [p.clave for p in plantillas_para("decisiones_tecnicas")] == ["en_blanco", "adr"]
    assert [p.clave for p in plantillas_para("especificaciones")] == ["en_blanco", "especificacion"]
    assert [p.clave for p in plantillas_para("arquitectura")] == ["en_blanco", "componente"]
    adr = plantillas_para("decisiones_tecnicas")[1]
    assert "## Decisión" in adr.contenido and "## Consecuencias" in adr.contenido
