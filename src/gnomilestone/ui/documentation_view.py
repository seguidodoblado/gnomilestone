from __future__ import annotations

import logging
from collections.abc import Callable

import gi

gi.require_version("Gdk", "4.0")
gi.require_version("Gtk", "4.0")
from gi.repository import Gdk, GLib, Gtk, Pango

from gnomilestone.codigo import dividir_bloques, recortar_bloques
from gnomilestone.diagrama import Diagrama
from gnomilestone.documentacion import (
    ResultadoBusqueda,
    buscar,
    candidatas_a_padre,
    eventos_roadmap,
    hijas,
    historial_realizado,
    ruta_de,
)
from gnomilestone.enlaces import Destino, Indice, destino_de_uri, entrantes, transformar_enlaces
from gnomilestone.i18n import _
from gnomilestone.models import (
    Dependencia,
    DiagramaDocumentacion,
    NotaDocumentacion,
    Proyecto,
    SubseccionDocumentacion,
    Tarea,
)
from gnomilestone.plantillas import Plantilla, plantillas_para
from gnomilestone.store import Store
from gnomilestone.ui.asignar_hito import asignar_tareas_a_hito, diferir
from gnomilestone.ui.diagram_canvas import MiniaturaDiagrama
from gnomilestone.ui.diagram_window import DiagramWindow
from gnomilestone.ui.dialogos import boton_con_icono, dato_con_icono, pedir_texto
from gnomilestone.ui.history_view import HistorialView
from gnomilestone.ui.hito_dialog import HitoDialog, SeleccionTareasHito
from gnomilestone.ui.markdown_view import VistaMarkdown
from gnomilestone.ui.milestones_view import MilestonesView
from gnomilestone.ui.note_preview_window import NotePreviewWindow
from gnomilestone.ui.note_window import ETIQUETAS_ESTADO, NoteWindow
from gnomilestone.ui.recortado import AlturaFija
from gnomilestone.ui.roadmap_view import RoadmapView
from gnomilestone.ui.selector_icono import SelectorIcono

log = logging.getLogger(__name__)

# (sección, título visible): mismo orden que SECCIONES_DOCUMENTACION.
_SECCIONES = (
    ("vision_general", _("Visión general")),
    ("arquitectura", _("Arquitectura")),
    ("especificaciones", _("Especificaciones")),
    ("blueprint", _("Blueprint")),
    ("decisiones_tecnicas", _("Decisiones técnicas")),
)
# Subsecciones fijas de Blueprint: se alimentan de las tareas, no de notas.
# Iconos simbólicos del sistema de cada sección y de las subsecciones fijas.
# Cada sección de documentación tiene su propio icono simbólico, como las
# subsecciones de Blueprint, para que se distingan visualmente en el árbol lateral.
_ICONOS_SECCION = {
    "vision_general": "help-about-symbolic",
    "arquitectura": "applications-engineering-symbolic",
    "especificaciones": "document-properties-symbolic",
    "blueprint": "emblem-documents-symbolic",
    "decisiones_tecnicas": "applications-utilities-symbolic",
}
_ICONOS_FIJAS = {
    "historial": "document-open-recent-symbolic",
    "hitos": "starred-symbolic",
    "roadmap": "mark-location-symbolic",
}
_ICONO_FECHA = "x-office-calendar-symbolic"
_ICONO_VERSION = "document-open-recent-symbolic"
_ICONO_NOTAS = "text-x-generic-symbolic"  # subsecciones editables de notas
_ICONO_DIAGRAMAS = "media-playlist-shuffle-symbolic"  # subsecciones de diagramas
_ICONO_LICENCIA = "balanza-symbolic"  # icono propio (assets/icons), no está en el tema
_TITULOS_LICENCIA = frozenset({"licencia", "license", "licence", "copying"})


def _icono_de_nota(titulo: str, seccion: str) -> str:
    """Las notas de licencia de Visión general llevan la balanza; el resto, el icono de nota."""
    if seccion == "vision_general" and titulo.strip().casefold() in _TITULOS_LICENCIA:
        return _ICONO_LICENCIA
    return _ICONO_NOTAS
_FIJAS = {
    "blueprint": (
        ("historial", _("Historial")),
        ("hitos", _("Hitos")),
        ("roadmap", _("Roadmap")),
    )
}
_css_notas_aplicado = False
_LINEAS_TARJETA = 8  # líneas de la nota (texto o código) que se ven en su tarjeta
_ANCHO_TITULO_TARJETA = 22  # caracteres: el título se recorta y no ensancha la tarjeta
_ALTO_CONTENIDO_TARJETA = 190  # alto fijo (px) del contenido de la tarjeta; el resto se recorta


def _asegurar_css_notas() -> None:
    """Tarjetas de nota con un degradado gris discreto que sigue al tema: se parte del color
    de texto del tema con poca opacidad, así queda más claro que el fondo en el tema oscuro
    y más oscuro en el claro. La tipografía y el color del texto son los del sistema."""
    global _css_notas_aplicado
    if _css_notas_aplicado:
        return
    proveedor = Gtk.CssProvider()
    proveedor.load_from_string(
        ".gnomilestone-nota { border-radius: 20px; padding: 20px 22px;"
        " background-image: linear-gradient(135deg, alpha(@theme_fg_color, 0.13),"
        " alpha(@theme_fg_color, 0.04));"
        " border: 1px solid alpha(@theme_fg_color, 0.14);"
        " box-shadow: 0 4px 14px alpha(black, 0.18); }\n"
        ".gnomilestone-estado { border-radius: 999px; padding: 1px 10px; }\n"
        ".gnomilestone-estado-borrador { background-color: alpha(#f6d32d, 0.30); }\n"
        ".gnomilestone-estado-vigente { background-color: alpha(#33d17a, 0.28); }\n"
        ".gnomilestone-estado-obsoleta { background-color: alpha(@theme_fg_color, 0.16); }\n"
    )
    Gtk.StyleContext.add_provider_for_display(
        Gdk.Display.get_default(), proveedor, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
    )
    _css_notas_aplicado = True


class DocumentationView(Gtk.Box):
    """Vista de documentación del proyecto (rail Documentación): a la izquierda las cuatro
    secciones con sus subsecciones; a la derecha, según la elegida, sus notas Markdown
    (Arquitectura, Especificaciones, Decisiones técnicas: subsecciones editables) o una
    vista calculada desde las tareas (Blueprint: Historial, Hitos y Roadmap). Todo el
    contenido es propio de la app; las notas se guardan solas."""

    def __init__(
        self,
        store: Store,
        al_abrir_tarea: Callable[[int], None] | None = None,
        al_cambiar_hitos: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL)
        _asegurar_css_notas()
        self._store = store
        self._al_abrir_tarea = al_abrir_tarea
        self._al_cambiar_hitos = al_cambiar_hitos
        self._proyecto: Proyecto | None = None
        self._tareas: list[Tarea] = []
        self._dependencias: list[Dependencia] = []
        # (sección, subsección): id numérico si es editable, clave de texto si es fija.
        self._seleccion: tuple[str, int | str] | None = None
        self._ventanas: dict[int, NoteWindow] = {}  # notas abiertas: una ventana por nota
        self._ventanas_diagramas: dict[int, DiagramWindow] = {}
        self._subsecciones: dict[int, SubseccionDocumentacion] = {}
        self._nivel: int | None = None  # nota cuyas subpáginas se ven (None = nivel raíz)
        # Nodos desplegados del árbol de navegación: ('sub', id) y ('nota', id).
        self._expandidos: set[tuple[str, int]] = set()
        self._secciones_plegadas: set[str] = set()  # secciones principales plegadas

        # Panel de navegación (árbol) a la izquierda, con el ancho ajustable arrastrando.
        panel = Gtk.Paned(
            orientation=Gtk.Orientation.HORIZONTAL,
            position=350,
            hexpand=True,
            vexpand=True,
            shrink_start_child=False,
            resize_start_child=False,
            shrink_end_child=False,
        )
        panel.set_start_child(self._construir_lateral())
        panel.set_end_child(self._construir_derecha())
        self.append(panel)

    # -- Construcción ------------------------------------------------------

    def _construir_lateral(self) -> Gtk.Widget:
        self._busqueda = Gtk.SearchEntry(
            placeholder_text=_("Buscar en la documentación"), margin_top=10, margin_start=10,
            margin_end=10,
        )
        self._busqueda.connect("search-changed", self._on_buscar)
        self._lateral = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        _margenes(self._lateral, 10)
        scroller = Gtk.ScrolledWindow(vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
        scroller.set_child(self._lateral)
        caja = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, width_request=280, vexpand=True)
        caja.append(self._busqueda)
        caja.append(scroller)
        return caja

    def _construir_derecha(self) -> Gtk.Widget:
        self._vacio = Gtk.Label(
            label=_("Elige una subsección de la izquierda."), wrap=True
        )
        self._vacio.add_css_class("dim-label")

        # Cabecera común: nombre de la subsección y, si es editable, renombrar/eliminar.
        self._titulo_sub = Gtk.Label(xalign=0, hexpand=True)
        self._titulo_sub.add_css_class("title-3")
        self._renombrar_btn = Gtk.Button(
            icon_name="document-edit-symbolic", tooltip_text=_("Editar subsección")
        )
        self._renombrar_btn.connect("clicked", self._on_renombrar_subseccion)
        self._eliminar_sub_btn = Gtk.Button(
            icon_name="user-trash-symbolic", tooltip_text=_("Eliminar subsección")
        )
        self._eliminar_sub_btn.connect("clicked", self._on_eliminar_subseccion)
        cabecera = Gtk.Box(spacing=6)
        cabecera.append(self._titulo_sub)
        cabecera.append(self._renombrar_btn)
        cabecera.append(self._eliminar_sub_btn)

        self._historial_view = HistorialView()
        self._hitos_view = MilestonesView(
            self._on_nuevo_hito,
            self._on_editar_hito,
            self._on_anadir_tareas_a_hito,
            self._on_quitar_tarea_de_hito,
        )
        self._roadmap_view = RoadmapView()

        self._contenido = Gtk.Stack(hexpand=True, vexpand=True)
        self._contenido.add_named(self._construir_notas(), "notas")
        self._contenido.add_named(self._construir_diagramas(), "diagramas")
        self._contenido.add_named(self._historial_view, "historial")
        self._contenido.add_named(self._hitos_view, "hitos")
        self._contenido.add_named(self._roadmap_view, "roadmap")

        pagina = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        _margenes(pagina, 16)
        pagina.append(cabecera)
        pagina.append(self._contenido)

        self._derecha = Gtk.Stack(hexpand=True, vexpand=True)
        self._derecha.add_named(self._vacio, "vacio")
        self._derecha.add_named(pagina, "pagina")
        self._derecha.add_named(self._construir_resultados(), "busqueda")
        self._derecha.set_visible_child_name("vacio")
        return self._derecha

    def _construir_resultados(self) -> Gtk.Widget:
        self._resultados = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        _margenes(self._resultados, 16)
        scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        scroller.set_child(self._resultados)
        return scroller

    def _construir_notas(self) -> Gtk.Widget:
        """Tarjetas grandes con las notas de la subsección; doble clic para editar."""
        contenido = Gtk.Box(spacing=6)
        contenido.append(Gtk.Image.new_from_icon_name("list-add-symbolic"))
        contenido.append(Gtk.Label(label=_("Nueva nota")))
        contenido.append(Gtk.Image.new_from_icon_name("pan-down-symbolic"))
        self._plantillas_caja = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        _margenes(self._plantillas_caja, 6)
        self._plantillas_popover = Gtk.Popover(child=self._plantillas_caja)
        nueva = Gtk.MenuButton(
            child=contenido, popover=self._plantillas_popover, halign=Gtk.Align.START,
            tooltip_text=_("Empezar una nota en blanco o desde una plantilla"),
        )
        # El estilo va en el botón interno del MenuButton (el contenedor no lo pinta).
        nueva.get_first_child().add_css_class("suggested-action")
        self._notas_vacio = Gtk.Label(
            label=_("Sin notas. Crea la primera con «Nueva nota»."), xalign=0, wrap=True
        )
        self._notas_vacio.add_css_class("dim-label")
        self._migas = Gtk.Box(spacing=2)
        self._tarjetas = Gtk.FlowBox(
            selection_mode=Gtk.SelectionMode.NONE,
            homogeneous=True,
            min_children_per_line=1,
            max_children_per_line=3,
            column_spacing=18,
            row_spacing=18,
            valign=Gtk.Align.START,
        )
        scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        scroller.set_child(self._tarjetas)
        caja = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        caja.append(nueva)
        caja.append(self._migas)
        caja.append(self._notas_vacio)
        caja.append(scroller)
        return caja

    def _construir_diagramas(self) -> Gtk.Widget:
        """Tarjetas con la miniatura de cada diagrama de la subsección; doble clic edita."""
        nuevo = boton_con_icono(_("Nuevo diagrama"), "list-add-symbolic", halign=Gtk.Align.START)
        nuevo.add_css_class("suggested-action")
        nuevo.connect("clicked", self._on_nuevo_diagrama)
        self._diagramas_vacio = Gtk.Label(
            label=_("Sin diagramas. Crea el primero con «Nuevo diagrama»."), xalign=0, wrap=True
        )
        self._diagramas_vacio.add_css_class("dim-label")
        self._tarjetas_diagramas = Gtk.FlowBox(
            selection_mode=Gtk.SelectionMode.NONE,
            homogeneous=True,
            min_children_per_line=1,
            max_children_per_line=3,
            column_spacing=18,
            row_spacing=18,
            valign=Gtk.Align.START,
        )
        scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        scroller.set_child(self._tarjetas_diagramas)
        caja = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        caja.append(nuevo)
        caja.append(self._diagramas_vacio)
        caja.append(scroller)
        return caja

    # -- Datos -------------------------------------------------------------

    def mostrar_proyecto(
        self, proyecto: Proyecto, tareas: list[Tarea], dependencias: list[Dependencia]
    ) -> None:
        if self._proyecto is None or proyecto.id != self._proyecto.id:
            self._seleccion = None
            self._nivel = None
            self._cerrar_ventanas()
        self._proyecto = proyecto
        self._tareas = tareas
        self._dependencias = dependencias
        self.refrescar()

    def refrescar(self) -> None:
        if self._proyecto is None:
            return
        subsecciones = self._store.listar_subsecciones_documentacion(self._proyecto.id)
        self._subsecciones = {s.id: s for s in subsecciones}
        ids_editables = set(self._subsecciones)
        if (
            self._seleccion is not None
            and isinstance(self._seleccion[1], int)
            and self._seleccion[1] not in ids_editables
        ):
            self._seleccion = None
        self._reconstruir_lateral(subsecciones)
        self._mostrar_seleccion()

    def _reconstruir_lateral(self, subsecciones: list[SubseccionDocumentacion]) -> None:
        _vaciar(self._lateral)
        if self._proyecto is not None:
            notas = self._store.listar_notas_documentacion(self._proyecto.id)
            diagramas = self._store.listar_diagramas_documentacion(self._proyecto.id)
        else:
            notas, diagramas = [], []
        for seccion, nombre in _SECCIONES:
            plegada = seccion in self._secciones_plegadas
            cabecera = Gtk.Box(spacing=4, margin_top=8)
            # Cabecera clicable: pliega o despliega toda la sección.
            contenido = Gtk.Box(spacing=6)
            contenido.append(
                Gtk.Image.new_from_icon_name("pan-end-symbolic" if plegada else "pan-down-symbolic")
            )
            contenido.append(Gtk.Image.new_from_icon_name(_ICONOS_SECCION[seccion]))
            titulo = Gtk.Label(label=nombre, xalign=0, hexpand=True)
            titulo.add_css_class("heading")
            contenido.append(titulo)
            cabecera_boton = Gtk.Button(
                child=contenido,
                hexpand=True,
                tooltip_text=_("Desplegar") if plegada else _("Plegar"),
            )
            cabecera_boton.add_css_class("flat")
            cabecera_boton.connect("clicked", lambda _b, sec=seccion: self._alternar_seccion(sec))
            cabecera.append(cabecera_boton)
            if seccion not in _FIJAS:
                nueva = Gtk.Button(
                    icon_name="list-add-symbolic", tooltip_text=_("Nueva subsección")
                )
                nueva.add_css_class("flat")
                nueva.connect("clicked", self._on_nueva_subseccion, seccion)
                cabecera.append(nueva)
            self._lateral.append(cabecera)
            if plegada:
                continue
            if seccion in _FIJAS:
                for clave, etiqueta in _FIJAS[seccion]:
                    boton = self._fila_subseccion(
                        seccion, clave, etiqueta, _ICONOS_FIJAS.get(clave, _ICONO_NOTAS)
                    )
                    boton.set_hexpand(True)
                    # Mismo hueco de flecha que las subsecciones editables, para alinearlas.
                    fila = Gtk.Box(spacing=0)
                    fila.append(self._flecha(("fija", 0), False))
                    fila.append(boton)
                    self._lateral.append(fila)
            else:
                for sub in (s for s in subsecciones if s.seccion == seccion):
                    self._anadir_subseccion_editable(sub, notas, diagramas)

    def _anadir_subseccion_editable(
        self,
        sub: SubseccionDocumentacion,
        notas: list[NotaDocumentacion],
        diagramas: list[DiagramaDocumentacion],
    ) -> None:
        """Fila de la subsección con su flecha de despliegue y, si está abierta, su contenido:
        las notas anidadas según su jerarquía, o los diagramas."""
        # Cada subsección tiene su propio icono simbólico (guardado en sub.icon_name
        # al crear el proyecto). Si no tiene uno asignado, se usa el genérico por tipo
        # (notas o diagramas), no el de la sección padre.
        icono = sub.icon_name or (_ICONO_DIAGRAMAS if sub.tipo == "diagramas" else _ICONO_NOTAS)
        de_la_sub = [n for n in notas if n.subseccion_id == sub.id]
        diagramas_sub = [d for d in diagramas if d.subseccion_id == sub.id]
        tiene_hijos = bool(diagramas_sub if sub.tipo == "diagramas" else de_la_sub)
        clave = ("sub", sub.id)
        fila = Gtk.Box(spacing=0)
        fila.append(self._flecha(clave, tiene_hijos))
        boton = self._fila_subseccion(sub.seccion, sub.id, sub.nombre, icono)
        boton.set_hexpand(True)
        fila.append(boton)
        self._lateral.append(fila)
        if not tiene_hijos or clave not in self._expandidos:
            return
        if sub.tipo == "diagramas":
            for diagrama in diagramas_sub:
                self._lateral.append(
                    self._fila_hoja(
                        diagrama.titulo, _ICONO_DIAGRAMAS, 1, lambda d=diagrama: self._abrir_desde_arbol_diagrama(sub, d)
                    )
                )
        else:
            self._anadir_notas(de_la_sub, None, 1, frozenset())

    def _anadir_notas(
        self,
        notas: list[NotaDocumentacion],
        padre_id: int | None,
        nivel: int,
        visitadas: frozenset[int],
    ) -> None:
        for nota in hijas(notas, padre_id):
            if nota.id in visitadas:
                continue
            tiene_hijas = bool(hijas(notas, nota.id))
            clave = ("nota", nota.id)
            fila = Gtk.Box(spacing=0, margin_start=nivel * 14)
            fila.append(self._flecha(clave, tiene_hijas))
            hoja = self._fila_hoja(
                nota.titulo,
                _icono_de_nota(nota.titulo, nota.seccion),
                0,
                lambda n=nota: self._abrir_desde_arbol(n),
            )
            hoja.set_hexpand(True)
            fila.append(hoja)
            self._lateral.append(fila)
            if tiene_hijas and clave in self._expandidos:
                self._anadir_notas(notas, nota.id, nivel + 1, visitadas | {nota.id})

    def _flecha(self, clave: tuple[str, int], activa: bool) -> Gtk.Widget:
        """Flecha de desplegar/plegar; sin hijos queda un hueco del mismo ancho."""
        if not activa:
            return Gtk.Box(width_request=30)
        abierto = clave in self._expandidos
        boton = Gtk.Button(
            icon_name="pan-down-symbolic" if abierto else "pan-end-symbolic",
            tooltip_text=_("Plegar") if abierto else _("Desplegar"),
        )
        boton.add_css_class("flat")
        boton.add_css_class("circular")
        boton.connect("clicked", lambda _b: self._alternar_nodo(clave))
        return boton

    def _fila_hoja(self, titulo: str, icono: str, sangria: int, al_pulsar) -> Gtk.Button:
        contenido = Gtk.Box(spacing=8, margin_start=sangria * 14)
        contenido.append(Gtk.Image.new_from_icon_name(icono))
        contenido.append(
            Gtk.Label(label=titulo or _("Sin título"), xalign=0, ellipsize=Pango.EllipsizeMode.END)
        )
        boton = Gtk.Button(child=contenido)
        boton.add_css_class("flat")
        boton.connect("clicked", lambda _b: al_pulsar())
        return boton

    def _alternar_seccion(self, seccion: str) -> None:
        self._secciones_plegadas.symmetric_difference_update({seccion})
        self._reconstruir_lateral(list(self._subsecciones.values()))

    def _alternar_nodo(self, clave: tuple[str, int]) -> None:
        self._expandidos.symmetric_difference_update({clave})
        self._reconstruir_lateral(list(self._subsecciones.values()))

    def _abrir_desde_arbol(self, nota: NotaDocumentacion) -> None:
        """Clic en una nota del árbol: muestra su nivel y abre su vista completa."""
        self._seleccion = (nota.seccion, nota.subseccion_id)
        self._secciones_plegadas.discard(nota.seccion)
        self._nivel = nota.padre_id
        self._expandir_hasta(nota)
        self.refrescar()
        self._abrir_vista_completa(nota.id)

    def _abrir_desde_arbol_diagrama(
        self, sub: SubseccionDocumentacion, diagrama: DiagramaDocumentacion
    ) -> None:
        self._seleccion = (sub.seccion, sub.id)
        self._secciones_plegadas.discard(sub.seccion)
        self._nivel = None
        self.refrescar()
        self._abrir_diagrama(diagrama.id)

    def _expandir_hasta(self, nota: NotaDocumentacion) -> None:
        """Despliega la subsección y los antepasados de la nota para que se vea en el árbol."""
        if nota.subseccion_id is None or self._proyecto is None:
            return
        self._expandidos.add(("sub", nota.subseccion_id))
        todas = self._store.listar_notas_documentacion(
            self._proyecto.id, subseccion_id=nota.subseccion_id
        )
        for antepasado in ruta_de(todas, nota.id)[:-1]:
            self._expandidos.add(("nota", antepasado.id))

    def _fila_subseccion(
        self, seccion: str, clave: int | str, texto: str, icono: str
    ) -> Gtk.Widget:
        activa = self._seleccion == (seccion, clave)
        boton = Gtk.ToggleButton(active=activa)
        boton.add_css_class("flat")
        contenido = Gtk.Box(spacing=8, margin_start=8)
        contenido.append(Gtk.Image.new_from_icon_name(icono))
        contenido.append(Gtk.Label(label=texto, xalign=0, ellipsize=Pango.EllipsizeMode.END))
        boton.set_child(contenido)
        boton.connect("clicked", self._on_seleccionar_subseccion, seccion, clave)
        return boton

    def _mostrar_seleccion(self) -> None:
        if self._busqueda.get_text().strip():
            self._pintar_resultados()  # hay una búsqueda activa: no se tapa con la subsección
            return
        if self._seleccion is None or self._proyecto is None:
            self._derecha.set_visible_child_name("vacio")
            return
        seccion, clave = self._seleccion
        editable = isinstance(clave, int)
        self._renombrar_btn.set_visible(editable)
        self._eliminar_sub_btn.set_visible(editable)
        self._derecha.set_visible_child_name("pagina")
        if editable:
            sub = self._subsecciones.get(clave)
            self._titulo_sub.set_text(sub.nombre if sub else "")
            if sub is not None and sub.tipo == "diagramas":
                self._contenido.set_visible_child_name("diagramas")
                self._refrescar_diagramas(clave)
            else:
                self._contenido.set_visible_child_name("notas")
                self._rellenar_plantillas()
                self._refrescar_notas(clave)
            return
        nombres = dict(_FIJAS[seccion])
        self._titulo_sub.set_text(nombres[clave])
        self._contenido.set_visible_child_name(clave)
        activas = [t for t in self._tareas if not t.archivada]
        if clave == "historial":
            self._historial_view.set_datos(historial_realizado(self._tareas))
        elif clave == "hitos":
            self._hitos_view.set_datos(self._store.listar_hitos(self._proyecto.id), activas)
        elif clave == "roadmap":
            hitos = self._store.listar_hitos(self._proyecto.id)
            self._roadmap_view.set_datos(self._proyecto.nombre, eventos_roadmap(activas, hitos))

    def _on_nuevo_hito(self) -> None:
        self._abrir_dialogo_hito(None)

    def _on_editar_hito(self, hito) -> None:
        self._abrir_dialogo_hito(hito)

    def _on_anadir_tareas_a_hito(self, hito) -> None:
        activas = [t for t in self._tareas if not t.archivada]
        SeleccionTareasHito(
            self.get_root(), self._store, hito, activas, self._hitos_cambiados
        ).present()

    def _on_quitar_tarea_de_hito(self, tarea) -> None:
        asignar_tareas_a_hito(self._store, [tarea.id], None)
        self._hitos_cambiados()

    def _abrir_dialogo_hito(self, hito) -> None:
        if self._proyecto is None:
            return
        HitoDialog(self.get_root(), self._store, self._proyecto.id, hito, self._hitos_cambiados).present()

    def _hitos_cambiados(self) -> None:
        # Diferido: se llama desde botones de esta misma vista, que se reconstruye.
        diferir(self._al_cambiar_hitos or self.refrescar)  # recarga el proyecto (y esta vista)

    def _refrescar_notas(self, subseccion_id: int) -> None:
        assert self._proyecto is not None
        todas = self._store.listar_notas_documentacion(
            self._proyecto.id, subseccion_id=subseccion_id
        )
        if self._nivel is not None and all(n.id != self._nivel for n in todas):
            self._nivel = None  # la nota del nivel actual ya no existe
        visibles = hijas(todas, self._nivel)
        self._pintar_migas(todas, subseccion_id)
        hijo = self._tarjetas.get_first_child()
        while hijo is not None:
            siguiente = hijo.get_next_sibling()
            self._tarjetas.remove(hijo)
            hijo = siguiente
        self._notas_vacio.set_label(
            _("Sin notas. Crea la primera con «Nueva nota».")
            if self._nivel is None
            else _("Sin subpáginas. Crea la primera con «Nueva nota».")
        )
        self._notas_vacio.set_visible(not visibles)
        indice = self._indice()  # una vez para todas las tarjetas
        versiones = self._store.contar_versiones_notas(self._proyecto.id)
        for nota in visibles:
            self._tarjetas.append(
                self._tarjeta_nota(
                    nota, indice, len(hijas(todas, nota.id)), versiones.get(nota.id, 0)
                )
            )

    def _pintar_migas(self, todas: list[NotaDocumentacion], subseccion_id: int) -> None:
        """Ruta hasta el nivel actual: «‹ Subsección › Padre › Nota»; cada tramo es clicable."""
        _vaciar(self._migas)
        self._migas.set_visible(self._nivel is not None)
        if self._nivel is None:
            return
        sub = self._subsecciones.get(subseccion_id)
        raiz = Gtk.Button(label=sub.nombre if sub else _("Raíz"), icon_name="go-previous-symbolic")
        raiz.add_css_class("flat")
        raiz.connect("clicked", lambda _b: self._ir_a_nivel(None))
        ruta = ruta_de(todas, self._nivel)
        self._migas.append(raiz)
        for nota in ruta[:-1]:
            self._migas.append(Gtk.Label(label="›"))
            tramo = Gtk.Button(label=nota.titulo or _("Sin título"))
            tramo.add_css_class("flat")
            tramo.connect("clicked", lambda _b, ident=nota.id: self._ir_a_nivel(ident))
            self._migas.append(tramo)
        self._migas.append(Gtk.Label(label="›"))
        actual = Gtk.Label(label=ruta[-1].titulo or _("Sin título"), margin_start=6)
        actual.add_css_class("heading")
        self._migas.append(actual)

    def _ir_a_nivel(self, nota_id: int | None) -> None:
        self._nivel = nota_id
        if self._seleccion is not None and isinstance(self._seleccion[1], int):
            self._refrescar_notas(self._seleccion[1])

    def _refrescar_diagramas(self, subseccion_id: int) -> None:
        assert self._proyecto is not None
        diagramas = self._store.listar_diagramas_documentacion(
            self._proyecto.id, subseccion_id=subseccion_id
        )
        hijo = self._tarjetas_diagramas.get_first_child()
        while hijo is not None:
            siguiente = hijo.get_next_sibling()
            self._tarjetas_diagramas.remove(hijo)
            hijo = siguiente
        self._diagramas_vacio.set_visible(not diagramas)
        versiones = self._store.contar_versiones_diagramas(self._proyecto.id)
        for diagrama in diagramas:
            self._tarjetas_diagramas.append(
                self._tarjeta_diagrama(diagrama, versiones.get(diagrama.id, 0))
            )

    def _tarjeta_diagrama(
        self, diagrama: DiagramaDocumentacion, n_versiones: int = 0
    ) -> Gtk.Widget:
        """Tarjeta con la miniatura del diagrama, su título y fecha; doble clic lo edita."""
        titulo = Gtk.Label(
            label=diagrama.titulo or _("Sin título"),
            xalign=0,
            ellipsize=Pango.EllipsizeMode.END,
        )
        titulo.add_css_class("title-3")
        titulo.set_max_width_chars(_ANCHO_TITULO_TARJETA)
        pie = Gtk.Box(spacing=12)
        pie.append(
            dato_con_icono(
                _ICONO_FECHA,
                (diagrama.actualizado or diagrama.creado)[:10],
                tooltip=_("Última modificación"),
            )
        )
        if n_versiones:
            pie.append(
                dato_con_icono(
                    _ICONO_VERSION, f"v{n_versiones + 1}", tooltip=_tooltip_versiones(n_versiones)
                )
            )
        tarjeta = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=10,
            width_request=300,
            height_request=240,
            tooltip_text=_("Doble clic para editar"),
        )
        tarjeta.add_css_class("gnomilestone-nota")
        tarjeta.append(titulo)
        tarjeta.append(MiniaturaDiagrama(Diagrama.de_json(diagrama.datos)))
        tarjeta.append(pie)
        gesto = Gtk.GestureClick(button=1)
        gesto.connect(
            "pressed", lambda _g, n_press, _x, _y: n_press == 2 and self._abrir_diagrama(diagrama.id)
        )
        tarjeta.add_controller(gesto)
        return tarjeta

    def _abrir_diagrama(self, diagrama_id: int) -> None:
        existente = self._ventanas_diagramas.get(diagrama_id)
        if existente is not None:
            existente.present()
            return
        diagrama = self._store.obtener_diagrama_documentacion(diagrama_id)
        if diagrama is None:
            return
        ventana = DiagramWindow(self.get_root(), self._store, diagrama, self._on_contenido_cambiado)
        ventana.connect("close-request", self._on_ventana_diagrama_cerrada, diagrama_id)
        self._ventanas_diagramas[diagrama_id] = ventana
        ventana.present()

    def _on_ventana_diagrama_cerrada(self, _ventana: Gtk.Window, diagrama_id: int) -> bool:
        self._ventanas_diagramas.pop(diagrama_id, None)
        return False  # deja cerrar

    def _on_nuevo_diagrama(self, _boton: Gtk.Button) -> None:
        if self._proyecto is None or self._seleccion is None:
            return
        sub_id = self._seleccion[1]
        if not isinstance(sub_id, int):
            return
        # Diagrama sin crear (id 0): solo se guarda en la base de datos al pulsar «Guardar».
        borrador = DiagramaDocumentacion(
            id=0, proyecto_id=self._proyecto.id, subseccion_id=sub_id, titulo=""
        )
        DiagramWindow(
            self.get_root(), self._store, borrador, self._on_contenido_cambiado
        ).present()

    def _tarjeta_nota(
        self,
        nota: NotaDocumentacion,
        indice: Indice,
        n_subpaginas: int = 0,
        n_versiones: int = 0,
    ) -> Gtk.Widget:
        """Tarjeta grande con el degradado de su sección: título, buena parte del contenido
        (Markdown ya formateado) y fecha. Doble clic abre la ventana de edición."""
        titulo = Gtk.Label(
            label=nota.titulo or _("Sin título"),
            xalign=0,
            ellipsize=Pango.EllipsizeMode.END,
        )
        titulo.add_css_class("title-3")
        titulo.set_hexpand(True)
        titulo.set_max_width_chars(_ANCHO_TITULO_TARJETA)
        ampliar = Gtk.Button(
            icon_name="view-fullscreen-symbolic", tooltip_text=_("Ver la nota completa")
        )
        ampliar.add_css_class("flat")
        ampliar.connect("clicked", lambda _b: self._abrir_vista_completa(nota.id))
        cabecera = Gtk.Box(spacing=6)
        cabecera.append(titulo)
        cabecera.append(ampliar)
        # Resumen con el mismo formato que la vista completa (bloques de código incluidos);
        # los enlaces internos se resuelven y funcionan también desde la tarjeta.
        cuerpo = VistaMarkdown(
            texto_vacio=_("Nota sin contenido"),
            al_enlace=self._on_enlace,
            preprocesar=lambda texto: transformar_enlaces(texto, indice),
            compacto=True,
        )
        cuerpo.fijar_bloques(recortar_bloques(dividir_bloques(nota.contenido), _LINEAS_TARJETA))
        # Altura fija: lo que no cabe se recorta, así todas las tarjetas miden lo mismo.
        recorte = AlturaFija(_ALTO_CONTENIDO_TARJETA, cuerpo)
        pie = Gtk.Box(spacing=12)
        pie.append(
            dato_con_icono(
                _ICONO_FECHA, (nota.actualizado or nota.creado)[:10], tooltip=_("Última modificación")
            )
        )
        if n_versiones:
            pie.append(
                dato_con_icono(
                    _ICONO_VERSION, f"v{n_versiones + 1}", tooltip=_tooltip_versiones(n_versiones)
                )
            )
        pie.append(Gtk.Box(hexpand=True))  # empuja subpáginas y estado a la derecha
        subpaginas = Gtk.Button(
            child=Gtk.Label(
                label=_("Subpáginas ({n})").format(n=n_subpaginas) if n_subpaginas else _("Subpáginas")
            ),
            tooltip_text=_("Ver y crear subpáginas de esta nota"),
        )
        subpaginas.add_css_class("flat")
        subpaginas.add_css_class("caption")
        subpaginas.connect("clicked", lambda _b: self._ir_a_nivel(nota.id))
        pie.append(subpaginas)
        if nota.estado:
            chip = Gtk.Label(label=ETIQUETAS_ESTADO[nota.estado])
            chip.add_css_class("caption")
            chip.add_css_class("gnomilestone-estado")
            chip.add_css_class(f"gnomilestone-estado-{nota.estado}")
            pie.append(chip)
        tarjeta = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=10,
            width_request=300,
            height_request=240,
            tooltip_text=_("Doble clic para editar"),
        )
        tarjeta.add_css_class("gnomilestone-nota")
        tarjeta.append(cabecera)
        tarjeta.append(recorte)
        tarjeta.append(pie)
        gesto = Gtk.GestureClick(button=1)
        gesto.connect(
            "pressed", lambda _g, n_press, _x, _y: n_press == 2 and self._abrir_nota(nota.id)
        )
        tarjeta.add_controller(gesto)
        return tarjeta

    def _abrir_vista_completa(self, nota_id: int) -> None:
        nota = self._store.obtener_nota_documentacion(nota_id)
        if nota is None or self._proyecto is None:
            return
        indice = self._indice()
        todas = self._store.listar_notas_documentacion(self._proyecto.id)
        origen = entrantes(Destino("nota", nota.id, nota.titulo), todas, indice)

        def enlace(n: NotaDocumentacion) -> tuple[str, str]:
            return n.titulo or _("Sin título"), Destino("nota", n.id, n.titulo).uri

        en_subseccion = [n for n in todas if n.subseccion_id == nota.subseccion_id]
        NotePreviewWindow(
            self.get_root(),
            nota,
            lambda: self._abrir_nota(nota_id),
            preprocesar=self._preprocesar_enlaces,
            al_enlace=self._on_enlace,
            entrantes=[enlace(n) for n in origen],
            ruta=[enlace(n) for n in ruta_de(en_subseccion, nota.id)[:-1]],
            subpaginas=[enlace(n) for n in hijas(en_subseccion, nota.id)],
            versiones=self._store.listar_versiones_nota(nota.id),
        ).present()

    def _ventana_nota(self, nota: NotaDocumentacion) -> NoteWindow:
        """Ventana de edición con las notas que pueden ser su página padre (misma subsección,
        sin ella ni sus descendientes)."""
        assert self._proyecto is not None
        notas = self._store.listar_notas_documentacion(
            self._proyecto.id, subseccion_id=nota.subseccion_id
        )
        return NoteWindow(
            self.get_root(),
            self._store,
            nota,
            self._on_contenido_cambiado,
            self._preprocesar_enlaces,
            self._on_enlace,
            padres=candidatas_a_padre(notas, nota.id or None),
        )

    def _abrir_nota(self, nota_id: int) -> None:
        existente = self._ventanas.get(nota_id)
        if existente is not None:
            existente.present()
            return
        nota = self._store.obtener_nota_documentacion(nota_id)
        if nota is None:
            return
        ventana = self._ventana_nota(nota)
        ventana.connect("close-request", self._on_ventana_nota_cerrada, nota_id)
        self._ventanas[nota_id] = ventana
        ventana.present()

    def _on_ventana_nota_cerrada(self, _ventana: Gtk.Window, nota_id: int) -> bool:
        self._ventanas.pop(nota_id, None)
        return False  # deja cerrar

    def _on_contenido_cambiado(self) -> None:
        """Una nota o un diagrama se ha creado, guardado o borrado: se repinta la subsección."""
        if self._busqueda.get_text().strip():
            self._pintar_resultados()
            return
        if self._seleccion is None or not isinstance(self._seleccion[1], int):
            return
        sub = self._subsecciones.get(self._seleccion[1])
        if sub is not None and sub.tipo == "diagramas":
            self._refrescar_diagramas(sub.id)
        elif sub is not None:
            self._refrescar_notas(sub.id)

    def _cerrar_ventanas(self) -> None:
        for ventana in [*self._ventanas.values(), *self._ventanas_diagramas.values()]:
            ventana.close()
        self._ventanas.clear()
        self._ventanas_diagramas.clear()

    # -- Búsqueda ----------------------------------------------------------

    def _on_buscar(self, _entrada: Gtk.SearchEntry) -> None:
        if self._busqueda.get_text().strip():
            self._pintar_resultados()
        else:
            self._mostrar_seleccion()

    def _pintar_resultados(self) -> None:
        if self._proyecto is None:
            return
        _vaciar(self._resultados)
        self._derecha.set_visible_child_name("busqueda")
        resultados = buscar(
            self._busqueda.get_text(),
            self._store.listar_notas_documentacion(self._proyecto.id),
            self._store.listar_diagramas_documentacion(self._proyecto.id),
        )
        if not resultados:
            vacio = Gtk.Label(label=_("Sin resultados."), xalign=0)
            vacio.add_css_class("dim-label")
            self._resultados.append(vacio)
            return
        for resultado in resultados:
            self._resultados.append(self._fila_resultado(resultado))

    def _fila_resultado(self, resultado: ResultadoBusqueda) -> Gtk.Widget:
        nombres = dict(_SECCIONES)
        sub = self._subsecciones.get(resultado.subseccion_id or 0)
        ruta = " › ".join(
            x for x in (nombres.get(sub.seccion, "") if sub else "", sub.nombre if sub else "") if x
        )
        titulo = Gtk.Label(label=resultado.titulo or _("Sin título"), xalign=0)
        titulo.add_css_class("heading")
        icono = _ICONO_DIAGRAMAS if resultado.tipo == "diagrama" else _ICONO_NOTAS
        cabecera = Gtk.Box(spacing=8)
        cabecera.append(Gtk.Image.new_from_icon_name(icono))
        cabecera.append(titulo)
        detalle = Gtk.Label(label=ruta, xalign=0)
        detalle.add_css_class("dim-label")
        detalle.add_css_class("caption")
        e = resultado.extracto
        i, n = resultado.inicio, resultado.longitud
        extracto = Gtk.Label(
            xalign=0, wrap=True, use_markup=True, lines=2, ellipsize=Pango.EllipsizeMode.END,
            label=(
                f"{GLib.markup_escape_text(e[:i])}<b>{GLib.markup_escape_text(e[i : i + n])}</b>"
                f"{GLib.markup_escape_text(e[i + n :])}"
            ),
        )
        cuerpo = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        cuerpo.append(cabecera)
        cuerpo.append(detalle)
        cuerpo.append(extracto)
        boton = Gtk.Button(child=cuerpo)
        boton.add_css_class("flat")
        boton.connect("clicked", lambda _b: self._abrir_resultado(resultado))
        return boton

    def _abrir_resultado(self, resultado: ResultadoBusqueda) -> None:
        sub = self._subsecciones.get(resultado.subseccion_id or 0)
        if sub is None:
            return
        self._seleccion = (sub.seccion, sub.id)
        self._secciones_plegadas.discard(sub.seccion)  # que el resultado quede visible en el árbol
        nota = self._store.obtener_nota_documentacion(resultado.id) if resultado.tipo == "nota" else None
        self._nivel = nota.padre_id if nota else None  # abre el nivel donde está la nota
        if nota is not None:
            self._expandir_hasta(nota)
        self._busqueda.set_text("")  # sale de la búsqueda (repinta la subsección)
        self.refrescar()
        if resultado.tipo == "diagrama":
            self._abrir_diagrama(resultado.id)
        else:
            self._abrir_vista_completa(resultado.id)

    # -- Enlaces internos --------------------------------------------------

    def _indice(self) -> Indice:
        assert self._proyecto is not None
        return Indice(
            self._store.listar_notas_documentacion(self._proyecto.id),
            self._store.listar_diagramas_documentacion(self._proyecto.id),
            self._tareas,
        )

    def _preprocesar_enlaces(self, texto: str) -> str:
        return transformar_enlaces(texto, self._indice()) if self._proyecto else texto

    def _on_enlace(self, uri: str) -> bool:
        """Clic en un enlace interno (`gnomilestone://…`); True si se ha atendido."""
        destino = destino_de_uri(uri)
        if destino is None:
            return False  # un enlace normal: GTK lo abre en el navegador
        tipo, ident = destino
        if tipo == "nota":
            self._abrir_vista_completa(ident)
        elif tipo == "diagrama":
            self._abrir_diagrama(ident)
        elif tipo == "tarea" and self._al_abrir_tarea is not None:
            self._al_abrir_tarea(ident)
        return True

    # -- Acciones ----------------------------------------------------------

    def _on_seleccionar_subseccion(
        self, _boton: Gtk.ToggleButton, seccion: str, clave: int | str
    ) -> None:
        self._seleccion = (seccion, clave)
        self._nivel = None
        if isinstance(clave, int):
            # La propia fila y su flecha deben tener el mismo comportamiento:
            # seleccionar y alternar el despliegue de sus notas o diagramas.
            self._expandidos.symmetric_difference_update({("sub", clave)})
        self.refrescar()

    def _on_nueva_subseccion(self, _boton: Gtk.Button, seccion: str) -> None:
        if self._proyecto is None:
            return
        proyecto_id = self._proyecto.id

        tipos = Gtk.DropDown.new_from_strings([_("Notas"), _("Diagramas")])
        selector = SelectorIcono(None, _ICONO_NOTAS)
        extra = Gtk.Box(spacing=8)
        extra.append(tipos)
        extra.append(selector)

        def crear(nombre: str) -> None:
            tipo = "diagramas" if tipos.get_selected() == 1 else "notas"
            sub = self._store.crear_subseccion_documentacion(
                proyecto_id, seccion, nombre, tipo, selector.icono
            )
            self._seleccion = (seccion, sub.id)
            self._secciones_plegadas.discard(seccion)
            self._nivel = None
            self.refrescar()

        # Al cambiar el tipo, el icono «por defecto» que muestra el botón es el de ese tipo.
        def al_cambiar_tipo(*_args) -> None:
            selector.por_defecto = _ICONO_DIAGRAMAS if tipos.get_selected() == 1 else _ICONO_NOTAS

        tipos.connect("notify::selected", al_cambiar_tipo)
        pedir_texto(self.get_root(), _("Nueva subsección"), "", crear, extra=extra)

    def _on_renombrar_subseccion(self, _boton: Gtk.Button) -> None:
        if self._seleccion is None or not isinstance(self._seleccion[1], int):
            return
        sub_id = self._seleccion[1]
        sub = self._subsecciones.get(sub_id)
        if sub is None:
            return
        selector = SelectorIcono(
            sub.icon_name, _ICONO_DIAGRAMAS if sub.tipo == "diagramas" else _ICONO_NOTAS
        )

        def renombrar(nombre: str) -> None:
            self._store.renombrar_subseccion_documentacion(sub_id, nombre)
            if selector.icono != sub.icon_name:
                self._store.cambiar_icono_subseccion_documentacion(sub_id, selector.icono)
            self.refrescar()

        pedir_texto(
            self.get_root(),
            _("Editar subsección"),
            self._titulo_sub.get_text(),
            renombrar,
            extra=selector,
        )

    def _on_eliminar_subseccion(self, _boton: Gtk.Button) -> None:
        if self._seleccion is None or not isinstance(self._seleccion[1], int):
            return
        sub_id = self._seleccion[1]
        dialog = Gtk.AlertDialog()
        dialog.set_message(_("Eliminar subsección"))
        dialog.set_detail(
            _(
                "¿Seguro que quieres eliminar «{nombre}» y todas sus notas? "
                "Esta acción no se puede deshacer."
            ).format(nombre=self._titulo_sub.get_text())
        )
        dialog.set_buttons([_("Cancelar"), _("Eliminar")])
        dialog.set_cancel_button(0)
        dialog.set_default_button(0)

        def respuesta(dlg: Gtk.AlertDialog, result) -> None:
            try:
                eleccion = dlg.choose_finish(result)
            except GLib.Error:
                return
            if eleccion != 1:
                return
            self._cerrar_ventanas()
            self._store.eliminar_subseccion_documentacion(sub_id)
            self._seleccion = None
            self.refrescar()

        dialog.choose(self.get_root(), None, respuesta)

    def _rellenar_plantillas(self) -> None:
        """Rellena el menú con las plantillas de la sección de la subsección elegida. Se hace
        al elegir la subsección y no al abrir el menú: cambiar el contenido de un popover
        mientras se muestra provoca avisos «snapshot … without a current allocation»."""
        if self._seleccion is None:
            return
        _vaciar(self._plantillas_caja)
        for plantilla in plantillas_para(self._seleccion[0]):
            nombre = Gtk.Label(label=plantilla.nombre, xalign=0)
            nombre.add_css_class("heading")
            detalle = Gtk.Label(label=plantilla.descripcion, xalign=0)
            detalle.add_css_class("dim-label")
            detalle.add_css_class("caption")
            cuerpo = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            cuerpo.append(nombre)
            cuerpo.append(detalle)
            boton = Gtk.Button(child=cuerpo)
            boton.add_css_class("flat")
            boton.connect("clicked", lambda _b, p=plantilla: self._nueva_nota_con(p))
            self._plantillas_caja.append(boton)

    def _nueva_nota_con(self, plantilla: Plantilla) -> None:
        self._plantillas_popover.popdown()
        if self._proyecto is None or self._seleccion is None:
            return
        seccion, sub_id = self._seleccion
        if not isinstance(sub_id, int):
            return
        # Nota sin crear (id 0): solo se guarda en la base de datos al pulsar «Guardar».
        borrador = NotaDocumentacion(
            id=0,
            proyecto_id=self._proyecto.id,
            seccion=seccion,
            titulo=plantilla.titulo,
            contenido=plantilla.contenido,
            subseccion_id=sub_id,
            padre_id=self._nivel,  # se crea dentro del nivel que se está viendo
        )
        self._ventana_nota(borrador).present()

def _tooltip_versiones(n_anteriores: int) -> str | None:
    if not n_anteriores:
        return None
    return _("Versión actual: {n} · {m} anteriores disponibles (botón «Versiones» al editar)").format(
        n=n_anteriores + 1, m=n_anteriores
    )


def _margenes(widget: Gtk.Widget, valor: int) -> None:
    widget.set_margin_top(valor)
    widget.set_margin_bottom(valor)
    widget.set_margin_start(valor)
    widget.set_margin_end(valor)


def _vaciar(caja: Gtk.Box) -> None:
    hijo = caja.get_first_child()
    while hijo is not None:
        siguiente = hijo.get_next_sibling()
        caja.remove(hijo)
        hijo = siguiente
