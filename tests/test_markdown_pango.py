import pytest

from gnomilestone import markdown_pango
from gnomilestone.markdown_pango import markdown_a_pango


@pytest.fixture(autouse=True)
def _sin_fuente_del_sistema(monkeypatch):
    """Los tests no dependen de la fuente monoespaciada del equipo donde se ejecutan."""
    monkeypatch.setattr(markdown_pango, "_familia_mono", lambda: None)


def test_inline_basico():
    assert markdown_a_pango("**a** y *b* y `c`") == "<b>a</b> y <i>b</i> y <tt>c</tt>"


def test_escapa_marcado_y_no_interpreta_dentro_de_codigo():
    assert markdown_a_pango("<b>x</b> & `**y**`") == "&lt;b&gt;x&lt;/b&gt; &amp; <tt>**y**</tt>"


def test_enlace():
    assert markdown_a_pango("[web](https://a.b/?x=1&y=2)") == '<a href="https://a.b/?x=1&amp;y=2">web</a>'


def test_titulo_y_listas():
    salida = markdown_a_pango("# T\n- uno\n1. dos\n- [x] hecho\n- [ ] pendiente")
    assert salida.splitlines() == [
        '<span size="x-large" weight="bold">T</span>',
        "• uno",
        "1. dos",
        "☑ hecho",
        "☐ pendiente",
    ]


def test_bloque_de_codigo():
    assert markdown_a_pango("```py\na < b\n```") == "<tt>a &lt; b</tt>"


def test_snake_case_no_es_cursiva():
    assert markdown_a_pango("mi_variable_larga") == "mi_variable_larga"


def test_codigo_con_la_fuente_monoespaciada_del_sistema(monkeypatch):
    monkeypatch.setattr(markdown_pango, "_familia_mono", lambda: "Ubuntu Mono")
    assert markdown_a_pango("`a<b`") == '<span font_family="Ubuntu Mono">a&lt;b</span>'
    assert markdown_a_pango("```\nx\n```") == '<span font_family="Ubuntu Mono">x</span>'
