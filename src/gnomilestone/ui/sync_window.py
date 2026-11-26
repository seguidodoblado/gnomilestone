from __future__ import annotations

import logging
from collections.abc import Callable

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk

from gnomilestone import proveedores
from gnomilestone.github import GitHubClient, GitHubError
from gnomilestone.i18n import _
from gnomilestone.models import Proyecto
from gnomilestone.proveedores import PROVEEDORES, Proveedor
from gnomilestone.store import Store
from gnomilestone.sync import GitHubSyncManager

log = logging.getLogger(__name__)


def _etiqueta_con_icono(texto: str, icon_name: str) -> Gtk.Widget:
    fila = Gtk.Box(spacing=6)
    icono = Gtk.Image.new_from_icon_name(icon_name)
    icono.add_css_class("dim-label")
    fila.append(icono)
    fila.append(Gtk.Label(label=texto, xalign=0))
    return fila


def _boton_con_icono(texto: str, icon_name: str) -> Gtk.Button:
    boton = Gtk.Button()
    contenido = Gtk.Box(spacing=6)
    contenido.append(Gtk.Image.new_from_icon_name(icon_name))
    contenido.append(Gtk.Label(label=texto))
    boton.set_child(contenido)
    return boton


class SyncWindow(Gtk.Window):
    """Ventana de sincronización: una página por proveedor (ahora solo GitHub) con el vínculo
    del proyecto y las plantillas propias de la plataforma. Un proyecto tiene una sola
    conexión: guardar el vínculo en una página fija ese proveedor como el del proyecto."""

    def __init__(
        self, parent: Gtk.Window, store: Store, proyecto: Proyecto, on_linked: Callable[[], None]
    ) -> None:
        super().__init__(
            title=_("Sincronización"),
            transient_for=parent,
            modal=True,
            default_width=480,
        )
        self._store = store
        self._proyecto = proyecto
        self._on_linked = on_linked

        pila = Gtk.Stack()
        # Cada proveedor registrado en proveedores.py aporta su página; las que aún no tienen
        # constructor propio (proveedores sin implementar) no se muestran.
        constructores = {"github": self._pagina_github}
        for proveedor in PROVEEDORES.values():
            if proveedor.id in constructores:
                pila.add_titled(constructores[proveedor.id](proveedor), proveedor.id, proveedor.nombre)
        pila.set_visible_child_name(proveedores.obtener(proyecto.proveedor).id)
        if len(PROVEEDORES) > 1:
            raiz = Gtk.Box()
            raiz.append(Gtk.StackSidebar(stack=pila))
            raiz.append(pila)
            self.set_child(raiz)
        else:
            self.set_child(pila)

    def _pagina_github(self, proveedor: Proveedor) -> Gtk.Widget:
        self._proveedor = proveedor
        self._client = GitHubClient()
        proyecto = self._proyecto
        box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=12,
            margin_top=16,
            margin_bottom=16,
            margin_start=16,
            margin_end=16,
        )

        titulo = Gtk.Box(spacing=8)
        icono_titulo = Gtk.Image.new_from_icon_name(proveedor.icono)
        icono_titulo.set_pixel_size(24)
        titulo.append(icono_titulo)
        etiqueta_titulo = Gtk.Label(label=_("Vincular con GitHub"), xalign=0)
        etiqueta_titulo.add_css_class("title-3")
        titulo.append(etiqueta_titulo)
        box.append(titulo)

        # Propietario (Owner)
        box.append(_etiqueta_con_icono(_("Usuario u Organización de GitHub"), "avatar-default-symbolic"))
        owner_default = proyecto.github_repo_owner or ""
        if not owner_default:
            try:
                owner_default = self._client.obtener_usuario_actual().login
            except GitHubError:
                owner_default = ""

        self._owner_entry = Gtk.Entry(text=owner_default, placeholder_text="ej. seguidodoblado")
        self._owner_entry.connect("changed", self._on_owner_changed)
        box.append(self._owner_entry)

        # Repositorio
        box.append(
            _etiqueta_con_icono(
                _("Repositorio (opcional para sincronizar Issues)"), "folder-remote-symbolic"
            )
        )
        self._repo_dropdown = Gtk.DropDown.new_from_strings([_("Ninguno")])
        self._repos: list[str] = [""]
        box.append(self._repo_dropdown)

        # Proyecto V2
        box.append(
            _etiqueta_con_icono(
                _("GitHub Project V2 (opcional para Tablero y fechas)"), "view-grid-symbolic"
            )
        )
        self._project_dropdown = Gtk.DropDown.new_from_strings([_("Ninguno")])
        self._projects: list[tuple[str, str]] = [("", "")]  # (id, number)
        box.append(self._project_dropdown)

        # Botón cargar
        load_btn = _boton_con_icono(_("Cargar repositorios y proyectos"), "view-refresh-symbolic")
        load_btn.connect("clicked", lambda _b: self._cargar_opciones())
        box.append(load_btn)

        self._status_label = Gtk.Label(xalign=0)
        self._status_label.add_css_class("dim-label")
        box.append(self._status_label)

        # Plantillas propias de GitHub
        box.append(Gtk.Separator(margin_top=6))
        box.append(_etiqueta_con_icono(_("Plantillas de GitHub"), "document-new-symbolic"))
        flujo_btn = _boton_con_icono(
            _("Usar el flujo de estados de GitHub"), "view-grid-symbolic"
        )
        flujo_btn.connect("clicked", self._on_aplicar_flujo)
        box.append(flujo_btn)
        etiquetas_btn = _boton_con_icono(
            _("Añadir las etiquetas por defecto de GitHub"), "etiqueta-symbolic"
        )
        etiquetas_btn.connect("clicked", self._on_aplicar_etiquetas)
        box.append(etiquetas_btn)
        self._plantillas_label = Gtk.Label(xalign=0, wrap=True)
        self._plantillas_label.add_css_class("dim-label")
        box.append(self._plantillas_label)

        # Botón guardar
        btn_box = Gtk.Box(spacing=8, halign=Gtk.Align.END, margin_top=12)
        cancel_btn = _boton_con_icono(_("Cancelar"), "window-close-symbolic")
        cancel_btn.connect("clicked", lambda _b: self.destroy())
        btn_box.append(cancel_btn)

        save_btn = _boton_con_icono(_("Guardar vinculación"), "emblem-ok-symbolic")
        save_btn.add_css_class("suggested-action")
        save_btn.connect("clicked", self._on_save)
        btn_box.append(save_btn)
        box.append(btn_box)

        if owner_default:
            self._cargar_opciones()
        return box

    def _on_owner_changed(self, _entry: Gtk.Entry) -> None:
        pass

    def _cargar_opciones(self) -> None:
        owner = self._owner_entry.get_text().strip()
        if not owner:
            self._status_label.set_text(_("Introduce un propietario primero."))
            return

        self._status_label.set_text(_("Consultando GitHub…"))
        try:
            # 1. Repos
            repos = self._client.listar_repositorios()
            repo_names = [_("Ninguno")]
            self._repos = [""]
            for r in repos:
                if r.owner.lower() == owner.lower() or not owner:
                    repo_names.append(r.name)
                    self._repos.append(r.name)

            self._repo_dropdown.set_model(Gtk.StringList.new(repo_names))
            if self._proyecto.github_repo_name in self._repos:
                self._repo_dropdown.set_selected(self._repos.index(self._proyecto.github_repo_name))

            # 2. Projects V2
            projs = self._client.listar_proyectos_v2(owner)
            proj_titles = [_("Ninguno")]
            self._projects = [("", "")]
            for p in projs:
                proj_titles.append(f"#{p.number} - {p.title}")
                self._projects.append((p.id, str(p.number)))

            self._project_dropdown.set_model(Gtk.StringList.new(proj_titles))
            sel_idx = 0
            for idx, (_pid, pnum) in enumerate(self._projects):
                if self._proyecto.github_project_v2_id in (_pid, pnum):
                    sel_idx = idx
                    break
            self._project_dropdown.set_selected(sel_idx)

            self._status_label.set_text(_("Datos cargados correctamente."))
        except Exception as e:
            log.exception("Error al cargar repos/proyectos de GitHub")
            self._status_label.set_text(_("Error al conectar con GitHub: {error}").format(error=str(e)))

    def _on_save(self, _button: Gtk.Button) -> None:
        owner = self._owner_entry.get_text().strip() or None
        sel_repo_idx = self._repo_dropdown.get_selected()
        repo = self._repos[sel_repo_idx] if sel_repo_idx < len(self._repos) and self._repos[sel_repo_idx] else None

        sel_proj_idx = self._project_dropdown.get_selected()
        project_num = (
            self._projects[sel_proj_idx][1]
            if sel_proj_idx < len(self._projects) and self._projects[sel_proj_idx][1]
            else None
        )

        self._proyecto.proveedor = self._proveedor.id
        self._proyecto.github_repo_owner = owner
        self._proyecto.github_repo_name = repo
        self._proyecto.github_project_v2_id = project_num
        self._store.actualizar_proyecto(self._proyecto)

        self._on_linked()
        self.destroy()

    def _on_aplicar_flujo(self, _button: Gtk.Button) -> None:
        informe = self._store.aplicar_flujo(self._proyecto.id, self._proveedor.flujo_estados)
        # Sin esto el siguiente pull traería de vuelta las columnas originales del Status.
        GitHubSyncManager(self._store).push_columnas(self._proyecto.id)
        self._plantillas_label.set_text(
            _("Flujo aplicado: {c} columnas creadas, {r} renombradas, {k} conservadas.").format(
                c=len(informe["creadas"]),
                r=len(informe["renombradas"]),
                k=len(informe["conservadas"]),
            )
        )
        self._on_linked()

    def _on_aplicar_etiquetas(self, _button: Gtk.Button) -> None:
        creadas = self._store.aplicar_etiquetas(
            self._proyecto.id, self._proveedor.etiquetas_por_defecto
        )
        self._plantillas_label.set_text(
            _("Etiquetas añadidas: {n}.").format(n=len(creadas))
        )
        self._on_linked()
