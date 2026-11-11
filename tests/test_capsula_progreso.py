from gnomilestone.ui.capsula_progreso import luminancia, texto_sobre

NEGRO, BLANCO = (0.0, 0.0, 0.0), (1.0, 1.0, 1.0)


def test_texto_blanco_sobre_fondos_oscuros():
    assert texto_sobre(0.0, 0.0, 0.0) == BLANCO
    assert texto_sobre(0.21, 0.52, 0.89) == BLANCO  # azul de acento de GNOME


def test_texto_negro_sobre_fondos_claros():
    assert texto_sobre(1.0, 1.0, 1.0) == NEGRO
    assert texto_sobre(0.96, 0.83, 0.11) == NEGRO  # amarillo


def test_luminancia_extremos():
    assert luminancia(0, 0, 0) == 0
    assert abs(luminancia(1, 1, 1) - 1) < 1e-9
