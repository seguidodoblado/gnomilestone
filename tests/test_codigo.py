from gnomilestone.codigo import Codigo, Tabla, Texto, colorear, dividir_bloques, nombre_lenguaje


def test_divide_texto_y_codigo_con_lenguaje_y_titulo():
    md = 'Intro\n\n```python "API de bajo nivel"\nx = 1\nprint(x)\n```\n\nFin'
    assert dividir_bloques(md) == [
        Texto("Intro"),
        Codigo("python", "API de bajo nivel", "x = 1\nprint(x)"),
        Texto("Fin"),
    ]


def test_formas_del_titulo_y_bloques_sin_lenguaje_o_sin_cerrar():
    assert dividir_bloques('```js title="Uno"\na\n```')[0] == Codigo("js", "Uno", "a")
    assert dividir_bloques("```bash Instalar paquetes\nls\n```")[0] == Codigo("bash", "Instalar paquetes", "ls")
    assert dividir_bloques("```\nsolo\n```")[0] == Codigo("", "", "solo")
    assert dividir_bloques("```py\nsin cerrar\nmás") == [Codigo("py", "", "sin cerrar\nmás")]


def test_una_valla_mas_larga_contiene_a_una_mas_corta():
    md = "````md\n```\ninterior\n```\n````"
    assert dividir_bloques(md) == [Codigo("md", "", "```\ninterior\n```")]


def test_sin_codigo_devuelve_un_solo_texto():
    assert dividir_bloques("# T\ntexto") == [Texto("# T\ntexto")]
    assert dividir_bloques("") == []


def test_colorear_python_distingue_palabras_cadenas_y_comentarios():
    lineas = colorear('# nota\ndef f():\n    return "x"', "python")
    assert len(lineas) == 3
    assert lineas[0][0] == ("comentario", "# nota")
    categorias = {c for linea in lineas for c, _t in linea}
    assert {"palabra_clave", "cadena", "definicion"} <= categorias
    assert "".join(t for _c, t in lineas[2]) == '    return "x"'


def test_colorear_lenguaje_desconocido_o_vacio_no_colorea_pero_conserva_las_lineas():
    assert colorear("a\nb", "") == [[("", "a")], [("", "b")]]
    assert colorear("a\n\nb", "no-existe") == [[("", "a")], [], [("", "b")]]


def test_colorear_no_deja_una_linea_vacia_de_mas_al_final():
    assert len(colorear("x = 1", "python")) == 1
    assert len(colorear("x = 1\n", "python")) == 2  # el bloque terminaba en salto: línea vacía real


def test_nombre_del_lenguaje():
    assert nombre_lenguaje("python") == "Python"
    assert nombre_lenguaje("nolose") == "Nolose"
    assert nombre_lenguaje("") == ""


def test_recortar_bloques_cuenta_lineas_de_texto_y_codigo():
    from gnomilestone.codigo import recortar_bloques

    bloques = [Texto("uno\n\ndos"), Codigo("py", "t", "a\nb\nc\nd")]
    assert recortar_bloques(bloques, 100) == bloques
    assert recortar_bloques(bloques, 3) == [Texto("uno\n\ndos"), Codigo("py", "t", "a\n…")]
    assert recortar_bloques(bloques, 1) == [Texto("uno\n…")]
    assert recortar_bloques(bloques, 0) == []


def test_recortar_codigo_largo_deja_puntos_suspensivos_en_la_ultima_linea():
    from gnomilestone.codigo import recortar_bloques

    codigo = Codigo("py", "", "\n".join(f"l{i}" for i in range(20)))
    cortado = recortar_bloques([codigo], 5)[0]
    assert cortado.codigo.split("\n") == ["l0", "l1", "l2", "l3", "l4", "…"]


def test_las_lineas_horizontales_son_bloques_aparte():
    from gnomilestone.codigo import Separador

    assert dividir_bloques("uno\n---\ndos\n\n***\n___\ntres") == [
        Texto("uno"), Separador(), Texto("dos"), Separador(), Separador(), Texto("tres"),
    ]
    assert dividir_bloques("---") == [Separador()]
    # Dentro de un bloque de código no se corta, y una tabla (`|---|`) no es una línea.
    assert dividir_bloques("```\n---\n```") == [Codigo("", "", "---")]
    assert dividir_bloques("|a|b|\n|---|---|") == [Tabla(("a", "b"), ("left", "left"), ())]


def test_tablas_markdown():
    md = "Antes\n\n| A | B | C |\n|:--|:-:|--:|\n| 1 | `x|y` | 3 \\| 4 |\n| solo |\n\nDespués"
    assert dividir_bloques(md) == [
        Texto("Antes"),
        Tabla(
            ("A", "B", "C"), ("left", "center", "right"),
            (("1", "`x|y`", "3 | 4"), ("solo", "", "")),
        ),
        Texto("Después"),
    ]
    # Sin barras en los bordes, y una tabla en un bloque de código sigue siendo código.
    assert dividir_bloques("a|b\n-|-\n1|2") == [Tabla(("a", "b"), ("left", "left"), (("1", "2"),))]
    assert dividir_bloques("```\n|a|b|\n|-|-|\n```") == [Codigo("", "", "|a|b|\n|-|-|")]
    # Sin fila separadora o con distinto número de columnas no es una tabla.
    assert dividir_bloques("|a|b|\n|1|2|") == [Texto("|a|b|\n|1|2|")]
    assert dividir_bloques("|a|b|\n|-|-|-|") == [Texto("|a|b|\n|-|-|-|")]


def test_recortar_tabla():
    from gnomilestone.codigo import recortar_bloques

    t = Tabla(("a",), ("left",), (("1",), ("2",), ("3",)))
    assert recortar_bloques([t], 3) == [Tabla(("a",), ("left",), (("1",), ("2",)))]


def test_recortar_cuenta_el_separador_como_una_linea():
    from gnomilestone.codigo import Separador, recortar_bloques

    assert recortar_bloques([Texto("a"), Separador(), Texto("b")], 2) == [Texto("a"), Separador()]


def test_el_lexer_se_cachea_y_mermaid_no_consulta_a_pygments():
    from gnomilestone import codigo

    codigo._lexer.cache_clear()
    assert codigo._lexer("mermaid") is None
    primero = codigo._lexer("python")
    assert primero is not None and codigo._lexer("python") is primero  # mismo objeto: caché
    assert codigo._lexer("lenguaje-inexistente") is None
    assert codigo._lexer.cache_info().hits >= 1


def test_alternar_tarea():
    from gnomilestone.codigo import alternar_tarea

    md = "- [ ] a\n```\n- [ ] código\n```\n1. [x] b\n- c"
    assert alternar_tarea(md, 0) == "- [x] a\n```\n- [ ] código\n```\n1. [x] b\n- c"
    assert alternar_tarea(md, 1) == "- [ ] a\n```\n- [ ] código\n```\n1. [ ] b\n- c"
    assert alternar_tarea(md, 2) == md


def test_pango_enlaza_las_casillas():
    from gnomilestone.markdown_pango import markdown_a_pango

    cuenta = [0]
    salida = markdown_a_pango("- [ ] a\n- [x] b", cuenta)
    assert 'tarea:0"><span size="large">☐' in salida and 'tarea:1"><span size="large">☑' in salida
    assert cuenta == [2]
    assert "href" not in markdown_a_pango("- [ ] a")
