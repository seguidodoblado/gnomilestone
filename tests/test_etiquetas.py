from gnomilestone.etiquetas import color_automatico, color_de_texto


def test_color_automatico_es_estable_y_no_distingue_mayusculas():
    assert color_automatico("Bug") == color_automatico(" bug ")
    assert len(color_automatico("x")) == 6


def test_color_de_texto_segun_luminosidad():
    assert color_de_texto("ffffff") == "000000"
    assert color_de_texto("#000000") == "ffffff"
    assert color_de_texto("d73a4a") == "ffffff"
    assert color_de_texto("zzz") == "000000"


def test_marcado_chip_escapa_el_nombre_y_usa_el_color():
    from gnomilestone.etiquetas import marcado_chip

    marcado = marcado_chip("a<b&c", "#d73a4a")
    assert "a&lt;b&amp;c" in marcado
    assert 'background="#d73a4a"' in marcado
