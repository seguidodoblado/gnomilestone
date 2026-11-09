"""Colocación automática de un diagrama por capas (sin GTK): los nodos se reparten en
capas según el sentido de las flechas y se ordenan dentro de cada capa para reducir cruces."""

from __future__ import annotations

from gnomilestone.diagrama import Diagrama

DIRECCIONES = ("TD", "TB", "BT", "LR", "RL")


def colocar_por_capas(
    diagrama: Diagrama, direccion: str = "TD", sep_capa: float = 70, sep_nodo: float = 50
) -> None:
    """Asigna `x`/`y` a los nodos. `direccion`: TD/TB (de arriba abajo), BT (de abajo arriba),
    LR (de izquierda a derecha) o RL. Las flechas que cierran ciclos no cuentan para las capas."""
    if not diagrama.nodos:
        return
    ids = [n.id for n in diagrama.nodos]
    sucesores, predecesores = _sin_ciclos(diagrama, ids)
    capa = _asignar_capas(ids, sucesores, predecesores)
    capas = _ordenar(ids, capa, sucesores, predecesores)

    horizontal = direccion in ("LR", "RL")
    por_id = {n.id: n for n in diagrama.nodos}

    def extension_principal(ident: int) -> float:
        return por_id[ident].w if horizontal else por_id[ident].h

    def extension_cruzada(ident: int) -> float:
        return por_id[ident].h if horizontal else por_id[ident].w

    # Eje principal (el de las capas): una posición por capa.
    principal: dict[int, float] = {}
    cursor = 0.0
    for fila in capas:
        grosor = max(extension_principal(i) for i in fila)
        centro = cursor + grosor / 2
        for ident in fila:
            principal[ident] = centro
        cursor += grosor + sep_capa

    cruzada = _repartir_cruzado(capas, sucesores, predecesores, extension_cruzada, sep_nodo)

    for ident, nodo in por_id.items():
        p, c = principal[ident], cruzada[ident]
        if direccion in ("BT", "RL"):
            p = cursor - sep_capa - p
        nodo.x, nodo.y = (p, c) if horizontal else (c, p)


def _sin_ciclos(
    diagrama: Diagrama, ids: list[int]
) -> tuple[dict[int, list[int]], dict[int, list[int]]]:
    """Sucesores y predecesores tras invertir las flechas que cierran un ciclo (DFS)."""
    salientes: dict[int, list[int]] = {i: [] for i in ids}
    for arista in diagrama.aristas:
        salientes[arista.desde].append(arista.hasta)
    estado = dict.fromkeys(ids, 0)  # 0 sin visitar, 1 en curso, 2 terminado
    invertidas: set[tuple[int, int]] = set()
    for raiz in ids:
        if estado[raiz]:
            continue
        pila = [(raiz, iter(salientes[raiz]))]
        estado[raiz] = 1
        while pila:
            actual, vecinos = pila[-1]
            for vecino in vecinos:
                if estado[vecino] == 1:
                    invertidas.add((actual, vecino))  # vuelve a un antepasado: cierra un ciclo
                elif estado[vecino] == 0:
                    estado[vecino] = 1
                    pila.append((vecino, iter(salientes[vecino])))
                    break
            else:
                estado[actual] = 2
                pila.pop()
    sucesores: dict[int, list[int]] = {i: [] for i in ids}
    predecesores: dict[int, list[int]] = {i: [] for i in ids}
    for arista in diagrama.aristas:
        origen, destino = arista.desde, arista.hasta
        if (origen, destino) in invertidas:
            origen, destino = destino, origen
        if destino not in sucesores[origen]:
            sucesores[origen].append(destino)
            predecesores[destino].append(origen)
    return sucesores, predecesores


def _asignar_capas(
    ids: list[int], sucesores: dict[int, list[int]], predecesores: dict[int, list[int]]
) -> dict[int, int]:
    """Capa de cada nodo: la longitud del camino más largo que llega hasta él."""
    pendientes = {i: len(predecesores[i]) for i in ids}
    cola = [i for i in ids if pendientes[i] == 0]
    capa = dict.fromkeys(ids, 0)
    indice = 0
    while indice < len(cola):
        actual = cola[indice]
        indice += 1
        for siguiente in sucesores[actual]:
            capa[siguiente] = max(capa[siguiente], capa[actual] + 1)
            pendientes[siguiente] -= 1
            if pendientes[siguiente] == 0:
                cola.append(siguiente)
    return capa


def _ordenar(
    ids: list[int],
    capa: dict[int, int],
    sucesores: dict[int, list[int]],
    predecesores: dict[int, list[int]],
) -> list[list[int]]:
    """Orden dentro de cada capa por el método del baricentro (varias pasadas)."""
    total = max(capa.values()) + 1
    capas: list[list[int]] = [[] for _ in range(total)]
    for ident in ids:
        capas[capa[ident]].append(ident)

    def posiciones() -> dict[int, int]:
        return {ident: k for fila in capas for k, ident in enumerate(fila)}

    for _ in range(4):
        for bajando in (True, False):
            rango = range(1, total) if bajando else range(total - 2, -1, -1)
            for indice in rango:
                pos = posiciones()
                vecinos = predecesores if bajando else sucesores

                def baricentro(ident: int, pos=pos, vecinos=vecinos) -> float:
                    cercanos = [pos[v] for v in vecinos[ident] if v in pos]
                    return sum(cercanos) / len(cercanos) if cercanos else pos[ident]

                capas[indice].sort(key=baricentro)  # estable: empates conservan su orden
    return capas


def _repartir_cruzado(
    capas: list[list[int]],
    sucesores: dict[int, list[int]],
    predecesores: dict[int, list[int]],
    extension,
    separacion: float,
) -> dict[int, float]:
    """Posición en el eje cruzado: cada nodo tiende a quedar a la altura de sus vecinos sin
    solaparse con los de su capa."""
    cruzada: dict[int, float] = {}
    for fila in capas:  # inicio: cada capa centrada en 0
        largo = sum(extension(i) for i in fila) + separacion * (len(fila) - 1)
        cursor = -largo / 2
        for ident in fila:
            cruzada[ident] = cursor + extension(ident) / 2
            cursor += extension(ident) + separacion
    for _ in range(6):
        for bajando in (True, False):
            orden = range(len(capas)) if bajando else range(len(capas) - 1, -1, -1)
            vecinos = predecesores if bajando else sucesores
            for indice in orden:
                fila = capas[indice]
                deseado = []
                for ident in fila:
                    cercanos = [cruzada[v] for v in vecinos[ident]]
                    deseado.append(sum(cercanos) / len(cercanos) if cercanos else cruzada[ident])
                _sin_solape(fila, deseado, extension, separacion, cruzada)
    return cruzada


def _sin_solape(
    fila: list[int], deseado: list[float], extension, separacion: float, cruzada: dict[int, float]
) -> None:
    """Coloca la fila lo más cerca posible de lo deseado, en orden y con separación mínima."""
    posiciones = list(deseado)
    for k in range(1, len(fila)):
        minimo = posiciones[k - 1] + (extension(fila[k - 1]) + extension(fila[k])) / 2 + separacion
        posiciones[k] = max(posiciones[k], minimo)
    desvio = sum(d - p for d, p in zip(deseado, posiciones, strict=True)) / len(fila)
    for ident, posicion in zip(fila, posiciones, strict=True):
        cruzada[ident] = posicion + desvio
