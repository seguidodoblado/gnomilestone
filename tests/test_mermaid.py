from itertools import pairwise

import pytest

from gnomilestone.diagrama import Diagrama
from gnomilestone.diagrama_layout import colocar_por_capas
from gnomilestone.mermaid import MermaidNoSoportado, interpretar


def nodos(d: Diagrama) -> dict[str, tuple[str, str]]:
    return {n.texto: (n.tipo, n.id) for n in d.nodos}  # type: ignore[misc]


def textos(d: Diagrama, estilo=False):
    por_id = {n.id: n.texto for n in d.nodos}
    return [
        (por_id[a.desde], por_id[a.hasta], a.etiqueta) + ((a.estilo, a.punta) if estilo else ())
        for a in d.aristas
    ]


def test_flujo_basico_con_formas_y_cadena():
    d = interpretar("graph TD\n  A[Inicio] --> B{¿Ok?}\n  B -->|sí| C([Fin])\n  B -->|no| D(Reintentar)")
    assert {n.texto: n.tipo for n in d.nodos} == {
        "Inicio": "paso", "¿Ok?": "decision", "Fin": "inicio", "Reintentar": "paso",
    }
    assert textos(d) == [("Inicio", "¿Ok?", ""), ("¿Ok?", "Fin", "sí"), ("¿Ok?", "Reintentar", "no")]


def test_cadenas_y_grupos_con_ampersand():
    d = interpretar("flowchart LR\n A --> B --> C\n D & E --> F")
    assert textos(d) == [("A", "B", ""), ("B", "C", ""), ("D", "F", ""), ("E", "F", "")]


def test_estilos_de_flecha_y_texto_en_medio():
    d = interpretar("graph TD\n A -.-> B\n B ==> C\n C --- D\n D -- texto --> E\n E -. punteada .-> F")
    assert textos(d, estilo=True) == [
        ("A", "B", "", "discontinua", True),
        ("B", "C", "", "gruesa", True),
        ("C", "D", "", "solida", False),
        ("D", "E", "texto", "solida", True),
        ("E", "F", "punteada", "discontinua", True),
    ]


def test_texto_entrecomillado_con_simbolos_y_saltos_de_linea():
    d = interpretar('graph TD\n A["Texto (con) [símbolos] <br/> y salto"] --> B')
    assert d.nodos[0].texto == "Texto (con) [símbolos] \n y salto"
    assert len(d.aristas) == 1


def test_comentarios_estilos_y_subgrafos_se_ignoran_pero_sus_nodos_si_cuentan():
    d = interpretar(
        "graph LR %% comentario\n"
        "  subgraph Grupo\n    A --> B\n  end\n"
        "  style A fill:#f9f\n  classDef x fill:#eee\n  class B x\n  B --> C; C --> D"
    )
    assert sorted(n.texto for n in d.nodos) == ["A", "B", "C", "D"]
    assert len(d.aristas) == 3


def test_redefinir_un_nodo_cambia_su_forma_y_texto_sin_duplicarlo():
    d = interpretar("graph TD\n A --> B\n B{Decide}")
    assert len(d.nodos) == 2
    assert {n.texto: n.tipo for n in d.nodos}["Decide"] == "decision"


def test_bucles_y_duplicados_no_rompen():
    d = interpretar("graph TD\n A --> A\n A --> B\n A --> B")
    assert len(d.aristas) == 1


@pytest.mark.parametrize("texto", ["sequenceDiagram\n A->>B: hola", "classDiagram\n class A", "pie\n a: 1", ""])
def test_otros_tipos_de_diagrama_no_estan_soportados(texto):
    with pytest.raises(MermaidNoSoportado):
        interpretar(texto)


def test_la_direccion_por_defecto_es_de_arriba_a_abajo():
    d = interpretar("graph\n A --> B --> C")
    ys = [n.y for n in sorted(d.nodos, key=lambda n: n.texto)]
    assert ys == sorted(ys) and len(set(ys)) == 3
    assert len({n.x for n in d.nodos}) == 1  # en una sola columna


def test_direccion_lr_coloca_de_izquierda_a_derecha_y_rl_al_reves():
    xs = lambda t: [n.x for n in sorted(interpretar(t).nodos, key=lambda n: n.texto)]
    lr, rl = xs("graph LR\n A --> B --> C"), xs("graph RL\n A --> B --> C")
    assert lr == sorted(lr) and rl == sorted(rl, reverse=True)
    bt = [n.y for n in sorted(interpretar("graph BT\n A --> B --> C").nodos, key=lambda n: n.texto)]
    assert bt == sorted(bt, reverse=True)


def test_los_nodos_de_una_misma_capa_no_se_solapan():
    d = interpretar("graph TD\n R --> A\n R --> B\n R --> C\n R --> D")
    fila = sorted((n for n in d.nodos if n.texto in "ABCD"), key=lambda n: n.x)
    for izq, der in pairwise(fila):
        assert der.x - izq.x >= (izq.w + der.w) / 2
    raiz = next(n for n in d.nodos if n.texto == "R")
    assert min(n.x for n in fila) < raiz.x < max(n.x for n in fila)  # el padre queda centrado


def test_un_ciclo_se_coloca_sin_bucle_infinito():
    d = interpretar("graph TD\n A --> B --> C --> A")
    ys = {n.texto: n.y for n in d.nodos}
    assert ys["A"] < ys["B"] < ys["C"]


def test_el_tamano_crece_con_el_texto():
    d = interpretar('graph TD\n A[Corto] --> B["Un texto bastante más largo que el otro"]')
    corto, largo = d.nodos
    assert largo.w > corto.w


def test_colocar_un_diagrama_vacio_no_falla():
    colocar_por_capas(Diagrama())
