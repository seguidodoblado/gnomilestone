"""Conversor ligero de Markdown a marcado Pango (sin dependencias).

Cubre lo que aparece en descripciones de tareas y de issues de GitHub: títulos, negrita,
cursiva, código en línea y en bloque, enlaces, listas, citas y separadores.
"""

from __future__ import annotations

import html
import re

_CODIGO_EN_LINEA = re.compile(r"`([^`\n]+)`")
_ENLACE = re.compile(r"\[([^\]\n]+)\]\(([^)\s]+)\)")
_NEGRITA = re.compile(r"(\*\*|__)(?=\S)(.+?)(?<=\S)\1")
_CURSIVA = re.compile(r"(?<![\w*])\*(?=\S)([^*\n]+?)(?<=\S)\*(?![\w*])|(?<![\w_])_(?=\S)([^_\n]+?)(?<=\S)_(?![\w_])")
_TACHADO = re.compile(r"~~(?=\S)(.+?)(?<=\S)~~")
_TITULO = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_LISTA = re.compile(r"^(\s*)([-*+]|\d+[.)])\s+(.*)$")
_TAREA = re.compile(r"^\[( |x|X)\]\s+(.*)$")
_SEPARADOR = re.compile(r"^\s*([-*_])(\s*\1){2,}\s*$")
_TAMANOS_TITULO = {1: "x-large", 2: "large", 3: "large", 4: "medium", 5: "medium", 6: "medium"}


def _en_linea(texto: str) -> str:
    codigos: list[str] = []

    def _guardar_codigo(m: re.Match[str]) -> str:
        codigos.append(f"<tt>{html.escape(m.group(1), quote=False)}</tt>")
        return f"\x00{len(codigos) - 1}\x00"

    texto = _CODIGO_EN_LINEA.sub(_guardar_codigo, texto)
    texto = html.escape(texto, quote=True)
    texto = _ENLACE.sub(lambda m: f'<a href="{m.group(2)}">{m.group(1)}</a>', texto)
    texto = _NEGRITA.sub(lambda m: f"<b>{m.group(2)}</b>", texto)
    texto = _CURSIVA.sub(lambda m: f"<i>{m.group(1) or m.group(2)}</i>", texto)
    texto = _TACHADO.sub(lambda m: f"<s>{m.group(1)}</s>", texto)
    return re.sub(r"\x00(\d+)\x00", lambda m: codigos[int(m.group(1))], texto)


def markdown_a_pango(texto: str) -> str:
    """Convierte `texto` (Markdown) en marcado Pango válido para `Gtk.Label(use_markup=True)`."""
    salida: list[str] = []
    en_bloque = False
    bloque: list[str] = []
    for linea in texto.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if linea.lstrip().startswith("```"):
            if en_bloque:
                salida.append(f"<tt>{html.escape(chr(10).join(bloque), quote=False)}</tt>")
                bloque = []
            en_bloque = not en_bloque
            continue
        if en_bloque:
            bloque.append(linea)
            continue
        if (m := _TITULO.match(linea)) is not None:
            tamano = _TAMANOS_TITULO[len(m.group(1))]
            salida.append(f'<span size="{tamano}" weight="bold">{_en_linea(m.group(2))}</span>')
        elif _SEPARADOR.match(linea):
            salida.append("─" * 24)
        elif (m := _LISTA.match(linea)) is not None:
            sangria = "    " * (len(m.group(1).expandtabs(4)) // 2)
            marca = "•" if m.group(2) in "-*+" else m.group(2)
            cuerpo = m.group(3)
            if (t := _TAREA.match(cuerpo)) is not None:
                marca = "☑" if t.group(1) != " " else "☐"
                cuerpo = t.group(2)
            salida.append(f"{sangria}{marca} {_en_linea(cuerpo)}")
        elif linea.startswith(">"):
            salida.append(f"<i>▎ {_en_linea(linea.lstrip('> ').strip())}</i>")
        else:
            salida.append(_en_linea(linea))
    if en_bloque:  # bloque sin cerrar: se muestra lo recogido hasta el final
        salida.append(f"<tt>{html.escape(chr(10).join(bloque), quote=False)}</tt>")
    return "\n".join(salida)
