from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Proyecto:
    id: int
    nombre: str
    descripcion: str = ""
    fecha_inicio: str | None = None
    fecha_fin_estimada: str | None = None
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


@dataclass
class Tarea:
    id: int
    proyecto_id: int
    titulo: str
    padre_id: int | None = None
    estado_id: int | None = None
    descripcion: str = ""
    fecha_inicio: str | None = None
    duracion_dias: int = 1
    porcentaje_completado: int = 0
    orden: int = 0
    es_hito: bool = False
    creado: str = ""
    actualizado: str = ""


@dataclass
class Dependencia:
    id: int
    tarea_origen_id: int
    tarea_destino_id: int
    tipo: str = "fin_a_inicio"


@dataclass
class Recurso:
    id: int
    proyecto_id: int
    nombre: str
    email: str | None = None
    color_hex: str | None = None
    # Ruta local o URL (p. ej. avatar de GitHub al vincular la cuenta).
    avatar_url: str | None = None


@dataclass
class Asignacion:
    id: int
    tarea_id: int
    recurso_id: int
    porcentaje_dedicacion: int = 100
