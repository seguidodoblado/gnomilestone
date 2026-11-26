"""Proveedores de alojamiento con los que un proyecto puede sincronizarse (hoy GitHub; GitLab,
y quizá Bitbucket y Codeberg, después).

Cada proveedor es un dato: su nombre, su icono y las plantillas propias de la plataforma
(el flujo de estados de issue y las etiquetas por defecto). Un proyecto tiene UNA sola conexión
(`Proyecto.proveedor`), así el pull siempre tiene una única fuente de verdad. Los campos
`github_repo_owner`, `github_repo_name` y `github_project_v2_id` del proyecto guardan los datos
del vínculo del proveedor activo (propietario, repositorio y proyecto con tablero)."""

from __future__ import annotations

from dataclasses import dataclass

from gnomilestone import estado_issue, etiquetas

PROVEEDOR_POR_DEFECTO = "github"


@dataclass(frozen=True)
class Proveedor:
    id: str
    nombre: str
    icono: str
    # (nombre de la columna, estado de issue, descripción), en orden.
    flujo_estados: tuple[tuple[str, str, str], ...]
    # (nombre, color hex sin «#», descripción).
    etiquetas_por_defecto: tuple[tuple[str, str, str], ...]


PROVEEDORES: dict[str, Proveedor] = {
    "github": Proveedor(
        id="github",
        nombre="GitHub",
        icono="github-symbolic",
        flujo_estados=estado_issue.FLUJO_GITHUB,
        etiquetas_por_defecto=etiquetas.ETIQUETAS_POR_DEFECTO,
    ),
}


def obtener(proveedor_id: str | None) -> Proveedor:
    """El proveedor con ese id; si no existe (base de otra versión), el de por defecto."""
    return PROVEEDORES.get(proveedor_id or "", PROVEEDORES[PROVEEDOR_POR_DEFECTO])
