from __future__ import annotations

import subprocess

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk

from gnomilestone import settings, theme
from gnomilestone.i18n import _
from gnomilestone.ui import gantt_drawing_area

# Los nombres de idioma no se traducen (convención habitual en selectores de idioma):
# "English" se ve igual estando la app en español, y viceversa.
_LANGUAGE_CODES: list[str | None] = [None, "es", "en"]
_LANGUAGE_LABELS = [_("Sistema"), "Español", "English"]

_THEME_VALUES: list[bool | None] = [None, False, True]

_PROGRESO_EJEMPLO = 65  # para la vista previa del estilo "píldora con progreso"


def _color_acento(widget: Gtk.Widget) -> tuple[float, float, float]:
    encontrado, rgba = widget.get_style_context().lookup_color("accent_color")
    if encontrado:
        return (rgba.red, rgba.green, rgba.blue)
    return (0.0, 0.47, 0.84)


class _VistaPreviaResumen(Gtk.DrawingArea):
    """Dibuja, a tamaño real, el mismo estilo de barra resumen que vería el usuario en el
    Gantt: usa las funciones de dibujo de `gantt_drawing_area` directamente, no una
    recreación aparte, para que la vista previa no se pueda desincronizar del resultado real."""

    def __init__(self, estilo: str) -> None:
        super().__init__(content_width=180, content_height=36)
        self._estilo = estilo
        self.set_draw_func(self._draw)

    def _draw(self, _area: Gtk.DrawingArea, cr, width: int, height: int) -> None:
        acento = _color_acento(self)
        margen = 10
        if self._estilo == gantt_drawing_area.ESTILO_RESUMEN_CORCHETES:
            gantt_drawing_area.dibujar_resumen_corchetes(
                cr, margen, width - margen, 16, acento
            )
        else:
            tema_oscuro = theme.is_dark_theme(
                Gtk.Settings.get_default().get_property("gtk-theme-name")
            )
            y_barra = (height - gantt_drawing_area.ALTO_RESUMEN_PROGRESO) / 2
            gantt_drawing_area.dibujar_resumen_progreso(
                cr,
                self.get_pango_context(),
                margen,
                width - margen,
                y_barra,
                acento,
                tema_oscuro,
                _PROGRESO_EJEMPLO,
            )


class PreferencesWindow(Gtk.Window):
    """Idioma, tema (claro/oscuro) y estilo de la barra resumen del Gantt, persistidos
    en ~/.config/gnomilestone/settings.json.

    Todo requiere reiniciar la aplicación para aplicarse: el idioma porque la mayoría
    de los textos ya están fijados en los widgets al construir la interfaz, el tema
    porque cambiar gtk-theme-name en caliente no repinta la ventana en Cinnamon/Mint, y
    el estilo de la barra resumen para no complicar el resto del diálogo con ajustes que
    sí se podrían aplicar en caliente y otros que no.
    """

    def __init__(self, application: Gtk.Application) -> None:
        super().__init__(
            title=_("Preferencias"),
            transient_for=application.props.active_window,
            modal=True,
            resizable=False,
        )
        self._application = application
        config = settings.read_settings()

        box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=12,
            margin_top=16,
            margin_bottom=16,
            margin_start=16,
            margin_end=16,
        )
        self.set_child(box)

        box.append(Gtk.Label(label=_("Idioma"), xalign=0))
        self._language_dropdown = Gtk.DropDown.new_from_strings(_LANGUAGE_LABELS)
        current_language = config.get("language")
        self._language_dropdown.set_selected(
            _LANGUAGE_CODES.index(current_language) if current_language in _LANGUAGE_CODES else 0
        )
        box.append(self._language_dropdown)

        box.append(Gtk.Label(label=_("Tema"), xalign=0))
        self._theme_dropdown = Gtk.DropDown.new_from_strings(
            [_("Sistema"), _("Claro"), _("Oscuro")]
        )
        current_dark = config.get("dark_mode")
        self._theme_dropdown.set_selected(
            _THEME_VALUES.index(current_dark) if current_dark in _THEME_VALUES else 0
        )
        box.append(self._theme_dropdown)

        box.append(Gtk.Label(label=_("Aviso rojo antes de la fecha límite (días)"), xalign=0))
        ajuste_alerta = Gtk.Adjustment(
            value=max(0, min(30, int(config.get("dias_alerta_vencimiento", 1)))),
            lower=0,
            upper=30,
            step_increment=1,
            page_increment=7,
        )
        self._dias_alerta_spin = Gtk.SpinButton(adjustment=ajuste_alerta, numeric=True)
        self._dias_alerta_spin.set_tooltip_text(
            _("La bandera roja aparece cuando faltan estos días o menos")
        )
        box.append(self._dias_alerta_spin)

        box.append(Gtk.Label(label=_("Tarea estancada tras (días sin cambios)"), xalign=0))
        ajuste_estancada = Gtk.Adjustment(
            value=max(1, min(90, int(config.get("dias_estancada", 14)))),
            lower=1, upper=90, step_increment=1, page_increment=7,
        )
        self._dias_estancada_spin = Gtk.SpinButton(adjustment=ajuste_estancada, numeric=True)
        self._dias_estancada_spin.set_tooltip_text(
            _("Una tarea en curso sin ningún cambio durante estos días o más cuenta como estancada en Informes")
        )
        box.append(self._dias_estancada_spin)

        box.append(Gtk.Label(label=_("Barra de tareas resumen en el Gantt"), xalign=0))
        estilo_actual = config.get(
            "estilo_barra_resumen", gantt_drawing_area.ESTILO_RESUMEN_PROGRESO
        )
        self._estilo_resumen_botones: dict[str, Gtk.CheckButton] = {}
        primero: Gtk.CheckButton | None = None
        for valor, etiqueta in (
            (gantt_drawing_area.ESTILO_RESUMEN_PROGRESO, _("Píldora con progreso")),
            (gantt_drawing_area.ESTILO_RESUMEN_CORCHETES, _("Extremos en corchete")),
        ):
            fila = Gtk.Box(spacing=12, valign=Gtk.Align.CENTER)
            radio = Gtk.CheckButton(label=etiqueta, group=primero)
            if primero is None:
                primero = radio
            radio.set_active(valor == estilo_actual)
            fila.append(radio)
            fila.append(_VistaPreviaResumen(valor))
            box.append(fila)
            self._estilo_resumen_botones[valor] = radio

        box.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))
        titulo_gh = Gtk.Box(spacing=6)
        titulo_gh.append(Gtk.Image.new_from_icon_name("github-symbolic"))
        titulo_gh.append(Gtk.Label(label=_("Integración con GitHub"), xalign=0))
        box.append(titulo_gh)

        from gnomilestone.github import GitHubClient, GitHubError, obtener_token
        token_actual = obtener_token()
        info_gh = _("Sesión no detectada")
        if token_actual:
            try:
                usuario = GitHubClient(token_actual).obtener_usuario_actual()
                info_gh = _("Conectado como @{login}").format(login=usuario.login)
            except GitHubError:
                info_gh = _("Token configurado")

        lbl_estado_gh = Gtk.Label(label=info_gh, xalign=0)
        lbl_estado_gh.add_css_class("dim-label")
        box.append(lbl_estado_gh)

        self._github_token_entry = Gtk.PasswordEntry(
            placeholder_text=_("Personal Access Token (opcional si usas gh CLI)"),
            text=config.get("github_token", ""),
        )
        box.append(self._github_token_entry)

        hint = Gtk.Label(
            label=_("Los cambios se aplican reiniciando la aplicación."),
            xalign=0,
            wrap=True,
        )
        hint.add_css_class("dim-label")
        box.append(hint)

        apply_button = Gtk.Button(label=_("Aplicar y reiniciar"))
        apply_button.add_css_class("suggested-action")
        apply_button.connect("clicked", self._on_apply)
        box.append(apply_button)

    def _on_apply(self, _button: Gtk.Button) -> None:
        config = settings.read_settings()
        config["language"] = _LANGUAGE_CODES[self._language_dropdown.get_selected()]
        config["dark_mode"] = _THEME_VALUES[self._theme_dropdown.get_selected()]
        config["dias_alerta_vencimiento"] = self._dias_alerta_spin.get_value_as_int()
        config["dias_estancada"] = self._dias_estancada_spin.get_value_as_int()
        config["estilo_barra_resumen"] = next(
            valor for valor, radio in self._estilo_resumen_botones.items() if radio.get_active()
        )
        token_ingresado = self._github_token_entry.get_text().strip()
        config["github_token"] = token_ingresado if token_ingresado else None
        settings.write_settings(config)
        # Un exec-in-place (os.execv) conserva el PID y, con él, los descriptores de
        # fichero abiertos: la conexión D-Bus donde esta app ya está registrada como
        # instancia única sigue "viva" para el bus, así que el proceso reaparecido se
        # ve a sí mismo como instancia secundaria y se cierra sin mostrar ventana.
        # Lanzar un proceso de verdad aparte y cerrar este con quit() evita el problema.
        #
        # El ejecutable se toma de /proc/self/exe, no de sys.executable: el lanzador
        # instalado hace "exec -a gnomilestone python3 -m gnomilestone.app" para que el
        # icono del dock salga bien, y ese "-a" engaña a sys.executable (apunta al propio
        # script /usr/bin/gnomilestone en vez de al intérprete real); /proc/self/exe
        # resuelve siempre al binario de verdad, venga o no de un venv.
        subprocess.Popen(
            ["/proc/self/exe", "-m", "gnomilestone.app"], start_new_session=True
        )
        self._application.quit()
