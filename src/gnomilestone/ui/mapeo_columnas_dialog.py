from __future__ import annotations

from collections.abc import Callable

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk

from gnomilestone.github import GitHubStatusOption
from gnomilestone.i18n import _
from gnomilestone.models import EstadoTablero


class MapeoColumnasDialog(Gtk.Window):
    """Pregunta a qué columna del tablero de GitHub migrar las tareas de cada columna local
    que GitHub no reconoce, antes de que el pull sustituya el tablero local por el remoto."""

    def __init__(
        self,
        parent: Gtk.Window,
        sin_equivalente: list[tuple[EstadoTablero, int]],
        opciones: list[GitHubStatusOption],
        on_aceptar: Callable[[dict[int, str | None]], None],
        on_cancelar: Callable[[], None],
    ) -> None:
        super().__init__(
            title=_("Columnas del tablero"), transient_for=parent, modal=True, default_width=460
        )
        self._opciones = opciones
        self._on_aceptar = on_aceptar
        self._on_cancelar = on_cancelar
        self._resuelto = False
        self._filas: list[tuple[EstadoTablero, Gtk.DropDown]] = []

        caja = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=12,
            margin_top=16,
            margin_bottom=16,
            margin_start=16,
            margin_end=16,
        )
        self.set_child(caja)

        intro = Gtk.Label(
            label=_(
                "El tablero de GitHub sustituirá al local. Estas columnas locales no existen "
                "en GitHub: elige a qué columna de GitHub pasan sus tareas."
            ),
            wrap=True,
            xalign=0,
        )
        caja.append(intro)

        nombres = [_("Sin columna (No Status)")] + [o.name for o in opciones]
        for estado, n in sin_equivalente:
            fila = Gtk.Box(spacing=12)
            etiqueta = Gtk.Label(
                label=_("«{nombre}» · tareas: {n}").format(nombre=estado.nombre, n=n),
                xalign=0,
                hexpand=True,
            )
            fila.append(etiqueta)
            desplegable = Gtk.DropDown.new_from_strings(nombres)
            fila.append(desplegable)
            caja.append(fila)
            self._filas.append((estado, desplegable))

        botones = Gtk.Box(spacing=8, halign=Gtk.Align.END, margin_top=12)
        cancelar = Gtk.Button(label=_("Cancelar"))
        cancelar.connect("clicked", lambda _b: self.close())
        botones.append(cancelar)
        continuar = Gtk.Button(label=_("Continuar"))
        continuar.add_css_class("suggested-action")
        continuar.connect("clicked", self._on_continuar)
        botones.append(continuar)
        caja.append(botones)

        self.connect("close-request", self._on_close)

    def _on_continuar(self, _boton: Gtk.Button) -> None:
        eleccion: dict[int, str | None] = {}
        for estado, desplegable in self._filas:
            i = desplegable.get_selected()
            eleccion[estado.id] = self._opciones[i - 1].id if i > 0 else None
        self._resuelto = True
        self.close()
        self._on_aceptar(eleccion)

    def _on_close(self, _ventana: Gtk.Window) -> bool:
        if not self._resuelto:
            self._resuelto = True
            self._on_cancelar()
        return False
