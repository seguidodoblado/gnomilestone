"""Modelo y geometría de los diagramas de flujo (sin GTK): nodos, flechas y su
(de)serialización a JSON, que es como se guardan en la base de datos."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field

TIPOS_NODO = ("inicio", "paso", "decision", "fin")

# (ancho, alto) en unidades del lienzo.
_TAMANOS = {
    "inicio": (150.0, 52.0),
    "fin": (150.0, 52.0),
    "paso": (170.0, 64.0),
    "decision": (190.0, 100.0),
}


def tamano(tipo: str) -> tuple[float, float]:
    return _TAMANOS.get(tipo, _TAMANOS["paso"])


@dataclass
class Nodo:
    id: int
    tipo: str
    texto: str
    x: float  # centro
    y: float
    ancho: float = 0.0  # 0 = el de su tipo
    alto: float = 0.0  # 0 = el de su tipo

    @property
    def w(self) -> float:
        return self.ancho or tamano(self.tipo)[0]

    @property
    def h(self) -> float:
        return self.alto or tamano(self.tipo)[1]


ESTILOS_ARISTA = ("solida", "discontinua", "gruesa")


@dataclass
class Arista:
    desde: int
    hasta: int
    etiqueta: str = ""
    estilo: str = "solida"  # una de ESTILOS_ARISTA
    punta: bool = True  # con punta de flecha en `hasta`


@dataclass
class Diagrama:
    nodos: list[Nodo] = field(default_factory=list)
    aristas: list[Arista] = field(default_factory=list)

    # -- (De)serialización --------------------------------------------------

    def a_json(self) -> str:
        return json.dumps(
            {
                "nodos": [vars(n) for n in self.nodos],
                "aristas": [vars(a) for a in self.aristas],
            },
            ensure_ascii=False,
            sort_keys=True,
        )

    @classmethod
    def de_json(cls, texto: str) -> Diagrama:
        try:
            datos = json.loads(texto or "{}")
            nodos = [
                Nodo(
                    int(n["id"]),
                    str(n["tipo"]),
                    str(n.get("texto", "")),
                    float(n["x"]),
                    float(n["y"]),
                    float(n.get("ancho", 0.0)),
                    float(n.get("alto", 0.0)),
                )
                for n in datos.get("nodos", [])
            ]
            ids = {n.id for n in nodos}
            aristas = [
                Arista(
                    int(a["desde"]),
                    int(a["hasta"]),
                    str(a.get("etiqueta", "")),
                    str(a.get("estilo", "solida")),
                    bool(a.get("punta", True)),
                )
                for a in datos.get("aristas", [])
                if int(a["desde"]) in ids and int(a["hasta"]) in ids
            ]
        except (ValueError, KeyError, TypeError, AttributeError):
            return cls()  # datos corruptos: diagrama vacío en vez de romper la vista
        return cls(nodos, aristas)

    # -- Edición ------------------------------------------------------------

    def nodo(self, nodo_id: int) -> Nodo | None:
        return next((n for n in self.nodos if n.id == nodo_id), None)

    def nuevo_nodo(self, tipo: str, texto: str, x: float, y: float) -> Nodo:
        nodo = Nodo(max((n.id for n in self.nodos), default=0) + 1, tipo, texto, x, y)
        self.nodos.append(nodo)
        return nodo

    def eliminar_nodo(self, nodo_id: int) -> None:
        self.nodos = [n for n in self.nodos if n.id != nodo_id]
        self.aristas = [a for a in self.aristas if nodo_id not in (a.desde, a.hasta)]

    def conectar(
        self,
        desde: int,
        hasta: int,
        etiqueta: str = "",
        estilo: str = "solida",
        punta: bool = True,
    ) -> Arista | None:
        """Crea la flecha `desde → hasta`; None si es un bucle o ya existe."""
        if desde == hasta or self.nodo(desde) is None or self.nodo(hasta) is None:
            return None
        if any(a.desde == desde and a.hasta == hasta for a in self.aristas):
            return None
        arista = Arista(desde, hasta, etiqueta, estilo, punta)
        self.aristas.append(arista)
        return arista

    # -- Geometría ----------------------------------------------------------

    def nodo_en(self, x: float, y: float) -> Nodo | None:
        """Nodo bajo el punto (el último dibujado, es decir, el de encima)."""
        for nodo in reversed(self.nodos):
            dx, dy = abs(x - nodo.x), abs(y - nodo.y)
            if nodo.tipo == "decision":
                if dx / (nodo.w / 2) + dy / (nodo.h / 2) <= 1:
                    return nodo
            elif dx <= nodo.w / 2 and dy <= nodo.h / 2:
                return nodo
        return None

    def extremos(self, arista: Arista) -> tuple[tuple[float, float], tuple[float, float]] | None:
        a, b = self.nodo(arista.desde), self.nodo(arista.hasta)
        if a is None or b is None:
            return None
        return punto_borde(a, b.x, b.y), punto_borde(b, a.x, a.y)

    def arista_en(self, x: float, y: float, tolerancia: float) -> Arista | None:
        for arista in reversed(self.aristas):
            extremos = self.extremos(arista)
            if extremos and _distancia_a_segmento(x, y, *extremos[0], *extremos[1]) <= tolerancia:
                return arista
        return None

    def limites(self) -> tuple[float, float, float, float] | None:
        """(min_x, min_y, max_x, max_y) que contiene todos los nodos; None si no hay."""
        if not self.nodos:
            return None
        return (
            min(n.x - n.w / 2 for n in self.nodos),
            min(n.y - n.h / 2 for n in self.nodos),
            max(n.x + n.w / 2 for n in self.nodos),
            max(n.y + n.h / 2 for n in self.nodos),
        )


def punto_borde(nodo: Nodo, hacia_x: float, hacia_y: float) -> tuple[float, float]:
    """Punto del borde del nodo en la recta que va de su centro a (hacia_x, hacia_y)."""
    dx, dy = hacia_x - nodo.x, hacia_y - nodo.y
    if dx == 0 and dy == 0:
        return nodo.x, nodo.y
    mitad_w, mitad_h = nodo.w / 2, nodo.h / 2
    if nodo.tipo == "decision":
        t = 1 / (abs(dx) / mitad_w + abs(dy) / mitad_h)
    else:
        t = min(
            mitad_w / abs(dx) if dx else math.inf,
            mitad_h / abs(dy) if dy else math.inf,
        )
    return nodo.x + dx * t, nodo.y + dy * t


def _distancia_a_segmento(
    px: float, py: float, ax: float, ay: float, bx: float, by: float
) -> float:
    largo2 = (bx - ax) ** 2 + (by - ay) ** 2
    if largo2 == 0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * (bx - ax) + (py - ay) * (by - ay)) / largo2))
    return math.hypot(px - (ax + t * (bx - ax)), py - (ay + t * (by - ay)))
