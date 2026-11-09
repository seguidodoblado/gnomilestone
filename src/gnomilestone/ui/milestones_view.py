from __future__ import annotations

from datetime import date, datetime

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gdk, Gtk, Pango

from gnomilestone.documentacion import hitos_del_proyecto
from gnomilestone.i18n import _
from gnomilestone.models import Dependencia, Tarea

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
        ".gnomilestone-hito-previa { background-image: linear-gradient(to bottom, #479ef2,"
        " #1f57ad); color: #f5faff; border-radius: 12px; padding: 6px 14px; }\n"
        ".gnomilestone-hito-previa.hecha { background-image: linear-gradient(to bottom,"
        " #5fb67d, #2f7f4f); }\n"
    )
    Gtk.StyleContext.add_provider_for_display(
        Gdk.Display.get_default(), proveedor, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
    )
    _css_aplicado = True


class MilestonesView(Gtk.ScrolledWindow):
    """Hitos del proyecto como una línea de tiempo vertical de tarjetas: fecha a la
    izquierda y, en la tarjeta, estado, avance y (al desplegar) las tareas previas de las
    que depende el hito con sus subtareas."""

    def __init__(self) -> None:
        super().__init__(hscrollbar_policy=Gtk.PolicyType.NEVER, hexpand=True, vexpand=True)
        _asegurar_css()
        self._caja = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        for margen in ("top", "bottom", "start", "end"):
            getattr(self._caja, f"set_margin_{margen}")(16)
        self.set_child(self._caja)

    def set_datos(self, tareas: list[Tarea], dependencias: list[Dependencia]) -> None:
        hijo = self._caja.get_first_child()
        while hijo is not None:
            siguiente = hijo.get_next_sibling()
            self._caja.remove(hijo)
            hijo = siguiente
        hitos = hitos_del_proyecto(tareas)
        if not hitos:
            vacio = Gtk.Label(
                label=_("No hay hitos. Marca una tarea como hito para verla aquí."),
                xalign=0,
                wrap=True,
            )
            vacio.add_css_class("dim-label")
            self._caja.append(vacio)
            return
        por_id = {t.id: t for t in tareas}
        hijos: dict[int | None, list[Tarea]] = {}
        for tarea in tareas:
            hijos.setdefault(tarea.padre_id, []).append(tarea)
        for hito in hitos:
            previas = [
                por_id[d.tarea_origen_id]
                for d in dependencias
                if d.tarea_destino_id == hito.id and d.tarea_origen_id in por_id
            ]
            self._caja.append(self._fila(hito, previas, hijos))

    def _fila(
        self, hito: Tarea, previas: list[Tarea], hijos: dict[int | None, list[Tarea]]
    ) -> Gtk.Widget:
        progreso = (
            sum(p.porcentaje_completado for p in previas) / len(previas)
            if previas
            else hito.porcentaje_completado
        )
        completado = hito.porcentaje_completado >= 100 or (previas and progreso >= 100)
        vencido = (
            not completado
            and hito.fecha_limite is not None
            and date.fromisoformat(hito.fecha_limite[:10]) < datetime.now().astimezone().date()
        )

        # Columna de fecha + hilo vertical que une los hitos.
        fecha = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.START)
        fecha.add_css_class("gnomilestone-hito-fecha")
        if hito.fecha_limite:
            d = date.fromisoformat(hito.fecha_limite[:10])
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

        detalle = Gtk.Label(
            label=_("{n} tareas previas · {progreso:.0f} % completado").format(
                n=len(previas), progreso=progreso
            )
            if previas
            else _("Sin tareas previas · {progreso:.0f} % completado").format(progreso=progreso),
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
        for previa in previas:
            cuerpo.append(self._pildora(previa, 0))
            for subtarea in hijos.get(previa.id, []):
                cuerpo.append(self._pildora(subtarea, 1))
        revelador = Gtk.Revealer(child=cuerpo, reveal_child=False)
        tarjeta.append(revelador)

        if previas:
            gesto = Gtk.GestureClick()
            gesto.connect(
                "released",
                lambda *_a: revelador.set_reveal_child(not revelador.get_reveal_child()),
            )
            interior.add_controller(gesto)
            interior.set_cursor(Gdk.Cursor.new_from_name("pointer"))
            chip.set_tooltip_text(_("Pulsa para ver las tareas previas"))

        fila = Gtk.Box(spacing=8, margin_bottom=14)
        fila.append(fecha)
        fila.append(linea)
        fila.append(tarjeta)
        return fila

    @staticmethod
    def _pildora(tarea: Tarea, nivel: int) -> Gtk.Widget:
        caja = Gtk.Box(spacing=8, margin_start=nivel * 24)
        caja.add_css_class("gnomilestone-hito-previa")
        if tarea.porcentaje_completado >= 100:
            caja.add_css_class("hecha")
        caja.append(
            Gtk.Label(
                label=tarea.titulo, xalign=0, hexpand=True, ellipsize=Pango.EllipsizeMode.END
            )
        )
        caja.append(Gtk.Label(label=f"{tarea.porcentaje_completado} %"))
        return caja
