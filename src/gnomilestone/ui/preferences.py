from __future__ import annotations

import subprocess

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk

from gnomilestone import settings
from gnomilestone.i18n import _

# Los nombres de idioma no se traducen (convención habitual en selectores de idioma):
# "English" se ve igual estando la app en español, y viceversa.
_LANGUAGE_CODES: list[str | None] = [None, "es", "en"]
_LANGUAGE_LABELS = [_("Sistema"), "Español", "English"]

_THEME_VALUES: list[bool | None] = [None, False, True]


class PreferencesWindow(Gtk.Window):
    """Idioma y tema (claro/oscuro), persistidos en ~/.config/gnomilestone/settings.json.

    Ambos requieren reiniciar la aplicación para aplicarse: el idioma porque la
    mayoría de los textos ya están fijados en los widgets al construir la interfaz,
    y el tema porque cambiar gtk-theme-name en caliente no repinta la ventana en
    Cinnamon/Mint.
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
