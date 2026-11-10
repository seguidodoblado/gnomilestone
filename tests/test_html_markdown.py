from gnomilestone.html_markdown import html_a_markdown

REPO = ("yo", "demo")


def conv(texto, ruta="README.md"):
    return html_a_markdown(texto, REPO, ruta)


def test_cabecera_centrada_logo_y_badge_pasan_a_markdown_con_rutas_absolutas():
    salida = conv(
        '<p align="center">\n  <img src="assets/logo.svg" alt="Logo" width="128">\n</p>\n\n'
        '<h1 align="center">Demo</h1>\n\n'
        '<p align="center">\n'
        '  <a href="https://ci/x"><img alt="CI" src="https://img.shields.io/ci.svg"></a>\n'
        '  <a href="docs/guia.md"><img alt="Guía" src="b.svg"></a>\n</p>\n'
    )
    assert "![Logo](https://github.com/yo/demo/raw/HEAD/assets/logo.svg)" in salida
    assert "\n# Demo\n" in salida
    assert "[![CI](https://img.shields.io/ci.svg)](https://ci/x)" in salida
    assert "[![Guía](https://github.com/yo/demo/raw/HEAD/b.svg)](https://github.com/yo/demo/blob/HEAD/docs/guia.md)" in salida
    assert "<" not in salida.replace("<https", "")


def test_markdown_normal_no_cambia_salvo_las_rutas_relativas():
    origen = "# Título\n\nTexto con **negrita** y [web](https://a.b) y [otra](README.en.md).\n\n- uno\n- dos\n"
    assert conv(origen) == origen.replace("(README.en.md)", "(https://github.com/yo/demo/blob/HEAD/README.en.md)")


def test_el_codigo_no_se_convierte():
    origen = "Usa `<b>negrita</b>` así:\n\n```html\n<p align=\"center\">hola</p>\n```\n\n<p>fuera</p>\n"
    salida = conv(origen)
    assert "`<b>negrita</b>`" in salida
    assert '```html\n<p align="center">hola</p>\n```' in salida
    assert salida.rstrip().endswith("fuera")


def test_listas_tablas_y_desplegables():
    salida = conv(
        "<ul><li>uno</li><li>dos <b>fuerte</b></li></ul>\n"
        "<ol><li>a</li><li>b</li></ol>\n"
        "<table><tr><th>Col</th><th>Val</th></tr><tr><td>x</td><td>1</td></tr></table>\n"
        "<details><summary>Más</summary>Contenido</details>\n"
    )
    assert "- uno\n- dos **fuerte**" in salida
    assert "1. a\n2. b" in salida
    assert "| Col | Val |\n| --- | --- |\n| x | 1 |" in salida
    assert "**Más**\n\nContenido" in salida


def test_comentarios_entidades_y_saltos():
    salida = conv("<!-- oculto -->Hola&nbsp;mundo &copy; 2026<br>fin <script>mala()</script>")
    assert "oculto" not in salida and "mala" not in salida
    assert "©" in salida and "Hola\xa0mundo" in salida
    assert "  \nfin" in salida


def test_rutas_relativas_con_carpeta_y_raiz():
    salida = html_a_markdown('<img src="../img/a.png" alt="a"> [l](/LICENSE) [m](#ancla) [n](mailto:a@b.c)', REPO, "docs/guia/README.md")
    assert "https://github.com/yo/demo/raw/HEAD/docs/img/a.png" in salida
    assert "(https://github.com/yo/demo/blob/HEAD/LICENSE)" in salida
    assert "(#ancla)" in salida and "(mailto:a@b.c)" in salida


def test_sin_repositorio_no_toca_las_rutas():
    assert html_a_markdown('<img src="a.png" alt="a">') == "![a](a.png)\n"


def test_html_roto_no_falla():
    assert "texto" in conv("<div><p>texto</b></i><span>")
