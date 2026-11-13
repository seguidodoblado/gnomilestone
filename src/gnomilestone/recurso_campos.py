"""Campos propios de cada categoría de recurso (Equipos, Medios y Lugares).

Se guardan en `Recurso.detalles` (un diccionario clave → texto, en JSON en la base de
datos). Definirlos aquí, y no como columnas, permite ampliar el formulario y el futuro
catálogo del parque técnico sin migrar la base de datos cada vez.
"""

from __future__ import annotations

from dataclasses import dataclass

from gnomilestone.i18n import _
from gnomilestone.models import Recurso


@dataclass(frozen=True)
class Campo:
    clave: str
    etiqueta: str
    # Si no está vacía, el campo es una lista desplegable con estos valores.
    opciones: tuple[str, ...] = ()
    multilinea: bool = False


def campos_de(categoria: str) -> tuple[Campo, ...]:
    """Campos del formulario de una categoría (vacío para Personas)."""
    if categoria == "equipos":
        return (
            Campo("tipo", _("Tipo"), (
                _("Portátil"), _("Sobremesa"), _("Monitor"), _("Móvil"), _("Tableta"),
                _("Servidor"), _("Periférico"), _("Otro"),
            )),
            Campo("marca", _("Marca")),
            Campo("modelo", _("Modelo")),
            Campo("numero_serie", _("Número de serie")),
            Campo("fecha_compra", _("Fecha de compra (AAAA-MM-DD)")),
            Campo("garantia_hasta", _("Garantía hasta (AAAA-MM-DD)")),
            Campo("estado", _("Estado"), (_("En uso"), _("En reserva"), _("En reparación"), _("De baja"))),
            Campo("notas", _("Notas"), multilinea=True),
        )
    if categoria == "medios":
        return (
            Campo("tipo", _("Tipo"), (
                _("Licencia de software"), _("Cuenta o acceso"), _("Servicio"),
                _("Conectividad"), _("Otro"),
            )),
            Campo("proveedor", _("Proveedor")),
            Campo("identificador", _("Identificador (usuario, clave de licencia…)")),
            Campo("caduca", _("Caduca (AAAA-MM-DD)")),
            Campo("coste", _("Coste")),
            Campo("notas", _("Notas"), multilinea=True),
        )
    if categoria == "lugares":
        return (
            Campo("tipo", _("Tipo"), (_("Oficina"), _("Remoto"), _("Coworking"), _("Otro"))),
            Campo("direccion", _("Dirección")),
            Campo("notas", _("Notas"), multilinea=True),
        )
    return ()


# Clave del dato que mejor resume cada categoría en una tarjeta.
_RESUMEN = {
    "equipos": ("marca", "modelo"),
    "medios": ("tipo", "proveedor"),
    "lugares": ("tipo", "direccion"),
}


def resumen(recurso: Recurso) -> str:
    """Texto corto con los datos clave del recurso para mostrarlo en una tarjeta."""
    claves = _RESUMEN.get(recurso.categoria, ())
    return " · ".join(v for c in claves if (v := recurso.detalles.get(c, "").strip()))
