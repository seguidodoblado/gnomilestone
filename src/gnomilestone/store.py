from __future__ import annotations

import os
import sqlite3
from contextlib import closing
from pathlib import Path

from gnomilestone.models import Asignacion, Dependencia, EstadoTablero, Proyecto, Recurso, Tarea

DATA_DIR = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "gnomilestone"
DB_PATH = DATA_DIR / "gnomilestone.db"

ESTADOS_POR_DEFECTO = ("Pendiente", "En curso", "Hecho")
PALETA_RECURSOS = (
    "#3584e4",
    "#33d17a",
    "#f6d32d",
    "#ff7800",
    "#e01b24",
    "#9141ac",
    "#26a269",
    "#c061cb",
)

_SCHEMA_V1 = """
CREATE TABLE proyecto (
    id INTEGER PRIMARY KEY,
    nombre TEXT NOT NULL,
    descripcion TEXT NOT NULL DEFAULT '',
    fecha_inicio TEXT,
    fecha_fin_estimada TEXT,
    github_repo_owner TEXT,
    github_repo_name TEXT,
    github_project_v2_id TEXT,
    creado TEXT NOT NULL DEFAULT (datetime('now')),
    actualizado TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE estado_tablero (
    id INTEGER PRIMARY KEY,
    proyecto_id INTEGER NOT NULL REFERENCES proyecto(id) ON DELETE CASCADE,
    nombre TEXT NOT NULL,
    orden INTEGER NOT NULL,
    color_hex TEXT
);

CREATE TABLE tarea (
    id INTEGER PRIMARY KEY,
    proyecto_id INTEGER NOT NULL REFERENCES proyecto(id) ON DELETE CASCADE,
    padre_id INTEGER REFERENCES tarea(id) ON DELETE CASCADE,
    estado_id INTEGER REFERENCES estado_tablero(id) ON DELETE RESTRICT,
    titulo TEXT NOT NULL,
    descripcion TEXT NOT NULL DEFAULT '',
    fecha_inicio TEXT,
    duracion_dias INTEGER NOT NULL DEFAULT 1,
    porcentaje_completado INTEGER NOT NULL DEFAULT 0,
    orden INTEGER NOT NULL DEFAULT 0,
    es_hito INTEGER NOT NULL DEFAULT 0,
    creado TEXT NOT NULL DEFAULT (datetime('now')),
    actualizado TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE dependencia (
    id INTEGER PRIMARY KEY,
    tarea_origen_id INTEGER NOT NULL REFERENCES tarea(id) ON DELETE CASCADE,
    tarea_destino_id INTEGER NOT NULL REFERENCES tarea(id) ON DELETE CASCADE,
    tipo TEXT NOT NULL DEFAULT 'fin_a_inicio',
    UNIQUE(tarea_origen_id, tarea_destino_id)
);

CREATE TABLE recurso (
    id INTEGER PRIMARY KEY,
    proyecto_id INTEGER NOT NULL REFERENCES proyecto(id) ON DELETE CASCADE,
    nombre TEXT NOT NULL,
    email TEXT,
    color_hex TEXT
);

CREATE TABLE asignacion (
    id INTEGER PRIMARY KEY,
    tarea_id INTEGER NOT NULL REFERENCES tarea(id) ON DELETE CASCADE,
    recurso_id INTEGER NOT NULL REFERENCES recurso(id) ON DELETE CASCADE,
    porcentaje_dedicacion INTEGER NOT NULL DEFAULT 100,
    UNIQUE(tarea_id, recurso_id)
);
"""


class CicloDependenciaError(Exception):
    """La dependencia crearía un ciclo entre tareas."""


class ColumnaNoVaciaError(Exception):
    """La columna del tablero todavía tiene tareas asignadas."""


def _proyecto_de_fila(fila: sqlite3.Row) -> Proyecto:
    datos = dict(fila)
    datos["archivado"] = bool(datos["archivado"])
    return Proyecto(**datos)


def _estado_de_fila(fila: sqlite3.Row) -> EstadoTablero:
    return EstadoTablero(**dict(fila))


def _tarea_de_fila(fila: sqlite3.Row) -> Tarea:
    datos = dict(fila)
    datos["es_hito"] = bool(datos["es_hito"])
    return Tarea(**datos)


def _dependencia_de_fila(fila: sqlite3.Row) -> Dependencia:
    return Dependencia(**dict(fila))


def _recurso_de_fila(fila: sqlite3.Row) -> Recurso:
    datos = dict(fila)
    datos["es_global"] = bool(datos["es_global"])
    return Recurso(**datos)


def _asignacion_de_fila(fila: sqlite3.Row) -> Asignacion:
    return Asignacion(**dict(fila))


class Store:
    def __init__(self, db_path: Path = DB_PATH) -> None:
        self.db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as db, db:
            self._migrar(db)

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.db_path)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        return db

    def _migrar(self, db: sqlite3.Connection) -> None:
        version = db.execute("PRAGMA user_version").fetchone()[0]
        if version < 1:
            db.executescript(_SCHEMA_V1)
            db.execute("PRAGMA user_version = 1")
            version = 1
        if version < 2:
            columnas = {fila[1] for fila in db.execute("PRAGMA table_info(recurso)")}
            if "avatar_url" not in columnas:
                db.execute("ALTER TABLE recurso ADD COLUMN avatar_url TEXT")
            db.execute("PRAGMA user_version = 2")
            version = 2
        # La versión 3, publicada durante una migración experimental, guardaba la
        # duración en horas. Volvemos al modelo estable de días al abrir la base.
        if version < 4:
            columnas = {fila[1] for fila in db.execute("PRAGMA table_info(tarea)")}
            if "duracion_horas" in columnas and "duracion_dias" not in columnas:
                db.execute("ALTER TABLE tarea RENAME COLUMN duracion_horas TO duracion_dias")
                db.execute(
                    "UPDATE tarea SET duracion_dias = MAX(1, (duracion_dias + 7) / 8)"
                )
            db.execute("PRAGMA user_version = 4")
            version = 4
        if version < 5:
            col_estados = {fila[1] for fila in db.execute("PRAGMA table_info(estado_tablero)")}
            if "github_option_id" not in col_estados:
                db.execute("ALTER TABLE estado_tablero ADD COLUMN github_option_id TEXT")

            col_tareas = {fila[1] for fila in db.execute("PRAGMA table_info(tarea)")}
            if "github_issue_number" not in col_tareas:
                db.execute("ALTER TABLE tarea ADD COLUMN github_issue_number INTEGER")
            if "github_issue_id" not in col_tareas:
                db.execute("ALTER TABLE tarea ADD COLUMN github_issue_id TEXT")
            if "github_item_id" not in col_tareas:
                db.execute("ALTER TABLE tarea ADD COLUMN github_item_id TEXT")
            if "github_url" not in col_tareas:
                db.execute("ALTER TABLE tarea ADD COLUMN github_url TEXT")

            db.execute("CREATE INDEX IF NOT EXISTS idx_tarea_gh_num ON tarea(proyecto_id, github_issue_number)")
            db.execute("CREATE INDEX IF NOT EXISTS idx_tarea_gh_item ON tarea(github_item_id)")
            db.execute("PRAGMA user_version = 5")
            version = 5
        if version < 6:
            columnas = {fila[1] for fila in db.execute("PRAGMA table_info(proyecto)")}
            if "estado" not in columnas:
                db.execute(
                    "ALTER TABLE proyecto ADD COLUMN estado TEXT NOT NULL DEFAULT 'pendiente'"
                )
            if "archivado" not in columnas:
                db.execute(
                    "ALTER TABLE proyecto ADD COLUMN archivado INTEGER NOT NULL DEFAULT 0"
                )
            db.execute("PRAGMA user_version = 6")
            version = 6
        if version < 7:
            columnas = {fila[1] for fila in db.execute("PRAGMA table_info(tarea)")}
            if "fecha_fin_planificada" not in columnas:
                db.execute("ALTER TABLE tarea ADD COLUMN fecha_fin_planificada TEXT")
            if "fecha_limite" not in columnas:
                db.execute("ALTER TABLE tarea ADD COLUMN fecha_limite TEXT")
            db.execute("PRAGMA user_version = 7")
            version = 7
        if version < 8:
            columnas = {fila[1] for fila in db.execute("PRAGMA table_info(proyecto)")}
            if "icon_name" not in columnas:
                db.execute(
                    "ALTER TABLE proyecto ADD COLUMN icon_name TEXT NOT NULL DEFAULT 'folder-symbolic'"
                )
            db.execute("PRAGMA user_version = 8")
            version = 8
        if version < 9:
            columnas = {fila[1] for fila in db.execute("PRAGMA table_info(proyecto)")}
            if "icon_path" not in columnas:
                db.execute("ALTER TABLE proyecto ADD COLUMN icon_path TEXT")
            db.execute("PRAGMA user_version = 9")
            version = 9
        if version < 10:
            columnas = {fila[1] for fila in db.execute("PRAGMA table_info(tarea)")}
            if "github_synced_at" not in columnas:
                # Cuándo quedó igual por última vez en local y en GitHub (en una
                # dirección u otra): si `actualizado` es posterior a esto, hay un
                # cambio local que un pull no debe pisar sin avisar (ver sync.py).
                db.execute("ALTER TABLE tarea ADD COLUMN github_synced_at TEXT")
            db.execute("PRAGMA user_version = 10")
            version = 10
        if version < 11:
            columnas = {fila[1] for fila in db.execute("PRAGMA table_info(recurso)")}
            if "categoria" not in columnas:
                db.execute(
                    "ALTER TABLE recurso ADD COLUMN categoria TEXT NOT NULL DEFAULT 'personas'"
                )
            if "es_global" not in columnas:
                # Un recurso global aparece y se puede asignar en todos los proyectos, no
                # solo en el suyo (ver `listar_recursos`): evita duplicar el alta de una
                # misma persona/medio/equipo/lugar en cada proyecto en el que participa.
                db.execute("ALTER TABLE recurso ADD COLUMN es_global INTEGER NOT NULL DEFAULT 0")
            db.execute("PRAGMA user_version = 11")

    # -- Proyectos ---------------------------------------------------------

    def crear_proyecto(
        self,
        nombre: str,
        descripcion: str = "",
        fecha_inicio: str | None = None,
        fecha_fin_estimada: str | None = None,
        github_repo_owner: str | None = None,
        github_repo_name: str | None = None,
        github_project_v2_id: str | None = None,
    ) -> Proyecto:
        with closing(self._connect()) as db, db:
            cursor = db.execute(
                "INSERT INTO proyecto "
                "(nombre, descripcion, fecha_inicio, fecha_fin_estimada, "
                " github_repo_owner, github_repo_name, github_project_v2_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (nombre, descripcion, fecha_inicio, fecha_fin_estimada,
                 github_repo_owner, github_repo_name, github_project_v2_id),
            )
            proyecto_id = cursor.lastrowid
            for indice, nombre_estado in enumerate(ESTADOS_POR_DEFECTO):
                db.execute(
                    "INSERT INTO estado_tablero (proyecto_id, nombre, orden) VALUES (?, ?, ?)",
                    (proyecto_id, nombre_estado, indice),
                )
            fila = db.execute("SELECT * FROM proyecto WHERE id = ?", (proyecto_id,)).fetchone()
            return _proyecto_de_fila(fila)

    def listar_proyectos(self) -> list[Proyecto]:
        with closing(self._connect()) as db:
            filas = db.execute("SELECT * FROM proyecto ORDER BY nombre").fetchall()
            return [_proyecto_de_fila(fila) for fila in filas]

    def obtener_proyecto(self, proyecto_id: int) -> Proyecto | None:
        with closing(self._connect()) as db:
            fila = db.execute("SELECT * FROM proyecto WHERE id = ?", (proyecto_id,)).fetchone()
            return _proyecto_de_fila(fila) if fila else None

    def actualizar_proyecto(self, proyecto: Proyecto) -> None:
        with closing(self._connect()) as db, db:
            db.execute(
                "UPDATE proyecto SET nombre = ?, descripcion = ?, fecha_inicio = ?, "
                "icon_name = ?, icon_path = ?, fecha_fin_estimada = ?, estado = ?, archivado = ?, "
                "github_repo_owner = ?, github_repo_name = ?, "
                "github_project_v2_id = ?, actualizado = datetime('now') WHERE id = ?",
                (proyecto.nombre, proyecto.descripcion, proyecto.fecha_inicio,
                 proyecto.icon_name, proyecto.icon_path, proyecto.fecha_fin_estimada, proyecto.estado,
                 int(proyecto.archivado),
                 proyecto.github_repo_owner,
                 proyecto.github_repo_name, proyecto.github_project_v2_id, proyecto.id),
            )

    def eliminar_proyecto(self, proyecto_id: int) -> None:
        with closing(self._connect()) as db, db:
            db.execute("DELETE FROM proyecto WHERE id = ?", (proyecto_id,))

    # -- Columnas del tablero (Kanban) -------------------------------------

    def listar_estados(self, proyecto_id: int) -> list[EstadoTablero]:
        with closing(self._connect()) as db:
            filas = db.execute(
                "SELECT * FROM estado_tablero WHERE proyecto_id = ? ORDER BY orden",
                (proyecto_id,),
            ).fetchall()
            return [_estado_de_fila(fila) for fila in filas]

    def crear_estado(
        self, proyecto_id: int, nombre: str, github_option_id: str | None = None
    ) -> EstadoTablero:
        with closing(self._connect()) as db, db:
            siguiente_orden = db.execute(
                "SELECT COALESCE(MAX(orden), -1) + 1 FROM estado_tablero WHERE proyecto_id = ?",
                (proyecto_id,),
            ).fetchone()[0]
            cursor = db.execute(
                "INSERT INTO estado_tablero (proyecto_id, nombre, orden, github_option_id) VALUES (?, ?, ?, ?)",
                (proyecto_id, nombre, siguiente_orden, github_option_id),
            )
            fila = db.execute(
                "SELECT * FROM estado_tablero WHERE id = ?", (cursor.lastrowid,)
            ).fetchone()
            return _estado_de_fila(fila)

    def renombrar_estado(self, estado_id: int, nombre: str) -> None:
        with closing(self._connect()) as db, db:
            db.execute("UPDATE estado_tablero SET nombre = ? WHERE id = ?", (nombre, estado_id))

    def asociar_github_option_estado(self, estado_id: int, github_option_id: str | None) -> None:
        with closing(self._connect()) as db, db:
            db.execute("UPDATE estado_tablero SET github_option_id = ? WHERE id = ?", (github_option_id, estado_id))

    def reordenar_estados(self, ids_en_orden: list[int]) -> None:
        with closing(self._connect()) as db, db:
            for orden, estado_id in enumerate(ids_en_orden):
                db.execute(
                    "UPDATE estado_tablero SET orden = ? WHERE id = ?", (orden, estado_id)
                )

    def contar_tareas_en_estado(self, estado_id: int) -> int:
        with closing(self._connect()) as db:
            return db.execute(
                "SELECT COUNT(*) FROM tarea WHERE estado_id = ?", (estado_id,)
            ).fetchone()[0]

    def mover_tareas_a_estado(self, estado_origen_id: int, estado_destino_id: int) -> None:
        with closing(self._connect()) as db, db:
            db.execute(
                "UPDATE tarea SET estado_id = ? WHERE estado_id = ?",
                (estado_destino_id, estado_origen_id),
            )

    def eliminar_estado(self, estado_id: int) -> None:
        if self.contar_tareas_en_estado(estado_id) > 0:
            raise ColumnaNoVaciaError(
                f"La columna {estado_id} todavía tiene tareas asignadas; "
                "muévelas a otra columna antes de eliminarla."
            )
        with closing(self._connect()) as db, db:
            db.execute("DELETE FROM estado_tablero WHERE id = ?", (estado_id,))

    # -- Tareas -------------------------------------------------------------

    def crear_tarea(
        self,
        proyecto_id: int,
        titulo: str,
        padre_id: int | None = None,
        estado_id: int | None = None,
        descripcion: str = "",
        fecha_inicio: str | None = None,
        fecha_fin_planificada: str | None = None,
        fecha_limite: str | None = None,
        duracion_dias: int = 1,
        porcentaje_completado: int = 0,
        es_hito: bool = False,
        github_issue_number: int | None = None,
        github_issue_id: str | None = None,
        github_item_id: str | None = None,
        github_url: str | None = None,
    ) -> Tarea:
        with closing(self._connect()) as db, db:
            siguiente_orden = db.execute(
                "SELECT COALESCE(MAX(orden), -1) + 1 FROM tarea WHERE proyecto_id = ?",
                (proyecto_id,),
            ).fetchone()[0]
            cursor = db.execute(
                "INSERT INTO tarea (proyecto_id, padre_id, estado_id, titulo, descripcion, "
                "fecha_inicio, fecha_fin_planificada, fecha_limite, duracion_dias, "
                "porcentaje_completado, orden, es_hito, "
                "github_issue_number, github_issue_id, github_item_id, github_url) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (proyecto_id, padre_id, estado_id, titulo, descripcion, fecha_inicio,
                 fecha_fin_planificada, fecha_limite, duracion_dias, porcentaje_completado,
                 siguiente_orden, int(es_hito),
                 github_issue_number, github_issue_id, github_item_id, github_url),
            )
            fila = db.execute("SELECT * FROM tarea WHERE id = ?", (cursor.lastrowid,)).fetchone()
            return _tarea_de_fila(fila)

    def listar_tareas(self, proyecto_id: int) -> list[Tarea]:
        with closing(self._connect()) as db:
            filas = db.execute(
                "SELECT * FROM tarea WHERE proyecto_id = ? ORDER BY orden", (proyecto_id,)
            ).fetchall()
            return [_tarea_de_fila(fila) for fila in filas]

    def listar_tareas_de_proyectos(self, proyecto_ids: list[int]) -> list[Tarea]:
        if not proyecto_ids:
            return []
        marcadores = ",".join("?" * len(proyecto_ids))
        with closing(self._connect()) as db:
            filas = db.execute(
                f"SELECT * FROM tarea WHERE proyecto_id IN ({marcadores}) ORDER BY proyecto_id, orden",
                proyecto_ids,
            ).fetchall()
            return [_tarea_de_fila(fila) for fila in filas]

    def obtener_tarea(self, tarea_id: int) -> Tarea | None:
        with closing(self._connect()) as db:
            fila = db.execute("SELECT * FROM tarea WHERE id = ?", (tarea_id,)).fetchone()
            return _tarea_de_fila(fila) if fila else None

    def obtener_tarea_por_github_issue(self, proyecto_id: int, issue_number: int) -> Tarea | None:
        with closing(self._connect()) as db:
            fila = db.execute(
                "SELECT * FROM tarea WHERE proyecto_id = ? AND github_issue_number = ?",
                (proyecto_id, issue_number),
            ).fetchone()
            return _tarea_de_fila(fila) if fila else None

    def obtener_tarea_por_github_item(self, item_id: str) -> Tarea | None:
        with closing(self._connect()) as db:
            fila = db.execute(
                "SELECT * FROM tarea WHERE github_item_id = ?",
                (item_id,),
            ).fetchone()
            return _tarea_de_fila(fila) if fila else None

    def actualizar_tarea(self, tarea: Tarea) -> None:
        with closing(self._connect()) as db, db:
            db.execute(
                "UPDATE tarea SET padre_id = ?, estado_id = ?, titulo = ?, descripcion = ?, "
                "fecha_inicio = ?, fecha_fin_planificada = ?, fecha_limite = ?, "
                "duracion_dias = ?, porcentaje_completado = ?, orden = ?, "
                "es_hito = ?, github_issue_number = ?, github_issue_id = ?, github_item_id = ?, "
                "github_url = ?, actualizado = datetime('now') WHERE id = ?",
                (tarea.padre_id, tarea.estado_id, tarea.titulo, tarea.descripcion,
                 tarea.fecha_inicio, tarea.fecha_fin_planificada, tarea.fecha_limite,
                 tarea.duracion_dias, tarea.porcentaje_completado,
                 tarea.orden, int(tarea.es_hito), tarea.github_issue_number,
                 tarea.github_issue_id, tarea.github_item_id, tarea.github_url, tarea.id),
            )

    def eliminar_tarea(self, tarea_id: int) -> None:
        with closing(self._connect()) as db, db:
            db.execute("DELETE FROM tarea WHERE id = ?", (tarea_id,))

    def marcar_sincronizada_github(self, tarea_id: int) -> None:
        """Registra que `tarea_id` quedó igual en local y en GitHub ahora mismo, sin
        tocar `actualizado` (eso marcaría la tarea como "editada" por el propio sync).
        Lo usa `sync.py` tras cada pull/push correcto de una tarea, para que el próximo
        pull sepa si hubo una edición local de por medio desde entonces (conflicto)."""
        with closing(self._connect()) as db, db:
            db.execute(
                "UPDATE tarea SET github_synced_at = datetime('now') WHERE id = ?", (tarea_id,)
            )

    # -- Dependencias ---------------------------------------------------------

    def listar_dependencias(self, proyecto_id: int) -> list[Dependencia]:
        with closing(self._connect()) as db:
            filas = db.execute(
                "SELECT d.* FROM dependencia d "
                "JOIN tarea t ON t.id = d.tarea_origen_id WHERE t.proyecto_id = ?",
                (proyecto_id,),
            ).fetchall()
            return [_dependencia_de_fila(fila) for fila in filas]

    def crear_dependencia(
        self, tarea_origen_id: int, tarea_destino_id: int, tipo: str = "fin_a_inicio"
    ) -> Dependencia:
        origen = self.obtener_tarea(tarea_origen_id)
        destino = self.obtener_tarea(tarea_destino_id)
        if origen is None or destino is None:
            raise ValueError("La tarea de origen o de destino no existe")
        if origen.proyecto_id != destino.proyecto_id:
            raise ValueError("Las dos tareas deben pertenecer al mismo proyecto")
        if self._crearia_ciclo(origen.proyecto_id, tarea_origen_id, tarea_destino_id):
            raise CicloDependenciaError(
                f"La dependencia {tarea_origen_id} -> {tarea_destino_id} crearía un ciclo"
            )
        with closing(self._connect()) as db, db:
            cursor = db.execute(
                "INSERT INTO dependencia (tarea_origen_id, tarea_destino_id, tipo) "
                "VALUES (?, ?, ?)",
                (tarea_origen_id, tarea_destino_id, tipo),
            )
            fila = db.execute(
                "SELECT * FROM dependencia WHERE id = ?", (cursor.lastrowid,)
            ).fetchone()
            return _dependencia_de_fila(fila)

    def _crearia_ciclo(self, proyecto_id: int, origen_id: int, destino_id: int) -> bool:
        """La nueva arista origen->destino cierra un ciclo si destino ya puede llegar a origen."""
        if origen_id == destino_id:
            return True
        grafo: dict[int, list[int]] = {}
        for dependencia in self.listar_dependencias(proyecto_id):
            grafo.setdefault(dependencia.tarea_origen_id, []).append(dependencia.tarea_destino_id)
        visitados: set[int] = set()
        pila = [destino_id]
        while pila:
            actual = pila.pop()
            if actual == origen_id:
                return True
            if actual in visitados:
                continue
            visitados.add(actual)
            pila.extend(grafo.get(actual, []))
        return False

    def eliminar_dependencia(self, dependencia_id: int) -> None:
        with closing(self._connect()) as db, db:
            db.execute("DELETE FROM dependencia WHERE id = ?", (dependencia_id,))

    # -- Recursos y asignaciones ----------------------------------------------

    def crear_recurso(
        self,
        proyecto_id: int,
        nombre: str,
        email: str | None = None,
        color_hex: str | None = None,
        avatar_url: str | None = None,
        categoria: str = "personas",
        es_global: bool = False,
    ) -> Recurso:
        with closing(self._connect()) as db, db:
            cursor = db.execute(
                "INSERT INTO recurso (proyecto_id, nombre, email, color_hex, avatar_url, "
                "categoria, es_global) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (proyecto_id, nombre, email, color_hex, avatar_url, categoria, int(es_global)),
            )
            fila = db.execute("SELECT * FROM recurso WHERE id = ?", (cursor.lastrowid,)).fetchone()
            return _recurso_de_fila(fila)

    def listar_recursos(self, proyecto_id: int) -> list[Recurso]:
        """Recursos propios de `proyecto_id`, más los globales de cualquier proyecto
        (ver `Recurso.es_global`): estos últimos se asignan igual en todos los proyectos
        sin tener que darlos de alta otra vez en cada uno."""
        with closing(self._connect()) as db:
            filas = db.execute(
                "SELECT * FROM recurso WHERE proyecto_id = ? OR es_global = 1 "
                "ORDER BY categoria, nombre",
                (proyecto_id,),
            ).fetchall()
            return [_recurso_de_fila(fila) for fila in filas]

    def obtener_recurso_por_nombre(self, proyecto_id: int, nombre: str) -> Recurso | None:
        buscado = nombre.strip().casefold()
        if not buscado:
            return None
        for recurso in self.listar_recursos(proyecto_id):
            if recurso.nombre.casefold() == buscado:
                return recurso
        return None

    def asegurar_recurso(self, proyecto_id: int, nombre: str) -> Recurso:
        """Devuelve el recurso existente (mismo nombre, sin distinguir mayúsculas) o lo crea
        con un color de la paleta. Es la vía normal de alta al asignar desde una tarea."""
        existente = self.obtener_recurso_por_nombre(proyecto_id, nombre)
        if existente is not None:
            return existente
        color = PALETA_RECURSOS[len(self.listar_recursos(proyecto_id)) % len(PALETA_RECURSOS)]
        return self.crear_recurso(proyecto_id, nombre.strip(), color_hex=color)

    def actualizar_recurso(self, recurso: Recurso) -> None:
        with closing(self._connect()) as db, db:
            db.execute(
                "UPDATE recurso SET nombre = ?, email = ?, color_hex = ?, avatar_url = ?, "
                "categoria = ?, es_global = ? WHERE id = ?",
                (
                    recurso.nombre,
                    recurso.email,
                    recurso.color_hex,
                    recurso.avatar_url,
                    recurso.categoria,
                    int(recurso.es_global),
                    recurso.id,
                ),
            )

    def eliminar_recurso(self, recurso_id: int) -> None:
        with closing(self._connect()) as db, db:
            db.execute("DELETE FROM recurso WHERE id = ?", (recurso_id,))

    def contar_asignaciones_recurso(self, recurso_id: int) -> int:
        with closing(self._connect()) as db:
            fila = db.execute(
                "SELECT COUNT(*) AS n FROM asignacion WHERE recurso_id = ?", (recurso_id,)
            ).fetchone()
            return int(fila["n"])

    def listar_titulos_asignados(self, recurso_id: int) -> list[str]:
        with closing(self._connect()) as db:
            filas = db.execute(
                "SELECT t.titulo FROM asignacion a "
                "JOIN tarea t ON t.id = a.tarea_id "
                "WHERE a.recurso_id = ? ORDER BY t.orden, t.id",
                (recurso_id,),
            ).fetchall()
            return [fila["titulo"] for fila in filas]

    def asignar_recurso(
        self, tarea_id: int, recurso_id: int, porcentaje_dedicacion: int = 100
    ) -> Asignacion:
        with closing(self._connect()) as db, db:
            existente = db.execute(
                "SELECT * FROM asignacion WHERE tarea_id = ? AND recurso_id = ?",
                (tarea_id, recurso_id),
            ).fetchone()
            if existente is not None:
                return _asignacion_de_fila(existente)
            cursor = db.execute(
                "INSERT INTO asignacion (tarea_id, recurso_id, porcentaje_dedicacion) "
                "VALUES (?, ?, ?)",
                (tarea_id, recurso_id, porcentaje_dedicacion),
            )
            fila = db.execute(
                "SELECT * FROM asignacion WHERE id = ?", (cursor.lastrowid,)
            ).fetchone()
            return _asignacion_de_fila(fila)

    def listar_asignaciones(self, tarea_id: int) -> list[Asignacion]:
        with closing(self._connect()) as db:
            filas = db.execute(
                "SELECT * FROM asignacion WHERE tarea_id = ?", (tarea_id,)
            ).fetchall()
            return [_asignacion_de_fila(fila) for fila in filas]

    def actualizar_dedicacion(self, tarea_id: int, recurso_id: int, porcentaje: int) -> None:
        porcentaje = max(0, min(100, int(porcentaje)))
        with closing(self._connect()) as db, db:
            db.execute(
                "UPDATE asignacion SET porcentaje_dedicacion = ? "
                "WHERE tarea_id = ? AND recurso_id = ?",
                (porcentaje, tarea_id, recurso_id),
            )

    def listar_asignaciones_del_proyecto(self, proyecto_id: int) -> list[Asignacion]:
        """Todas las asignaciones de las tareas del proyecto (para la vista Uso)."""
        with closing(self._connect()) as db:
            filas = db.execute(
                "SELECT a.* FROM asignacion a "
                "JOIN tarea t ON t.id = a.tarea_id "
                "WHERE t.proyecto_id = ? ORDER BY a.id",
                (proyecto_id,),
            ).fetchall()
            return [_asignacion_de_fila(fila) for fila in filas]

    def listar_recursos_de_tarea(self, tarea_id: int) -> list[Recurso]:
        with closing(self._connect()) as db:
            filas = db.execute(
                "SELECT r.* FROM asignacion a "
                "JOIN recurso r ON r.id = a.recurso_id "
                "WHERE a.tarea_id = ? ORDER BY r.nombre",
                (tarea_id,),
            ).fetchall()
            return [_recurso_de_fila(fila) for fila in filas]

    def listar_recursos_por_tarea(self, proyecto_id: int) -> dict[int, list[Recurso]]:
        """Mapa tarea_id → recursos asignados, en una sola consulta por proyecto."""
        with closing(self._connect()) as db:
            filas = db.execute(
                "SELECT a.tarea_id AS tarea_asignada_id, r.id, r.proyecto_id, r.nombre, "
                "r.email, r.color_hex, r.avatar_url, r.categoria, r.es_global "
                "FROM asignacion a "
                "JOIN recurso r ON r.id = a.recurso_id "
                "JOIN tarea t ON t.id = a.tarea_id "
                "WHERE t.proyecto_id = ? ORDER BY r.nombre",
                (proyecto_id,),
            ).fetchall()
            resultado: dict[int, list[Recurso]] = {}
            for fila in filas:
                datos = dict(fila)
                tarea_id = int(datos.pop("tarea_asignada_id"))
                datos["es_global"] = bool(datos["es_global"])
                resultado.setdefault(tarea_id, []).append(Recurso(**datos))
            return resultado

    def quitar_asignacion(self, asignacion_id: int) -> None:
        with closing(self._connect()) as db, db:
            db.execute("DELETE FROM asignacion WHERE id = ?", (asignacion_id,))

    def quitar_asignacion_tarea_recurso(self, tarea_id: int, recurso_id: int) -> None:
        with closing(self._connect()) as db, db:
            db.execute(
                "DELETE FROM asignacion WHERE tarea_id = ? AND recurso_id = ?",
                (tarea_id, recurso_id),
            )
