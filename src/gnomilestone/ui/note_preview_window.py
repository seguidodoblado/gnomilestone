from __future__ import annotations

from collections.abc import Callable

import gi

gi.require_version("Gdk", "4.0")
gi.require_version("Graphene", "1.0")
gi.require_version("Gtk", "4.0")
from gi.repository import Gdk, GLib, Graphene, Gtk, Pango

from gnomilestone.documentacion import secciones_por_titulo
from gnomilestone.i18n import _
from gnomilestone.models import NotaDocumentacion, VersionDocumentacion
from gnomilestone.ui.dialogos import dato_con_icono
from gnomilestone.ui.hoja import HojaPagina, ZoomHoja
from gnomilestone.ui.markdown_view import VistaMarkdown
from gnomilestone.ui.note_window import ETIQUETAS_ESTADO
from gnomilestone.versiones import formatear_fecha

_VERSIONES_VISIBLES = 10
_ANCHO_INDICE = 260  # ancho inicial del índice de títulos (se puede arrastrar)
_ANCHO_INDICE_MINIMO = 140


class NotePreviewWindow(Gtk.Window):
    """Vista de página completa de una nota: todo su contenido ya formateado, en una
    página que ocupa todo el ancho de la ventana. Solo lectura; desde aquí se puede pasar a editarla.
    Esc la cierra."""

    def __init__(
        self,
        parent: Gtk.Window | None,
        nota: NotaDocumentacion,
        al_editar: Callable[[], None],
        preprocesar: Callable[[str], str] | None = None,
        al_enlace: Callable[[str], bool] | None = None,
        entrantes: list[tuple[str, str]] | None = None,
        ruta: list[tuple[str, str]] | None = None,
        subpaginas: list[tuple[str, str]] | None = None,
        versiones: list[VersionDocumentacion] | None = None,
    ) -> None:
        """`entrantes` = [(título, uri)] de las notas que enlazan con ésta; `ruta` = sus
        antepasados (de la raíz hacia abajo) y `subpaginas` = sus subpáginas directas y `versiones` = sus
        versiones anteriores (de la más reciente a la más antigua)."""
        super().__init__(
            title=nota.titulo or _("Sin título"),
            # Sin transient_for: con él, X11 la marca como «diálogo» y el gestor de ventanas
            # quita el botón de maximizar y puede ignorar maximize(). Es una ventana de
            # documento, así que se asocia a la aplicación y no a la ventana principal.
            application=parent.get_application() if parent is not None else None,
            default_width=1100,
            default_height=900,
        )
        titulo = Gtk.Label(label=nota.titulo or _("Sin título"), xalign=0, wrap=True)
        titulo.add_css_class("title-1")
        subtitulo = Gtk.Box(spacing=16)
        subtitulo.append(
            dato_con_icono(
                "x-office-calendar-symbolic",
                (nota.actualizado or nota.creado)[:10],
                tooltip=_("Última modificación"),
                pequeno=False,
            )
        )
        versiones = versiones or []
        if versiones:
            subtitulo.append(
                dato_con_icono(
                    "document-open-recent-symbolic",
                    _("Versión {n} · {m} anteriores").format(
                        n=len(versiones) + 1, m=len(versiones)
                    ),
                    pequeno=False,
                )
            )
        if nota.estado:
            estado = Gtk.Label(label=ETIQUETAS_ESTADO[nota.estado])
            estado.add_css_class("caption")
            estado.add_css_class("gnomilestone-estado")
            estado.add_css_class(f"gnomilestone-estado-{nota.estado}")
            subtitulo.append(estado)

        # Página tipo A4 centrada sobre un escritorio gris (ver ui/hoja.py).
        self._zoom = ZoomHoja()
        self._scroller = HojaPagina(self._zoom)
        pagina = self._scroller.hoja
        if ruta:  # «Padre › Abuelo…» clicable, encima del título
            migas = Gtk.Label(xalign=0, wrap=True, use_markup=True)
            migas.set_markup(
                " › ".join(f'<a href="{GLib.markup_escape_text(uri)}">{GLib.markup_escape_text(t)}</a>' for t, uri in ruta)
            )
            if al_enlace is not None:
                migas.connect("activate-link", lambda _l, uri: al_enlace(uri))
            pagina.append(migas)
        pagina.append(titulo)
        pagina.append(subtitulo)
        pagina.append(Gtk.Separator())

        # Una etiqueta por sección (cada título abre una): así el índice puede llevar a ella.
        destinos: list[tuple[int, str, Gtk.Widget]] = []
        if nota.contenido.strip():
            for seccion in secciones_por_titulo(nota.contenido):
                cuerpo = VistaMarkdown(al_enlace=al_enlace, preprocesar=preprocesar)
                cuerpo.fijar(seccion.markdown)
                pagina.append(cuerpo)
                if seccion.titulo is not None and seccion.nivel is not None:
                    destinos.append((seccion.nivel, seccion.titulo, cuerpo))
        else:
            vacio = Gtk.Label(xalign=0)
            vacio.set_markup(f"<i>{GLib.markup_escape_text(_('Nota sin contenido'))}</i>")
            vacio.add_css_class("dim-label")
            pagina.append(vacio)
        for encabezado, enlaces in ((_("Subpáginas"), subpaginas), (_("Enlazada desde"), entrantes)):
            if not enlaces:
                continue
            pagina.append(Gtk.Separator(margin_top=12))
            cabecera = Gtk.Label(label=encabezado, xalign=0)
            cabecera.add_css_class("heading")
            pagina.append(cabecera)
            for titulo_enlace, uri in enlaces:
                enlace = Gtk.LinkButton(uri=uri, label=titulo_enlace, halign=Gtk.Align.START)
                if al_enlace is not None:
                    enlace.connect("activate-link", lambda b: al_enlace(b.get_uri()))
                pagina.append(enlace)
        if versiones:
            pagina.append(Gtk.Separator(margin_top=12))
            cabecera_v = Gtk.Label(label=_("Historial de versiones"), xalign=0)
            cabecera_v.add_css_class("heading")
            pagina.append(cabecera_v)
            for version in versiones[:_VERSIONES_VISIBLES]:
                pagina.append(
                    dato_con_icono(
                        "document-open-recent-symbolic",
                        f"{formatear_fecha(version.creado)} · {version.titulo or _('Sin título')}",
                        pequeno=False,
                    )
                )
            if len(versiones) > _VERSIONES_VISIBLES:
                resto = Gtk.Label(
                    label=_("…y {n} más").format(n=len(versiones) - _VERSIONES_VISIBLES), xalign=0
                )
                resto.add_css_class("dim-label")
                pagina.append(resto)

        if len(destinos) >= 2:
            # Índice y página separados por un borde que se arrastra para ensanchar el índice.
            cuerpo_ventana: Gtk.Widget = Gtk.Paned(
                orientation=Gtk.Orientation.HORIZONTAL,
                position=_ANCHO_INDICE,
                vexpand=True,
                shrink_start_child=False,
                resize_start_child=False,
                shrink_end_child=False,
            )
            cuerpo_ventana.set_start_child(self._construir_indice(destinos))
            cuerpo_ventana.set_end_child(self._scroller)
        else:
            cuerpo_ventana = self._scroller

        cerrar = Gtk.Button(label=_("Cerrar"))
        cerrar.connect("clicked", lambda _b: self.close())
        editar = Gtk.Button(label=_("Editar"))
        editar.add_css_class("suggested-action")
        editar.connect("clicked", lambda _b: (self.close(), al_editar()))
        botones = Gtk.Box(spacing=8)
        botones.append(self._zoom.botones())
        botones.append(Gtk.Box(hexpand=True))
        botones.append(cerrar)
        botones.append(editar)
        for margen in ("top", "bottom", "start", "end"):
            getattr(botones, f"set_margin_{margen}")(10)

        caja = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        caja.append(cuerpo_ventana)
        caja.append(botones)
        self.set_child(caja)

        teclas = Gtk.EventControllerKey()
        teclas.connect("key-pressed", self._on_tecla)
        self.add_controller(teclas)

    def _construir_indice(self, destinos: list[tuple[int, str, Gtk.Widget]]) -> Gtk.Widget:
        """Índice lateral con los títulos de la nota; cada uno desplaza a su sección."""
        caja = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        for margen in ("top", "bottom", "start", "end"):
            getattr(caja, f"set_margin_{margen}")(12)
        cabecera = Gtk.Label(label=_("Contenido"), xalign=0, margin_bottom=6)
        cabecera.add_css_class("heading")
        caja.append(cabecera)
        nivel_minimo = min(nivel for nivel, _t, _w in destinos)
        for nivel, titulo, destino in destinos:
            boton = Gtk.Button(
                child=Gtk.Label(
                    label=titulo, xalign=0, ellipsize=Pango.EllipsizeMode.END,
                    margin_start=(nivel - nivel_minimo) * 14,
                )
            )
            boton.add_css_class("flat")
            boton.set_tooltip_text(titulo)  # el título completo, si el índice lo recorta
            boton.connect("clicked", lambda _b, d=destino: self._ir_a(d))
            caja.append(boton)
        scroller = Gtk.ScrolledWindow(
            hscrollbar_policy=Gtk.PolicyType.NEVER, width_request=_ANCHO_INDICE_MINIMO, vexpand=True
        )
        scroller.set_child(caja)
        return scroller

    def _ir_a(self, destino: Gtk.Widget) -> None:
        """Desplaza la página hasta el widget `destino`."""
        encontrado, punto = destino.compute_point(self._scroller.escritorio, Graphene.Point())
        if encontrado:
            self._scroller.get_vadjustment().set_value(max(0.0, punto.y - 8))

    def _on_tecla(self, _c: Gtk.EventControllerKey, keyval: int, _code: int, _estado) -> bool:
        if keyval == Gdk.KEY_Escape:
            self.close()
            return True
        return False
