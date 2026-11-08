from gnomilestone.markdown_pango import markdown_a_pango


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
