"""Texto legible de los eventos del historial de una tarea."""

from __future__ import annotations

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

    def mostrar(valor: str | None) -> str:
        if not valor:
            return "—"
        if evento.tipo == "estado" and nombres_estado and valor.isdigit():
            return nombres_estado.get(int(valor), valor)
        if evento.tipo == "tipo":
            return nombre_tipo(valor)
        if evento.tipo == "progreso":
            return f"{valor}%"
        return valor

    return f"{mostrar(evento.valor_anterior)} → {mostrar(evento.valor_nuevo)}"
