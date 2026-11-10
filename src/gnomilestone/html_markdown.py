"""Convierte el HTML que llevan muchos README (cabeceras centradas, badges, imágenes) a
Markdown, y las rutas relativas del repositorio a direcciones absolutas de GitHub.

Sin GTK ni dependencias. El código (bloques con ``` y trozos entre `) no se toca. Lo que no se
puede expresar en Markdown (alineación, tamaños) se pierde; el contenido se conserva.
"""

from __future__ import annotations

import html
import re
from html.parser import HTMLParser
from urllib.parse import quote, urljoin

_ETIQUETA_HTML = re.compile(r"<\s*/?\s*[a-zA-Z!]")
_VALLA = re.compile(r"^\s*(`{3,}|~{3,})")
_CODIGO_EN_LINEA = re.compile(r"`[^`\n]+`")
_FICHA = re.compile(r"\x06([BI])(\d+)\x07")
_IMAGEN_MD = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)((?:\s+\"[^\"]*\")?)\)")
_ENLACE_MD = re.compile(r"(?<!!)\[([^\]]+)\]\(([^)\s]+)((?:\s+\"[^\"]*\")?)\)")
_FICHA_IMAGEN = re.compile(r"\x08(\d+)\x08")

_BLOQUES = {
    "p", "div", "center", "section", "article", "header", "footer", "main", "nav", "aside",
    "figure", "figcaption", "details", "blockquote", "address",
}
_VACIAS = {"img", "br", "hr", "source", "input", "meta", "link", "wbr", "area", "col", "base"}
_DESCARTAR = {"script", "style", "head", "title", "svg", "template", "noscript"}
_PASAN = {"span", "font", "sup", "sub", "u", "abbr", "small", "big", "mark", "label", "picture",
          "thead", "tbody", "tfoot", "caption", "dl", "dd", "dt", "html", "body", "ins", "cite",
          "q", "time", "var", "samp", "bdi", "bdo"}


def _resolver(destino: str, raiz: str, carpeta: str) -> str:
    """Dirección absoluta de un destino relativo; los absolutos, anclas y mailto no cambian."""
    destino = destino.strip()
    if not destino or destino.startswith(("#", "mailto:", "tel:", "data:", "//")) or re.match(
        r"^[a-zA-Z][a-zA-Z0-9+.-]*:", destino
    ):
        return destino
    if destino.startswith("/"):
        absoluta = raiz + quote(destino.lstrip("/"), safe="/%#?=&:@")
    else:
        absoluta = urljoin(raiz + carpeta, quote(destino, safe="/%#?=&:@.-_~"))
    return absoluta


class _Marco:
    __slots__ = ("atributos", "etiqueta", "partes")

    def __init__(self, etiqueta: str, atributos: dict[str, str]) -> None:
        self.etiqueta = etiqueta
        self.atributos = atributos
        self.partes: list[str] = []


class _Conversor(HTMLParser):
    def __init__(self, base: tuple[str, str] | None, carpeta: str) -> None:
        super().__init__(convert_charrefs=False)
        self._raiz_imagenes = self._raiz_enlaces = ""
        if base is not None:
            propietario, repo = base
            self._raiz_imagenes = f"https://github.com/{propietario}/{repo}/raw/HEAD/"
            self._raiz_enlaces = f"https://github.com/{propietario}/{repo}/blob/HEAD/"
        self._carpeta = carpeta
        self._raiz = _Marco("", {})
        self._pila: list[_Marco] = [self._raiz]
        self._en_pre = 0

    # -- utilidades ---------------------------------------------------------

    def _destino(self, valor: str, imagen: bool) -> str:
        raiz = self._raiz_imagenes if imagen else self._raiz_enlaces
        return _resolver(valor, raiz, self._carpeta) if raiz else valor.strip()

    def _emitir(self, texto: str) -> None:
        self._pila[-1].partes.append(texto)

    @property
    def _profundidad(self) -> int:
        return len(self._pila) - 1

    # -- eventos del analizador ---------------------------------------------

    def handle_starttag(self, etiqueta: str, atributos) -> None:
        atributos = {k: (v or "") for k, v in atributos}
        if etiqueta in _VACIAS:
            self._emitir(self._vacia(etiqueta, atributos))
            return
        if etiqueta == "pre":
            self._en_pre += 1
        self._pila.append(_Marco(etiqueta, atributos))

    def handle_startendtag(self, etiqueta: str, atributos) -> None:
        atributos = {k: (v or "") for k, v in atributos}
        if etiqueta in _VACIAS:
            self._emitir(self._vacia(etiqueta, atributos))
        # Una etiqueta de apertura autocerrada (<div/>) no tiene contenido: se ignora.

    def handle_endtag(self, etiqueta: str) -> None:
        if etiqueta in _VACIAS or all(m.etiqueta != etiqueta for m in self._pila[1:]):
            return
        while len(self._pila) > 1:
            marco = self._pila.pop()
            if marco.etiqueta == "pre":
                self._en_pre -= 1
            self._emitir(self._cerrar(marco))
            if marco.etiqueta == etiqueta:
                break

    def handle_data(self, datos: str) -> None:
        if self._profundidad and not self._en_pre:
            datos = re.sub(r"\s+", " ", datos)
            datos = _FICHA.sub(lambda m: f"\n\n{m.group(0)}\n\n" if m.group(1) == "B" else m.group(0), datos)
        self._emitir(datos)

    def handle_entityref(self, nombre: str) -> None:
        self._emitir(html.unescape(f"&{nombre};"))

    def handle_charref(self, nombre: str) -> None:
        self._emitir(html.unescape(f"&#{nombre};"))

    def handle_comment(self, datos: str) -> None:
        pass

    def handle_decl(self, decl: str) -> None:
        pass

    def unknown_decl(self, datos: str) -> None:
        pass

    # -- generación de Markdown --------------------------------------------

    def _vacia(self, etiqueta: str, atributos: dict[str, str]) -> str:
        if etiqueta == "br":
            return "  \n"
        if etiqueta == "hr":
            return "\n\n---\n\n"
        if etiqueta == "img":
            alt = re.sub(r"\s+", " ", html.unescape(atributos.get("alt", ""))).strip().replace("]", ")")
            origen = atributos.get("src", "").strip()
            if not origen:
                return alt
            return f"![{alt}]({self._destino(origen, imagen=True)})"
        return ""

    @staticmethod
    def _envolver(interior: str, marca: str) -> str:
        sin_bordes = interior.strip()
        if not sin_bordes:
            return interior
        inicio = " " if interior[:1].isspace() else ""
        fin = " " if interior[-1:].isspace() else ""
        return f"{inicio}{marca}{sin_bordes}{marca}{fin}"

    def _cerrar(self, marco: _Marco) -> str:
        etiqueta, interior = marco.etiqueta, "".join(marco.partes)
        if etiqueta in _DESCARTAR:
            return ""
        if etiqueta in _BLOQUES:
            cuerpo = interior.strip()
            return f"\n\n{cuerpo}\n\n" if cuerpo else ""
        if re.fullmatch(r"h[1-6]", etiqueta):
            titulo = re.sub(r"\s+", " ", interior).strip()
            return f"\n\n{'#' * int(etiqueta[1])} {titulo}\n\n" if titulo else ""
        if etiqueta == "a":
            texto = interior.strip()
            destino = marco.atributos.get("href", "").strip()
            if not destino or destino.lower().startswith("javascript:"):
                return interior
            if not texto:
                return ""
            return f"[{texto}]({self._destino(destino, imagen=False)})"
        if etiqueta in ("b", "strong"):
            return self._envolver(interior, "**")
        if etiqueta in ("i", "em"):
            return self._envolver(interior, "*")
        if etiqueta in ("s", "del", "strike"):
            return self._envolver(interior, "~~")
        if etiqueta in ("code", "kbd", "tt"):
            if self._en_pre:
                return interior
            return self._envolver(interior.replace("`", "'"), "`")
        if etiqueta == "pre":
            cuerpo = interior.strip("\n")
            valla = "```"
            while valla in cuerpo:
                valla += "`"
            return f"\n\n{valla}\n{cuerpo}\n{valla}\n\n"
        if etiqueta in ("ul", "ol"):
            return self._lista(etiqueta, interior)
        if etiqueta == "li":
            return "\n\x01" + re.sub(r"\n{2,}", "\n", interior.strip())
        if etiqueta == "summary":
            titulo = re.sub(r"\s+", " ", interior).strip()
            return f"\n\n**{titulo}**\n\n" if titulo else ""
        if etiqueta in ("td", "th"):
            celda = re.sub(r"\s+", " ", interior).strip().replace("|", "\\|")
            return f"\x02{celda}\x03"
        if etiqueta == "tr":
            return f"\x04{interior}\x05"
        if etiqueta == "table":
            return self._tabla(interior)
        # span, font, sup, unknown...: se conserva el contenido sin la etiqueta.
        return interior

    @staticmethod
    def _lista(etiqueta: str, interior: str) -> str:
        contador = 0

        def marca(_m: re.Match[str]) -> str:
            nonlocal contador
            contador += 1
            return f"{contador}. " if etiqueta == "ol" else "- "

        cuerpo = re.sub(r"\x01", marca, interior).strip("\n")
        return f"\n\n{cuerpo}\n\n" if cuerpo else ""

    @staticmethod
    def _tabla(interior: str) -> str:
        filas = [re.findall(r"\x02(.*?)\x03", fila, re.DOTALL) for fila in re.findall(r"\x04(.*?)\x05", interior, re.DOTALL)]
        filas = [fila for fila in filas if fila]
        if not filas:
            return re.sub(r"[\x02-\x05]", " ", interior)
        ancho = max(len(f) for f in filas)
        filas = [f + [""] * (ancho - len(f)) for f in filas]
        lineas = ["| " + " | ".join(filas[0]) + " |", "| " + " | ".join(["---"] * ancho) + " |"]
        lineas += ["| " + " | ".join(f) + " |" for f in filas[1:]]
        return "\n\n" + "\n".join(lineas) + "\n\n"

    def resultado(self) -> str:
        self.close()
        while len(self._pila) > 1:  # etiquetas sin cerrar: se cierran al final
            marco = self._pila.pop()
            if marco.etiqueta == "pre":
                self._en_pre -= 1
            self._emitir(self._cerrar(marco))
        return "".join(self._raiz.partes)


def _proteger_codigo(texto: str) -> tuple[str, list[str]]:
    """Cambia los bloques de código y el código en línea por fichas para no convertirlos."""
    guardados: list[str] = []
    salida: list[str] = []
    bloque: list[str] = []
    valla: str | None = None
    for linea in texto.split("\n"):
        if valla is None:
            if (m := _VALLA.match(linea)) is not None:
                valla = m.group(1)
                bloque = [linea]
                continue
            salida.append(_CODIGO_EN_LINEA.sub(lambda c: _ficha(guardados, "I", c.group(0)), linea))
            continue
        bloque.append(linea)
        cierre = _VALLA.match(linea)
        if cierre and cierre.group(1)[0] == valla[0] and len(cierre.group(1)) >= len(valla) and linea.strip() == cierre.group(1):
            salida.append(_ficha(guardados, "B", "\n".join(bloque)))
            valla, bloque = None, []
    if valla is not None:  # bloque sin cerrar: se deja como estaba
        salida.append(_ficha(guardados, "B", "\n".join(bloque)))
    return "\n".join(salida), guardados


def _ficha(guardados: list[str], tipo: str, contenido: str) -> str:
    guardados.append(contenido)
    return f"\x06{tipo}{len(guardados) - 1}\x07"


def _restaurar_codigo(texto: str, guardados: list[str]) -> str:
    return _FICHA.sub(lambda m: guardados[int(m.group(2))], texto)


def _absolutizar_markdown(texto: str, base: tuple[str, str], carpeta: str) -> str:
    propietario, repo = base
    raiz_img = f"https://github.com/{propietario}/{repo}/raw/HEAD/"
    raiz_enl = f"https://github.com/{propietario}/{repo}/blob/HEAD/"
    imagenes: list[str] = []

    def imagen(m: re.Match[str]) -> str:
        imagenes.append(f"![{m.group(1)}]({_resolver(m.group(2), raiz_img, carpeta)}{m.group(3)})")
        return f"\x08{len(imagenes) - 1}\x08"

    texto = _IMAGEN_MD.sub(imagen, texto)
    texto = _ENLACE_MD.sub(
        lambda m: f"[{m.group(1)}]({_resolver(m.group(2), raiz_enl, carpeta)}{m.group(3)})", texto
    )
    return _FICHA_IMAGEN.sub(lambda m: imagenes[int(m.group(1))], texto)


def html_a_markdown(texto: str, base: tuple[str, str] | None = None, ruta: str = "") -> str:
    """Markdown limpio a partir de un README con HTML.

    `base` = (propietario, repositorio) para convertir las rutas relativas a direcciones de
    GitHub; `ruta` es la del fichero en el repositorio (para resolver «../» y «./»).
    """
    carpeta = ruta.rsplit("/", 1)[0] + "/" if "/" in ruta else ""
    protegido, guardados = _proteger_codigo(texto.replace("\r\n", "\n").replace("\r", "\n"))
    if _ETIQUETA_HTML.search(protegido):
        conversor = _Conversor(base, carpeta)
        conversor.feed(protegido)
        protegido = conversor.resultado()
    else:
        protegido = html.unescape(protegido) if re.search(r"&(?:[a-zA-Z]+|#\d+|#x[0-9a-fA-F]+);", protegido) else protegido
    if base is not None:
        protegido = _absolutizar_markdown(protegido, base, carpeta)
    protegido = re.sub(r"[ \t]+\n", lambda m: "  \n" if m.group(0).count(" ") == 2 else "\n", protegido)
    protegido = re.sub(r"\n{3,}", "\n\n", protegido).strip("\n")
    return _restaurar_codigo(protegido, guardados) + "\n"
