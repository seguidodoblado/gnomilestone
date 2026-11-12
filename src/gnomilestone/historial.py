"""Texto legible de los eventos del historial de una tarea."""

from __future__ import annotations

import json

from gnomilestone.i18n import _
from gnomilestone.models import HistorialTarea
from gnomilestone.tipos import nombre_tipo


def titulo_evento(tipo: str) -> str:
    return {
        "creacion": _("Tarea creada"),
        "estado": _("Estado cambiado"),
        "progreso": _("Progreso cambiado"),
        "planificacion": _("Final planificado cambiado"),
        "planificacion_base": _("Planificado inicial cambiado"),
        "fin_real": _("Final real cambiado"),
        "fecha_inicio": _("Inicio cambiado"),
        "limite": _("Límite cambiado"),
        "tipo": _("Tipo cambiado"),
    }.get(tipo, tipo)


def detalle_evento(evento: HistorialTarea, nombres_estado: dict[int, str] | None = None) -> str:
    """«anterior → nuevo» del cambio, con los nombres de columna y de tipo en vez de ids."""
    if evento.valor_anterior is None and evento.valor_nuevo is None:
        return evento.detalle

    guardados = _nombres_guardados(evento) if evento.tipo == "estado" else {}

    def mostrar(valor: str | None, lado: str = "") -> str:
        if not valor:
            return "—"
        if evento.tipo == "estado" and valor.isdigit():
            nombre = (nombres_estado or {}).get(int(valor)) or guardados.get(lado)
            return nombre or _("(columna eliminada)")
        if evento.tipo == "tipo":
            return nombre_tipo(valor)
        if evento.tipo == "progreso":
            return f"{valor}%"
        return valor

    return f"{mostrar(evento.valor_anterior, 'anterior')} → {mostrar(evento.valor_nuevo, 'nuevo')}"


def _nombres_guardados(evento: HistorialTarea) -> dict[str, str]:
    """Nombres de columna que el evento guardó al registrarse (los antiguos no los tienen)."""
    try:
        datos = json.loads(evento.detalle)
    except (TypeError, ValueError):
        return {}
    if not isinstance(datos, dict):
        return {}
    return {k: v for k, v in datos.items() if isinstance(v, str)}
