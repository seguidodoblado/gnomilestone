from __future__ import annotations

import faulthandler
import os
import signal
import sys
from pathlib import Path

import gi

gi.require_version("Gdk", "4.0")
gi.require_version("Gtk", "4.0")
from gi.repository import Gdk, GLib, Gtk

from gnomilestone import i18n, settings, theme
from gnomilestone.ui.window import MainWindow

APPLICATION_ID = "io.github.seguidodoblado.GnoMilestone"

# Con "python3 -m" argv[0] es la ruta de __main__.py y GTK derivaría de ahí el WM_CLASS;
# se fija para que coincida con StartupWMClass del .desktop y el panel muestre el icono.
GLib.set_prgname("gnomilestone")

_ICONOS = Path(__file__).resolve().parent / "assets" / "icons"


class GnoMilestoneApplication(Gtk.Application):
    def __init__(self) -> None:
        super().__init__(application_id=APPLICATION_ID)
        self.system_theme: str | None = None

    def do_activate(self) -> None:
        window = self.props.active_window
        if window is None:
            # El tema del sistema se captura antes de tocar gtk-theme-name, para
            # poder derivar la variante oscura sin perder el acento del usuario
            # (p. ej. Mint-Y-Orange) ni al volver a "Sistema" más adelante.
            self.system_theme = Gtk.Settings.get_default().get_property("gtk-theme-name")
            dark = settings.read_settings().get("dark_mode")
            if dark is not None:
                Gtk.Settings.get_default().set_property(
                    "gtk-theme-name", theme.theme_variant(self.system_theme, bool(dark))
                )
            # Iconos propios (p. ej. «etiqueta-symbolic»), con la estructura de un tema
            # (hicolor/scalable/actions) para que GTK los trate como simbólicos y los
            # recolore según el tema, también el oscuro. Funciona desde el código fuente y
            # en el .deb sin depender del tema de iconos del usuario.
            Gtk.IconTheme.get_for_display(Gdk.Display.get_default()).add_search_path(str(_ICONOS))
            window = MainWindow(self)
        window.present()


def main() -> int:
    # Diagnóstico de cuelgues: `kill -USR1 <pid>` vuelca en la terminal la pila de Python
    # de todos los hilos sin cerrar la aplicación.
    faulthandler.register(signal.SIGUSR1, all_threads=True)
    language = settings.read_settings().get("language")
    if language:
        os.environ["LANGUAGE"] = language
    else:
        os.environ.pop("LANGUAGE", None)
    i18n.install()
    app = GnoMilestoneApplication()
    return app.run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())
