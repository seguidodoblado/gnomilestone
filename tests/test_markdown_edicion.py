import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk

from gnomilestone.ui.markdown_edicion import envolver, prefijar_lineas


def _buffer(texto: str, seleccion: tuple[int, int] | None = None, cursor: int | None = None):
    buf = Gtk.TextBuffer()
    buf.set_text(texto)
    if seleccion:
        buf.select_range(buf.get_iter_at_offset(seleccion[0]), buf.get_iter_at_offset(seleccion[1]))
    elif cursor is not None:
        buf.place_cursor(buf.get_iter_at_offset(cursor))
    return buf


def _texto(buf):
    return buf.get_text(*buf.get_bounds(), False)


def test_titulo_en_la_linea_del_cursor():
    buf = _buffer("uno\ndos", cursor=5)  # en «dos»
    prefijar_lineas(buf, "## ")
    assert _texto(buf) == "uno\n## dos"


def test_pulsar_dos_veces_quita_el_prefijo():
    buf = _buffer("uno", cursor=1)
    prefijar_lineas(buf, "- ")
    prefijar_lineas(buf, "- ")
    assert _texto(buf) == "uno"


def test_lista_sobre_varias_lineas_seleccionadas():
    buf = _buffer("a\nb\nc", seleccion=(0, 3))  # a y b
    prefijar_lineas(buf, "- ")
    assert _texto(buf) == "- a\n- b\nc"


def test_lista_numerada():
    buf = _buffer("a\nb", seleccion=(0, 3))
    prefijar_lineas(buf, "1. ")
    assert _texto(buf) == "1. a\n2. b"


def test_negrita_rodea_la_seleccion_y_sin_seleccion_inserta_ejemplo():
    buf = _buffer("hola mundo", seleccion=(0, 4))
    envolver(buf, "**", "**", "texto")
    assert _texto(buf) == "**hola** mundo"

    vacio = _buffer("")
    envolver(vacio, "*", "*", "texto")
    assert _texto(vacio) == "*texto*"
    inicio, fin = vacio.get_selection_bounds()
    assert vacio.get_text(inicio, fin, False) == "texto"


def _enter(texto: str):
    from gnomilestone.ui.markdown_edicion import continuar_lista

    buf = _buffer(texto, cursor=len(texto))
    return continuar_lista(buf), _texto(buf)


def test_enter_continua_lista_numerada():
    assert _enter("1. uno") == (True, "1. uno\n2. ")
    assert _enter("9. nueve") == (True, "9. nueve\n10. ")


def test_enter_continua_vinetas_casillas_y_citas():
    assert _enter("- a") == (True, "- a\n- ")
    assert _enter("  * a") == (True, "  * a\n  * ")
    assert _enter("- [x] hecho") == (True, "- [x] hecho\n- [ ] ")
    assert _enter("> cita") == (True, "> cita\n> ")


def test_enter_en_elemento_vacio_termina_la_lista():
    assert _enter("1. uno\n2. ") == (True, "1. uno\n")
    assert _enter("- ") == (True, "")


def test_enter_normal_fuera_de_lista_o_a_mitad_de_linea():
    assert _enter("texto") == (False, "texto")
    from gnomilestone.ui.markdown_edicion import continuar_lista

    buf = _buffer("1. uno", cursor=4)
    assert continuar_lista(buf) is False


def test_lista_numerada_alterna_en_una_linea():
    buf = _buffer("hola", cursor=2)
    prefijar_lineas(buf, "1. ")
    assert _texto(buf) == "1. hola"
    prefijar_lineas(buf, "1. ")
    assert _texto(buf) == "hola"


def test_lista_numerada_alterna_en_varias_lineas():
    buf = _buffer("uno\ndos\ntres", seleccion=(0, 12))
    prefijar_lineas(buf, "1. ")
    assert _texto(buf) == "1. uno\n2. dos\n3. tres"
    buf.select_range(*buf.get_bounds())
    prefijar_lineas(buf, "1. ")
    assert _texto(buf) == "uno\ndos\ntres"


def test_lista_numerada_renumera_si_solo_algunas_lineas_llevan_numero():
    buf = _buffer("1. uno\ndos", seleccion=(0, 10))
    prefijar_lineas(buf, "1. ")
    assert _texto(buf) == "1. uno\n2. dos"
