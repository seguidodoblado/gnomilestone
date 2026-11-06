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
    return Proyecto(**dict(fila))


def _estado_de_fila(fila: sqlite3.Row) -> EstadoTablero:
    return EstadoTablero(**dict(fila))


def _tarea_de_fila(fila: sqlite3.Row) -> Tarea:
    datos = dict(fila)
    datos["es_hito"] = bool(datos["es_hito"])
    return Tarea(**datos)


def _dependencia_de_fila(fila: sqlite3.Row) -> Dependencia:
    return Dependencia(**dict(fila))


def _recurso_de_fila(fila: sqlite3.Row) -> Recurso:
    return Recurso(**dict(fila))


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

    # -- Proyectos ---------------------------------------------------------

    def crear_proyecto(
        self,
        nombre: str,
        descripcion: str = "",
        fecha_inicio: str | None = None,
        fecha_fin_estimada: str | None = None,
        github_repo_owner: str | None = None,
        github_repo_name: str | None = None,
    ) -> Proyecto:
        with closing(self._connect()) as db, db:
            cursor = db.execute(
                "INSERT INTO proyecto "
                "(nombre, descripcion, fecha_inicio, fecha_fin_estimada, "
                " github_repo_owner, github_repo_name) VALUES (?, ?, ?, ?, ?, ?)",
                (nombre, descripcion, fecha_inicio, fecha_fin_estimada,
                 github_repo_owner, github_repo_name),
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
                "fecha_fin_estimada = ?, github_repo_owner = ?, github_repo_name = ?, "
                "github_project_v2_id = ?, actualizado = datetime('now') WHERE id = ?",
                (proyecto.nombre, proyecto.descripcion, proyecto.fecha_inicio,
                 proyecto.fecha_fin_estimada, proyecto.github_repo_owner,
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

    def crear_estado(self, proyecto_id: int, nombre: str) -> EstadoTablero:
        with closing(self._connect()) as db, db:
            siguiente_orden = db.execute(
                "SELECT COALESCE(MAX(orden), -1) + 1 FROM estado_tablero WHERE proyecto_id = ?",
                (proyecto_id,),
            ).fetchone()[0]
            cursor = db.execute(
                "INSERT INTO estado_tablero (proyecto_id, nombre, orden) VALUES (?, ?, ?)",
                (proyecto_id, nombre, siguiente_orden),
            )
            fila = db.execute(
                "SELECT * FROM estado_tablero WHERE id = ?", (cursor.lastrowid,)
            ).fetchone()
            return _estado_de_fila(fila)

    def renombrar_estado(self, estado_id: int, nombre: str) -> None:
        with closing(self._connect()) as db, db:
            db.execute("UPDATE estado_tablero SET nombre = ? WHERE id = ?", (nombre, estado_id))

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
        duracion_dias: int = 1,
        porcentaje_completado: int = 0,
        es_hito: bool = False,
    ) -> Tarea:
        with closing(self._connect()) as db, db:
            siguiente_orden = db.execute(
                "SELECT COALESCE(MAX(orden), -1) + 1 FROM tarea WHERE proyecto_id = ?",
                (proyecto_id,),
            ).fetchone()[0]
            cursor = db.execute(
                "INSERT INTO tarea (proyecto_id, padre_id, estado_id, titulo, descripcion, "
                "fecha_inicio, duracion_dias, porcentaje_completado, orden, es_hito) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (proyecto_id, padre_id, estado_id, titulo, descripcion, fecha_inicio,
                 duracion_dias, porcentaje_completado, siguiente_orden, int(es_hito)),
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

    def actualizar_tarea(self, tarea: Tarea) -> None:
        with closing(self._connect()) as db, db:
            db.execute(
                "UPDATE tarea SET padre_id = ?, estado_id = ?, titulo = ?, descripcion = ?, "
                "fecha_inicio = ?, duracion_dias = ?, porcentaje_completado = ?, orden = ?, "
                "es_hito = ?, actualizado = datetime('now') WHERE id = ?",
                (tarea.padre_id, tarea.estado_id, tarea.titulo, tarea.descripcion,
                 tarea.fecha_inicio, tarea.duracion_dias, tarea.porcentaje_completado,
                 tarea.orden, int(tarea.es_hito), tarea.id),
            )

    def eliminar_tarea(self, tarea_id: int) -> None:
        with closing(self._connect()) as db, db:
            db.execute("DELETE FROM tarea WHERE id = ?", (tarea_id,))

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
    ) -> Recurso:
        with closing(self._connect()) as db, db:
            cursor = db.execute(
                "INSERT INTO recurso (proyecto_id, nombre, email, color_hex, avatar_url) "
                "VALUES (?, ?, ?, ?, ?)",
                (proyecto_id, nombre, email, color_hex, avatar_url),
            )
            fila = db.execute("SELECT * FROM recurso WHERE id = ?", (cursor.lastrowid,)).fetchone()
            return _recurso_de_fila(fila)

    def listar_recursos(self, proyecto_id: int) -> list[Recurso]:
        with closing(self._connect()) as db:
            filas = db.execute(
                "SELECT * FROM recurso WHERE proyecto_id = ? ORDER BY nombre", (proyecto_id,)
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
                "UPDATE recurso SET nombre = ?, email = ?, color_hex = ?, avatar_url = ? "
                "WHERE id = ?",
                (
                    recurso.nombre,
                    recurso.email,
                    recurso.color_hex,
                    recurso.avatar_url,
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
                "r.email, r.color_hex, r.avatar_url "
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
