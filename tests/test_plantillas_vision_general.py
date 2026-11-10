from gnomilestone.plantillas import plantillas_para


def test_vision_general_ofrece_los_cinco_documentos_de_contexto():
    nombres = [p.titulo for p in plantillas_para("vision_general")]
    assert nombres == ["", "README", "Código de conducta", "Contribuyendo", "Licencia", "Seguridad"]


def test_cada_plantilla_de_vision_general_trae_contenido():
    for plantilla in plantillas_para("vision_general")[1:]:
        assert plantilla.contenido.startswith("## "), plantilla.clave


def test_otras_secciones_no_reciben_las_de_vision_general():
    assert "readme" not in [p.clave for p in plantillas_para("arquitectura")]
