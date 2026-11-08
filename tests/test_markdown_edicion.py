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
