from __future__ import annotations

import logging
import re
import shutil
import threading
from collections.abc import Callable
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, Gio, GLib, Gtk

from gnomilestone import imagenes_remotas
from gnomilestone.github import GitHubClient, GitHubError
from gnomilestone.i18n import _
from gnomilestone.models import Recurso
from gnomilestone.recurso_campos import Campo, campos_de, resumen
from gnomilestone.store import DATA_DIR, PALETA_RECURSOS, Store
from gnomilestone.ui.avatar_widget import AvatarWidget
from gnomilestone.ui.task_dialog import _SugerenciasEntry

log = logging.getLogger(__name__)

_AVATARS_DIR = DATA_DIR / "avatars"
_css_aplicado = False
_GLOBE_ICON = Path(__file__).resolve().parent.parent / "assets" / "globe-symbolic.svg"


def _globe_icon_path() -> Path:
    settings = Gtk.Settings.get_default()
    dark = bool(settings and "dark" in (settings.get_property("gtk-theme-name") or "").lower())
    return _GLOBE_ICON.with_name("globe-symbolic-dark.svg" if dark else "globe-symbolic-light.svg")

# (categoría, etiqueta, icono): el orden es el que se usa en el filtro y en la ordenación
# de tarjetas (que ya llega agrupada por categoría desde `Store.listar_recursos`).
_CATEGORIAS = (
    ("personas", _("Personas"), "avatar-default-symbolic"),
    ("equipos", _("Equipos"), "computer-symbolic"),
    ("medios", _("Medios"), "image-x-generic-symbolic"),
    ("lugares", _("Lugares"), "mark-location-symbolic"),
)
_ICONO_POR_CATEGORIA = {valor: icono for valor, _etq, icono in _CATEGORIAS}
_ETIQUETA_POR_CATEGORIA = {valor: etq for valor, etq, _ic in _CATEGORIAS}


def _asegurar_css() -> None:
    global _css_aplicado
    if _css_aplicado:
        return
    proveedor = Gtk.CssProvider()
    proveedor.load_from_string(
        ".gnomilestone-color-swatch { "
        "min-width: 24px; min-height: 24px; border-radius: 9999px; padding: 0; }\n"
        ".gnomilestone-avatar-boton { padding: 0; min-width: 0; min-height: 0; }\n"
        ".gnomilestone-tarjeta-persona { padding: 18px 20px; }\n"
        ".gnomilestone-tarjeta-interior { background-color: @theme_bg_color; "
        "border-radius: 11px; }\n"
        ".gnomilestone-tarjeta-persona .titulo-seccion { font-weight: bold; }\n"
        ".gnomilestone-tarjeta-recurso { "
        "padding: 20px 16px; min-width: 220px; min-height: 220px; }\n"
    )
    Gtk.StyleContext.add_provider_for_display(
        Gdk.Display.get_default(), proveedor, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
    )
    _css_aplicado = True


_clases_borde: set[str] = set()


def _clase_borde(color_hex: str | None) -> str | None:
    """Clase CSS que dibuja el contorno degradado de una tarjeta con ese color.

    El degradado va, en diagonal, de un tono claro del color elegido a uno oscuro, pasando por él. Lo
    pinta una caja exterior con un relleno de 3 px; la tarjeta, con fondo liso, va dentro.
    """
    if not color_hex or not re.fullmatch(r"#[0-9a-fA-F]{6}", color_hex):
        return None
    clase = f"gnomilestone-borde-{color_hex[1:].lower()}"
    if clase not in _clases_borde:
        proveedor = Gtk.CssProvider()
        proveedor.load_from_string(
            f".{clase} {{ padding: 3px; border-radius: 14px; "
            f"background-image: linear-gradient(135deg, mix({color_hex}, #ffffff, 0.45), "
            f"{color_hex} 50%, shade({color_hex}, 0.5)); }}"
        )
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), proveedor, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )
        _clases_borde.add(clase)
    return clase


def _es_ruta_local(avatar_url: str) -> bool:
    return not avatar_url.startswith(("http://", "https://"))


def _formulario_detalles(categoria: str, detalles: dict[str, str]):
    """Caja con un campo por cada dato propio de la categoría y una función que devuelve
    los valores escritos (solo los no vacíos)."""
    caja = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
    lectores: dict[str, Callable[[], str]] = {}
    for campo in campos_de(categoria):
        caja.append(Gtk.Label(label=campo.etiqueta, xalign=0))
        lectores[campo.clave] = _widget_campo(caja, campo, detalles.get(campo.clave, ""))
    return caja, lambda: {c: v for c, f in lectores.items() if (v := f().strip())}


def _widget_campo(caja: Gtk.Box, campo: Campo, valor: str) -> Callable[[], str]:
    if campo.opciones:
        desplegable = Gtk.DropDown.new_from_strings(["", *campo.opciones])
        if valor in campo.opciones:
            desplegable.set_selected(campo.opciones.index(valor) + 1)
        caja.append(desplegable)
        return lambda: ("", *campo.opciones)[desplegable.get_selected()]
    if campo.multilinea:
        texto = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD, top_margin=4, bottom_margin=4,
                             left_margin=6, right_margin=6)
        texto.get_buffer().set_text(valor)
        marco = Gtk.ScrolledWindow(min_content_height=70, has_frame=True)
        marco.set_child(texto)
        caja.append(marco)
        buf = texto.get_buffer()
        return lambda: buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)
    entry = Gtk.Entry(text=valor)
    caja.append(entry)
    return entry.get_text


class ResourceView(Gtk.Box):
    """Vista de recursos del proyecto (rail Recursos): tarjetas agrupadas por categoría
    (Personas, Medios, Equipos, Lugares), con alta rápida y un recurso global opcional
    que aparece en todos los proyectos. El alta normal sigue siendo asignar desde una
    tarea; esta vista es para gestionarlos (avatar, categoría, alcance, baja)."""

    def __init__(self, store: Store, on_changed: Callable[[], None]) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.set_margin_top(16)
        self.set_margin_bottom(16)
        self.set_margin_start(16)
        self.set_margin_end(16)
        _asegurar_css()
        self._store = store
        self._proyecto_id: int | None = None
        self._on_changed = on_changed
        self._filtro_categoria = "personas"
        self._plegadas: set[int] = set()  # personas con la tarjeta plegada

        # Se crean antes que el filtro: activar su primer botón dispara refrescar(), que
        # ya necesita _flujo/_vacio existentes.
        self._flujo = Gtk.FlowBox(
            selection_mode=Gtk.SelectionMode.NONE,
            homogeneous=False,
            max_children_per_line=1,
            row_spacing=12,
            column_spacing=12,
            margin_top=6,
        )
        self._vacio = Gtk.Label(
            label=_("Aún no hay recursos. Añade uno arriba o asígnalo al crear una tarea."),
            wrap=True,
            xalign=0,
        )
        self._vacio.add_css_class("dim-label")
        self._flujo_scroller = Gtk.ScrolledWindow(vexpand=True, hexpand=True)
        self._flujo_scroller.set_child(self._flujo)
        self._tabla_scroller = Gtk.ScrolledWindow(vexpand=True, hexpand=True)

        self.append(self._build_filtro())
        self.append(self._build_alta_rapida())

        self.append(self._flujo_scroller)
        self.append(self._tabla_scroller)
        self.append(self._vacio)

    # -- Construcción de la cabecera -----------------------------------------

    def _build_filtro(self) -> Gtk.Widget:
        fila = Gtk.Box(spacing=6)
        primero: Gtk.ToggleButton | None = None
        for valor, etiqueta_icono, boton in self._botones_filtro():
            if primero is None:
                primero = boton
                boton.set_active(True)
            fila.append(boton)
        todas = Gtk.Button(
            icon_name="view-list-symbolic",
            tooltip_text=_("Plegar o desplegar todas las tarjetas"),
            hexpand=True,
            halign=Gtk.Align.END,
        )
        todas.add_css_class("flat")
        todas.connect("clicked", self._on_plegar_todas)
        fila.append(todas)
        return fila

    def _on_plegar_todas(self, _button: Gtk.Button) -> None:
        if self._proyecto_id is None:
            return
        personas = {
            r.id for r in self._store.listar_recursos(self._proyecto_id) if r.categoria == "personas"
        }
        # Si alguna está desplegada se pliegan todas; si todas están plegadas, se despliegan.
        if personas <= self._plegadas:
            self._plegadas -= personas
        else:
            self._plegadas |= personas
        self.refrescar()

    def _botones_filtro(self):
        opciones = list(_CATEGORIAS)
        primero: Gtk.ToggleButton | None = None
        for valor, etiqueta, icono in opciones:
            contenido = Gtk.Box(spacing=4)
            if icono:
                contenido.append(Gtk.Image.new_from_icon_name(icono))
            contenido.append(Gtk.Label(label=etiqueta))
            boton = Gtk.ToggleButton(child=contenido, group=primero)
            boton.connect("toggled", self._on_filtro_toggled, valor)
            if primero is None:
                primero = boton
            yield valor, etiqueta, boton

    def _on_filtro_toggled(self, boton: Gtk.ToggleButton, valor: str | None) -> None:
        if boton.get_active():
            self._filtro_categoria = valor
            self.refrescar()

    def _build_alta_rapida(self) -> Gtk.Widget:
        fila = Gtk.Box(spacing=6, orientation=Gtk.Orientation.VERTICAL)
        controles = Gtk.Box(spacing=6)
        self._name_entry = Gtk.Entry(placeholder_text=_("Nombre del nuevo recurso"), hexpand=True)
        self._name_entry.connect("activate", self._on_add_manual)
        controles.append(self._name_entry)

        self._categoria_dropdown = Gtk.DropDown.new_from_strings(
            [etiqueta for _v, etiqueta, _i in _CATEGORIAS]
        )
        controles.append(self._categoria_dropdown)

        add_button = Gtk.Button(icon_name="list-add-symbolic", tooltip_text=_("Añadir recurso"))
        add_button.add_css_class("suggested-action")
        add_button.connect("clicked", self._on_add_manual)
        controles.append(add_button)
        fila.append(controles)

        self._global_check = Gtk.CheckButton(
            label=_("Recurso global (disponible en todos los proyectos)")
        )
        fila.append(self._global_check)
        return fila

    # -- Listado ---------------------------------------------------------------

    def mostrar_proyecto(self, proyecto_id: int) -> None:
        self._proyecto_id = proyecto_id
        self.refrescar()

    def refrescar(self) -> None:
        while (hijo := self._flujo.get_first_child()) is not None:
            self._flujo.remove(hijo)
        if self._proyecto_id is None:
            self._vacio.set_visible(True)
            self._flujo_scroller.set_visible(False)
            self._tabla_scroller.set_visible(False)
            return
        todos = self._store.listar_recursos(self._proyecto_id)
        # «Personas» muestra las tarjetas de persona (con sus equipos, medios y
        # lugares dentro); cada una de las otras categorías, su propia tabla.
        categoria = self._filtro_categoria
        recursos = [r for r in todos if r.categoria == categoria]
        self._vacio.set_visible(not recursos)
        self._flujo_scroller.set_visible(bool(recursos) and categoria == "personas")
        self._tabla_scroller.set_visible(bool(recursos) and categoria != "personas")
        if categoria == "personas":
            for recurso in recursos:
                self._flujo.append(self._tarjeta_recurso(recurso))
        else:
            nombres = {r.id: r.nombre for r in todos if r.categoria == "personas"}
            self._tabla_scroller.set_child(self._tabla(categoria, recursos, nombres))

    def _tabla(
        self,
        categoria: str,
        recursos: list[Recurso],
        personas: dict[int, str],
        desde_persona: Recurso | None = None,
    ) -> Gtk.Widget:
        """Tabla de una categoría con las columnas de su tipología. Dentro de la tarjeta de
        una persona (`desde_persona`) se omite «Asignado a», que ya es la propia persona;
        quien lo cambia es el formulario de cada elemento."""
        campos = [c for c in campos_de(categoria) if not c.multilinea]
        rejilla = Gtk.Grid(column_spacing=18, row_spacing=6, margin_top=4, margin_start=22)
        # Los botones van en la primera columna: así no quedan fuera de vista cuando la
        # tabla (Equipos tiene siete campos) es más ancha que la tarjeta.
        encabezados = ["", _("Nombre"), *[c.etiqueta.split(" (")[0] for c in campos]]
        if desde_persona is None:
            encabezados.append(_("Asignado a"))
        for col, texto in enumerate(encabezados):
            etiqueta = Gtk.Label(label=texto, xalign=0)
            etiqueta.add_css_class("caption-heading")
            rejilla.attach(etiqueta, col, 0, 1, 1)
        for fila, recurso in enumerate(recursos, start=1):
            valores = [
                recurso.nombre,
                *[recurso.detalles.get(c.clave, "") or "—" for c in campos],
            ]
            if desde_persona is None:
                valores.append(personas.get(recurso.persona_id, _("Nadie")))
            for col, texto in enumerate(valores, start=1):
                etiqueta = Gtk.Label(label=texto, xalign=0, selectable=True)
                if texto == "—":
                    etiqueta.add_css_class("dim-label")
                rejilla.attach(etiqueta, col, fila, 1, 1)
            acciones = Gtk.Box(spacing=2)
            editar = Gtk.Button(icon_name="document-edit-symbolic", tooltip_text=_("Editar"))
            editar.add_css_class("flat")
            editar.connect("clicked", self._on_editar_clicked, recurso)
            acciones.append(editar)
            borrar = Gtk.Button(icon_name="user-trash-symbolic", tooltip_text=_("Eliminar"))
            borrar.connect("clicked", self._on_delete, recurso)
            borrar.add_css_class("flat")
            acciones.append(borrar)
            rejilla.attach(acciones, 0, fila, 1, 1)
        marco = Gtk.ScrolledWindow(
            vscrollbar_policy=Gtk.PolicyType.NEVER, propagate_natural_height=True
        )
        marco.set_child(rejilla)
        return marco

    def _refrescar_tras_cerrar(self) -> None:
        """Refresca cuando un menú desplegable ya ha terminado de cerrarse: destruir la
        tarjeta que lo contiene mientras se cierra provoca avisos críticos de GTK."""

        def hacer() -> bool:
            self.refrescar()
            self._on_changed()
            return GLib.SOURCE_REMOVE

        GLib.timeout_add(250, hacer)

    def _boton_anadir(self, persona: Recurso, categoria: str) -> Gtk.Widget:
        """Botón «Añadir» de una sección de la tarjeta: nombre con autocompletado de los
        recursos libres de esa categoría; si no existe, se crea y se abre su formulario."""
        entry = Gtk.Entry(placeholder_text=_("Nombre (se crea si no existe)"), width_chars=28)
        pid = self._proyecto_id or persona.proyecto_id

        def sugerencias(texto: str) -> list[str]:
            return [
                r.nombre for r in self._store.listar_recursos(pid)
                if r.categoria == categoria and r.persona_id != persona.id
                and (not texto or texto in r.nombre.casefold())
            ]

        popover = Gtk.Popover()
        popover.set_child(entry)

        def anadir(nombre: str) -> None:
            nombre = nombre.strip()
            if not nombre:
                return
            popover.popdown()
            entry.set_text("")
            existente = next(
                (r for r in self._store.listar_recursos(pid)
                 if r.categoria == categoria and r.nombre.casefold() == nombre.casefold()),
                None,
            )
            if existente is None:
                color = PALETA_RECURSOS[
                    len(self._store.listar_recursos(pid)) % len(PALETA_RECURSOS)
                ]
                existente = self._store.crear_recurso(
                    pid, nombre, color_hex=color, categoria=categoria, persona_id=persona.id
                )
                self._dialogo_recurso(existente)
            else:
                existente.persona_id = persona.id
                self._store.actualizar_recurso(existente)
            self._refrescar_tras_cerrar()

        entry.connect("activate", lambda e: anadir(e.get_text()))
        _SugerenciasEntry(entry, sugerencias, anadir)
        boton = Gtk.MenuButton(
            icon_name="list-add-symbolic", tooltip_text=_("Añadir"), popover=popover,
            halign=Gtk.Align.START, margin_start=22,
        )
        boton.add_css_class("flat")
        return boton

    # -- Tarjeta -----------------------------------------------------------

    def _tarjeta_recurso(self, recurso: Recurso) -> Gtk.Widget:
        if recurso.categoria == "personas":
            return self._tarjeta_persona(recurso)
        n_tareas = self._store.contar_asignaciones_recurso(recurso.id)
        titulos = self._store.listar_titulos_asignados(recurso.id)

        tarjeta = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        tarjeta.add_css_class("card")
        tarjeta.add_css_class("gnomilestone-tarjeta-recurso")

        cabecera = Gtk.Box(halign=Gtk.Align.CENTER)
        cabecera.append(self._boton_avatar(recurso))
        tarjeta.append(cabecera)

        nombre = Gtk.Label(label=recurso.nombre, xalign=0.5, halign=Gtk.Align.CENTER, wrap=True)
        nombre.add_css_class("heading")
        tarjeta.append(nombre)

        if recurso.email:
            email = Gtk.Label(label=recurso.email, xalign=0.5, halign=Gtk.Align.CENTER)
            email.add_css_class("caption")
            email.add_css_class("dim-label")
            tarjeta.append(email)

        etiquetas = Gtk.Box(spacing=4, halign=Gtk.Align.CENTER)
        categoria_box = Gtk.Box(spacing=4)
        categoria_box.append(
            Gtk.Image.new_from_icon_name(_ICONO_POR_CATEGORIA[recurso.categoria])
        )
        categoria_label = Gtk.Label(label=_ETIQUETA_POR_CATEGORIA[recurso.categoria])
        categoria_label.add_css_class("caption")
        categoria_box.append(categoria_label)
        etiquetas.append(categoria_box)
        if recurso.es_global:
            global_box = Gtk.Box(spacing=4, tooltip_text=_("Disponible en todos los proyectos"))
            global_box.append(Gtk.Image.new_from_file(str(_globe_icon_path())))
            etiqueta_global = Gtk.Label(label=_("Global"))
            etiqueta_global.add_css_class("caption")
            global_box.append(etiqueta_global)
            etiquetas.append(global_box)
        tarjeta.append(etiquetas)

        if recurso.persona_id is not None:
            dueno = next(
                (r for r in self._store.listar_recursos(self._proyecto_id or recurso.proyecto_id)
                 if r.id == recurso.persona_id),
                None,
            )
            if dueno is not None:
                asignado = Gtk.Label(
                    label=_("Asignado a: {persona}").format(persona=dueno.nombre),
                    xalign=0.5,
                    halign=Gtk.Align.CENTER,
                )
                asignado.add_css_class("caption")
                tarjeta.append(asignado)

        if recurso.categoria != "personas":
            extra = resumen(recurso)
            if extra:
                datos = Gtk.Label(label=extra, xalign=0.5, halign=Gtk.Align.CENTER, wrap=True)
                datos.add_css_class("caption")
                tarjeta.append(datos)

        if n_tareas == 0:
            detalle = _("Sin tareas asignadas")
        elif n_tareas == 1:
            detalle = _("1 tarea: {titulo}").format(titulo=titulos[0])
        else:
            detalle = _("{n} tareas: {lista}").format(
                n=n_tareas, lista=", ".join(titulos[:3]) + ("…" if n_tareas > 3 else "")
            )
        meta = Gtk.Label(label=detalle, xalign=0.5, halign=Gtk.Align.CENTER, wrap=True)
        meta.add_css_class("caption")
        meta.add_css_class("dim-label")
        tarjeta.append(meta)

        acciones = Gtk.Box(spacing=6, halign=Gtk.Align.CENTER, margin_top=4)
        edit_button = Gtk.Button(icon_name="document-edit-symbolic", tooltip_text=_("Editar recurso"))
        edit_button.add_css_class("flat")
        edit_button.connect("clicked", self._on_editar_clicked, recurso)
        acciones.append(edit_button)
        delete_button = Gtk.Button(icon_name="user-trash-symbolic", tooltip_text=_("Eliminar recurso"))
        delete_button.add_css_class("flat")
        delete_button.connect("clicked", self._on_delete, recurso)
        acciones.append(delete_button)
        tarjeta.append(acciones)

        return tarjeta

    def _tarjeta_persona(self, persona: Recurso) -> Gtk.Widget:
        """Tarjeta de visita: avatar y datos de contacto arriba; debajo, siempre los tres
        bloques (Equipos, Medios y Lugares), con «Ninguno» si la persona no tiene."""
        n_tareas = self._store.contar_asignaciones_recurso(persona.id)
        propios = self._store.listar_recursos_de_persona(persona.id)

        tarjeta = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        tarjeta.add_css_class("card")
        tarjeta.add_css_class("gnomilestone-tarjeta-persona")
        tarjeta.add_css_class("gnomilestone-tarjeta-interior")
        tarjeta.set_hexpand(True)

        cabecera = Gtk.Box(spacing=16)
        cabecera.append(self._boton_avatar(persona))
        datos = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3, hexpand=True,
                        valign=Gtk.Align.CENTER)
        nombre = Gtk.Label(label=persona.nombre, xalign=0, wrap=True)
        nombre.add_css_class("title-3")
        datos.append(nombre)
        for icono, texto, vacio in (
            ("emblem-system-symbolic", persona.cargo, _("Sin cargo")),
            ("mail-unread-symbolic", persona.email, _("Sin email")),
            ("phone-symbolic", persona.telefono, _("Sin teléfono")),
        ):
            fila = Gtk.Box(spacing=6)
            fila.append(Gtk.Image.new_from_icon_name(icono))
            etiqueta = Gtk.Label(label=texto or vacio, xalign=0, wrap=True, selectable=bool(texto))
            if not texto:
                etiqueta.add_css_class("dim-label")
            fila.append(etiqueta)
            datos.append(fila)
        if persona.es_global:
            global_box = Gtk.Box(spacing=4, tooltip_text=_("Disponible en todos los proyectos"))
            global_box.append(Gtk.Image.new_from_file(str(_globe_icon_path())))
            etiqueta_global = Gtk.Label(label=_("Global"))
            etiqueta_global.add_css_class("caption")
            global_box.append(etiqueta_global)
            datos.append(global_box)
        cabecera.append(datos)
        tarjeta.append(cabecera)

        # Lo que se pliega: las tres tablas. Plegada, la tarjeta deja solo la cabecera y un
        # resumen de cuánto tiene la persona.
        tablas = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        for categoria, titulo in (
            ("equipos", _("Equipos")), ("medios", _("Medios")), ("lugares", _("Lugares"))
        ):
            tablas.append(Gtk.Separator())
            encabezado = Gtk.Box(spacing=6)
            encabezado.append(Gtk.Image.new_from_icon_name(_ICONO_POR_CATEGORIA[categoria]))
            etiqueta_titulo = Gtk.Label(label=titulo, xalign=0)
            etiqueta_titulo.add_css_class("titulo-seccion")
            encabezado.append(etiqueta_titulo)
            tablas.append(encabezado)
            grupo = [r for r in propios if r.categoria == categoria]
            if grupo:
                tablas.append(self._tabla(categoria, grupo, {}, desde_persona=persona))
            else:
                ninguno = Gtk.Label(label=_("Ninguno"), xalign=0, margin_start=22)
                ninguno.add_css_class("dim-label")
                tablas.append(ninguno)
            tablas.append(self._boton_anadir(persona, categoria))

        tarjeta.append(tablas)
        n = {c: sum(1 for r in propios if r.categoria == c) for c in ("equipos", "medios", "lugares")}
        resumen_plegada = Gtk.Label(
            label=_("{e} equipos · {m} medios · {l} lugares").format(
                e=n["equipos"], m=n["medios"], l=n["lugares"]
            ),
            xalign=0,
        )
        resumen_plegada.add_css_class("dim-label")
        tarjeta.append(resumen_plegada)

        def aplicar_plegado(plegada: bool) -> None:
            tablas.set_visible(not plegada)
            resumen_plegada.set_visible(plegada)
            toggle.set_icon_name("pan-end-symbolic" if plegada else "pan-down-symbolic")
            toggle.set_tooltip_text(_("Desplegar") if plegada else _("Plegar"))

        def alternar(_b: Gtk.Button) -> None:
            if persona.id in self._plegadas:
                self._plegadas.discard(persona.id)
            else:
                self._plegadas.add(persona.id)
            aplicar_plegado(persona.id in self._plegadas)

        toggle = Gtk.Button()
        toggle.add_css_class("flat")
        toggle.connect("clicked", alternar)
        edit_button = Gtk.Button(icon_name="document-edit-symbolic", tooltip_text=_("Editar recurso"))
        edit_button.add_css_class("flat")
        edit_button.connect("clicked", self._on_editar_clicked, persona)
        delete_button = Gtk.Button(icon_name="user-trash-symbolic", tooltip_text=_("Eliminar recurso"))
        delete_button.add_css_class("flat")
        delete_button.connect("clicked", self._on_delete, persona)
        botones = Gtk.Box(spacing=2, valign=Gtk.Align.START)
        for boton in (edit_button, delete_button, toggle):
            botones.append(boton)
        cabecera.append(botones)
        aplicar_plegado(persona.id in self._plegadas)

        tarjeta.append(Gtk.Separator())
        if n_tareas == 0:
            detalle = _("Sin tareas asignadas")
        else:
            detalle = _("{n} tareas asignadas").format(n=n_tareas)
        meta = Gtk.Label(label=detalle, xalign=0)
        meta.add_css_class("caption")
        meta.add_css_class("dim-label")
        tarjeta.append(meta)

        clase_borde = _clase_borde(persona.color_hex)
        if clase_borde is None:
            return tarjeta
        contorno = Gtk.Box(valign=Gtk.Align.START, hexpand=True)
        contorno.add_css_class(clase_borde)
        contorno.append(tarjeta)
        return contorno

    # -- Avatar (color/imagen) ----------------------------------------------

    def _boton_avatar(self, recurso: Recurso) -> Gtk.MenuButton:
        boton = Gtk.MenuButton(tooltip_text=_("Cambiar avatar"))
        boton.add_css_class("flat")
        boton.add_css_class("gnomilestone-avatar-boton")
        avatar = AvatarWidget(recurso, size=56)
        boton.set_child(avatar)
        boton.avatar_widget = avatar
        boton.set_popover(self._popover_avatar(recurso, boton))
        return boton

    def _pintar_avatar(self, boton: Gtk.MenuButton, recurso: Recurso) -> None:
        avatar = getattr(boton, "avatar_widget", None)
        if isinstance(avatar, AvatarWidget):
            avatar.actualizar(recurso)
        else:
            nuevo = AvatarWidget(recurso, size=56)
            boton.set_child(nuevo)
            boton.avatar_widget = nuevo

    def _popover_avatar(self, recurso: Recurso, boton: Gtk.MenuButton) -> Gtk.Popover:
        popover = Gtk.Popover()
        caja = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=8,
            margin_top=10,
            margin_bottom=10,
            margin_start=10,
            margin_end=10,
        )
        caja.append(Gtk.Label(label=_("Color"), xalign=0))

        paleta = Gtk.Box(spacing=4)
        for color in PALETA_RECURSOS:
            swatch = Gtk.Button()
            swatch.add_css_class("gnomilestone-color-swatch")
            swatch.add_css_class("flat")
            css = Gtk.CssProvider()
            clase = f"swatch-{color.lstrip('#')}"
            swatch.add_css_class(clase)
            css.load_from_string(f".{clase} {{ background-color: {color}; }}")
            Gtk.StyleContext.add_provider_for_display(
                Gdk.Display.get_default(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
            )
            swatch.connect("clicked", self._on_color, recurso, color, boton, popover)
            paleta.append(swatch)
        caja.append(paleta)

        imagen_button = Gtk.Button(label=_("Elegir imagen…"))
        imagen_button.connect("clicked", self._on_elegir_imagen, recurso, boton, popover)
        caja.append(imagen_button)

        if recurso.categoria == "personas":
            github_button = Gtk.Button(label=_("Traer datos de GitHub"))
            github_button.connect("clicked", self._on_datos_github, recurso, boton, popover)
            caja.append(github_button)

        quitar = Gtk.Button(label=_("Quitar imagen"))
        quitar.set_sensitive(bool(recurso.avatar_url))
        quitar.connect("clicked", self._on_quitar_imagen, recurso, boton, popover)
        caja.append(quitar)

        nota = Gtk.Label(
            label=_(
                "Trae nombre, email público y avatar del usuario de GitHub (el indicado en "
                "la persona o, si no, su nombre). Necesita la cuenta de GitHub conectada."
            ),
            wrap=True,
            xalign=0,
        )
        nota.add_css_class("caption")
        nota.add_css_class("dim-label")
        caja.append(nota)

        popover.set_child(caja)
        return popover

    def _ventana(self) -> Gtk.Window | None:
        raiz = self.get_root()
        return raiz if isinstance(raiz, Gtk.Window) else None

    def _on_color(
        self,
        _button: Gtk.Button,
        recurso: Recurso,
        color: str,
        avatar_button: Gtk.MenuButton,
        popover: Gtk.Popover,
    ) -> None:
        recurso.color_hex = color
        self._store.actualizar_recurso(recurso)
        self._pintar_avatar(avatar_button, recurso)
        popover.popdown()
        self._on_changed()

    def _on_elegir_imagen(
        self,
        _button: Gtk.Button,
        recurso: Recurso,
        avatar_button: Gtk.MenuButton,
        popover: Gtk.Popover,
    ) -> None:
        popover.popdown()
        dialog = Gtk.FileDialog(title=_("Elegir imagen de avatar"))
        filtros = Gio.ListStore.new(Gtk.FileFilter)
        filtro = Gtk.FileFilter(name=_("Imágenes"))
        filtro.add_pixbuf_formats()
        filtros.append(filtro)
        dialog.set_filters(filtros)
        dialog.open(self._ventana(), None, self._on_imagen_elegida, recurso, avatar_button)

    def _on_imagen_elegida(
        self,
        dialog: Gtk.FileDialog,
        result: Gio.AsyncResult,
        recurso: Recurso,
        avatar_button: Gtk.MenuButton,
    ) -> None:
        try:
            archivo = dialog.open_finish(result)
        except GLib.Error:
            return
        if archivo is None:
            return
        origen = archivo.get_path()
        if not origen:
            return
        try:
            destino = self._copiar_avatar(recurso.id, Path(origen))
        except OSError:
            log.exception("No se pudo guardar el avatar de recurso %s", recurso.id)
            return
        recurso.avatar_url = str(destino)
        self._store.actualizar_recurso(recurso)
        self._pintar_avatar(avatar_button, recurso)
        self.refrescar()
        self._on_changed()

    def _on_datos_github(
        self,
        boton_accion: Gtk.Button,
        recurso: Recurso,
        avatar_button: Gtk.MenuButton,
        popover: Gtk.Popover,
    ) -> None:
        """Trae de GitHub el perfil de la persona: nombre completo, email público y avatar.

        El usuario es el guardado en `github_login` o, si no hay, el nombre del recurso. El
        nombre visible pasa a ser el de GitHub, así que se guarda el usuario aparte.
        """
        login = re.sub(r"[^A-Za-z0-9-]", "", recurso.github_login or recurso.nombre)
        if not login:
            return
        etiqueta_original = boton_accion.get_label()
        boton_accion.set_sensitive(False)
        boton_accion.set_label(_("Descargando…"))

        def trabajo() -> None:
            try:
                perfil = GitHubClient().obtener_perfil_usuario(login)
                datos_avatar = imagenes_remotas.obtener(f"https://github.com/{login}.png?size=256")
                GLib.idle_add(terminado, perfil, datos_avatar, None)
            except GitHubError as e:
                GLib.idle_add(terminado, None, None, str(e))

        def terminado(perfil: dict | None, datos_avatar: bytes | None, error: str | None) -> bool:
            boton_accion.set_sensitive(True)
            if error or not perfil:
                boton_accion.set_label(etiqueta_original)
                aviso = Gtk.AlertDialog(
                    message=_("No se pudieron traer los datos de GitHub"),
                    detail=error or _("Sin respuesta."),
                )
                aviso.show(self._ventana())
                return GLib.SOURCE_REMOVE
            boton_accion.set_label(etiqueta_original)
            recurso.github_login = perfil.get("login") or login
            if nombre := (perfil.get("name") or "").strip():
                recurso.nombre = nombre
            if email := (perfil.get("email") or "").strip():
                recurso.email = email
            if datos_avatar:
                try:
                    _AVATARS_DIR.mkdir(parents=True, exist_ok=True)
                    destino = _AVATARS_DIR / f"{recurso.id}.png"
                    destino.write_bytes(datos_avatar)
                    recurso.avatar_url = str(destino)
                except OSError:
                    log.exception("No se pudo guardar el avatar de recurso %s", recurso.id)
            self._store.actualizar_recurso(recurso)
            popover.popdown()
            self._refrescar_tras_cerrar()
            return GLib.SOURCE_REMOVE

        threading.Thread(target=trabajo, daemon=True).start()

    def _on_quitar_imagen(
        self,
        _button: Gtk.Button,
        recurso: Recurso,
        avatar_button: Gtk.MenuButton,
        popover: Gtk.Popover,
    ) -> None:
        anterior = recurso.avatar_url
        recurso.avatar_url = None
        self._store.actualizar_recurso(recurso)
        if anterior and _es_ruta_local(anterior):
            Path(anterior).unlink(missing_ok=True)
        self._pintar_avatar(avatar_button, recurso)
        popover.popdown()
        self.refrescar()
        self._on_changed()

    def _copiar_avatar(self, recurso_id: int, origen: Path) -> Path:
        _AVATARS_DIR.mkdir(parents=True, exist_ok=True)
        destino = _AVATARS_DIR / f"{recurso_id}{origen.suffix.lower() or '.png'}"
        shutil.copy2(origen, destino)
        return destino

    # -- Formulario propio de Equipos, Medios y Lugares ----------------------------

    def _on_editar_clicked(self, _button: Gtk.Button, recurso: Recurso) -> None:
        if recurso.categoria == "personas":
            self._editar_persona(recurso)
        else:
            self._dialogo_recurso(recurso)

    def _dialogo_recurso(
        self,
        recurso: Recurso,
        padre: Gtk.Window | None = None,
        on_guardado: Callable[[], None] | None = None,
    ) -> None:
        """Formulario de un Equipo, Medio o Lugar con los campos de su tipología."""
        titulos = {
            "equipos": _("Equipo"), "medios": _("Medio (licencia o acceso)"), "lugares": _("Lugar"),
        }
        dialog = Gtk.Window(
            title=titulos.get(recurso.categoria, _("Recurso")),
            transient_for=padre or self._ventana(),
            modal=True,
            default_width=420,
            default_height=560,
        )
        raiz = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        for lado in ("top", "bottom", "start", "end"):
            getattr(raiz, f"set_margin_{lado}")(16)
        dialog.set_child(raiz)

        formulario = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        formulario.append(Gtk.Label(label=_("Nombre"), xalign=0))
        nombre_entry = Gtk.Entry(text=recurso.nombre)
        formulario.append(nombre_entry)
        caja_detalles, leer_detalles = _formulario_detalles(recurso.categoria, recurso.detalles)
        formulario.append(caja_detalles)

        formulario.append(Gtk.Label(label=_("Asignado a"), xalign=0))
        pid = self._proyecto_id or recurso.proyecto_id
        personas = [r for r in self._store.listar_recursos(pid) if r.categoria == "personas"]
        asignado = Gtk.DropDown.new_from_strings([_("Nadie"), *[p.nombre for p in personas]])
        for i, persona in enumerate(personas, start=1):
            if persona.id == recurso.persona_id:
                asignado.set_selected(i)
        formulario.append(asignado)

        global_check = Gtk.CheckButton(
            label=_("Recurso global (disponible y asignable en todos los proyectos)")
        )
        global_check.set_active(recurso.es_global)
        formulario.append(global_check)

        scroller = Gtk.ScrolledWindow(vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
        scroller.set_child(formulario)
        raiz.append(scroller)

        error_label = Gtk.Label(xalign=0, wrap=True)
        error_label.add_css_class("error")
        raiz.append(error_label)
        acciones = Gtk.Box(spacing=8, halign=Gtk.Align.END)
        cancelar = Gtk.Button(label=_("Cancelar"))
        cancelar.connect("clicked", lambda _b: dialog.close())
        acciones.append(cancelar)
        guardar = Gtk.Button(label=_("Guardar"))
        guardar.add_css_class("suggested-action")

        def on_guardar(_b: Gtk.Button) -> None:
            nombre = nombre_entry.get_text().strip()
            if not nombre:
                error_label.set_text(_("El nombre no puede estar vacío."))
                return
            recurso.nombre = nombre
            recurso.detalles = leer_detalles()
            seleccionado = asignado.get_selected()
            recurso.persona_id = personas[seleccionado - 1].id if seleccionado > 0 else None
            recurso.es_global = global_check.get_active()
            self._store.actualizar_recurso(recurso)
            dialog.close()
            if on_guardado is not None:
                on_guardado()
            self.refrescar()
            self._on_changed()

        guardar.connect("clicked", on_guardar)
        acciones.append(guardar)
        raiz.append(acciones)
        dialog.present()

    # -- Ventana de Persona (General + Equipos, Medios y Lugares) ---------------

    def _editar_persona(self, persona: Recurso) -> None:
        """Datos de la propia persona. Sus equipos, medios y lugares se ven y se editan en
        las tablas de su tarjeta."""
        dialog = Gtk.Window(
            title=_("Editar persona"), transient_for=self._ventana(), modal=True, default_width=380
        )
        raiz = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        for lado in ("top", "bottom", "start", "end"):
            getattr(raiz, f"set_margin_{lado}")(16)
        dialog.set_child(raiz)

        entradas: dict[str, Gtk.Entry] = {}
        for clave, etiqueta, valor in (
            ("nombre", _("Nombre"), persona.nombre),
            ("github_login", _("Usuario de GitHub"), persona.github_login or ""),
            ("cargo", _("Cargo"), persona.cargo or ""),
            ("email", _("Email"), persona.email or ""),
            ("telefono", _("Teléfono"), persona.telefono or ""),
        ):
            raiz.append(Gtk.Label(label=etiqueta, xalign=0))
            entradas[clave] = Gtk.Entry(text=valor)
            raiz.append(entradas[clave])
        global_check = Gtk.CheckButton(
            label=_("Recurso global (disponible y asignable en todos los proyectos)")
        )
        global_check.set_active(persona.es_global)
        raiz.append(global_check)

        error_label = Gtk.Label(xalign=0, wrap=True)
        error_label.add_css_class("error")
        raiz.append(error_label)
        acciones = Gtk.Box(spacing=8, halign=Gtk.Align.END)
        cancelar = Gtk.Button(label=_("Cancelar"))
        cancelar.connect("clicked", lambda _b: dialog.close())
        acciones.append(cancelar)
        guardar = Gtk.Button(label=_("Guardar"))
        guardar.add_css_class("suggested-action")

        def on_guardar(_b: Gtk.Button) -> None:
            nombre = entradas["nombre"].get_text().strip()
            if not nombre:
                error_label.set_text(_("El nombre no puede estar vacío."))
                return
            persona.nombre = nombre
            persona.github_login = entradas["github_login"].get_text().strip() or None
            persona.cargo = entradas["cargo"].get_text().strip() or None
            persona.email = entradas["email"].get_text().strip() or None
            persona.telefono = entradas["telefono"].get_text().strip() or None
            persona.es_global = global_check.get_active()
            self._store.actualizar_recurso(persona)
            dialog.close()
            self.refrescar()
            self._on_changed()

        guardar.connect("clicked", on_guardar)
        acciones.append(guardar)
        raiz.append(acciones)
        dialog.present()

    # -- Alta rápida y baja --------------------------------------------------

    def _on_add_manual(self, _widget: Gtk.Widget) -> None:
        if self._proyecto_id is None:
            return
        nombre = self._name_entry.get_text().strip()
        if not nombre:
            return
        categoria = _CATEGORIAS[self._categoria_dropdown.get_selected()][0]
        existente = self._store.obtener_recurso_por_nombre(self._proyecto_id, nombre)
        if existente is None:
            color = PALETA_RECURSOS[
                len(self._store.listar_recursos(self._proyecto_id)) % len(PALETA_RECURSOS)
            ]
            nuevo = self._store.crear_recurso(
                self._proyecto_id,
                nombre.strip(),
                color_hex=color,
                categoria=categoria,
                es_global=self._global_check.get_active(),
            )
            if categoria != "personas":
                self._dialogo_recurso(nuevo)  # su formulario propio, para completar los datos
        self._name_entry.set_text("")
        self._global_check.set_active(False)
        self.refrescar()
        self._on_changed()

    def _on_delete(self, _button: Gtk.Button, recurso: Recurso) -> None:
        """Pide confirmación: borrar es definitivo y, en una persona, arrastra sus
        asignaciones a tareas y deja libres sus equipos, medios y lugares."""
        detalle = [_("Esta acción no se puede deshacer.")]
        n_tareas = self._store.contar_asignaciones_recurso(recurso.id)
        if n_tareas:
            detalle.append(_("Deja de estar asignado a {n} tareas.").format(n=n_tareas))
        if recurso.categoria == "personas":
            propios = self._store.listar_recursos_de_persona(recurso.id)
            if propios:
                detalle.append(
                    _("Sus {n} equipos, medios y lugares quedarán sin asignar.").format(
                        n=len(propios)
                    )
                )
        dialogo = Gtk.AlertDialog(
            message=_("¿Eliminar «{nombre}»?").format(nombre=recurso.nombre),
            detail="\n".join(detalle),
            buttons=[_("Cancelar"), _("Eliminar")],
            cancel_button=0,
            default_button=0,
        )

        def respondido(dlg: Gtk.AlertDialog, resultado: Gio.AsyncResult) -> None:
            try:
                if dlg.choose_finish(resultado) != 1:
                    return
            except GLib.Error:
                return
            self._eliminar(recurso)

        dialogo.choose(self._ventana(), None, respondido)

    def _eliminar(self, recurso: Recurso) -> None:
        if recurso.avatar_url and _es_ruta_local(recurso.avatar_url):
            Path(recurso.avatar_url).unlink(missing_ok=True)
        self._store.eliminar_recurso(recurso.id)
        self.refrescar()
        self._on_changed()
