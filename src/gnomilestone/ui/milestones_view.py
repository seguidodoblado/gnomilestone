from __future__ import annotations

from collections.abc import Callable
from datetime import date

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gdk, Gtk, Pango

from gnomilestone.documentacion import hitos_del_proyecto
from gnomilestone.hitos import avance_hito, esta_conseguido, esta_vencido, tareas_por_hito
from gnomilestone.i18n import _
from gnomilestone.models import Hito, Tarea

_css_aplicado = False


def _asegurar_css() -> None:
    global _css_aplicado
    if _css_aplicado:
        return
    proveedor = Gtk.CssProvider()
    proveedor.load_from_string(
        ".gnomilestone-hito-fecha { min-width: 64px; }\n"
        ".gnomilestone-hito-dia { font-size: 26px; font-weight: 800; }\n"
        ".gnomilestone-hito-mes { font-size: 11px; font-weight: 700; opacity: 0.7; }\n"
        ".gnomilestone-hito-linea { min-width: 3px; background-color: alpha(#f0a030, 0.35);"
        " border-radius: 2px; margin: 0 6px; }\n"
        ".gnomilestone-hito-tarjeta { background-image: linear-gradient(to bottom, #ffb838,"
        " #c75710); color: #29200f; border-radius: 14px; padding: 14px 18px;"
        " box-shadow: 0 2px 8px alpha(black, 0.35); }\n"
        ".gnomilestone-hito-tarjeta.completado { background-image: linear-gradient(to bottom,"
        " #6cc78a, #2f7f4f); color: #0e2417; }\n"
        ".gnomilestone-hito-tarjeta.vencido { background-image: linear-gradient(to bottom,"
        " #f2705f, #a3261b); color: #2a0c08; }\n"
        ".gnomilestone-hito-titulo { font-size: 17px; font-weight: 800; }\n"
        ".gnomilestone-hito-detalle { font-size: 12px; opacity: 0.8; }\n"
        ".gnomilestone-hito-chip { background-color: alpha(black, 0.22); color: white;"
        " border-radius: 999px; padding: 2px 10px; font-size: 11px; font-weight: 700; }\n"
        ".gnomilestone-hito-tarjeta progressbar trough { min-height: 6px;"
        " background-color: alpha(black, 0.25); }\n"
        ".gnomilestone-hito-tarjeta progressbar progress { min-height: 6px;"
        " background-color: white; }\n"
        ".gnomilestone-hito-anadir { background-image: linear-gradient(to bottom,"
        " alpha(#fff3d6, 0.42), alpha(#fff3d6, 0.12)); color: #29200f; font-weight: 700;"
        " border: 1px solid alpha(#7a3200, 0.35); border-radius: 999px;"
        " padding: 3px 16px; box-shadow: 0 1px 2px alpha(black, 0.25); }\n"
        ".gnomilestone-hito-anadir:hover { background-image: linear-gradient(to bottom,"
        " alpha(#fff3d6, 0.6), alpha(#fff3d6, 0.22)); }\n"
        ".gnomilestone-hito-previa { background-image: linear-gradient(to bottom, #479ef2,"
        " #1f57ad); color: #f5faff; border-radius: 12px; padding: 6px 14px; }\n"
        ".gnomilestone-hito-previa.hecha { background-image: linear-gradient(to bottom,"
        " #5fb67d, #2f7f4f); }\n"
    )
    Gtk.StyleContext.add_provider_for_display(
        Gdk.Display.get_default(), proveedor, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
    )
    _css_aplicado = True


class MilestonesView(Gtk.Box):
    """Hitos del proyecto como una línea de tiempo vertical de tarjetas: fecha a la
    izquierda y, en la tarjeta, estado, avance y (al desplegar) las tareas que contribuyen
    al hito con sus subtareas. Un Hito es un Milestone de GitHub, no una tarea."""

    def __init__(
        self,
        on_nuevo: Callable[[], None] | None = None,
        on_editar: Callable[[Hito], None] | None = None,
        on_anadir_tareas: Callable[[Hito], None] | None = None,
        on_quitar_tarea: Callable[[Tarea], None] | None = None,
    ) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, hexpand=True, vexpand=True)
        _asegurar_css()
        self._on_editar = on_editar
        self._on_anadir_tareas = on_anadir_tareas
        self._on_quitar_tarea = on_quitar_tarea
        self._plegadas: set[int] = set()  # tareas con las subtareas plegadas
        barra = Gtk.Box(margin_top=8, margin_start=16, margin_end=16)
        nuevo = Gtk.Button(label=_("Nuevo hito"))
        nuevo.add_css_class("suggested-action")
        nuevo.connect("clicked", lambda _b: on_nuevo() if on_nuevo else None)
        barra.append(nuevo)
        self.append(barra)
        self._caja = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        for margen in ("top", "bottom", "start", "end"):
            getattr(self._caja, f"set_margin_{margen}")(16)
        desplazable = Gtk.ScrolledWindow(
            hscrollbar_policy=Gtk.PolicyType.NEVER, hexpand=True, vexpand=True
        )
        desplazable.set_child(self._caja)
        self.append(desplazable)

    def set_datos(self, hitos: list[Hito], tareas: list[Tarea]) -> None:
        hijo = self._caja.get_first_child()
        while hijo is not None:
            siguiente = hijo.get_next_sibling()
            self._caja.remove(hijo)
            hijo = siguiente
        hitos = hitos_del_proyecto(hitos)
        if not hitos:
            vacio = Gtk.Label(
                label=_("No hay hitos. Crea uno con «Nuevo hito» o en un Milestone de GitHub."),
                xalign=0,
                wrap=True,
            )
            vacio.add_css_class("dim-label")
            self._caja.append(vacio)
            return
        hijos: dict[int | None, list[Tarea]] = {}
        for tarea in tareas:
            hijos.setdefault(tarea.padre_id, []).append(tarea)
        por_hito = tareas_por_hito(tareas)
        for hito in hitos:
            self._caja.append(self._fila(hito, por_hito.get(hito.id, []), hijos))

    def _fila(
        self, hito: Hito, previas: list[Tarea], hijos: dict[int | None, list[Tarea]]
    ) -> Gtk.Widget:
        progreso = avance_hito(hito, previas)
        completado = esta_conseguido(hito, previas)
        vencido = esta_vencido(hito, previas)

        # Columna de fecha + hilo vertical que une los hitos.
        fecha = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.START)
        fecha.add_css_class("gnomilestone-hito-fecha")
        if hito.fecha:
            d = date.fromisoformat(hito.fecha[:10])
            dia = Gtk.Label(label=f"{d.day}")
            dia.add_css_class("gnomilestone-hito-dia")
            mes = Gtk.Label(label=f"{d.strftime('%b').upper()} {d.year}")
            mes.add_css_class("gnomilestone-hito-mes")
            fecha.append(dia)
            fecha.append(mes)
        else:
            sin = Gtk.Label(label=_("Sin fecha"))
            sin.add_css_class("gnomilestone-hito-mes")
            fecha.append(sin)
        linea = Gtk.Box()
        linea.add_css_class("gnomilestone-hito-linea")

        # Tarjeta: cabecera pulsable (título, estado, avance) + detalle desplegable.
        titulo = Gtk.Label(
            label=hito.titulo, xalign=0, hexpand=True, ellipsize=Pango.EllipsizeMode.END
        )
        titulo.add_css_class("gnomilestone-hito-titulo")
        if completado:
            estado = _("Completado")
        elif vencido:
            estado = _("Vencido")
        else:
            estado = _("Pendiente")
        chip = Gtk.Label(label=estado, valign=Gtk.Align.CENTER)
        chip.add_css_class("gnomilestone-hito-chip")
        cabecera = Gtk.Box(spacing=10)
        cabecera.append(titulo)
        cabecera.append(chip)
        editar = Gtk.Button(icon_name="document-edit-symbolic", valign=Gtk.Align.CENTER)
        editar.add_css_class("flat")
        editar.set_tooltip_text(_("Editar hito"))
        editar.connect("clicked", lambda _b: self._on_editar(hito) if self._on_editar else None)
        cabecera.append(editar)

        detalle = Gtk.Label(
            label=_("{n} tareas · {progreso:.0f} % completado").format(
                n=len(previas), progreso=progreso
            )
            if previas
            else _("Sin tareas · {progreso:.0f} % completado").format(progreso=progreso),
            xalign=0,
        )
        detalle.add_css_class("gnomilestone-hito-detalle")
        barra = Gtk.ProgressBar(fraction=min(1.0, progreso / 100), margin_top=6)

        interior = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        interior.append(cabecera)
        interior.append(detalle)
        interior.append(barra)

        tarjeta = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True)
        tarjeta.add_css_class("gnomilestone-hito-tarjeta")
        if completado:
            tarjeta.add_css_class("completado")
        elif vencido:
            tarjeta.add_css_class("vencido")
        tarjeta.append(interior)

        cuerpo = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_top=12)
        anadir = Gtk.Button(label=_("Añadir tareas…"), halign=Gtk.Align.START)
        anadir.add_css_class("gnomilestone-hito-anadir")
        anadir.connect(
            "clicked", lambda _b: self._on_anadir_tareas(hito) if self._on_anadir_tareas else None
        )
        cuerpo.append(anadir)
        ids_miembros = {t.id for t in previas}
        for previa in previas:
            if previa.padre_id in ids_miembros:
                continue  # ya cuelga, como subtarea, de otra tarea del hito
            cuerpo.append(self._rama(previa, 0, hijos, quitable=True))
        revelador = Gtk.Revealer(child=cuerpo, reveal_child=False)
        tarjeta.append(revelador)

        gesto = Gtk.GestureClick()
        gesto.connect(
            "released",
            lambda *_a: revelador.set_reveal_child(not revelador.get_reveal_child()),
        )
        interior.add_controller(gesto)
        interior.set_cursor(Gdk.Cursor.new_from_name("pointer"))
        chip.set_tooltip_text(_("Pulsa para ver sus tareas y añadir otras"))

        fila = Gtk.Box(spacing=8, margin_bottom=14)
        fila.append(fecha)
        fila.append(linea)
        fila.append(tarjeta)
        return fila

    def _rama(
        self, tarea: Tarea, nivel: int, hijos: dict[int | None, list[Tarea]], quitable: bool
    ) -> Gtk.Widget:
        """La tarea y, plegables con ▾/▸, sus subtareas."""
        subtareas = hijos.get(tarea.id, [])
        rama = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        pildora = Gtk.Box(spacing=6, margin_start=nivel * 24)
        pildora.add_css_class("gnomilestone-hito-previa")
        if tarea.porcentaje_completado >= 100:
            pildora.add_css_class("hecha")
        caja_subtareas = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        if subtareas:
            plegada = tarea.id in self._plegadas
            marca = Gtk.Button(label="▸" if plegada else "▾")
            marca.add_css_class("flat")
            marca.add_css_class("circular")
            marca.set_tooltip_text(_("Plegar o desplegar las subtareas"))

            def _alternar(_b, tarea_id=tarea.id, marca=marca, caja=caja_subtareas) -> None:
                if tarea_id in self._plegadas:
                    self._plegadas.discard(tarea_id)
                else:
                    self._plegadas.add(tarea_id)
                abierta = tarea_id not in self._plegadas
                marca.set_label("▾" if abierta else "▸")
                caja.set_visible(abierta)

            marca.connect("clicked", _alternar)
            pildora.append(marca)
            caja_subtareas.set_visible(not plegada)
        pildora.append(
            Gtk.Label(
                label=tarea.titulo, xalign=0, hexpand=True, ellipsize=Pango.EllipsizeMode.END
            )
        )
        pildora.append(Gtk.Label(label=f"{tarea.porcentaje_completado} %"))
        if quitable:
            quitar = Gtk.Button(icon_name="window-close-symbolic")
            quitar.add_css_class("flat")
            quitar.add_css_class("circular")
            quitar.set_tooltip_text(_("Quitar del hito"))
            quitar.connect(
                "clicked", lambda _b: self._on_quitar_tarea(tarea) if self._on_quitar_tarea else None
            )
            pildora.append(quitar)
        rama.append(pildora)
        for subtarea in subtareas:
            caja_subtareas.append(self._rama(subtarea, nivel + 1, hijos, quitable=False))
        rama.append(caja_subtareas)
        return rama
