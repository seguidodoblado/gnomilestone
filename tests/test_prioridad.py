from gnomilestone.prioridad import ALTA, BAJA, MEDIA, URGENTE, nivel_desde_opcion, opcion_para_nivel


def test_nivel_desde_opcion_reconoce_nombres_habituales():
    assert nivel_desde_opcion("High") == ALTA
    assert nivel_desde_opcion("🔴 Alta") == ALTA
    assert nivel_desde_opcion("P0") == ALTA
    assert nivel_desde_opcion("Medium") == MEDIA
    assert nivel_desde_opcion("P1") == MEDIA
    assert nivel_desde_opcion("Low") == BAJA
    assert nivel_desde_opcion("P2") == BAJA


def test_nivel_desde_opcion_desconocido_es_none():
    assert nivel_desde_opcion("Sprint 4") is None
    assert nivel_desde_opcion(None) is None


def test_opcion_para_nivel():
    opciones = {"P0": "a", "P1": "b", "P2": "c"}
    assert opcion_para_nivel(ALTA, opciones) == "a"
    assert opcion_para_nivel(BAJA, opciones) == "c"
    assert opcion_para_nivel(0, opciones) is None
    assert opcion_para_nivel(ALTA, {"Sprint": "x"}) is None


def test_urgente_es_un_nivel_propio():
    assert nivel_desde_opcion("Urgent") == URGENTE
    assert nivel_desde_opcion("High") == ALTA
    opciones = {"Urgent": "u", "High": "h", "Medium": "m", "Low": "l"}
    assert opcion_para_nivel(URGENTE, opciones) == "u"
    assert opcion_para_nivel(ALTA, opciones) == "h"


def test_urgente_sin_opcion_urgent_cae_en_high():
    assert opcion_para_nivel(URGENTE, {"High": "h", "Low": "l"}) == "h"
