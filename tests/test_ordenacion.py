from gnomilestone.ordenacion import mover_tarea


def test_mover_antes_y_despues():
    assert mover_tarea([1, 2, 3, 4], 4, 2, False) == [1, 4, 2, 3]
    assert mover_tarea([1, 2, 3, 4], 1, 3, True) == [2, 3, 1, 4]


def test_sin_referencia_o_sobre_si_misma_no_cambia():
    assert mover_tarea([1, 2, 3], 2, None, True) == [1, 2, 3]
    assert mover_tarea([1, 2, 3], 2, 2, False) == [1, 2, 3]
    assert mover_tarea([1, 2, 3], 2, 99, False) == [1, 2, 3]
    assert mover_tarea([1, 2, 3], 99, 1, False) == [1, 2, 3]
