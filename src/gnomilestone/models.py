from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Proyecto:
    id: int
    nombre: str
    icon_name: str = "folder-symbolic"
    icon_path: str | None = None
    descripcion: str = ""
    fecha_inicio: str | None = None
    fecha_fin_estimada: str | None = None
    estado: str = "pendiente"
    archivado: bool = False
    github_repo_owner: str | None = None
    github_repo_name: str | None = None
    github_project_v2_id: str | None = None
    creado: str = ""
    actualizado: str = ""


@dataclass
class EstadoTablero:
    id: int
    proyecto_id: int
    nombre: str
    orden: int
    color_hex: str | None = None
    github_option_id: str | None = None
    es_final: bool = False  # columna «de completadas»: entrar completa la tarea (ver completado.py)


@dataclass
class Tarea:
    id: int
    proyecto_id: int
    titulo: str
    padre_id: int | None = None
    estado_id: int | None = None
    descripcion: str = ""
    fecha_inicio: str | None = None
    fecha_fin_planificada: str | None = None
    fecha_limite: str | None = None
    duracion_dias: int = 1
    porcentaje_completado: int = 0
    archivada: bool = False  # fuera de todas las vistas hasta que se desarchive
    porcentaje_previo: int | None = None  # % antes de completarse al entrar en la columna final
    orden: int = 0
    es_hito: bool = False
    prioridad: int = 0  # 0 ninguna, 1 baja, 2 media, 3 alta (ver prioridad.py)
    github_issue_number: int | None = None
    github_issue_id: str | None = None
    github_item_id: str | None = None
    github_url: str | None = None
    github_synced_at: str | None = None
    creado: str = ""
    actualizado: str = ""


@dataclass
class Dependencia:
    id: int
    tarea_origen_id: int
    tarea_destino_id: int
    tipo: str = "fin_a_inicio"


CATEGORIAS_RECURSO = ("personas", "medios", "equipos", "lugares")


@dataclass
class Recurso:
    id: int
    proyecto_id: int
    nombre: str
    email: str | None = None
    color_hex: str | None = None
    # Ruta local o URL (p. ej. avatar de GitHub al vincular la cuenta).
    avatar_url: str | None = None
    categoria: str = "personas"
    # Si es True, aparece y se puede asignar en todos los proyectos, no solo en
    # `proyecto_id` (el proyecto donde se creó). Evita duplicar el alta de una misma
    # persona/medio/equipo/lugar en cada proyecto en el que participa.
    es_global: bool = False


@dataclass
class Asignacion:
    id: int
    tarea_id: int
    recurso_id: int
    porcentaje_dedicacion: int = 100


@dataclass
class Comentario:
    id: int
    tarea_id: int
    cuerpo: str
    autor: str = ""
    creado: str = ""
    github_comment_id: int | None = None
    pendiente_envio: bool = False  # editado en local y aún sin enviar a GitHub


@dataclass
class Etiqueta:
    id: int
    proyecto_id: int
    nombre: str
    color: str = "6e7781"  # hex sin «#», como lo da GitHub
