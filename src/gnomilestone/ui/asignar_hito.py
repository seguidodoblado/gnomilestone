"""Asignar tareas a un Hito (desde el menú contextual, el diálogo de tarea y la vista Hitos)."""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass

import gi

gi.require_version("GLib", "2.0")
from gi.repository import GLib

from gnomilestone.models import Hito, Tarea
from gnomilestone.store import Store
from gnomilestone.sync import GitHubSyncManager


def diferir(accion: Callable[[], None]) -> None:
    """Ejecuta `accion` al volver al bucle principal. Las vistas se reconstruyen al cambiar los
    hitos; hacerlo dentro del manejador de un botón o menú que está en esas mismas vistas
    destruye el widget que sigue emitiendo la señal y puede tumbar GTK."""
    GLib.idle_add(lambda: accion() or False)


def asignar_tareas_a_hito(
    store: Store, tarea_ids: list[int], hito_id: int | None, enviar: bool = True
) -> None:
    """Pone (o quita, con `None`) el Hito de cada tarea y, si el proyecto está vinculado con
    GitHub, mete o saca sus issues del Milestone en segundo plano."""
    cambiadas: list[Tarea] = []
    for tarea_id in tarea_ids:
        tarea = store.obtener_tarea(tarea_id)
        if tarea is None or tarea.hito_id == hito_id:
            continue
        tarea.hito_id = hito_id
        store.actualizar_tarea(tarea)
        cambiadas.append(tarea)
    if not (enviar and cambiadas):
        return
    proyecto = store.obtener_proyecto(cambiadas[0].proyecto_id)
    if not (proyecto and proyecto.github_repo_owner and proyecto.github_repo_name):
        return

    def _enviar() -> None:
        sync = GitHubSyncManager(store)
        for tarea in cambiadas:
            sync.push_tarea(tarea.id)

    threading.Thread(target=_enviar, daemon=True).start()


@dataclass
class AsignacionHito:
    """Lo que necesita un menú contextual para ofrecer «Asignar a hito»."""

    hitos_de: Callable[[Tarea], list[Hito]]
    asignar: Callable[[Tarea, int | None], None]


def crear_asignacion(store: Store, al_cambiar: Callable[[], None]) -> AsignacionHito:
    def _asignar(tarea: Tarea, hito_id: int | None) -> None:
        asignar_tareas_a_hito(store, [tarea.id], hito_id)
        diferir(al_cambiar)

    return AsignacionHito(lambda tarea: store.listar_hitos(tarea.proyecto_id), _asignar)
