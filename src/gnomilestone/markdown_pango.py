"""Conversor ligero de Markdown a marcado Pango (sin dependencias).

Cubre lo que aparece en descripciones de tareas y de issues de GitHub: títulos, negrita,
cursiva, código en línea y en bloque, enlaces, listas, citas y separadores.
"""

from __future__ import annotations

import functools
import html
import re


@functools.cache
def _familia_mono() -> str | None:
    """Familia de la fuente monoespaciada del sistema (ajuste del escritorio); None si no se
    puede saber. `<tt>` de Pango usa el alias «monospace» de fontconfig, que puede ser otra
    distinta de la que el usuario tiene elegida en su escritorio."""
    try:
        import gi

        gi.require_version("Pango", "1.0")
        from gi.repository import Gio, Pango

        origen = Gio.SettingsSchemaSource.get_default()
        if origen is None:
            return None
        for esquema in ("org.gnome.desktop.interface", "org.cinnamon.desktop.interface"):
            definicion = origen.lookup(esquema, True)
            if definicion is not None and definicion.has_key("monospace-font-name"):
                nombre = Gio.Settings.new(esquema).get_string("monospace-font-name")
                familia = Pango.FontDescription.from_string(nombre).get_family()
                if familia:
                    return familia.split(",")[0].strip()
    except (ImportError, ValueError):
        return None
    return None


def _codigo(texto_escapado: str) -> str:
    """Envuelve texto ya escapado en la fuente monoespaciada del sistema."""
    familia = _familia_mono()
    if familia is None:
        return f"<tt>{texto_escapado}</tt>"
    return f'<span font_family="{html.escape(familia)}">{texto_escapado}</span>'


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
        codigos.append(_codigo(html.escape(m.group(1), quote=False)))
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
                salida.append(_codigo(html.escape(chr(10).join(bloque), quote=False)))
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
        salida.append(_codigo(html.escape(chr(10).join(bloque), quote=False)))
    return "\n".join(salida)


def familia_monoespaciada() -> str | None:
    """Familia monoespaciada elegida en el escritorio (None si no se puede saber)."""
    return _familia_mono()
