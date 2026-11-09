"""Comparación entre versiones de notas y diagramas (sin GTK)."""

from __future__ import annotations

import difflib

from gnomilestone.diagrama import Diagrama
from gnomilestone.i18n import _


def formatear_fecha(iso: str) -> str:
    """«2026-11-09T14:32:05Z» → «2026-11-09 14:32»."""
    return iso.replace("T", " ").rstrip("Z")[:16]


def diferencias(antiguo: str, nuevo: str) -> list[tuple[str, str]]:
    """Diferencia por líneas de `antiguo` a `nuevo`: lista de (marca, línea) con marca
    «-» (estaba y ya no), «+» (es nueva) o « » (igual)."""
    a, b = antiguo.splitlines(), nuevo.splitlines()
    resultado: list[tuple[str, str]] = []
    for operacion, i1, i2, j1, j2 in difflib.SequenceMatcher(a=a, b=b, autojunk=False).get_opcodes():
        if operacion == "equal":
            resultado.extend((" ", linea) for linea in a[i1:i2])
            continue
        resultado.extend(("-", linea) for linea in a[i1:i2])
        resultado.extend(("+", linea) for linea in b[j1:j2])
    return resultado


def hay_cambios(diff: list[tuple[str, str]]) -> bool:
    return any(marca != " " for marca, _l in diff)


def resumen_diagrama(antiguo: Diagrama, nuevo: Diagrama) -> str:
    """Frase con lo que cambiaría de la versión `antiguo` al diagrama `nuevo`."""
    por_id_antiguo = {n.id: n for n in antiguo.nodos}
    por_id_nuevo = {n.id: n for n in nuevo.nodos}
    quitados = len(por_id_antiguo.keys() - por_id_nuevo.keys())
    anadidos = len(por_id_nuevo.keys() - por_id_antiguo.keys())
    cambiados = sum(
        1
        for ident in por_id_antiguo.keys() & por_id_nuevo.keys()
        if (por_id_antiguo[ident].texto, por_id_antiguo[ident].tipo)
        != (por_id_nuevo[ident].texto, por_id_nuevo[ident].tipo)
    )
    flechas_antiguas = {(a.desde, a.hasta, a.etiqueta) for a in antiguo.aristas}
    flechas_nuevas = {(a.desde, a.hasta, a.etiqueta) for a in nuevo.aristas}
    partes = []
    if anadidos:
        partes.append(_("{n} elementos añadidos").format(n=anadidos))
    if quitados:
        partes.append(_("{n} elementos quitados").format(n=quitados))
    if cambiados:
        partes.append(_("{n} elementos con texto o tipo distinto").format(n=cambiados))
    dif_flechas = len(flechas_antiguas ^ flechas_nuevas)
    if dif_flechas:
        partes.append(_("{n} flechas distintas").format(n=dif_flechas))
    if not partes:
        return _("Sin diferencias de contenido con la versión actual (puede cambiar la posición).")
    return _("Respecto a la versión actual: ") + ", ".join(partes) + "."
