from __future__ import annotations

import gi

gi.require_version("Gdk", "4.0")
gi.require_version("Gtk", "4.0")
from gi.repository import Gdk, GLib, Gtk, Pango

from gnomilestone.codigo import Codigo, colorear, nombre_lenguaje
from gnomilestone.i18n import _
from gnomilestone.markdown_pango import familia_monoespaciada

# Colores por categoría de código (ver codigo.py) para tema oscuro y claro.
_PALETAS = {
    True: {
        "comentario": "#6b7280",
        "cadena": "#34d399",
        "numero": "#fb923c",
        "palabra_clave": "#f472b6",
        "definicion": "#7dd3fc",
        "interno": "#2dd4bf",
        "operador": "#cbd5e1",
    },
    False: {
        "comentario": "#8a8f98",
        "cadena": "#0a8f5e",
        "numero": "#d9480f",
        "palabra_clave": "#d6336c",
        "definicion": "#1c7ed6",
        "interno": "#0c8599",
        "operador": "#495057",
    },
}
_css_aplicado = False


def _asegurar_css() -> None:
    global _css_aplicado
    if _css_aplicado:
        return
    proveedor = Gtk.CssProvider()
    proveedor.load_from_string(
        ".gnomilestone-codigo { background-color: alpha(@theme_fg_color, 0.07);"
        " border-radius: 10px; border-left: 4px solid #3b82c4; }\n"
        ".gnomilestone-codigo-cabecera { background-color: alpha(@theme_fg_color, 0.05);"
        " border-radius: 8px 8px 0 0; padding: 4px 10px; }\n"
    )
    Gtk.StyleContext.add_provider_for_display(
        Gdk.Display.get_default(), proveedor, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
    )
    _css_aplicado = True


def _tema_oscuro() -> bool:
    ajustes = Gtk.Settings.get_default()
    if ajustes is None:
        return True
    return bool(
        ajustes.get_property("gtk-application-prefer-dark-theme")
        or "dark" in (ajustes.get_property("gtk-theme-name") or "").lower()
    )


def _marcar_linea(linea: list[tuple[str, str]], paleta: dict[str, str]) -> str:
    partes = []
    for categoria, texto in linea:
        escapado = GLib.markup_escape_text(texto)
        color = paleta.get(categoria)
        partes.append(f'<span foreground="{color}">{escapado}</span>' if color else escapado)
    return "".join(partes)


def cuerpo_de_codigo(bloque: Codigo, compacto: bool = False) -> Gtk.Widget:
    """Cuerpo de un bloque de código: líneas numeradas y coloreadas, con scroll horizontal."""
    _asegurar_css()
    lineas = colorear(bloque.codigo, bloque.lenguaje)
    paleta = _PALETAS[_tema_oscuro()]
    familia = familia_monoespaciada() or "monospace"
    marcado = "\n".join(_marcar_linea(linea, paleta) for linea in lineas)
    numeros = "\n".join(str(i) for i in range(1, len(lineas) + 1))
    fuente = f'font_family="{GLib.markup_escape_text(familia)}"'

    etiqueta_numeros = Gtk.Label(xalign=1, yalign=0, use_markup=True, margin_end=14)
    etiqueta_numeros.set_markup(f'<span {fuente} alpha="45%">{numeros}</span>')
    etiqueta_codigo = Gtk.Label(xalign=0, yalign=0, use_markup=True, selectable=not compacto)
    etiqueta_codigo.set_focusable(False)
    etiqueta_codigo.set_markup(f"<span {fuente}>{marcado}</span>")
    margen_v, margen_h = (6, 10) if compacto else (12, 14)
    cuerpo = Gtk.Box(
        margin_top=margen_v, margin_bottom=margen_v, margin_start=margen_h, margin_end=margen_h
    )
    cuerpo.append(etiqueta_numeros)
    cuerpo.append(etiqueta_codigo)
    desplazable = Gtk.ScrolledWindow(
        hscrollbar_policy=Gtk.PolicyType.AUTOMATIC,
        vscrollbar_policy=Gtk.PolicyType.NEVER,
        propagate_natural_height=True,
    )
    desplazable.set_child(cuerpo)
    return desplazable


class BloqueCodigo(Gtk.Box):
    """Bloque de código con cabecera (lenguaje, leyenda, copiar y plegar), numeración de
    líneas y coloreado de sintaxis, con la fuente monoespaciada del sistema."""

    def __init__(self, bloque: Codigo, compacto: bool = False) -> None:
        """`compacto` (para las tarjetas): cabecera mínima, sin leyenda ni pliegue, menos
        márgenes y sin texto seleccionable (para no robarle el doble clic a la tarjeta)."""
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        _asegurar_css()
        self.add_css_class("gnomilestone-codigo")
        self._codigo = bloque.codigo

        cabecera = Gtk.Box(spacing=10)
        cabecera.add_css_class("gnomilestone-codigo-cabecera")
        cabecera.append(Gtk.Image.new_from_icon_name("utilities-terminal-symbolic"))
        lenguaje = nombre_lenguaje(bloque.lenguaje) or _("Código")
        etiqueta_lenguaje = Gtk.Label(label=lenguaje, xalign=0)
        etiqueta_lenguaje.add_css_class("heading")
        cabecera.append(etiqueta_lenguaje)
        leyenda = Gtk.Label(label=bloque.titulo, xalign=0, hexpand=True)
        leyenda.add_css_class("dim-label")
        leyenda.set_markup(f"<i>{GLib.markup_escape_text(bloque.titulo)}</i>")
        leyenda.set_ellipsize(Pango.EllipsizeMode.END)
        leyenda.set_visible(not compacto)
        if compacto:
            etiqueta_lenguaje.set_hexpand(True)
        cabecera.append(leyenda)
        self._copiar = Gtk.Button(
            icon_name="edit-copy-symbolic", tooltip_text=_("Copiar el código")
        )
        self._copiar.add_css_class("flat")
        self._copiar.connect("clicked", self._on_copiar)
        cabecera.append(self._copiar)
        plegar = Gtk.ToggleButton(icon_name="pan-down-symbolic", active=True)
        plegar.set_tooltip_text(_("Plegar o desplegar el código"))
        plegar.add_css_class("flat")
        plegar.set_visible(not compacto)
        cabecera.append(plegar)
        self.append(cabecera)

        revelador = Gtk.Revealer(child=cuerpo_de_codigo(bloque, compacto), reveal_child=True)
        plegar.connect("toggled", self._on_plegar, revelador)
        self.append(revelador)

    def _on_copiar(self, boton: Gtk.Button) -> None:
        self.get_clipboard().set(self._codigo)
        boton.set_icon_name("object-select-symbolic")  # confirmación visual breve
        GLib.timeout_add(1500, self._restaurar_icono, boton)

    @staticmethod
    def _restaurar_icono(boton: Gtk.Button) -> bool:
        boton.set_icon_name("edit-copy-symbolic")
        return False

    @staticmethod
    def _on_plegar(boton: Gtk.ToggleButton, revelador: Gtk.Revealer) -> None:
        revelador.set_reveal_child(boton.get_active())
        boton.set_icon_name("pan-down-symbolic" if boton.get_active() else "pan-end-symbolic")
