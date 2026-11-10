import io
import time
import urllib.request

from gnomilestone import imagenes_remotas
from gnomilestone.markdown_imagenes import (
    Imagen,
    SegmentoImagenes,
    SegmentoTexto,
    segmentar,
)

BADGE = "[![CI](https://x/ci.svg)](https://x/ci)"


def test_un_parrafo_solo_de_imagenes_se_separa_del_texto():
    segmentos = segmentar(f"# Título\n\n{BADGE} ![Logo](https://x/l.svg)\n\nTexto final\n")
    assert segmentos == [
        SegmentoTexto("# Título"),
        SegmentoImagenes([Imagen("CI", "https://x/ci.svg", "https://x/ci"), Imagen("Logo", "https://x/l.svg")]),
        SegmentoTexto("Texto final\n"),
    ]


def test_una_imagen_mezclada_con_texto_sigue_siendo_texto():
    segmentos = segmentar("Mira ![icono](https://x/i.png) aquí\n")
    assert segmentos == [SegmentoTexto("Mira ![icono](https://x/i.png) aquí\n")]


def test_imagenes_en_lineas_distintas_del_mismo_parrafo_forman_una_fila():
    segmentos = segmentar(f"{BADGE}\n{BADGE}\n")
    assert len(segmentos) == 1 and len(segmentos[0].imagenes) == 2


def test_texto_sin_imagenes_se_conserva_unido():
    assert segmentar("uno\n\ndos\n\n- a\n- b") == [SegmentoTexto("uno\n\ndos\n\n- a\n- b")]


class _Respuesta(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False


def test_obtener_descarga_guarda_en_cache_y_la_reutiliza(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    llamadas = []

    def abrir(peticion, timeout=None):
        llamadas.append(peticion.full_url)
        return _Respuesta(b"<svg/>")

    monkeypatch.setattr(urllib.request, "urlopen", abrir)
    assert imagenes_remotas.obtener("https://x/a.svg") == b"<svg/>"
    assert imagenes_remotas.obtener("https://x/a.svg") == b"<svg/>"
    assert llamadas == ["https://x/a.svg"]  # la segunda sale de la caché


def test_obtener_usa_la_copia_caducada_si_falla_la_red(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    ruta = imagenes_remotas._ruta("https://x/a.svg")
    ruta.parent.mkdir(parents=True)
    ruta.write_bytes(b"vieja")
    antiguo = time.time() - 2 * imagenes_remotas.VIGENCIA_SEGUNDOS
    import os
    os.utime(ruta, (antiguo, antiguo))

    def falla(*_a, **_k):
        raise OSError("sin red")

    monkeypatch.setattr(urllib.request, "urlopen", falla)
    assert imagenes_remotas.obtener("https://x/a.svg") == b"vieja"


def test_solo_https_y_con_limite_de_tamano(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    assert imagenes_remotas.obtener("http://x/a.png") is None
    assert imagenes_remotas.obtener("file:///etc/passwd") is None
    monkeypatch.setattr(
        urllib.request, "urlopen",
        lambda *_a, **_k: _Respuesta(b"x" * (imagenes_remotas.TAMANO_MAXIMO + 5)),
    )
    assert imagenes_remotas.obtener("https://x/enorme.png") is None
