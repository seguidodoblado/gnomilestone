"""Usuario de gestión activo: quien maneja la aplicación y firma los cambios del historial.

El usuario activo es global (el mismo en todos los proyectos) y se guarda en los ajustes como
`usuario_actual`. La primera vez se crea uno con el nombre de la sesión del sistema para que
la auditoría funcione sin configurar nada."""

from __future__ import annotations

import getpass

from gnomilestone import settings
from gnomilestone.store import Store


def inicializar_usuario_actual(store: Store) -> None:
    """Fija en el almacén el usuario guardado en los ajustes, o crea uno si no hay ninguno."""
    ajustes = settings.read_settings()
    usuario_id = ajustes.get("usuario_actual")
    usuario = store.obtener_usuario(usuario_id if isinstance(usuario_id, int) else None)
    if usuario is None:
        usuarios = store.listar_usuarios()
        if usuarios:
            usuario = usuarios[0]
        else:
            try:
                nombre = getpass.getuser()
            except (KeyError, OSError):
                nombre = "usuario"
            usuario = store.crear_usuario(nombre)
    establecer_usuario_actual(store, usuario.id)


def establecer_usuario_actual(store: Store, usuario_id: int | None) -> None:
    store.usuario_actual_id = usuario_id
    ajustes = settings.read_settings()
    if usuario_id is None:
        ajustes.pop("usuario_actual", None)
    else:
        ajustes["usuario_actual"] = usuario_id
    settings.write_settings(ajustes)
