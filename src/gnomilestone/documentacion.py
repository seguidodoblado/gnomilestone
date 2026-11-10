"""Datos derivados de las tareas para las subsecciones de Blueprint (sin GTK)."""

from __future__ import annotations

import re
from dataclasses import dataclass

from gnomilestone.diagrama import Diagrama
from gnomilestone.enlaces import normalizar
from gnomilestone.models import DiagramaDocumentacion, NotaDocumentacion, Tarea


def fecha_completada(tarea: Tarea) -> str | None:
    """Día (AAAA-MM-DD) en que se completó la tarea, o None si no lo está.

    Es su fecha de fin real, que se puede fijar a mano (una tarea insertada con retraso se
    completó cuando se terminó de verdad, no cuando se dio de alta). Solo si falta, se usa
    la de la última modificación, que es cuando llegó al 100 %.
    """
    if tarea.porcentaje_completado < 100:
        return None
    dia = (tarea.fecha_fin_real or tarea.actualizado or "")[:10]
    return dia or None


def historial_realizado(tareas: list[Tarea]) -> list[tuple[str, list[Tarea]]]:
    """Tareas completadas (incluidas las archivadas) agrupadas por el día de su fecha de fin
    real (ver `fecha_completada`), de más antiguo a más reciente."""
    por_dia: dict[str, list[Tarea]] = {}
    for tarea in tareas:
        if (dia := fecha_completada(tarea)) is not None:
            por_dia.setdefault(dia, []).append(tarea)
    return [
        (dia, sorted(grupo, key=lambda t: (t.actualizado, t.id)))
        for dia, grupo in sorted(por_dia.items())
    ]


def hitos_del_proyecto(tareas: list[Tarea]) -> list[Tarea]:
    """Hitos por fecha límite (los que no la tienen, al final)."""
    hitos = [t for t in tareas if t.es_hito]
    return sorted(hitos, key=lambda t: (t.fecha_limite is None, t.fecha_limite or "", t.id))


@dataclass(frozen=True)
class EventoRoadmap:
    tarea: Tarea
    fecha: str  # ISO (AAAA-MM-DD)
    es_hito: bool
    completado: bool


def eventos_roadmap(tareas: list[Tarea]) -> list[EventoRoadmap]:
    """Eventos del Roadmap en orden cronológico: los hitos y las tareas de primer nivel
    que tienen fecha. Se sitúan en su fecha límite (o, si no la tienen, en su inicio)."""
    eventos = []
    for tarea in tareas:
        if not (tarea.es_hito or tarea.padre_id is None):
            continue
        fecha = tarea.fecha_limite or tarea.fecha_inicio
        if not fecha:
            continue
        eventos.append(
            EventoRoadmap(tarea, fecha[:10], tarea.es_hito, tarea.porcentaje_completado >= 100)
        )
    return sorted(eventos, key=lambda e: (e.fecha, e.tarea.id))


@dataclass(frozen=True)
class ResultadoBusqueda:
    tipo: str  # "nota" | "diagrama"
    id: int
    titulo: str
    seccion: str
    subseccion_id: int | None
    extracto: str  # fragmento alrededor de la primera coincidencia
    inicio: int  # posición de la coincidencia dentro del extracto (para resaltarla)
    longitud: int


def buscar(
    consulta: str,
    notas: list[NotaDocumentacion],
    diagramas: list[DiagramaDocumentacion],
    contexto: int = 60,
) -> list[ResultadoBusqueda]:
    """Notas y diagramas que contienen TODAS las palabras de `consulta` (sin distinguir
    mayúsculas ni acentos), con las coincidencias en el título primero."""
    terminos = [t for t in normalizar(consulta).split() if t]
    if not terminos:
        return []
    candidatos = [
        ("nota", n.id, n.titulo, n.seccion, n.subseccion_id, n.contenido) for n in notas
    ] + [
        ("diagrama", d.id, d.titulo, "arquitectura", d.subseccion_id, _texto_diagrama(d))
        for d in diagramas
    ]
    puntuados = []
    for tipo, ident, titulo, seccion, sub_id, cuerpo in candidatos:
        nt, nc = normalizar(titulo), normalizar(cuerpo)
        if not all(t in nt or t in nc for t in terminos):
            continue
        puntos = sum(10 * nt.count(t) + nc.count(t) for t in terminos)
        extracto, inicio, longitud = _fragmento(cuerpo, nc, terminos, contexto)
        puntuados.append(
            (-puntos, titulo.casefold(), ResultadoBusqueda(tipo, ident, titulo, seccion, sub_id, extracto, inicio, longitud))
        )
    return [r for _p, _t, r in sorted(puntuados, key=lambda x: (x[0], x[1]))]


def _texto_diagrama(diagrama: DiagramaDocumentacion) -> str:
    modelo = Diagrama.de_json(diagrama.datos)
    return " · ".join([*(n.texto for n in modelo.nodos), *(a.etiqueta for a in modelo.aristas if a.etiqueta)])


def _fragmento(
    texto: str, normalizado: str, terminos: list[str], contexto: int
) -> tuple[str, int, int]:
    """Fragmento de `texto` alrededor de la primera coincidencia en una sola línea."""
    posiciones = [(normalizado.find(t), t) for t in terminos if t in normalizado]
    if not posiciones:
        return texto[: contexto * 2].replace("\n", " ").strip(), 0, 0
    pos, termino = min(posiciones)
    inicio = max(0, pos - contexto)
    fin = min(len(texto), pos + len(termino) + contexto)
    fragmento = texto[inicio:fin].replace("\n", " ")
    prefijo = "…" if inicio > 0 else ""
    sufijo = "…" if fin < len(texto) else ""
    return prefijo + fragmento + sufijo, len(prefijo) + (pos - inicio), len(termino)


_TITULO_MD = re.compile(r"^(#{1,3})\s+(.*?)\s*#*\s*$")


@dataclass(frozen=True)
class SeccionNota:
    nivel: int | None  # 1-3 si empieza por un título; None en la introducción previa al primero
    titulo: str | None
    markdown: str  # incluye la línea del título


def secciones_por_titulo(contenido: str) -> list[SeccionNota]:
    """Trocea una nota en secciones que empiezan en cada título `#`, `##` o `###` (los `#`
    dentro de bloques de código no cuentan). Sirve para el índice de la vista completa."""
    secciones: list[SeccionNota] = []
    nivel: int | None = None
    titulo: str | None = None
    lineas: list[str] = []
    en_codigo = False

    def cerrar() -> None:
        texto = "\n".join(lineas).strip("\n")
        if texto or titulo is not None:
            secciones.append(SeccionNota(nivel, titulo, texto))

    for linea in contenido.splitlines():
        if linea.lstrip().startswith("```"):
            en_codigo = not en_codigo
        coincidencia = None if en_codigo else _TITULO_MD.match(linea)
        if coincidencia:
            cerrar()
            nivel, titulo, lineas = len(coincidencia.group(1)), coincidencia.group(2), [linea]
        else:
            lineas.append(linea)
    cerrar()
    return secciones


def hijas(notas: list[NotaDocumentacion], padre_id: int | None) -> list[NotaDocumentacion]:
    """Subpáginas directas de `padre_id` (None = las del nivel raíz), en su orden."""
    return [n for n in notas if n.padre_id == padre_id]


def ruta_de(notas: list[NotaDocumentacion], nota_id: int) -> list[NotaDocumentacion]:
    """Antepasados de la nota seguidos de ella misma, de la raíz hacia abajo."""
    por_id = {n.id: n for n in notas}
    ruta: list[NotaDocumentacion] = []
    actual = por_id.get(nota_id)
    while actual is not None and actual not in ruta:
        ruta.append(actual)
        actual = por_id.get(actual.padre_id) if actual.padre_id is not None else None
    return list(reversed(ruta))


def descendientes(notas: list[NotaDocumentacion], nota_id: int) -> set[int]:
    """Ids de todas las subpáginas (directas e indirectas) de la nota."""
    resultado: set[int] = set()
    pendientes = [nota_id]
    while pendientes:
        actual = pendientes.pop()
        for hija in hijas(notas, actual):
            if hija.id not in resultado:
                resultado.add(hija.id)
                pendientes.append(hija.id)
    return resultado


def candidatas_a_padre(
    notas: list[NotaDocumentacion], nota_id: int | None
) -> list[tuple[int, str]]:
    """(id, título sangrado por profundidad) de las notas que pueden ser padre de `nota_id`
    (todas menos ella y sus descendientes), ordenadas como un árbol."""
    excluidas = {nota_id, *descendientes(notas, nota_id)} if nota_id is not None else set()
    resultado: list[tuple[int, str]] = []

    def recorrer(padre_id: int | None, nivel: int, visitadas: frozenset[int]) -> None:
        for nota in hijas(notas, padre_id):
            if nota.id in excluidas or nota.id in visitadas:
                continue
            resultado.append((nota.id, "    " * nivel + (nota.titulo or "…")))
            recorrer(nota.id, nivel + 1, visitadas | {nota.id})

    recorrer(None, 0, frozenset())
    return resultado
