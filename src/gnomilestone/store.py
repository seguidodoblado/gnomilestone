from __future__ import annotations

import json
import os
import sqlite3
from contextlib import closing
from pathlib import Path

from gnomilestone.i18n import _
from gnomilestone.models import (
    ESTADOS_NOTA,
    SECCIONES_DOCUMENTACION,
    SUBSECCIONES_FIJAS,
    TIPOS_SUBSECCION,
    Asignacion,
    Comentario,
    Dependencia,
    DiagramaDocumentacion,
    EstadoTablero,
    Etiqueta,
    HistorialTarea,
    NotaDocumentacion,
    Proyecto,
    Recurso,
    SubseccionDocumentacion,
    Tarea,
    VersionDocumentacion,
)

DATA_DIR = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "gnomilestone"
DB_PATH = DATA_DIR / "gnomilestone.db"

MAX_VERSIONES = 50  # versiones anteriores que se conservan por nota o diagrama
# Mismos nombres que trae un Project V2 de GitHub recién creado (sin tocar): así se
# puede detectar con una comparación exacta si un tablero de GitHub sigue siendo el
# esquema de fábrica (ver `sync.py`), y un proyecto nuevo local ya nace igual que él.
ESTADOS_POR_DEFECTO = ("Todo", "In Progress", "Done")
# Mismas descripciones que trae GitHub de fábrica para esas tres columnas.
DESCRIPCIONES_ESTADOS_POR_DEFECTO = {
    "Todo": "This item hasn't been started",
    "In Progress": "This is actively being worked on",
    "Done": "This has been completed",
}
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
    datos = dict(fila)
    datos["es_final"] = bool(datos.get("es_final"))
    datos["es_temporal"] = bool(datos.get("es_temporal"))
    return EstadoTablero(**datos)


def _tarea_de_fila(fila: sqlite3.Row) -> Tarea:
    datos = dict(fila)
    datos["es_hito"] = bool(datos["es_hito"])
    datos["archivada"] = bool(datos.get("archivada"))
    datos.pop("github_etiquetas", None)  # base de fusión de etiquetas: no es campo del modelo
    return Tarea(**datos)


def _dependencia_de_fila(fila: sqlite3.Row) -> Dependencia:
    return Dependencia(**dict(fila))


def _recurso_de_fila(fila: sqlite3.Row) -> Recurso:
    datos = dict(fila)
    datos["es_global"] = bool(datos["es_global"])
    return Recurso(**datos)


def _comentario_de_fila(fila: sqlite3.Row) -> Comentario:
    datos = dict(fila)
    datos["pendiente_envio"] = bool(datos.get("pendiente_envio"))
    return Comentario(**datos)


def _historial_de_fila(fila: sqlite3.Row) -> HistorialTarea:
    return HistorialTarea(**dict(fila))


def _etiqueta_de_fila(fila: sqlite3.Row) -> Etiqueta:
    return Etiqueta(**dict(fila))


def _asignacion_de_fila(fila: sqlite3.Row) -> Asignacion:
    return Asignacion(**dict(fila))


def _subsecciones_por_defecto() -> dict[str, tuple[tuple[str, str], ...]]:
    """Subsecciones (nombre, tipo) con las que nace cada proyecto; editables después.
    Función y no constante para traducirlas con el idioma ya instalado."""
    return {
        "vision_general": ((_("Contexto del proyecto"), "notas"),),
        "arquitectura": (
            (_("Diseño y estructura"), "notas"),
            (_("Stack y empaquetado"), "notas"),
            (_("Calidad y entrega"), "notas"),
            (_("Diagramas"), "diagramas"),
        ),
        "especificaciones": (
            (_("Modelo de datos"), "notas"),
            (_("Datos de usuario"), "notas"),
            (_("Interfaz"), "notas"),
            (_("Integraciones"), "notas"),
            (_("Funcionalidades"), "notas"),
        ),
        "decisiones_tecnicas": ((_("General"), "notas"),),
    }


def _sembrar_subsecciones(db: sqlite3.Connection, proyecto_id: int) -> None:
    for seccion, subsecciones in _subsecciones_por_defecto().items():
        for orden, (nombre, tipo) in enumerate(subsecciones):
            db.execute(
                "INSERT INTO subseccion_documentacion (proyecto_id, seccion, nombre, orden, tipo) "
                "VALUES (?, ?, ?, ?, ?)",
                (proyecto_id, seccion, nombre, orden, tipo),
            )
    notas_por_categoria = {
        "Contexto del proyecto": ("README", "Código de conducta", "Contribuyendo", "Licencia", "Seguridad"),
        "Diseño y estructura": ("Capas", "Estructura del proyecto", "Componentes", "Flujos"),
        "Stack y empaquetado": ("Pilas", "Empaquetado"),
        "Calidad y entrega": ("Pruebas", "Integración continua", "Despliegue continuo"),
    }
    for categoria, notas in notas_por_categoria.items():
        subseccion = db.execute(
            "SELECT id FROM subseccion_documentacion WHERE proyecto_id = ? "
            "AND seccion = 'arquitectura' AND nombre = ?",
            (proyecto_id, categoria),
        ).fetchone()
        if subseccion is None:
            continue
        for orden, titulo in enumerate(notas):
            db.execute(
                "INSERT INTO nota_documentacion "
                "(proyecto_id, seccion, subseccion_id, titulo, orden) VALUES (?, 'arquitectura', ?, ?, ?)",
                (proyecto_id, subseccion[0], titulo, orden),
            )


class EtiquetaDuplicadaError(Exception):
    """Ya existe otra etiqueta con ese nombre en el proyecto."""


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
            version = 11
        if version < 12:
            # Issues/items de GitHub cuya tarea local se eliminó a propósito: la
            # sincronización no debe volver a traerlos.
            db.execute(
                "CREATE TABLE IF NOT EXISTS github_descartado ("
                " proyecto_id INTEGER NOT NULL REFERENCES proyecto(id) ON DELETE CASCADE,"
                " issue_number INTEGER,"
                " item_id TEXT)"
            )
            db.execute("PRAGMA user_version = 12")
            version = 12
        if version < 13:
            # Comentarios por tarea; los de un issue de GitHub llevan su id remoto.
            db.execute(
                "CREATE TABLE IF NOT EXISTS comentario ("
                " id INTEGER PRIMARY KEY,"
                " tarea_id INTEGER NOT NULL REFERENCES tarea(id) ON DELETE CASCADE,"
                " autor TEXT NOT NULL DEFAULT '',"
                " cuerpo TEXT NOT NULL,"
                " creado TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),"
                " github_comment_id INTEGER UNIQUE)"
            )
            db.execute("PRAGMA user_version = 13")
            version = 13
        if version < 14:
            columnas = {fila[1] for fila in db.execute("PRAGMA table_info(comentario)")}
            if "pendiente_envio" not in columnas:
                # Comentario editado en local que aún no se ha enviado a GitHub: el pull no
                # debe pisarlo con la versión remota.
                db.execute(
                    "ALTER TABLE comentario ADD COLUMN pendiente_envio INTEGER NOT NULL DEFAULT 0"
                )
            db.execute("PRAGMA user_version = 14")
            version = 14
        if version < 15:
            columnas = {fila[1] for fila in db.execute("PRAGMA table_info(tarea)")}
            if "prioridad" not in columnas:
                db.execute("ALTER TABLE tarea ADD COLUMN prioridad INTEGER NOT NULL DEFAULT 0")
            if "github_etiquetas" not in columnas:
                # Etiquetas que tenía el issue en el último sync (JSON): base de la fusión.
                db.execute("ALTER TABLE tarea ADD COLUMN github_etiquetas TEXT")
            db.execute(
                "CREATE TABLE IF NOT EXISTS etiqueta ("
                " id INTEGER PRIMARY KEY,"
                " proyecto_id INTEGER NOT NULL REFERENCES proyecto(id) ON DELETE CASCADE,"
                " nombre TEXT NOT NULL COLLATE NOCASE,"
                " color TEXT NOT NULL DEFAULT '6e7781',"
                " UNIQUE (proyecto_id, nombre))"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS tarea_etiqueta ("
                " tarea_id INTEGER NOT NULL REFERENCES tarea(id) ON DELETE CASCADE,"
                " etiqueta_id INTEGER NOT NULL REFERENCES etiqueta(id) ON DELETE CASCADE,"
                " PRIMARY KEY (tarea_id, etiqueta_id))"
            )
            db.execute("PRAGMA user_version = 15")
            version = 15
        if version < 16:
            cols_estado = {fila[1] for fila in db.execute("PRAGMA table_info(estado_tablero)")}
            if "es_final" not in cols_estado:
                db.execute("ALTER TABLE estado_tablero ADD COLUMN es_final INTEGER NOT NULL DEFAULT 0")
            cols_tarea = {fila[1] for fila in db.execute("PRAGMA table_info(tarea)")}
            if "porcentaje_previo" not in cols_tarea:
                db.execute("ALTER TABLE tarea ADD COLUMN porcentaje_previo INTEGER")
            db.execute("PRAGMA user_version = 16")
            version = 16
        if version < 17:
            cols_tarea = {fila[1] for fila in db.execute("PRAGMA table_info(tarea)")}
            if "archivada" not in cols_tarea:
                db.execute("ALTER TABLE tarea ADD COLUMN archivada INTEGER NOT NULL DEFAULT 0")
            db.execute("PRAGMA user_version = 17")
            version = 17
        if version < 18:
            # Notas de documentación del proyecto (Markdown propio de la app).
            db.execute(
                "CREATE TABLE IF NOT EXISTS nota_documentacion ("
                " id INTEGER PRIMARY KEY,"
                " proyecto_id INTEGER NOT NULL REFERENCES proyecto(id) ON DELETE CASCADE,"
                " seccion TEXT NOT NULL,"
                " titulo TEXT NOT NULL,"
                " contenido TEXT NOT NULL DEFAULT '',"
                " orden INTEGER NOT NULL DEFAULT 0,"
                " creado TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),"
                " actualizado TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')))"
            )
            db.execute("PRAGMA user_version = 18")
            version = 18
        if version < 19:
            # Subsecciones editables de la documentación; las notas cuelgan de una.
            db.execute(
                "CREATE TABLE IF NOT EXISTS subseccion_documentacion ("
                " id INTEGER PRIMARY KEY,"
                " proyecto_id INTEGER NOT NULL REFERENCES proyecto(id) ON DELETE CASCADE,"
                " seccion TEXT NOT NULL,"
                " nombre TEXT NOT NULL,"
                " orden INTEGER NOT NULL DEFAULT 0,"
                " tipo TEXT NOT NULL DEFAULT 'notas')"
            )
            columnas = {fila[1] for fila in db.execute("PRAGMA table_info(nota_documentacion)")}
            if "subseccion_id" not in columnas:
                db.execute(
                    "ALTER TABLE nota_documentacion ADD COLUMN subseccion_id INTEGER "
                    "REFERENCES subseccion_documentacion(id) ON DELETE CASCADE"
                )
            for fila in db.execute("SELECT id FROM proyecto").fetchall():
                _sembrar_subsecciones(db, fila[0])
            # Las notas que ya existían pasan a la primera subsección de su sección.
            db.execute(
                "UPDATE nota_documentacion SET subseccion_id = ("
                " SELECT s.id FROM subseccion_documentacion s"
                " WHERE s.proyecto_id = nota_documentacion.proyecto_id"
                " AND s.seccion = nota_documentacion.seccion ORDER BY s.orden LIMIT 1)"
            )
            db.execute("PRAGMA user_version = 19")
            version = 19
        if version < 20:
            # Subsecciones de tipo «diagramas» (flujos dibujados) y su tabla.
            columnas = {fila[1] for fila in db.execute("PRAGMA table_info(subseccion_documentacion)")}
            if "tipo" not in columnas:
                db.execute(
                    "ALTER TABLE subseccion_documentacion ADD COLUMN tipo TEXT NOT NULL "
                    "DEFAULT 'notas'"
                )
                # «Flujos» (de Arquitectura) pasa a ser de diagramas en los proyectos que ya
                # tenían las subsecciones por defecto.
                db.execute(
                    "UPDATE subseccion_documentacion SET tipo = 'diagramas' "
                    "WHERE seccion = 'arquitectura' AND nombre IN ('Flujos', 'Flows')"
                )
            db.execute(
                "CREATE TABLE IF NOT EXISTS diagrama_documentacion ("
                " id INTEGER PRIMARY KEY,"
                " proyecto_id INTEGER NOT NULL REFERENCES proyecto(id) ON DELETE CASCADE,"
                " subseccion_id INTEGER NOT NULL"
                "  REFERENCES subseccion_documentacion(id) ON DELETE CASCADE,"
                " titulo TEXT NOT NULL,"
                " datos TEXT NOT NULL DEFAULT '',"
                " orden INTEGER NOT NULL DEFAULT 0,"
                " creado TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),"
                " actualizado TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')))"
            )
            db.execute("PRAGMA user_version = 20")
            version = 20
        if version < 21:
            # Versiones anteriores de notas y diagramas (se guardan al sobrescribir).
            db.execute(
                "CREATE TABLE IF NOT EXISTS version_documentacion ("
                " id INTEGER PRIMARY KEY,"
                " nota_id INTEGER REFERENCES nota_documentacion(id) ON DELETE CASCADE,"
                " diagrama_id INTEGER REFERENCES diagrama_documentacion(id) ON DELETE CASCADE,"
                " titulo TEXT NOT NULL,"
                " contenido TEXT NOT NULL,"
                " creado TEXT NOT NULL)"
            )
            db.execute("PRAGMA user_version = 21")
            version = 21
        if version < 22:
            columnas = {fila[1] for fila in db.execute("PRAGMA table_info(nota_documentacion)")}
            if "estado" not in columnas:
                db.execute("ALTER TABLE nota_documentacion ADD COLUMN estado TEXT NOT NULL DEFAULT ''")
            db.execute("PRAGMA user_version = 22")
            version = 22
        if version < 23:
            # Jerarquía de páginas: una nota puede colgar de otra de la misma subsección.
            columnas = {fila[1] for fila in db.execute("PRAGMA table_info(nota_documentacion)")}
            if "padre_id" not in columnas:
                db.execute(
                    "ALTER TABLE nota_documentacion ADD COLUMN padre_id INTEGER "
                    "REFERENCES nota_documentacion(id) ON DELETE SET NULL"
                )
            db.execute("PRAGMA user_version = 23")
            version = 23
        if version < 24:
            columnas = {fila[1] for fila in db.execute("PRAGMA table_info(tarea)")}
            if "fecha_fin_planificada_inicial" not in columnas:
                db.execute("ALTER TABLE tarea ADD COLUMN fecha_fin_planificada_inicial TEXT")
            if "fecha_fin_real" not in columnas:
                db.execute("ALTER TABLE tarea ADD COLUMN fecha_fin_real TEXT")
            db.execute(
                "CREATE TABLE IF NOT EXISTS historial_tarea ("
                "id INTEGER PRIMARY KEY, tarea_id INTEGER NOT NULL REFERENCES tarea(id) ON DELETE CASCADE,"
                "creado TEXT NOT NULL DEFAULT (datetime('now')), tipo TEXT NOT NULL, campo TEXT,"
                "valor_anterior TEXT, valor_nuevo TEXT, detalle TEXT NOT NULL DEFAULT '')"
            )
            db.execute("CREATE INDEX IF NOT EXISTS idx_historial_tarea ON historial_tarea(tarea_id, id)")
            db.execute("PRAGMA user_version = 24")
            version = 24
        if version < 25:
            # Visión general es contexto del proyecto, no una subsección de Arquitectura.
            db.execute(
                "UPDATE subseccion_documentacion SET seccion = 'vision_general' "
                "WHERE seccion = 'arquitectura' AND nombre IN ('Visión general', 'Vision general')"
            )
            db.execute(
                "UPDATE nota_documentacion SET seccion = 'vision_general' "
                "WHERE seccion = 'arquitectura' AND subseccion_id IN "
                "(SELECT id FROM subseccion_documentacion WHERE seccion = 'vision_general')"
            )
            db.execute("PRAGMA user_version = 25")
            version = 25
        if version < 26:
            # Agrupa las subsecciones de Arquitectura sin convertir Diagramas en notas.
            agrupaciones = {
                "Diseño y estructura": ("Capas", "Estructura del proyecto", "Componentes"),
                "Stack y empaquetado": ("Pilas", "Empaquetado"),
                "Calidad y entrega": ("Pruebas", "Integración continua"),
            }
            proyectos = db.execute("SELECT id FROM proyecto").fetchall()
            for proyecto in proyectos:
                proyecto_id = proyecto[0]
                for categoria, nombres in agrupaciones.items():
                    fila = db.execute(
                        "SELECT id FROM subseccion_documentacion "
                        "WHERE proyecto_id = ? AND seccion = 'arquitectura' AND nombre = ?",
                        (proyecto_id, categoria),
                    ).fetchone()
                    if fila is None:
                        cursor = db.execute(
                            "INSERT INTO subseccion_documentacion "
                            "(proyecto_id, seccion, nombre, orden, tipo) VALUES (?, 'arquitectura', ?, ?, 'notas')",
                            (proyecto_id, categoria, 0),
                        )
                        categoria_id = cursor.lastrowid
                    else:
                        categoria_id = fila[0]
                    marcadores = ",".join("?" * len(nombres))
                    antiguos = db.execute(
                        f"SELECT id FROM subseccion_documentacion WHERE proyecto_id = ? "
                        f"AND seccion = 'arquitectura' AND nombre IN ({marcadores})",
                        (proyecto_id, *nombres),
                    ).fetchall()
                    for antiguo in antiguos:
                        db.execute(
                            "UPDATE nota_documentacion SET subseccion_id = ? WHERE subseccion_id = ?",
                            (categoria_id, antiguo[0]),
                        )
                        db.execute("DELETE FROM subseccion_documentacion WHERE id = ?", (antiguo[0],))
                db.execute(
                    "UPDATE subseccion_documentacion SET nombre = 'Diagramas' "
                    "WHERE proyecto_id = ? AND seccion = 'arquitectura' AND nombre IN ('Flujos', 'Flows')",
                    (proyecto_id,),
                )
            db.execute("PRAGMA user_version = 26")
            version = 26
        if version < 27:
            notas_por_categoria = {
                "Contexto del proyecto": ("README", "Código de conducta", "Contribuyendo", "Licencia", "Seguridad"),
                "Diseño y estructura": ("Capas", "Estructura del proyecto", "Componentes", "Flujos"),
                "Stack y empaquetado": ("Pilas", "Empaquetado"),
                "Calidad y entrega": ("Pruebas", "Integración continua", "Despliegue continuo"),
            }
            for proyecto in db.execute("SELECT id FROM proyecto"):
                proyecto_id = proyecto[0]
                for categoria, notas in notas_por_categoria.items():
                    subseccion = db.execute(
                        "SELECT id FROM subseccion_documentacion WHERE proyecto_id = ? "
                        "AND seccion = 'arquitectura' AND nombre = ?",
                        (proyecto_id, categoria),
                    ).fetchone()
                    if subseccion is None:
                        continue
                    for titulo in notas:
                        existe = db.execute(
                            "SELECT 1 FROM nota_documentacion WHERE proyecto_id = ? "
                            "AND subseccion_id = ? AND titulo = ? LIMIT 1",
                            (proyecto_id, subseccion[0], titulo),
                        ).fetchone()
                        if existe is None:
                            orden = db.execute(
                                "SELECT COALESCE(MAX(orden), -1) + 1 FROM nota_documentacion "
                                "WHERE proyecto_id = ? AND subseccion_id = ?",
                                (proyecto_id, subseccion[0]),
                            ).fetchone()[0]
                            db.execute(
                                "INSERT INTO nota_documentacion "
                                "(proyecto_id, seccion, subseccion_id, titulo, orden) "
                                "VALUES (?, 'arquitectura', ?, ?, ?)",
                                (proyecto_id, subseccion[0], titulo, orden),
                            )
            db.execute("PRAGMA user_version = 27")
            version = 27
        if version < 28:
            db.execute(
                "UPDATE subseccion_documentacion SET nombre = 'Contexto del proyecto' "
                "WHERE seccion = 'vision_general' AND nombre IN ('Visión general', 'Vision general')"
            )
            notas_por_categoria = {
                "Contexto del proyecto": ("README", "Código de conducta", "Contribuyendo", "Licencia", "Seguridad"),
                "Calidad y entrega": ("Despliegue continuo",),
            }
            for proyecto in db.execute("SELECT id FROM proyecto"):
                proyecto_id = proyecto[0]
                for categoria, notas in notas_por_categoria.items():
                    subseccion = db.execute(
                        "SELECT id FROM subseccion_documentacion WHERE proyecto_id = ? AND nombre = ?",
                        (proyecto_id, categoria),
                    ).fetchone()
                    if subseccion is None:
                        continue
                    for titulo in notas:
                        existe = db.execute(
                            "SELECT 1 FROM nota_documentacion WHERE subseccion_id = ? AND titulo = ?",
                            (subseccion[0], titulo),
                        ).fetchone()
                        if existe is None:
                            orden = db.execute(
                                "SELECT COALESCE(MAX(orden), -1) + 1 FROM nota_documentacion WHERE subseccion_id = ?",
                                (subseccion[0],),
                            ).fetchone()[0]
                            db.execute(
                                "INSERT INTO nota_documentacion "
                                "(proyecto_id, seccion, subseccion_id, titulo, orden) "
                                "VALUES (?, ?, ?, ?, ?)",
                                (proyecto_id, "vision_general" if categoria == "Contexto del proyecto" else "arquitectura", subseccion[0], titulo, orden),
                            )
            db.execute("PRAGMA user_version = 28")
            version = 28
        if version < 29:
            db.execute(
                "UPDATE nota_documentacion SET titulo = 'Licencia' "
                "WHERE titulo = 'Licencia GPL-3.0'"
            )
            db.execute("PRAGMA user_version = 29")
            version = 29
        if version < 30:
            # Columna del tablero generada por un pull que sustituye el esquema por el de
            # GitHub (ver sync.py): agrupa las tareas que se quedan sin columna real y se
            # borra sola en cuanto se vacía.
            cols_estado = {fila[1] for fila in db.execute("PRAGMA table_info(estado_tablero)")}
            if "es_temporal" not in cols_estado:
                db.execute(
                    "ALTER TABLE estado_tablero ADD COLUMN es_temporal INTEGER NOT NULL DEFAULT 0"
                )
            db.execute("PRAGMA user_version = 30")
            version = 30
        if version < 31:
            # Descripción de una columna, como la de una opción de Status de GitHub.
            cols_estado = {fila[1] for fila in db.execute("PRAGMA table_info(estado_tablero)")}
            if "descripcion" not in cols_estado:
                db.execute(
                    "ALTER TABLE estado_tablero ADD COLUMN descripcion TEXT NOT NULL DEFAULT ''"
                )
            db.execute("PRAGMA user_version = 31")

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
                    "INSERT INTO estado_tablero "
                    "(proyecto_id, nombre, orden, es_final, descripcion) VALUES (?, ?, ?, ?, ?)",
                    (proyecto_id, nombre_estado, indice, int(nombre_estado == "Done"),
                     DESCRIPCIONES_ESTADOS_POR_DEFECTO.get(nombre_estado, "")),
                )
            _sembrar_subsecciones(db, proyecto_id)
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
        self,
        proyecto_id: int,
        nombre: str,
        github_option_id: str | None = None,
        es_final: bool = False,
        es_temporal: bool = False,
        descripcion: str = "",
    ) -> EstadoTablero:
        with closing(self._connect()) as db, db:
            siguiente_orden = db.execute(
                "SELECT COALESCE(MAX(orden), -1) + 1 FROM estado_tablero WHERE proyecto_id = ?",
                (proyecto_id,),
            ).fetchone()[0]
            cursor = db.execute(
                "INSERT INTO estado_tablero "
                "(proyecto_id, nombre, orden, github_option_id, es_final, es_temporal, descripcion) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (proyecto_id, nombre, siguiente_orden, github_option_id,
                 int(es_final), int(es_temporal), descripcion),
            )
            fila = db.execute(
                "SELECT * FROM estado_tablero WHERE id = ?", (cursor.lastrowid,)
            ).fetchone()
            return _estado_de_fila(fila)

    def actualizar_descripcion_estado(self, estado_id: int, descripcion: str) -> None:
        with closing(self._connect()) as db, db:
            db.execute(
                "UPDATE estado_tablero SET descripcion = ? WHERE id = ?",
                (descripcion, estado_id),
            )

    def limpiar_estado_de_tareas(self, proyecto_id: int) -> None:
        """Quita la columna a todas las tareas del proyecto (antes de sustituir el tablero
        entero por el de GitHub, ver `sync.py`)."""
        with closing(self._connect()) as db, db:
            db.execute("UPDATE tarea SET estado_id = NULL WHERE proyecto_id = ?", (proyecto_id,))

    def eliminar_estados_de_proyecto(self, proyecto_id: int) -> None:
        """Borra todas las columnas del proyecto sin comprobar que estén vacías (a
        diferencia de `eliminar_estado`): llamar siempre después de
        `limpiar_estado_de_tareas`, nunca por iniciativa propia de la interfaz."""
        with closing(self._connect()) as db, db:
            db.execute("DELETE FROM estado_tablero WHERE proyecto_id = ?", (proyecto_id,))

    def obtener_o_crear_estado_temporal(self, proyecto_id: int) -> EstadoTablero:
        """La columna «No Status» (mismo nombre que usa GitHub) que agrupa tareas sin
        columna real tras un pull de un Project V2 (ver `sync.py`). Se reutiliza si ya
        existe."""
        with closing(self._connect()) as db:
            fila = db.execute(
                "SELECT * FROM estado_tablero WHERE proyecto_id = ? AND es_temporal = 1 LIMIT 1",
                (proyecto_id,),
            ).fetchone()
            if fila:
                return _estado_de_fila(fila)
        return self.crear_estado(proyecto_id, _("No Status"), es_temporal=True)

    def asignar_estado_a_huerfanas(self, proyecto_id: int, estado_id: int) -> int:
        """Asigna `estado_id` a las tareas del proyecto que se hayan quedado sin columna
        (tras el espejo de un tablero de GitHub, ver `sync.py`). Devuelve cuántas.

        Las archivadas quedan fuera: el Tablero las excluye de por sí (`listar_tareas`
        sin `incluir_archivadas`), así que contarlas aquí desajustaría el aviso del
        número de tareas frente a lo que se ve realmente en la columna."""
        with closing(self._connect()) as db, db:
            cursor = db.execute(
                "UPDATE tarea SET estado_id = ? WHERE proyecto_id = ? AND estado_id IS NULL "
                "AND archivada = 0",
                (estado_id, proyecto_id),
            )
            return cursor.rowcount

    def purgar_estado_temporal_si_vacio(self, estado_id: int) -> bool:
        """Borra `estado_id` si es la columna temporal «No Status» y ya no tiene tareas,
        igual que GitHub la oculta en cuanto se vacía. Devuelve si se ha borrado."""
        with closing(self._connect()) as db, db:
            fila = db.execute(
                "SELECT es_temporal FROM estado_tablero WHERE id = ?", (estado_id,)
            ).fetchone()
            if not fila or not fila[0]:
                return False
            if db.execute(
                "SELECT COUNT(*) FROM tarea WHERE estado_id = ?", (estado_id,)
            ).fetchone()[0]:
                return False
            db.execute("DELETE FROM estado_tablero WHERE id = ?", (estado_id,))
            return True

    def renombrar_estado(self, estado_id: int, nombre: str) -> None:
        with closing(self._connect()) as db, db:
            db.execute("UPDATE estado_tablero SET nombre = ? WHERE id = ?", (nombre, estado_id))

    def establecer_estado_final(self, proyecto_id: int, estado_id: int | None) -> None:
        """Marca `estado_id` como la columna «de completadas» del proyecto (solo una; con
        None se desmarca la que hubiera)."""
        with closing(self._connect()) as db, db:
            db.execute("UPDATE estado_tablero SET es_final = 0 WHERE proyecto_id = ?", (proyecto_id,))
            if estado_id is not None:
                db.execute(
                    "UPDATE estado_tablero SET es_final = 1 WHERE id = ? AND proyecto_id = ?",
                    (estado_id, proyecto_id),
                )

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
        fecha_fin_planificada_inicial: str | None = None,
        fecha_limite: str | None = None,
        fecha_fin_real: str | None = None,
        duracion_dias: int = 1,
        porcentaje_completado: int = 0,
        es_hito: bool = False,
        github_issue_number: int | None = None,
        github_issue_id: str | None = None,
        github_item_id: str | None = None,
        github_url: str | None = None,
        prioridad: int = 0,
    ) -> Tarea:
        if fecha_fin_planificada_inicial is None:
            fecha_fin_planificada_inicial = fecha_fin_planificada
        with closing(self._connect()) as db, db:
            if porcentaje_completado >= 100:
                estado_final = db.execute(
                    "SELECT id FROM estado_tablero WHERE proyecto_id = ? AND es_final = 1 "
                    "ORDER BY orden, id LIMIT 1",
                    (proyecto_id,),
                ).fetchone()
                if estado_final:
                    estado_id = estado_final[0]
            siguiente_orden = db.execute(
                "SELECT COALESCE(MAX(orden), -1) + 1 FROM tarea WHERE proyecto_id = ?",
                (proyecto_id,),
            ).fetchone()[0]
            cursor = db.execute(
                "INSERT INTO tarea (proyecto_id, padre_id, estado_id, titulo, descripcion, "
                "fecha_inicio, fecha_fin_planificada_inicial, fecha_fin_planificada, fecha_limite, "
                "fecha_fin_real, duracion_dias, "
                "porcentaje_completado, orden, es_hito, "
                "github_issue_number, github_issue_id, github_item_id, github_url, prioridad) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (proyecto_id, padre_id, estado_id, titulo, descripcion, fecha_inicio,
                 fecha_fin_planificada_inicial, fecha_fin_planificada, fecha_limite,
                 fecha_fin_real, duracion_dias, porcentaje_completado,
                 siguiente_orden, int(es_hito),
                 github_issue_number, github_issue_id, github_item_id, github_url, prioridad),
            )
            fila = db.execute("SELECT * FROM tarea WHERE id = ?", (cursor.lastrowid,)).fetchone()
            self._registrar_historial_db(db, cursor.lastrowid, "creacion", detalle=titulo)
            return _tarea_de_fila(fila)

    def listar_tareas(self, proyecto_id: int, incluir_archivadas: bool = False) -> list[Tarea]:
        """Tareas del proyecto. Las archivadas quedan fuera salvo que se pidan (la
        sincronización con GitHub necesita verlas todas)."""
        filtro = "" if incluir_archivadas else " AND archivada = 0"
        with closing(self._connect()) as db:
            filas = db.execute(
                f"SELECT * FROM tarea WHERE proyecto_id = ?{filtro} ORDER BY orden",
                (proyecto_id,),
            ).fetchall()
            return [_tarea_de_fila(fila) for fila in filas]

    def reordenar_tareas(self, ids_en_orden: list[int]) -> None:
        """Renumera `orden` según la secuencia dada (la misma que usan Lista y Gantt)."""
        with closing(self._connect()) as db, db:
            db.executemany(
                "UPDATE tarea SET orden = ? WHERE id = ?",
                [(orden, tarea_id) for orden, tarea_id in enumerate(ids_en_orden)],
            )

    def listar_tareas_archivadas(self, proyecto_id: int) -> list[Tarea]:
        with closing(self._connect()) as db:
            filas = db.execute(
                "SELECT * FROM tarea WHERE proyecto_id = ? AND archivada = 1 ORDER BY orden",
                (proyecto_id,),
            ).fetchall()
            return [_tarea_de_fila(fila) for fila in filas]

    # -- Archivo -------------------------------------------------------------

    def _ids_descendientes(self, db: sqlite3.Connection, tarea_id: int) -> list[int]:
        filas = db.execute(
            self._ARBOL_SQL + "SELECT id FROM arbol", (tarea_id,)
        ).fetchall()
        return [f[0] for f in filas]

    def archivar_tarea(self, tarea_id: int) -> None:
        """Archiva la tarea y sus subtareas (si no, quedarían huérfanas en las vistas)."""
        with closing(self._connect()) as db, db:
            ids = self._ids_descendientes(db, tarea_id)
            db.executemany("UPDATE tarea SET archivada = 1 WHERE id = ?", [(i,) for i in ids])

    def desarchivar_tarea(self, tarea_id: int) -> None:
        """Recupera la tarea con sus subtareas y con sus ancestros (una tarea cuyo padre
        sigue archivado no se vería en ninguna vista)."""
        with closing(self._connect()) as db, db:
            ids = set(self._ids_descendientes(db, tarea_id))
            actual = db.execute("SELECT padre_id FROM tarea WHERE id = ?", (tarea_id,)).fetchone()
            while actual is not None and actual[0] is not None and actual[0] not in ids:
                ids.add(actual[0])
                actual = db.execute(
                    "SELECT padre_id FROM tarea WHERE id = ?", (actual[0],)
                ).fetchone()
            db.executemany("UPDATE tarea SET archivada = 0 WHERE id = ?", [(i,) for i in ids])

    def archivar_completadas(self, proyecto_id: int) -> int:
        """Archiva las tareas completadas junto con su rama, solo si toda la rama está al
        100 %. Devuelve cuántas tareas se han archivado (contando subtareas)."""
        tareas = self.listar_tareas(proyecto_id)
        por_id = {t.id: t for t in tareas}
        hijos: dict[int | None, list[Tarea]] = {}
        for t in tareas:
            hijos.setdefault(t.padre_id, []).append(t)

        def rama_completa(t: Tarea) -> bool:
            return t.porcentaje_completado >= 100 and all(
                rama_completa(h) for h in hijos.get(t.id, [])
            )

        antes = len(self.listar_tareas_archivadas(proyecto_id))
        for t in tareas:
            padre = por_id.get(t.padre_id) if t.padre_id is not None else None
            # Solo la rama más alta: archivarla ya archiva a sus descendientes.
            if rama_completa(t) and (padre is None or not rama_completa(padre)):
                self.archivar_tarea(t.id)
        return len(self.listar_tareas_archivadas(proyecto_id)) - antes

    def listar_tareas_de_proyectos(self, proyecto_ids: list[int]) -> list[Tarea]:
        if not proyecto_ids:
            return []
        marcadores = ",".join("?" * len(proyecto_ids))
        with closing(self._connect()) as db:
            filas = db.execute(
                f"SELECT * FROM tarea WHERE proyecto_id IN ({marcadores}) AND archivada = 0 "
                "ORDER BY proyecto_id, orden",
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

    def vincular_issue_github(self, tarea_id: int, numero: int | None, url: str | None) -> None:
        """Guarda solo el número y la URL del issue recién creado, sin tocar el resto de la fila
        (que el usuario pudo editar mientras se enviaba)."""
        with closing(self._connect()) as db, db:
            db.execute(
                "UPDATE tarea SET github_issue_number = ?, github_url = ? WHERE id = ?",
                (numero, url, tarea_id),
            )

    def actualizar_tarea(self, tarea: Tarea) -> None:
        with closing(self._connect()) as db, db:
            fila_anterior = db.execute("SELECT * FROM tarea WHERE id = ?", (tarea.id,)).fetchone()
            anterior = _tarea_de_fila(fila_anterior) if fila_anterior else None
            if tarea.porcentaje_completado >= 100:
                estado_final = db.execute(
                    "SELECT id FROM estado_tablero WHERE proyecto_id = ? AND es_final = 1 "
                    "ORDER BY orden, id LIMIT 1",
                    (tarea.proyecto_id,),
                ).fetchone()
                if estado_final:
                    tarea.estado_id = estado_final[0]
            db.execute(
                "UPDATE tarea SET padre_id = ?, estado_id = ?, titulo = ?, descripcion = ?, "
                "fecha_inicio = ?, fecha_fin_planificada_inicial = ?, fecha_fin_planificada = ?, "
                "fecha_limite = ?, fecha_fin_real = ?, "
                "duracion_dias = ?, porcentaje_completado = ?, orden = ?, "
                # El vínculo con GitHub nunca se borra desde aquí: un objeto Tarea viejo (p. ej.
                # el de un diálogo abierto antes de que termine el primer envío) llegaría sin
                # número de issue y lo borraría, y el siguiente envío crearía un issue duplicado.
                "es_hito = ?, github_issue_number = COALESCE(?, github_issue_number), "
                "github_issue_id = COALESCE(?, github_issue_id), "
                "github_item_id = COALESCE(?, github_item_id), "
                "github_url = COALESCE(?, github_url), prioridad = ?, porcentaje_previo = ?, "
                "actualizado = datetime('now') WHERE id = ?",
                (tarea.padre_id, tarea.estado_id, tarea.titulo, tarea.descripcion,
                 tarea.fecha_inicio, tarea.fecha_fin_planificada_inicial,
                 tarea.fecha_fin_planificada, tarea.fecha_limite, tarea.fecha_fin_real,
                 tarea.duracion_dias, tarea.porcentaje_completado,
                 tarea.orden, int(tarea.es_hito), tarea.github_issue_number,
                 tarea.github_issue_id, tarea.github_item_id, tarea.github_url,
                 tarea.prioridad, tarea.porcentaje_previo, tarea.id),
            )
            if anterior:
                cambios = (
                    ("estado_id", anterior.estado_id, tarea.estado_id, "estado"),
                    ("porcentaje_completado", anterior.porcentaje_completado, tarea.porcentaje_completado, "progreso"),
                    ("fecha_inicio", anterior.fecha_inicio, tarea.fecha_inicio, "fecha_inicio"),
                    ("fecha_fin_planificada_inicial", anterior.fecha_fin_planificada_inicial, tarea.fecha_fin_planificada_inicial, "planificacion_base"),
                    ("fecha_fin_planificada", anterior.fecha_fin_planificada, tarea.fecha_fin_planificada, "planificacion"),
                    ("fecha_limite", anterior.fecha_limite, tarea.fecha_limite, "limite"),
                    ("fecha_fin_real", anterior.fecha_fin_real, tarea.fecha_fin_real, "fin_real"),
                )
                for campo, viejo, nuevo, tipo in cambios:
                    if viejo != nuevo:
                        self._registrar_historial_db(db, tarea.id, tipo, campo, viejo, nuevo)

    @staticmethod
    def _registrar_historial_db(
        db: sqlite3.Connection,
        tarea_id: int,
        tipo: str,
        campo: str | None = None,
        valor_anterior: object | None = None,
        valor_nuevo: object | None = None,
        detalle: str = "",
    ) -> None:
        db.execute(
            "INSERT INTO historial_tarea "
            "(tarea_id, tipo, campo, valor_anterior, valor_nuevo, detalle) VALUES (?, ?, ?, ?, ?, ?)",
            (tarea_id, tipo, campo, valor_anterior, valor_nuevo, detalle),
        )

    def listar_historial_tarea(self, tarea_id: int) -> list[HistorialTarea]:
        with closing(self._connect()) as db:
            filas = db.execute(
                "SELECT * FROM historial_tarea WHERE tarea_id = ? ORDER BY id DESC", (tarea_id,)
            ).fetchall()
            return [_historial_de_fila(fila) for fila in filas]

    # -- Etiquetas ---------------------------------------------------------

    def listar_etiquetas(self, proyecto_id: int) -> list[Etiqueta]:
        with closing(self._connect()) as db:
            filas = db.execute(
                "SELECT * FROM etiqueta WHERE proyecto_id = ? ORDER BY nombre", (proyecto_id,)
            ).fetchall()
            return [_etiqueta_de_fila(f) for f in filas]

    def asegurar_etiqueta(
        self, proyecto_id: int, nombre: str, color: str | None = None
    ) -> Etiqueta:
        """La etiqueta con ese nombre (sin distinguir mayúsculas), creándola si no existe.
        Si ya existe y llega un color distinto (el de GitHub manda), lo actualiza."""
        nombre = nombre.strip()
        with closing(self._connect()) as db, db:
            fila = db.execute(
                "SELECT * FROM etiqueta WHERE proyecto_id = ? AND nombre = ?",
                (proyecto_id, nombre),
            ).fetchone()
            if fila is None:
                cursor = db.execute(
                    "INSERT INTO etiqueta (proyecto_id, nombre, color) VALUES (?, ?, ?)",
                    (proyecto_id, nombre, (color or "6e7781").lstrip("#")),
                )
                fila = db.execute(
                    "SELECT * FROM etiqueta WHERE id = ?", (cursor.lastrowid,)
                ).fetchone()
            elif color and fila["color"] != color.lstrip("#"):
                db.execute(
                    "UPDATE etiqueta SET color = ? WHERE id = ?", (color.lstrip("#"), fila["id"])
                )
                fila = db.execute("SELECT * FROM etiqueta WHERE id = ?", (fila["id"],)).fetchone()
            return _etiqueta_de_fila(fila)

    def contar_tareas_por_etiqueta(self, proyecto_id: int) -> dict[int, int]:
        with closing(self._connect()) as db:
            filas = db.execute(
                "SELECT te.etiqueta_id, COUNT(*) FROM tarea_etiqueta te "
                "JOIN etiqueta e ON e.id = te.etiqueta_id WHERE e.proyecto_id = ? "
                "GROUP BY te.etiqueta_id",
                (proyecto_id,),
            ).fetchall()
            return {f[0]: f[1] for f in filas}

    def obtener_etiqueta(self, etiqueta_id: int) -> Etiqueta | None:
        with closing(self._connect()) as db:
            fila = db.execute("SELECT * FROM etiqueta WHERE id = ?", (etiqueta_id,)).fetchone()
            return _etiqueta_de_fila(fila) if fila else None

    def renombrar_etiqueta(self, etiqueta_id: int, nombre: str) -> None:
        """Cambia el nombre. Lanza `EtiquetaDuplicadaError` si ya hay otra con ese nombre."""
        nombre = nombre.strip()
        with closing(self._connect()) as db:
            try:
                with db:
                    db.execute(
                        "UPDATE etiqueta SET nombre = ? WHERE id = ?", (nombre, etiqueta_id)
                    )
            except sqlite3.IntegrityError as e:
                raise EtiquetaDuplicadaError(nombre) from e

    def actualizar_color_etiqueta(self, etiqueta_id: int, color: str) -> None:
        with closing(self._connect()) as db, db:
            db.execute(
                "UPDATE etiqueta SET color = ? WHERE id = ?", (color.lstrip("#"), etiqueta_id)
            )

    def eliminar_etiqueta(self, etiqueta_id: int) -> None:
        with closing(self._connect()) as db, db:
            db.execute("DELETE FROM etiqueta WHERE id = ?", (etiqueta_id,))

    def sustituir_en_bases_github(
        self, proyecto_id: int, viejo: str, nuevo: str | None
    ) -> None:
        """Renombra (o, con `nuevo=None`, quita) una etiqueta en las bases de fusión de las
        tareas del proyecto, para que un renombrado o borrado no se tome por edición local."""
        with closing(self._connect()) as db, db:
            filas = db.execute(
                "SELECT id, github_etiquetas FROM tarea "
                "WHERE proyecto_id = ? AND github_etiquetas IS NOT NULL",
                (proyecto_id,),
            ).fetchall()
            for fila in filas:
                nombres = json.loads(fila[1])
                if not any(n.casefold() == viejo.casefold() for n in nombres):
                    continue
                nombres = [n for n in nombres if n.casefold() != viejo.casefold()]
                if nuevo is not None:
                    nombres.append(nuevo)
                db.execute(
                    "UPDATE tarea SET github_etiquetas = ? WHERE id = ?",
                    (json.dumps(nombres), fila[0]),
                )

    def listar_etiquetas_de_tarea(self, tarea_id: int) -> list[Etiqueta]:
        with closing(self._connect()) as db:
            filas = db.execute(
                "SELECT e.* FROM etiqueta e JOIN tarea_etiqueta te ON te.etiqueta_id = e.id "
                "WHERE te.tarea_id = ? ORDER BY e.nombre",
                (tarea_id,),
            ).fetchall()
            return [_etiqueta_de_fila(f) for f in filas]

    def listar_etiquetas_por_tarea(self, proyecto_id: int) -> dict[int, list[Etiqueta]]:
        with closing(self._connect()) as db:
            filas = db.execute(
                "SELECT te.tarea_id AS tarea_id, e.* FROM etiqueta e "
                "JOIN tarea_etiqueta te ON te.etiqueta_id = e.id "
                "WHERE e.proyecto_id = ? ORDER BY e.nombre",
                (proyecto_id,),
            ).fetchall()
            resultado: dict[int, list[Etiqueta]] = {}
            for f in filas:
                datos = dict(f)
                tarea_id = datos.pop("tarea_id")
                resultado.setdefault(tarea_id, []).append(Etiqueta(**datos))
            return resultado

    def establecer_etiquetas_de_tarea(self, tarea_id: int, etiqueta_ids: list[int]) -> None:
        with closing(self._connect()) as db, db:
            db.execute("DELETE FROM tarea_etiqueta WHERE tarea_id = ?", (tarea_id,))
            db.executemany(
                "INSERT OR IGNORE INTO tarea_etiqueta (tarea_id, etiqueta_id) VALUES (?, ?)",
                [(tarea_id, e) for e in etiqueta_ids],
            )

    def etiquetas_base_github(self, tarea_id: int) -> list[str] | None:
        """Nombres de etiqueta que tenía el issue en el último sync, o None si nunca se sincronizó."""
        with closing(self._connect()) as db:
            fila = db.execute(
                "SELECT github_etiquetas FROM tarea WHERE id = ?", (tarea_id,)
            ).fetchone()
            return json.loads(fila[0]) if fila and fila[0] is not None else None

    def guardar_etiquetas_base_github(self, tarea_id: int, nombres: list[str]) -> None:
        """Sin tocar `actualizado`: no es una edición del usuario (no debe causar conflicto)."""
        with closing(self._connect()) as db, db:
            db.execute(
                "UPDATE tarea SET github_etiquetas = ? WHERE id = ?",
                (json.dumps(nombres), tarea_id),
            )

    # -- Documentación -----------------------------------------------------

    @staticmethod
    def _guardar_version(
        db: sqlite3.Connection,
        tabla: str,
        columna: str,
        objeto_id: int,
        titulo_nuevo: str,
        contenido_nuevo: str,
        campo: str,
    ) -> None:
        """Antes de sobrescribir una nota o un diagrama, guarda su estado actual como versión
        (si va a cambiar) y conserva solo las `MAX_VERSIONES` más recientes."""
        actual = db.execute(
            f"SELECT titulo, {campo} AS contenido, actualizado FROM {tabla} WHERE id = ?",
            (objeto_id,),
        ).fetchone()
        if actual is None or (actual["titulo"], actual["contenido"]) == (titulo_nuevo, contenido_nuevo):
            return
        db.execute(
            f"INSERT INTO version_documentacion ({columna}, titulo, contenido, creado) "
            "VALUES (?, ?, ?, ?)",
            (objeto_id, actual["titulo"], actual["contenido"], actual["actualizado"]),
        )
        db.execute(
            f"DELETE FROM version_documentacion WHERE {columna} = ? AND id NOT IN ("
            f" SELECT id FROM version_documentacion WHERE {columna} = ? ORDER BY id DESC LIMIT ?)",
            (objeto_id, objeto_id, MAX_VERSIONES),
        )

    def contar_versiones_notas(self, proyecto_id: int) -> dict[int, int]:
        """Versiones anteriores disponibles de cada nota del proyecto: {nota_id: cantidad}."""
        with closing(self._connect()) as db:
            filas = db.execute(
                "SELECT v.nota_id, COUNT(*) FROM version_documentacion v "
                "JOIN nota_documentacion n ON n.id = v.nota_id "
                "WHERE n.proyecto_id = ? GROUP BY v.nota_id",
                (proyecto_id,),
            ).fetchall()
            return {fila[0]: fila[1] for fila in filas}

    def contar_versiones_diagramas(self, proyecto_id: int) -> dict[int, int]:
        """Igual que `contar_versiones_notas`, para diagramas."""
        with closing(self._connect()) as db:
            filas = db.execute(
                "SELECT v.diagrama_id, COUNT(*) FROM version_documentacion v "
                "JOIN diagrama_documentacion d ON d.id = v.diagrama_id "
                "WHERE d.proyecto_id = ? GROUP BY v.diagrama_id",
                (proyecto_id,),
            ).fetchall()
            return {fila[0]: fila[1] for fila in filas}

    def listar_versiones_nota(self, nota_id: int) -> list[VersionDocumentacion]:
        return self._listar_versiones("nota_id", nota_id)

    def listar_versiones_diagrama(self, diagrama_id: int) -> list[VersionDocumentacion]:
        return self._listar_versiones("diagrama_id", diagrama_id)

    def _listar_versiones(self, columna: str, objeto_id: int) -> list[VersionDocumentacion]:
        """Versiones anteriores, de la más reciente a la más antigua."""
        with closing(self._connect()) as db:
            filas = db.execute(
                "SELECT id, titulo, contenido, creado FROM version_documentacion "
                f"WHERE {columna} = ? ORDER BY id DESC",
                (objeto_id,),
            ).fetchall()
            return [VersionDocumentacion(**dict(f)) for f in filas]

    def listar_subsecciones_documentacion(
        self, proyecto_id: int, seccion: str | None = None
    ) -> list[SubseccionDocumentacion]:
        consulta = "SELECT * FROM subseccion_documentacion WHERE proyecto_id = ?"
        parametros: list = [proyecto_id]
        if seccion is not None:
            consulta += " AND seccion = ?"
            parametros.append(seccion)
        with closing(self._connect()) as db:
            filas = db.execute(consulta + " ORDER BY seccion, orden, id", parametros).fetchall()
            return [SubseccionDocumentacion(**dict(f)) for f in filas]

    def crear_subseccion_documentacion(
        self, proyecto_id: int, seccion: str, nombre: str, tipo: str = "notas"
    ) -> SubseccionDocumentacion:
        if seccion not in SECCIONES_DOCUMENTACION or seccion in SUBSECCIONES_FIJAS:
            raise ValueError(f"Sección sin subsecciones editables: {seccion}")
        if tipo not in TIPOS_SUBSECCION:
            raise ValueError(f"Tipo de subsección desconocido: {tipo}")
        with closing(self._connect()) as db, db:
            orden = db.execute(
                "SELECT COALESCE(MAX(orden), -1) + 1 FROM subseccion_documentacion "
                "WHERE proyecto_id = ? AND seccion = ?",
                (proyecto_id, seccion),
            ).fetchone()[0]
            cursor = db.execute(
                "INSERT INTO subseccion_documentacion "
                "(proyecto_id, seccion, nombre, orden, tipo) VALUES (?, ?, ?, ?, ?)",
                (proyecto_id, seccion, nombre, orden, tipo),
            )
            fila = db.execute(
                "SELECT * FROM subseccion_documentacion WHERE id = ?", (cursor.lastrowid,)
            ).fetchone()
            return SubseccionDocumentacion(**dict(fila))

    def renombrar_subseccion_documentacion(self, subseccion_id: int, nombre: str) -> None:
        with closing(self._connect()) as db, db:
            db.execute(
                "UPDATE subseccion_documentacion SET nombre = ? WHERE id = ?",
                (nombre, subseccion_id),
            )

    def eliminar_subseccion_documentacion(self, subseccion_id: int) -> None:
        """Elimina la subsección y, en cascada, sus notas."""
        with closing(self._connect()) as db, db:
            db.execute("DELETE FROM subseccion_documentacion WHERE id = ?", (subseccion_id,))

    def crear_nota_documentacion(
        self,
        proyecto_id: int,
        seccion: str,
        titulo: str,
        contenido: str = "",
        subseccion_id: int | None = None,
        estado: str = "",
        padre_id: int | None = None,
    ) -> NotaDocumentacion:
        if seccion not in SECCIONES_DOCUMENTACION:
            raise ValueError(f"Sección de documentación desconocida: {seccion}")
        if estado not in ESTADOS_NOTA:
            raise ValueError(f"Estado de nota desconocido: {estado}")
        with closing(self._connect()) as db, db:
            self._validar_padre(db, None, padre_id, subseccion_id)
            orden = db.execute(
                "SELECT COALESCE(MAX(orden), -1) + 1 FROM nota_documentacion "
                "WHERE proyecto_id = ? AND seccion = ? AND subseccion_id IS ?",
                (proyecto_id, seccion, subseccion_id),
            ).fetchone()[0]
            cursor = db.execute(
                "INSERT INTO nota_documentacion "
                "(proyecto_id, seccion, subseccion_id, titulo, contenido, orden, estado, padre_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (proyecto_id, seccion, subseccion_id, titulo, contenido, orden, estado, padre_id),
            )
            fila = db.execute(
                "SELECT * FROM nota_documentacion WHERE id = ?", (cursor.lastrowid,)
            ).fetchone()
            return NotaDocumentacion(**dict(fila))

    def listar_notas_documentacion(
        self, proyecto_id: int, seccion: str | None = None, subseccion_id: int | None = None
    ) -> list[NotaDocumentacion]:
        consulta = "SELECT * FROM nota_documentacion WHERE proyecto_id = ?"
        parametros: list = [proyecto_id]
        if seccion is not None:
            consulta += " AND seccion = ?"
            parametros.append(seccion)
        if subseccion_id is not None:
            consulta += " AND subseccion_id = ?"
            parametros.append(subseccion_id)
        with closing(self._connect()) as db:
            filas = db.execute(consulta + " ORDER BY seccion, orden, id", parametros).fetchall()
            return [NotaDocumentacion(**dict(f)) for f in filas]

    def obtener_nota_documentacion(self, nota_id: int) -> NotaDocumentacion | None:
        with closing(self._connect()) as db:
            fila = db.execute(
                "SELECT * FROM nota_documentacion WHERE id = ?", (nota_id,)
            ).fetchone()
            return NotaDocumentacion(**dict(fila)) if fila else None

    def actualizar_nota_documentacion(self, nota: NotaDocumentacion) -> None:
        with closing(self._connect()) as db, db:
            self._validar_padre(db, nota.id, nota.padre_id, nota.subseccion_id)
            self._guardar_version(
                db, "nota_documentacion", "nota_id", nota.id, nota.titulo, nota.contenido, "contenido"
            )
            db.execute(
                "UPDATE nota_documentacion SET titulo = ?, contenido = ?, orden = ?, estado = ?, "
                "padre_id = ?, actualizado = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') WHERE id = ?",
                (nota.titulo, nota.contenido, nota.orden, nota.estado, nota.padre_id, nota.id),
            )

    def eliminar_nota_documentacion(self, nota_id: int) -> None:
        """Elimina la nota; sus subpáginas no se pierden: pasan a colgar de su abuela."""
        with closing(self._connect()) as db, db:
            fila = db.execute(
                "SELECT padre_id FROM nota_documentacion WHERE id = ?", (nota_id,)
            ).fetchone()
            if fila is not None:
                db.execute(
                    "UPDATE nota_documentacion SET padre_id = ? WHERE padre_id = ?",
                    (fila["padre_id"], nota_id),
                )
            db.execute("DELETE FROM nota_documentacion WHERE id = ?", (nota_id,))

    @staticmethod
    def _validar_padre(
        db: sqlite3.Connection, nota_id: int | None, padre_id: int | None, subseccion_id: int | None
    ) -> None:
        """El padre debe existir, ser de la misma subsección y no ser la propia nota ni una
        de sus descendientes (no puede haber ciclos)."""
        if padre_id is None:
            return
        if nota_id is not None and padre_id == nota_id:
            raise ValueError("Una nota no puede ser su propia página padre")
        padre = db.execute(
            "SELECT subseccion_id FROM nota_documentacion WHERE id = ?", (padre_id,)
        ).fetchone()
        if padre is None or padre["subseccion_id"] != subseccion_id:
            raise ValueError("La página padre debe existir y ser de la misma subsección")
        actual = padre_id
        while actual is not None:  # se sube por los ancestros del padre buscando la nota
            if actual == nota_id:
                raise ValueError("La página padre no puede ser una subpágina de la propia nota")
            fila = db.execute(
                "SELECT padre_id FROM nota_documentacion WHERE id = ?", (actual,)
            ).fetchone()
            actual = fila["padre_id"] if fila else None

    def crear_diagrama_documentacion(
        self, proyecto_id: int, subseccion_id: int, titulo: str, datos: str = ""
    ) -> DiagramaDocumentacion:
        with closing(self._connect()) as db, db:
            orden = db.execute(
                "SELECT COALESCE(MAX(orden), -1) + 1 FROM diagrama_documentacion "
                "WHERE subseccion_id = ?",
                (subseccion_id,),
            ).fetchone()[0]
            cursor = db.execute(
                "INSERT INTO diagrama_documentacion "
                "(proyecto_id, subseccion_id, titulo, datos, orden) VALUES (?, ?, ?, ?, ?)",
                (proyecto_id, subseccion_id, titulo, datos, orden),
            )
            fila = db.execute(
                "SELECT * FROM diagrama_documentacion WHERE id = ?", (cursor.lastrowid,)
            ).fetchone()
            return DiagramaDocumentacion(**dict(fila))

    def listar_diagramas_documentacion(
        self, proyecto_id: int, subseccion_id: int | None = None
    ) -> list[DiagramaDocumentacion]:
        consulta = "SELECT * FROM diagrama_documentacion WHERE proyecto_id = ?"
        parametros: list = [proyecto_id]
        if subseccion_id is not None:
            consulta += " AND subseccion_id = ?"
            parametros.append(subseccion_id)
        with closing(self._connect()) as db:
            filas = db.execute(consulta + " ORDER BY orden, id", parametros).fetchall()
            return [DiagramaDocumentacion(**dict(f)) for f in filas]

    def obtener_diagrama_documentacion(self, diagrama_id: int) -> DiagramaDocumentacion | None:
        with closing(self._connect()) as db:
            fila = db.execute(
                "SELECT * FROM diagrama_documentacion WHERE id = ?", (diagrama_id,)
            ).fetchone()
            return DiagramaDocumentacion(**dict(fila)) if fila else None

    def actualizar_diagrama_documentacion(self, diagrama: DiagramaDocumentacion) -> None:
        with closing(self._connect()) as db, db:
            self._guardar_version(
                db, "diagrama_documentacion", "diagrama_id", diagrama.id, diagrama.titulo,
                diagrama.datos, "datos",
            )
            db.execute(
                "UPDATE diagrama_documentacion SET titulo = ?, datos = ?, orden = ?, "
                "actualizado = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') WHERE id = ?",
                (diagrama.titulo, diagrama.datos, diagrama.orden, diagrama.id),
            )

    def eliminar_diagrama_documentacion(self, diagrama_id: int) -> None:
        with closing(self._connect()) as db, db:
            db.execute("DELETE FROM diagrama_documentacion WHERE id = ?", (diagrama_id,))

    # -- Comentarios -------------------------------------------------------

    def crear_comentario(
        self,
        tarea_id: int,
        cuerpo: str,
        autor: str = "",
        creado: str | None = None,
        github_comment_id: int | None = None,
    ) -> Comentario:
        with closing(self._connect()) as db, db:
            if creado is None:
                cursor = db.execute(
                    "INSERT INTO comentario (tarea_id, autor, cuerpo, github_comment_id) "
                    "VALUES (?, ?, ?, ?)",
                    (tarea_id, autor, cuerpo, github_comment_id),
                )
            else:
                cursor = db.execute(
                    "INSERT INTO comentario (tarea_id, autor, cuerpo, creado, github_comment_id) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (tarea_id, autor, cuerpo, creado, github_comment_id),
                )
            fila = db.execute(
                "SELECT * FROM comentario WHERE id = ?", (cursor.lastrowid,)
            ).fetchone()
            return _comentario_de_fila(fila)

    def listar_comentarios(self, tarea_id: int) -> list[Comentario]:
        with closing(self._connect()) as db:
            filas = db.execute(
                "SELECT * FROM comentario WHERE tarea_id = ? ORDER BY creado, id", (tarea_id,)
            ).fetchall()
            return [_comentario_de_fila(f) for f in filas]

    def obtener_comentario(self, comentario_id: int) -> Comentario | None:
        with closing(self._connect()) as db:
            fila = db.execute(
                "SELECT * FROM comentario WHERE id = ?", (comentario_id,)
            ).fetchone()
            return _comentario_de_fila(fila) if fila else None

    def obtener_comentario_por_github(self, github_comment_id: int) -> Comentario | None:
        with closing(self._connect()) as db:
            fila = db.execute(
                "SELECT * FROM comentario WHERE github_comment_id = ?", (github_comment_id,)
            ).fetchone()
            return _comentario_de_fila(fila) if fila else None

    def listar_comentarios_sin_enviar(self, proyecto_id: int) -> list[Comentario]:
        """Comentarios locales de tareas con issue que aún no se han publicado en GitHub."""
        with closing(self._connect()) as db:
            filas = db.execute(
                "SELECT c.* FROM comentario c JOIN tarea t ON t.id = c.tarea_id "
                "WHERE t.proyecto_id = ? AND t.github_issue_number IS NOT NULL "
                "AND c.github_comment_id IS NULL ORDER BY c.id",
                (proyecto_id,),
            ).fetchall()
            return [_comentario_de_fila(f) for f in filas]

    def listar_ediciones_sin_enviar(self, proyecto_id: int) -> list[Comentario]:
        """Comentarios ya publicados en GitHub que se editaron en local."""
        with closing(self._connect()) as db:
            filas = db.execute(
                "SELECT c.* FROM comentario c JOIN tarea t ON t.id = c.tarea_id "
                "WHERE t.proyecto_id = ? AND c.pendiente_envio = 1 "
                "AND c.github_comment_id IS NOT NULL ORDER BY c.id",
                (proyecto_id,),
            ).fetchall()
            return [_comentario_de_fila(f) for f in filas]

    def actualizar_comentario(
        self,
        comentario_id: int,
        cuerpo: str | None = None,
        autor: str | None = None,
        github_comment_id: int | None = None,
        pendiente_envio: bool | None = None,
    ) -> None:
        with closing(self._connect()) as db, db:
            if pendiente_envio is not None:
                db.execute(
                    "UPDATE comentario SET pendiente_envio = ? WHERE id = ?",
                    (int(pendiente_envio), comentario_id),
                )
            if cuerpo is not None:
                db.execute("UPDATE comentario SET cuerpo = ? WHERE id = ?", (cuerpo, comentario_id))
            if autor is not None:
                db.execute("UPDATE comentario SET autor = ? WHERE id = ?", (autor, comentario_id))
            if github_comment_id is not None:
                db.execute(
                    "UPDATE comentario SET github_comment_id = ? WHERE id = ?",
                    (github_comment_id, comentario_id),
                )

    def eliminar_comentario(self, comentario_id: int) -> None:
        with closing(self._connect()) as db, db:
            db.execute("DELETE FROM comentario WHERE id = ?", (comentario_id,))

    _ARBOL_SQL = (
        "WITH RECURSIVE arbol(id) AS ("
        " SELECT id FROM tarea WHERE id = ?"
        " UNION ALL SELECT t.id FROM tarea t JOIN arbol a ON t.padre_id = a.id) "
    )

    def vinculos_github_de_arbol(self, tarea_id: int) -> list[tuple[int | None, str | None]]:
        """(número de issue, id de item) de la tarea y sus subtareas que están vinculadas."""
        with closing(self._connect()) as db:
            filas = db.execute(
                self._ARBOL_SQL
                + "SELECT github_issue_number, github_item_id FROM tarea "
                "WHERE id IN (SELECT id FROM arbol) "
                "AND (github_issue_number IS NOT NULL OR github_item_id IS NOT NULL)",
                (tarea_id,),
            ).fetchall()
            return [(f[0], f[1]) for f in filas]

    def eliminar_tarea(self, tarea_id: int) -> None:
        with closing(self._connect()) as db, db:
            # La tarea y sus subtareas (se borran en cascada): se recuerda su vínculo con
            # GitHub para que el siguiente pull no las resucite.
            db.execute(
                self._ARBOL_SQL
                + "INSERT INTO github_descartado (proyecto_id, issue_number, item_id) "
                "SELECT proyecto_id, github_issue_number, github_item_id FROM tarea "
                "WHERE id IN (SELECT id FROM arbol) "
                "AND (github_issue_number IS NOT NULL OR github_item_id IS NOT NULL)",
                (tarea_id,),
            )
            db.execute("DELETE FROM tarea WHERE id = ?", (tarea_id,))

    def github_descartado(
        self, proyecto_id: int, issue_number: int | None, item_id: str | None
    ) -> bool:
        """True si la tarea de ese issue/item se eliminó localmente y no debe reimportarse."""
        with closing(self._connect()) as db:
            fila = db.execute(
                "SELECT 1 FROM github_descartado WHERE proyecto_id = ? "
                "AND ((issue_number IS NOT NULL AND issue_number = ?) "
                "OR (item_id IS NOT NULL AND item_id = ?)) LIMIT 1",
                (proyecto_id, issue_number, item_id),
            ).fetchone()
            return fila is not None

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
