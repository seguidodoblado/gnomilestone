"""Estado de un issue de GitHub (Backlog, Todo, In progress, In review, Done…) a partir de la
columna y el progreso de la tarea. Es un estado propio del issue, distinto de la columna Status
de un Project V2; cada estado implica además que el issue esté abierto o cerrado."""

from __future__ import annotations

from gnomilestone import completado
from gnomilestone.models import EstadoTablero, Tarea

COMPLETADO = "Completed"
EN_CURSO = "Started"
EN_REVISION = "review"
SIN_EMPEZAR = "Backlog"
PLANIFICADO = "Planned"
NO_PLANIFICADO = "Not planned"
DUPLICADO = "Duplicate"

# El flujo de columnas de GitHub, en su orden: (nombre de la columna, estado de issue,
# descripción). Las de Todo, In progress y Done son las de GitHub; el resto siguen su estilo.
FLUJO_GITHUB = (
    ("Backlog", SIN_EMPEZAR, "This item is not scheduled or prioritized yet"),
    ("Todo", PLANIFICADO, "This item hasn't been started"),
    ("In progress", EN_CURSO, "This is actively being worked on"),
    ("In review", EN_REVISION, "This item is being reviewed"),
    ("Done", COMPLETADO, "This has been completed"),
    ("Not planned", NO_PLANIFICADO, "This item won't be worked on"),
    ("Duplicate", DUPLICADO, "This item already exists"),
)
# Nombres con los que un proyecto suele tener ya esas columnas (para reutilizarlas).
_SINONIMOS = {
    SIN_EMPEZAR: ("backlog", "pendiente", "sin empezar"),
    PLANIFICADO: ("todo", "por hacer", "a hacer", "planificado"),
    EN_CURSO: ("in progress", "en progreso", "en curso"),
    EN_REVISION: ("in review", "en revisión", "en revision", "revisión", "revision", "review"),
    COMPLETADO: ("done", "hecho", "hecha", "completado", "completada", "completadas"),
    NO_PLANIFICADO: ("not planned", "no planificado", "descartado", "descartada"),
    DUPLICADO: ("duplicate", "duplicado", "duplicada"),
}


def columna_para(categoria: str, existentes: list[EstadoTablero], usadas: set[int]) -> EstadoTablero | None:
    """La columna del proyecto que ya hace de `categoria`: la enlazada a ella o, si no, la que
    se llama como se suele llamar (Pendiente, En progreso, Hecho…). No repite una ya usada."""
    libres = [e for e in existentes if e.id not in usadas]
    enlazada = next((e for e in libres if e.estado_issue == categoria), None)
    if enlazada is not None:
        return enlazada
    nombres = _SINONIMOS.get(categoria, ())
    por_nombre = next((e for e in libres if e.nombre.strip().casefold() in nombres), None)
    if por_nombre is not None:
        return por_nombre
    if categoria == COMPLETADO:
        return next((e for e in libres if e.es_final), None)
    return None

_PALABRAS_REVISION = ("review", "revis")


def categoria_estado_issue(tarea: Tarea, estados: list[EstadoTablero]) -> str:
    """Qué estado de issue le corresponde a la tarea, como categoría de GitHub:

    - Si la columna está enlazada a un estado (`estado_issue`), ese; solo «Not planned» y «Duplicate»
      mandan siempre, y «Done» también si la tarea está al 100 %.
    - `Completed` (Done): al 100 % o en la columna de completadas.
    - `review` (In review): su columna se llama «review» o «revisión».
    - `Started` (In progress): con algo de progreso o fuera de la primera columna.
    - `Backlog`: sin empezar, en la primera columna que no es la de completadas.
    """
    columna = next((e for e in estados if e.id == tarea.estado_id), None)
    if columna is not None and columna.estado_issue in (NO_PLANIFICADO, DUPLICADO):
        return columna.estado_issue  # cerrada sin completar, aunque tenga algún progreso
    final = completado.id_columna_final(estados)
    if tarea.porcentaje_completado >= 100 or (final is not None and tarea.estado_id == final):
        return COMPLETADO
    if columna is not None and columna.estado_issue in (SIN_EMPEZAR, PLANIFICADO, EN_CURSO, EN_REVISION):
        return columna.estado_issue  # la columna dice qué estado es
    if columna is not None and any(p in columna.nombre.casefold() for p in _PALABRAS_REVISION):
        return EN_REVISION
    primera = next((e for e in estados if not e.es_final), None)
    fuera_de_la_primera = columna is not None and primera is not None and columna.id != primera.id
    if tarea.porcentaje_completado > 0 or fuera_de_la_primera:
        return EN_CURSO
    return SIN_EMPEZAR


def elegir_estado(categoria: str, estados_github: list[dict]) -> dict | None:
    """El estado de GitHub (`{id, name, category}`) que corresponde a esa categoría: «In review»
    por su nombre, y el resto por su categoría (con «In progress» antes que «In review»)."""
    if categoria == EN_REVISION:
        return next((e for e in estados_github if e.get("name", "").casefold() == "in review"), None)
    if categoria == PLANIFICADO:
        return next((e for e in estados_github if e.get("name", "").casefold() == "todo"), None)
    candidatos = [e for e in estados_github if e.get("category") == categoria]
    preferido = next((e for e in candidatos if e.get("name", "").casefold() != "in review"), None)
    return preferido
