from gnomilestone.tipos import (
    ERROR,
    FUNCIONALIDAD,
    NINGUNO,
    TRABAJO,
    nombre_github,
    tipo_desde_github,
)


def test_correspondencia_con_los_tipos_de_github():
    assert [nombre_github(t) for t in (TRABAJO, ERROR, FUNCIONALIDAD, NINGUNO)] == ["Task", "Bug", "Feature", None]
    assert [tipo_desde_github(n) for n in ("Task", "bug", "FEATURE")] == [TRABAJO, ERROR, FUNCIONALIDAD]
    assert tipo_desde_github("Epic") is None and tipo_desde_github(None) is None


def test_reconoce_los_tipos_renombrados_en_espanol_y_elige_el_nombre_del_repositorio():
    from gnomilestone.tipos import nombre_remoto

    assert [tipo_desde_github(n) for n in ("Tarea", "Error", "Funcionalidad")] == [TRABAJO, ERROR, FUNCIONALIDAD]
    remotos = ["Tarea", "Error", "Funcionalidad"]
    assert [nombre_remoto(t, remotos) for t in (TRABAJO, ERROR, FUNCIONALIDAD)] == remotos
    assert nombre_remoto(ERROR, ["Task", "Feature"]) is None
    assert nombre_remoto(ERROR, ["Task", "Bug"]) == "Bug"
