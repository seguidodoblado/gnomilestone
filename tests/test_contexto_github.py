import base64

import pytest

from gnomilestone import contexto_github
from gnomilestone.github import GitHubClient, GitHubNotFoundError
from gnomilestone.store import Store


class ClienteFalso:
    def __init__(self, ficheros):
        self.ficheros = ficheros
        self.consultados = []

    def obtener_fichero_repo(self, owner, repo, ruta):
        self.consultados.append(ruta)
        return self.ficheros.get(ruta)


@pytest.fixture
def proyecto(tmp_path):
    store = Store(tmp_path / "gnomilestone.db")
    proyecto = store.crear_proyecto("Demo")
    sub = store.listar_subsecciones_documentacion(proyecto.id, contexto_github.SECCION)[0]
    return store, proyecto, sub


def test_busca_en_orden_y_se_queda_con_el_primer_fichero_existente():
    cliente = ClienteFalso({"README.md": "# Hola", ".github/SECURITY.md": "# Seguridad"})
    docs = {d.titulo: d for d in contexto_github.traer_documentos(cliente, "o", "r")}
    assert docs["README"].ruta == "README.md" and docs["README"].markdown == "# Hola\n"
    assert docs["Seguridad"].ruta == ".github/SECURITY.md"
    assert docs["Licencia"].markdown is None
    assert "README.markdown" not in cliente.consultados  # no sigue buscando tras acertar


def test_el_texto_plano_va_en_bloque_de_codigo_y_el_markdown_tal_cual():
    assert contexto_github.como_markdown("LICENSE", "GPL\nlínea 2\n") == "```\nGPL\nlínea 2\n```\n"
    assert contexto_github.como_markdown("LICENSE", "con ``` dentro").startswith("````\n")
    assert contexto_github.como_markdown("CONTRIBUTING.md", "# Hola\n") == "# Hola\n"


def test_aplica_actualiza_crea_y_respeta_lo_que_no_hay(proyecto):
    store, p, sub = proyecto
    # El proyecto nace con las notas vacías o sin ellas, según la migración: se fija el caso.
    for nota in store.listar_notas_documentacion(p.id, subseccion_id=sub.id):
        store.eliminar_nota_documentacion(nota.id)
    existente = store.crear_nota_documentacion(p.id, contexto_github.SECCION, "README", "viejo", sub.id)
    store.crear_nota_documentacion(p.id, contexto_github.SECCION, "Licencia", "igual\n", sub.id)
    docs = [
        contexto_github.DocumentoRemoto("README", "README.md", "nuevo\n"),
        contexto_github.DocumentoRemoto("Licencia", "LICENSE.md", "igual\n"),
        contexto_github.DocumentoRemoto("Seguridad", "SECURITY.md", "# Seg\n"),
        contexto_github.DocumentoRemoto("Contribuyendo", None, None),
    ]
    res = contexto_github.aplicar_documentos(store, p.id, sub.id, docs)
    assert (res.actualizadas, res.creadas, res.sin_cambios, res.no_encontradas) == (
        ["README"], ["Seguridad"], ["Licencia"], ["Contribuyendo"],
    )
    assert store.obtener_nota_documentacion(existente.id).contenido == "nuevo\n"
    # La versión anterior queda guardada y recuperable.
    assert [v.contenido for v in store.listar_versiones_nota(existente.id)] == ["viejo"]
    # Repetir el pull no cambia nada.
    otra = contexto_github.aplicar_documentos(store, p.id, sub.id, docs)
    assert not otra.hubo_cambios


def test_obtener_fichero_repo_decodifica_y_trata_lo_que_no_es_fichero(monkeypatch):
    cliente = GitHubClient(token="t")
    contenido = base64.b64encode("Licencia ñ".encode()).decode()
    monkeypatch.setattr(
        cliente, "_request",
        lambda *_a, **_k: {"type": "file", "encoding": "base64", "content": contenido},
    )
    assert cliente.obtener_fichero_repo("o", "r", "LICENSE") == "Licencia ñ"
    monkeypatch.setattr(cliente, "_request", lambda *_a, **_k: [{"type": "dir"}])
    assert cliente.obtener_fichero_repo("o", "r", "docs") is None

    def no_existe(*_a, **_k):
        raise GitHubNotFoundError("404")

    monkeypatch.setattr(cliente, "_request", no_existe)
    assert cliente.obtener_fichero_repo("o", "r", "SECURITY.md") is None


def test_el_readme_con_html_se_trae_como_markdown_con_rutas_absolutas():
    cliente = ClienteFalso({"README.md": '<h1 align="center">Demo</h1>\n<img src="logo.svg" alt="Logo">\n'})
    readme = next(d for d in contexto_github.traer_documentos(cliente, "yo", "demo") if d.titulo == "README")
    assert readme.markdown == "# Demo\n\n![Logo](https://github.com/yo/demo/raw/HEAD/logo.svg)\n"
