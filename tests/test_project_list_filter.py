from gnomilestone.ui.project_list_view import coincide_proyecto


def test_sin_texto_se_muestran_todos():
    assert coincide_proyecto("GnoMilestone", "")
    assert coincide_proyecto("GnoMilestone", "   ")


def test_filtra_en_cualquier_parte_y_sin_distinguir_mayusculas():
    assert coincide_proyecto("GnoMilestone", "mile")
    assert coincide_proyecto("GnoMilestone", "GNO")
    assert not coincide_proyecto("GnoMilestone", "bloguero")


def test_buscar_por_nombre_exacto_sin_distinguir_mayusculas():
    from gnomilestone.models import Proyecto
    from gnomilestone.ui.project_list_view import buscar_por_nombre

    proyectos = [Proyecto(id=1, nombre="GnoMilestone"), Proyecto(id=2, nombre="Bloguero")]
    assert buscar_por_nombre(proyectos, "  gnomilestone ").id == 1
    assert buscar_por_nombre(proyectos, "Gno") is None
    assert buscar_por_nombre(proyectos, "") is None
