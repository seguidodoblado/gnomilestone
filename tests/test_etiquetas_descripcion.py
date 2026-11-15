from gnomilestone.store import Store
from gnomilestone.sync import GitHubSyncManager


class _Cliente:
    def __init__(self, remotas=None):
        self.remotas = remotas or []
        self.llamadas = []

    def listar_etiquetas_repo(self, owner, repo):
        return self.remotas

    def actualizar_etiqueta(self, owner, repo, nombre, **kw):
        self.llamadas.append(("actualizar", nombre, kw))

    def crear_etiqueta(self, owner, repo, nombre, color, descripcion=""):
        self.llamadas.append(("crear", nombre, descripcion))


def _proyecto(tmp_path):
    store = Store(tmp_path / "t.db")
    p = store.crear_proyecto("P")
    p.github_repo_owner, p.github_repo_name = "yo", "repo"
    store.actualizar_proyecto(p)
    return store, p


def test_descripcion_se_guarda_y_una_vacia_no_borra_la_local(tmp_path):
    store, p = _proyecto(tmp_path)
    e = store.asegurar_etiqueta(p.id, "Bug", "d73a4a", "Algo no funciona")
    assert e.descripcion == "Algo no funciona"
    e = store.asegurar_etiqueta(p.id, "bug", "d73a4a", None)  # sin distinguir mayúsculas
    assert e.descripcion == "Algo no funciona"
    e = store.asegurar_etiqueta(p.id, "BUG", None, "Otra")
    assert e.descripcion == "Otra"
    assert len(store.listar_etiquetas(p.id)) == 1


def test_pull_trae_etiquetas_del_repo_con_color_y_descripcion(tmp_path):
    store, p = _proyecto(tmp_path)
    store.asegurar_etiqueta(p.id, "bug", "111111", "Mi descripción local")
    cliente = _Cliente(
        [
            {"name": "Bug", "color": "d73a4a", "description": ""},
            {"name": "docs", "color": "0075ca", "description": "Documentación"},
            {"name": " ", "color": "000000", "description": "x"},
        ]
    )
    from gnomilestone.sync import SyncResult

    GitHubSyncManager(store, cliente)._pull_etiquetas_repo(p.id, "yo", "repo", SyncResult())

    por_nombre = {e.nombre.casefold(): e for e in store.listar_etiquetas(p.id)}
    assert set(por_nombre) == {"bug", "docs"}
    assert por_nombre["bug"].color == "d73a4a"
    assert por_nombre["bug"].descripcion == "Mi descripción local"
    assert por_nombre["docs"].descripcion == "Documentación"


def test_cambiar_descripcion_guarda_y_envia_a_github(tmp_path):
    store, p = _proyecto(tmp_path)
    e = store.asegurar_etiqueta(p.id, "bug", "d73a4a")
    cliente = _Cliente()

    GitHubSyncManager(store, cliente).cambiar_descripcion_etiqueta(
        e.id, "  Algo falla ", en_segundo_plano=False
    )

    assert store.obtener_etiqueta(e.id).descripcion == "Algo falla"
    assert cliente.llamadas == [("actualizar", "bug", {"descripcion": "Algo falla"})]
