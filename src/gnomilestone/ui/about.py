from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk

from gnomilestone import __version__
from gnomilestone.i18n import _


def build_about_dialog(parent: Gtk.Window) -> Gtk.AboutDialog:
    about = Gtk.AboutDialog(
        transient_for=parent,
        modal=True,
        program_name="GnoMilestone",
        version=__version__,
        logo_icon_name="gnomilestone",
        comments=_("Gestor de proyectos con diagrama de Gantt e integración con GitHub"),
        website="https://github.com/seguidodoblado/gnomilestone",
        website_label=_("github.com/seguidodoblado/gnomilestone"),
        authors=["José Antonio Seguido Doblado <jose.antonio.seguido@gmail.com>"],
        copyright="© 2026 José Antonio Seguido Doblado",
        license_type=Gtk.License.GPL_3_0,
        translator_credits=_("translator-credits"),
    )
    about.add_credit_section(_("Datos de terceros"), ["GitHub API — https://docs.github.com/rest"])
    return about
