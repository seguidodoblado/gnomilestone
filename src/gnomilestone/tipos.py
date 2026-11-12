"""Tipo de una tarea y su correspondencia con los tipos de issue de GitHub.

GitHub ofrece por defecto tres tipos de issue: Task, Bug y Feature. Localmente se guardan
como clave estable (`trabajo`, `error`, `funcionalidad`; vacío si no tiene) y se envían con
el nombre que GitHub espera. «Tarea» ya es el nombre de nuestras issues, de ahí «Trabajo».
"""

from __future__ import annotations

from gnomilestone.i18n import _

NINGUNO, TRABAJO, ERROR, FUNCIONALIDAD = "", "trabajo", "error", "funcionalidad"
TIPOS = (TRABAJO, ERROR, FUNCIONALIDAD)

# Nombre del tipo en GitHub tal y como lo crea por defecto (inglés).
_GITHUB = {TRABAJO: "Task", ERROR: "Bug", FUNCIONALIDAD: "Feature"}
# Nombres con los que se reconoce cada tipo en GitHub, en inglés y en español, por si se
# renombran en el repositorio.
_SINONIMOS = {
    TRABAJO: ("task", "tarea", "trabajo"),
    ERROR: ("bug", "error", "fallo"),
    FUNCIONALIDAD: ("feature", "funcionalidad", "función", "funcion", "característica", "caracteristica"),
}
_DESDE_GITHUB = {n: clave for clave, nombres in _SINONIMOS.items() for n in nombres}


def nombre_github(tipo: str) -> str | None:
    """Nombre del tipo en GitHub, o None si la tarea no tiene tipo."""
    return _GITHUB.get(tipo)


def tipo_desde_github(nombre: str | None) -> str | None:
    """Tipo local de un tipo de issue de GitHub, o None si no se reconoce (no se toca)."""
    return _DESDE_GITHUB.get((nombre or "").casefold())


def nombre_remoto(tipo: str, nombres_remotos: list[str]) -> str | None:
    """Nombre que el repositorio da a este tipo (p. ej. «Error» si lo renombró del inglés),
    o None si no tiene ninguno equivalente."""
    for nombre in nombres_remotos:
        if tipo_desde_github(nombre) == tipo:
            return nombre
    return None


def nombre_tipo(tipo: str) -> str:
    return {
        TRABAJO: _("Trabajo"), ERROR: _("Error"), FUNCIONALIDAD: _("Funcionalidad"),
    }.get(tipo, _("Sin tipo"))
