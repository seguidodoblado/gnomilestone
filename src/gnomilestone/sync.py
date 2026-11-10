from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from datetime import date

from gnomilestone import completado, contexto_github, ganttcalc
from gnomilestone.github import (
    GitHubClient,
    GitHubError,
    GitHubItem,
    GitHubNotFoundError,
    GitHubStatusOption,
)
from gnomilestone.models import Recurso, Tarea
from gnomilestone.prioridad import nivel_desde_opcion, opcion_para_nivel
from gnomilestone.store import Store

log = logging.getLogger(__name__)

# Mientras se reemplazan las opciones del Status en GitHub (ids nuevos, items en blanco) no
# debe leerse ni escribirse nada del proyecto: un pull o un push en ese intervalo vería
# las tareas sin estado, o usaría ids viejos. Reentrante porque un push puede llamar a otro.
_BLOQUEO_PROYECTO = threading.RLock()


@dataclass
class SyncResult:
    tareas_creadas: int = 0
    tareas_actualizadas: int = 0
    estados_creados: int = 0
    recursos_creados: int = 0
    documentos_actualizados: int = 0  # notas de «Contexto del proyecto» traídas del repositorio
    errores: list[str] | None = None
    conflictos: list[str] | None = None

    def __post_init__(self) -> None:
        if self.errores is None:
            self.errores = []
        if self.conflictos is None:
            self.conflictos = []


class GitHubSyncManager:
    """Gestiona la sincronización bidireccional entre GnoMilestone y GitHub."""

    def __init__(self, store: Store, client: GitHubClient | None = None) -> None:
        self._store = store
        self._client = client or GitHubClient()

    # -- Eliminación ----------------------------------------------------------

    def eliminar_tarea(self, tarea_id: int, *, en_segundo_plano: bool = True) -> None:
        """Elimina la tarea (y sus subtareas) en local y, si el proyecto está vinculado con
        GitHub, también allí: borra el issue (o lo cierra como no planificado si no hay
        permisos) y quita el item del Project V2. El borrado local no espera a la red."""
        tarea = self._store.obtener_tarea(tarea_id)
        if tarea is None:
            return
        vinculos = self._store.vinculos_github_de_arbol(tarea_id)
        proyecto = self._store.obtener_proyecto(tarea.proyecto_id)
        self._store.eliminar_tarea(tarea_id)
        if not vinculos or not proyecto or not proyecto.github_repo_owner:
            return
        if en_segundo_plano:
            threading.Thread(
                target=self._eliminar_en_github, args=(proyecto, vinculos), daemon=True
            ).start()
        else:
            self._eliminar_en_github(proyecto, vinculos)

    def _eliminar_en_github(self, proyecto, vinculos) -> None:
        owner = proyecto.github_repo_owner
        repo = proyecto.github_repo_name
        project_id: str | None = None
        for issue_number, item_id in vinculos:
            try:
                if issue_number and repo:
                    self._client.eliminar_issue(owner, repo, issue_number)
                elif item_id and proyecto.github_project_v2_id:
                    if project_id is None:
                        project_id = self._id_proyecto_v2(proyecto)
                    if project_id:
                        self._client.eliminar_item_v2(project_id, item_id)
            except Exception:  # el borrado local ya está hecho: se registra y se sigue
                log.exception("No se pudo eliminar en GitHub (issue %s, item %s)", issue_number, item_id)

    def _id_proyecto_v2(self, proyecto) -> str | None:
        valor = proyecto.github_project_v2_id
        if not valor.isdigit():
            return valor
        meta, _opts, _items = self._client.obtener_detalles_proyecto_v2(
            proyecto.github_repo_owner, int(valor)
        )
        return meta.get("id")

    # -- Pull (GitHub -> GnoMilestone) ---------------------------------------

    def pull_proyecto(self, proyecto_id: int) -> SyncResult:
        """Sincroniza desde GitHub hacia el proyecto local."""
        with _BLOQUEO_PROYECTO:
            return self._pull_proyecto(proyecto_id)

    def _pull_proyecto(self, proyecto_id: int) -> SyncResult:
        resultado = SyncResult()
        proyecto = self._store.obtener_proyecto(proyecto_id)
        if not proyecto:
            resultado.errores.append(f"El proyecto con id {proyecto_id} no existe.")
            return resultado

        owner = proyecto.github_repo_owner
        repo_name = proyecto.github_repo_name
        project_v2_id = proyecto.github_project_v2_id

        if not owner:
            resultado.errores.append("El proyecto no tiene configurado propietario de GitHub.")
            return resultado

        # 1. Si hay Project V2 vinculado, sincronizar columnas de estado e items
        items_v2: list[GitHubItem] = []
        status_map: dict[str, int] = {}  # status_option_id o name -> estado_id

        estados_existentes = self._store.listar_estados(proyecto_id)
        for est in estados_existentes:
            if est.github_option_id:
                status_map[est.github_option_id] = est.id
            status_map[est.nombre.strip().lower()] = est.id

        if project_v2_id:
            try:
                # project_v2_id puede ser el número o el ID del proyecto
                num = int(project_v2_id) if project_v2_id.isdigit() else None
                if num is None:
                    # Si era node ID, listar para buscar su número
                    for p in self._client.listar_proyectos_v2(owner):
                        if p.id == project_v2_id:
                            num = p.number
                            break

                if num is not None:
                    _meta, status_options, items_v2 = self._client.obtener_detalles_proyecto_v2(owner, num)

                    # Crear o asociar estados
                    for opt in status_options:
                        estado_existente = next(
                            (e for e in estados_existentes if e.github_option_id == opt.id or e.nombre.strip().lower() == opt.name.strip().lower()),
                            None,
                        )
                        if estado_existente:
                            if estado_existente.github_option_id != opt.id:
                                self._store.asociar_github_option_estado(estado_existente.id, opt.id)
                            status_map[opt.id] = estado_existente.id
                            status_map[opt.name.strip().lower()] = estado_existente.id
                        else:
                            nuevo_estado = self._store.crear_estado(
                                proyecto_id=proyecto_id,
                                nombre=opt.name,
                                github_option_id=opt.id,
                            )
                            resultado.estados_creados += 1
                            estados_existentes.append(nuevo_estado)
                            status_map[opt.id] = nuevo_estado.id
                            status_map[opt.name.strip().lower()] = nuevo_estado.id
            except Exception as e:
                log.exception("Error al sincronizar Project V2")
                resultado.errores.append(f"Error sincronizando GitHub Project V2: {e}")

        # Recurso / Assignees cache
        recursos_por_nombre: dict[str, Recurso] = {
            r.nombre.lower(): r for r in self._store.listar_recursos(proyecto_id)
        }

        def _asegurar_recurso(login: str) -> Recurso:
            login_lower = login.lower()
            if login_lower in recursos_por_nombre:
                return recursos_por_nombre[login_lower]
            avatar = f"https://github.com/{login}.png?size=64"
            nuevo_recurso = self._store.crear_recurso(
                proyecto_id=proyecto_id,
                nombre=login,
                avatar_url=avatar,
            )
            recursos_por_nombre[login_lower] = nuevo_recurso
            resultado.recursos_creados += 1
            return nuevo_recurso

        def _en_conflicto(tarea: Tarea) -> bool:
            # Si la tarea se editó en local después del último sync con GitHub, un pull
            # no debe pisar esos cambios en silencio: se deja para que el usuario decida
            # (el próximo push mandará la versión local, que es la que gana si no se toca).
            return bool(
                tarea.actualizado
                and tarea.github_synced_at
                and tarea.actualizado > tarea.github_synced_at
            )

        # 2. Procesar items del Project V2
        procesados_issues: set[int] = set()

        for item in items_v2:
            if item.issue_number:
                procesados_issues.add(item.issue_number)

            tarea_existente = None
            if item.id:
                tarea_existente = self._store.obtener_tarea_por_github_item(item.id)
            if not tarea_existente and item.issue_number:
                tarea_existente = self._store.obtener_tarea_por_github_issue(proyecto_id, item.issue_number)
            if not tarea_existente and self._store.github_descartado(
                proyecto_id, item.issue_number, item.id
            ):
                continue

            estado_id = None
            if item.status_option_id and item.status_option_id in status_map:
                estado_id = status_map[item.status_option_id]
            elif item.status_name and item.status_name.strip().lower() in status_map:
                estado_id = status_map[item.status_name.strip().lower()]
            elif estados_existentes:
                estado_id = estados_existentes[0].id

            # Fechas y duración
            fecha_inicio = item.start_date
            duracion_dias = 1
            if item.start_date and item.target_date:
                try:
                    f_ini = date.fromisoformat(item.start_date)
                    f_fin = date.fromisoformat(item.target_date)
                    # La fecha objetivo es un día inclusive, igual que la duración local.
                    duracion_dias = max((f_fin - f_ini).days + 1, 1)
                except ValueError:
                    duracion_dias = 1
            elif not fecha_inicio and item.target_date:
                fecha_inicio = item.target_date

            es_hito = False
            if item.milestone_title and not item.start_date and item.target_date:
                # O si tiene etiqueta milestone
                pass

            conflicto_item = False
            nivel_prioridad = nivel_desde_opcion(item.priority_name)
            if tarea_existente:
                if _en_conflicto(tarea_existente):
                    conflicto_item = True
                    resultado.conflictos.append(
                        f"'{tarea_existente.titulo}' se editó en local después del último "
                        "sync: no se han traído los cambios de GitHub para no perder los tuyos."
                    )
                    tarea_id = tarea_existente.id
                else:
                    # Actualizar campos locales si han cambiado
                    modificada = False
                    if tarea_existente.titulo != item.title:
                        tarea_existente.titulo = item.title
                        modificada = True
                    if item.body and tarea_existente.descripcion != item.body:
                        tarea_existente.descripcion = item.body
                        modificada = True
                    if estado_id is not None and tarea_existente.estado_id != estado_id:
                        completado.al_cambiar_de_columna(
                            tarea_existente, estado_id, estados_existentes
                        )
                        tarea_existente.estado_id = estado_id
                        modificada = True
                    if fecha_inicio and tarea_existente.fecha_inicio != fecha_inicio:
                        tarea_existente.fecha_inicio = fecha_inicio
                        modificada = True
                    if duracion_dias != tarea_existente.duracion_dias:
                        tarea_existente.duracion_dias = duracion_dias
                        modificada = True
                    if item.target_date:
                        if tarea_existente.fecha_fin_planificada != item.target_date:
                            tarea_existente.fecha_fin_planificada = item.target_date
                            modificada = True
                    else:
                        sincronizada = ganttcalc.sincronizar_fin_planificado(tarea_existente)
                        if sincronizada is not tarea_existente:
                            tarea_existente = sincronizada
                            modificada = True
                    if nivel_prioridad is not None and tarea_existente.prioridad != nivel_prioridad:
                        tarea_existente.prioridad = nivel_prioridad
                        modificada = True
                    if (
                        tarea_existente.github_item_id != item.id
                        or tarea_existente.github_url != item.url
                    ):
                        tarea_existente.github_item_id = item.id
                        tarea_existente.github_url = item.url
                        modificada = True

                    if modificada:
                        self._store.actualizar_tarea(tarea_existente)
                        resultado.tareas_actualizadas += 1
                    self._store.marcar_sincronizada_github(tarea_existente.id)
                    tarea_id = tarea_existente.id
            else:
                nueva = self._store.crear_tarea(
                    proyecto_id=proyecto_id,
                    titulo=item.title,
                    descripcion=item.body or "",
                    estado_id=estado_id,
                    fecha_inicio=fecha_inicio,
                    fecha_fin_planificada=item.target_date or fecha_inicio,
                    duracion_dias=duracion_dias,
                    es_hito=es_hito,
                    github_issue_number=item.issue_number,
                    github_item_id=item.id,
                    github_url=item.url,
                    prioridad=nivel_prioridad or 0,
                )
                resultado.tareas_creadas += 1
                self._store.marcar_sincronizada_github(nueva.id)
                tarea_id = nueva.id

            if not conflicto_item and item.labels is not None:
                self._aplicar_etiquetas(
                    proyecto_id, tarea_id, item.labels, item.label_colors or {}
                )

            # Asignaciones (solo añade recursos nuevos, nunca quita: seguro ante conflicto)
            if item.assignees:
                recursos_tarea = self._store.listar_recursos_de_tarea(tarea_id)
                asignados_ids = {r.id for r in recursos_tarea}
                for asignee in item.assignees:
                    rec = _asegurar_recurso(asignee)
                    if rec.id not in asignados_ids:
                        self._store.asignar_recurso(tarea_id, rec.id)

        # 3. Si hay un repo configurado, sincronizar los issues restantes del repo
        if repo_name:
            try:
                issues_repo = self._client.listar_issues(owner, repo_name, state="all")
                for issue in issues_repo:
                    num = issue.get("number")
                    if not num or num in procesados_issues or "pull_request" in issue:
                        continue

                    tarea_existente = self._store.obtener_tarea_por_github_issue(proyecto_id, num)
                    if not tarea_existente and self._store.github_descartado(proyecto_id, num, None):
                        continue
                    is_closed = issue.get("state") == "closed"
                    title = issue.get("title", "")
                    body = issue.get("body") or ""
                    url = issue.get("html_url")

                    # Estado por defecto según abierto/cerrado
                    estado_id = None
                    if is_closed:
                        # Buscar columna con nombre 'done', 'cerrado', 'terminado' o la última
                        for e in reversed(estados_existentes):
                            if any(k in e.nombre.lower() for k in ("done", "cerrad", "hech", "finaliz")):
                                estado_id = e.id
                                break
                    if estado_id is None and estados_existentes:
                        estado_id = estados_existentes[0].id

                    assignees = [a["login"] for a in issue.get("assignees", [])]
                    milestone = issue.get("milestone")
                    fecha_inicio = None
                    es_hito = False
                    if milestone and milestone.get("due_on"):
                        fecha_inicio = milestone["due_on"][:10]
                        es_hito = True

                    conflicto_issue = False
                    if tarea_existente:
                        if _en_conflicto(tarea_existente):
                            conflicto_issue = True
                            resultado.conflictos.append(
                                f"'{tarea_existente.titulo}' se editó en local después del "
                                "último sync: no se han traído los cambios de GitHub."
                            )
                            t_id = tarea_existente.id
                        else:
                            modificada = False
                            if tarea_existente.titulo != title:
                                tarea_existente.titulo = title
                                modificada = True
                            if body and tarea_existente.descripcion != body:
                                tarea_existente.descripcion = body
                                modificada = True
                            if is_closed and tarea_existente.porcentaje_completado < 100:
                                tarea_existente.porcentaje_completado = 100
                                modificada = True
                            if tarea_existente.github_url != url:
                                tarea_existente.github_url = url
                                modificada = True
                            if modificada:
                                self._store.actualizar_tarea(tarea_existente)
                                resultado.tareas_actualizadas += 1
                            self._store.marcar_sincronizada_github(tarea_existente.id)
                            t_id = tarea_existente.id
                    else:
                        nueva = self._store.crear_tarea(
                            proyecto_id=proyecto_id,
                            titulo=title,
                            descripcion=body,
                            estado_id=estado_id,
                            fecha_inicio=fecha_inicio,
                            fecha_fin_planificada=fecha_inicio,
                            es_hito=es_hito,
                            porcentaje_completado=100 if is_closed else 0,
                            github_issue_number=num,
                            github_url=url,
                        )
                        resultado.tareas_creadas += 1
                        self._store.marcar_sincronizada_github(nueva.id)
                        t_id = nueva.id

                    if not conflicto_issue:
                        etiquetas_issue = issue.get("labels") or []
                        self._aplicar_etiquetas(
                            proyecto_id,
                            t_id,
                            [e["name"] for e in etiquetas_issue],
                            {e["name"]: e["color"] for e in etiquetas_issue if e.get("color")},
                        )

                    if assignees:
                        recursos_tarea = self._store.listar_recursos_de_tarea(t_id)
                        asignados_ids = {r.id for r in recursos_tarea}
                        for login in assignees:
                            rec = _asegurar_recurso(login)
                            if rec.id not in asignados_ids:
                                self._store.asignar_recurso(t_id, rec.id)
            except Exception as e:
                log.exception("Error al sincronizar issues de repositorio")
                resultado.errores.append(f"Error sincronizando issues de {owner}/{repo_name}: {e}")
            self._pull_comentarios(proyecto_id, owner, repo_name, resultado)
            self._pull_contexto(proyecto_id, owner, repo_name, resultado)

        return resultado

    def _pull_contexto(self, proyecto_id: int, owner: str, repo_name: str, resultado: SyncResult) -> None:
        """Rellena las notas de «Contexto del proyecto» (README, código de conducta,
        contribución, licencia y seguridad) con los ficheros del repositorio. GitHub manda:
        si la nota difiere se sobrescribe, y su versión anterior queda en «Versiones»."""
        try:
            subsecciones = self._store.listar_subsecciones_documentacion(
                proyecto_id, contexto_github.SECCION
            )
            if not subsecciones:
                return
            documentos = contexto_github.traer_documentos(self._client, owner, repo_name)
            aplicado = contexto_github.aplicar_documentos(
                self._store, proyecto_id, subsecciones[0].id, documentos
            )
            resultado.documentos_actualizados += len(aplicado.actualizadas) + len(aplicado.creadas)
        except Exception as e:
            log.exception("Error al traer los ficheros de contexto del repositorio")
            resultado.errores.append(f"Error trayendo los ficheros de contexto de {owner}/{repo_name}: {e}")

    # -- Columnas del tablero -> campo Status del Project V2 ------------------------

    _COLORES_OPCION = ("BLUE", "GREEN", "YELLOW", "ORANGE", "RED", "PURPLE", "GRAY", "PINK")

    def push_columnas(self, proyecto_id: int, *, en_segundo_plano: bool = True) -> None:
        """Envía las columnas locales (nombres, orden, altas y bajas) al campo Status del
        Project V2 vinculado. Ojo: GitHub regenera los ids de las opciones, por lo que después
        se releen y se vuelve a enviar el estado de cada tarea con item."""
        proyecto = self._store.obtener_proyecto(proyecto_id)
        if not (proyecto and proyecto.github_repo_owner and proyecto.github_project_v2_id):
            return
        if en_segundo_plano:
            threading.Thread(
                target=self._push_columnas, args=(proyecto,), daemon=True
            ).start()
        else:
            self._push_columnas(proyecto)

    def _push_columnas(self, proyecto) -> None:
        with _BLOQUEO_PROYECTO:
            try:
                self._reemplazar_columnas(proyecto)
            except Exception:
                log.exception("No se pudieron enviar las columnas a GitHub")

    def _reemplazar_columnas(self, proyecto) -> None:
        valor = proyecto.github_project_v2_id
        num = int(valor) if valor.isdigit() else None
        if num is None:
            for p in self._client.listar_proyectos_v2(proyecto.github_repo_owner):
                if p.id == valor:
                    num = p.number
                    break
        if num is None:
            return
        meta, remotas, items_antes = self._client.obtener_detalles_proyecto_v2(
            proyecto.github_repo_owner, num
        )
        field_id = meta.get("status_field_id")
        estados = self._store.listar_estados(proyecto.id)
        if not field_id or not estados:
            return
        por_id = {o.id: o for o in remotas}
        por_nombre = {o.name.casefold(): o for o in remotas}
        deseadas = []
        nombre_por_opcion_vieja: dict[str, str] = {}  # id de opción antes -> columna (nombre nuevo)
        for indice, estado in enumerate(estados):
            previa = por_id.get(estado.github_option_id) or por_nombre.get(
                estado.nombre.casefold()
            )
            if previa:
                nombre_por_opcion_vieja[previa.id] = estado.nombre
            deseadas.append(
                GitHubStatusOption(
                    id="",
                    name=estado.nombre,
                    color=previa.color if previa else self._COLORES_OPCION[indice % 8],
                    description=previa.description if previa else "",
                )
            )
        self._client.reemplazar_opciones_status(field_id, deseadas)

        # Los ids han cambiado: se relee y se reasocia cada columna por su nombre.
        _meta, nuevas, _items = self._client.obtener_detalles_proyecto_v2(
            proyecto.github_repo_owner, num
        )
        nuevas_por_nombre = {o.name.casefold(): o for o in nuevas}
        for estado in estados:
            opcion = nuevas_por_nombre.get(estado.nombre.casefold())
            self._store.asociar_github_option_estado(estado.id, opcion.id if opcion else None)

        # GitHub deja los items sin Status: se restituye el que tenían ANTES del cambio
        # (la verdad remota, incluidos items que no estén en local); los items sin estado
        # remoto, pero con tarea local, reciben el de su tarea.
        restituidos: set[str] = set()
        for item in items_antes:
            nombre = nombre_por_opcion_vieja.get(item.status_option_id or "")
            opcion = nuevas_por_nombre.get(nombre.casefold()) if nombre else None
            if opcion:
                self._fijar_status(meta["id"], item.id, field_id, opcion.id)
                restituidos.add(item.id)
        por_estado = {e.id: nuevas_por_nombre.get(e.nombre.casefold()) for e in estados}
        items_del_proyecto = {item.id for item in items_antes}
        for tarea in self._store.listar_tareas(proyecto.id, incluir_archivadas=True):
            opcion = por_estado.get(tarea.estado_id)
            # Solo items que siguen en el proyecto: una tarea puede conservar el id de un
            # item que ya no existe (borrado en GitHub o de otro proyecto) y fallaría.
            if (
                tarea.github_item_id in items_del_proyecto
                and tarea.github_item_id not in restituidos
                and opcion
            ):
                self._fijar_status(meta["id"], tarea.github_item_id, field_id, opcion.id)

    def _fijar_status(self, project_id: str, item_id: str, field_id: str, option_id: str) -> None:
        try:
            self._client.actualizar_status_item_v2(
                project_id=project_id,
                item_id=item_id,
                status_field_id=field_id,
                single_select_option_id=option_id,
            )
        except Exception:
            log.exception("No se pudo restituir el estado del item %s", item_id)

    # -- Gestión de etiquetas del proyecto ------------------------------------------

    def _repo_de(self, proyecto_id: int) -> tuple[str, str] | None:
        proyecto = self._store.obtener_proyecto(proyecto_id)
        if proyecto and proyecto.github_repo_owner and proyecto.github_repo_name:
            return proyecto.github_repo_owner, proyecto.github_repo_name
        return None

    def _en_remoto(self, accion, descripcion: str, en_segundo_plano: bool) -> None:
        def _ejecutar() -> None:
            try:
                accion()
            except Exception:
                log.exception("No se pudo %s en GitHub", descripcion)

        if en_segundo_plano:
            threading.Thread(target=_ejecutar, daemon=True).start()
        else:
            _ejecutar()

    def renombrar_etiqueta(
        self, etiqueta_id: int, nombre: str, *, en_segundo_plano: bool = True
    ) -> None:
        """Renombra la etiqueta en local (y en el repositorio vinculado, donde GitHub la
        renombra también en todos sus issues). Lanza `EtiquetaDuplicadaError` si ya existe."""
        etiqueta = self._store.obtener_etiqueta(etiqueta_id)
        nombre = nombre.strip()
        if etiqueta is None or not nombre or etiqueta.nombre == nombre:
            return
        self._store.renombrar_etiqueta(etiqueta_id, nombre)
        self._store.sustituir_en_bases_github(etiqueta.proyecto_id, etiqueta.nombre, nombre)
        repo = self._repo_de(etiqueta.proyecto_id)
        if repo:
            def _renombrar() -> None:
                try:
                    self._client.actualizar_etiqueta(*repo, etiqueta.nombre, nuevo_nombre=nombre)
                except GitHubNotFoundError:
                    # Aún no existía en el repositorio: se creará con el nombre nuevo al
                    # enviar la primera tarea que la lleve.
                    log.info("La etiqueta %s no existe en GitHub; nada que renombrar", etiqueta.nombre)

            self._en_remoto(_renombrar, "renombrar la etiqueta", en_segundo_plano)

    def cambiar_color_etiqueta(
        self, etiqueta_id: int, color: str, *, en_segundo_plano: bool = True
    ) -> None:
        etiqueta = self._store.obtener_etiqueta(etiqueta_id)
        if etiqueta is None or etiqueta.color == color.lstrip("#"):
            return
        self._store.actualizar_color_etiqueta(etiqueta_id, color)
        repo = self._repo_de(etiqueta.proyecto_id)
        if repo:
            def _recolorear() -> None:
                try:
                    self._client.actualizar_etiqueta(*repo, etiqueta.nombre, color=color)
                except GitHubNotFoundError:
                    # No existe todavía en el repositorio: se crea ya con su color.
                    self._client.crear_etiqueta(*repo, etiqueta.nombre, color)

            self._en_remoto(_recolorear, "cambiar el color de la etiqueta", en_segundo_plano)

    def eliminar_etiqueta(self, etiqueta_id: int, *, en_segundo_plano: bool = True) -> None:
        """Borra la etiqueta de todas las tareas y, si hay repositorio vinculado, de GitHub
        (donde desaparece de todos sus issues)."""
        etiqueta = self._store.obtener_etiqueta(etiqueta_id)
        if etiqueta is None:
            return
        self._store.eliminar_etiqueta(etiqueta_id)
        self._store.sustituir_en_bases_github(etiqueta.proyecto_id, etiqueta.nombre, None)
        repo = self._repo_de(etiqueta.proyecto_id)
        if repo:
            def _eliminar() -> None:
                try:
                    self._client.eliminar_etiqueta(*repo, etiqueta.nombre)
                except GitHubNotFoundError:
                    log.info("La etiqueta %s no existe en GitHub; nada que borrar", etiqueta.nombre)

            self._en_remoto(_eliminar, "eliminar la etiqueta", en_segundo_plano)

    # -- Etiquetas y prioridad --------------------------------------------------

    def _aplicar_etiquetas(
        self, proyecto_id: int, tarea_id: int, nombres: list[str], colores: dict[str, str]
    ) -> None:
        """Deja la tarea con exactamente las etiquetas de GitHub (y recuerda cuáles eran)."""
        ids = [
            self._store.asegurar_etiqueta(proyecto_id, nombre, colores.get(nombre)).id
            for nombre in nombres
        ]
        self._store.establecer_etiquetas_de_tarea(tarea_id, ids)
        self._store.guardar_etiquetas_base_github(tarea_id, nombres)

    def _etiquetas_para_issue(self, owner: str, repo: str, tarea: Tarea, remotas: list[str]) -> list[str]:
        """Fusión a tres bandas de las etiquetas: lo que GitHub tiene ahora, lo que tenía
        en el último sync (base) y lo que hay en local. Así no se borran etiquetas ajenas
        puestas en GitHub desde el último sync."""
        locales = {e.nombre: e for e in self._store.listar_etiquetas_de_tarea(tarea.id)}
        base = self._store.etiquetas_base_github(tarea.id)
        locales_cf = {n.casefold() for n in locales}
        if base is None:
            # Nunca sincronizada: no se sabe qué se quitó en local, así que no se quita nada.
            base_cf = {n.casefold() for n in remotas}
            quitadas: set[str] = set()
        else:
            base_cf = {n.casefold() for n in base}
            quitadas = base_cf - locales_cf
        anadidas = [e for n, e in locales.items() if n.casefold() not in base_cf]
        for etiqueta in anadidas:
            if etiqueta.nombre.casefold() not in {n.casefold() for n in remotas}:
                try:
                    self._client.crear_etiqueta(owner, repo, etiqueta.nombre, etiqueta.color)
                except Exception:
                    log.exception("No se pudo crear la etiqueta %s en GitHub", etiqueta.nombre)
        resultado = [n for n in remotas if n.casefold() not in quitadas]
        resultado += [
            e.nombre for e in anadidas if e.nombre.casefold() not in {n.casefold() for n in resultado}
        ]
        return resultado

    # -- Comentarios ------------------------------------------------------------

    def _pull_comentarios(
        self, proyecto_id: int, owner: str, repo: str, resultado: SyncResult
    ) -> None:
        """Trae los comentarios de los issues (alta, cambios y borrados) y publica los
        comentarios locales que aún no se habían podido enviar."""
        try:
            remotos = self._client.listar_comentarios_repo(owner, repo)
        except Exception as e:
            log.exception("Error al traer comentarios de %s/%s", owner, repo)
            resultado.errores.append(f"Error sincronizando comentarios de {owner}/{repo}: {e}")
            return
        vistos: set[int] = set()
        tareas_con_comentarios: set[int] = set()
        for c in remotos:
            try:
                numero = int(str(c.get("issue_url", "")).rstrip("/").rsplit("/", 1)[-1])
            except ValueError:
                continue
            tarea = self._store.obtener_tarea_por_github_issue(proyecto_id, numero)
            if tarea is None:
                continue
            tareas_con_comentarios.add(tarea.id)
            vistos.add(c["id"])
            cuerpo = c.get("body") or ""
            existente = self._store.obtener_comentario_por_github(c["id"])
            if existente is None:
                self._store.crear_comentario(
                    tarea.id,
                    cuerpo,
                    autor=(c.get("user") or {}).get("login", ""),
                    creado=c.get("created_at"),
                    github_comment_id=c["id"],
                )
            elif existente.pendiente_envio:
                # Editado en local y sin enviar: no se pisa; el envío de más abajo manda la
                # versión local (igual que con las tareas editadas en local).
                if existente.cuerpo != cuerpo:
                    resultado.conflictos.append(
                        f"Un comentario de '{tarea.titulo}' se editó en local: "
                        "no se han traído los cambios de GitHub."
                    )
            elif existente.cuerpo != cuerpo:
                self._store.actualizar_comentario(existente.id, cuerpo=cuerpo)
        # Comentarios que ya no existen en GitHub (borrados allí).
        for tarea in self._store.listar_tareas(proyecto_id, incluir_archivadas=True):
            if tarea.github_issue_number is None:
                continue
            for local in self._store.listar_comentarios(tarea.id):
                if local.github_comment_id is not None and local.github_comment_id not in vistos:
                    self._store.eliminar_comentario(local.id)
        for pendiente in self._store.listar_comentarios_sin_enviar(proyecto_id):
            self.push_comentario(pendiente.id)
        for editado in self._store.listar_ediciones_sin_enviar(proyecto_id):
            self.push_edicion_comentario(editado.id)

    def editar_comentario(
        self, comentario_id: int, cuerpo: str, *, en_segundo_plano: bool = True
    ) -> None:
        """Cambia el texto en local y, si el comentario está en GitHub, lo envía allí."""
        comentario = self._store.obtener_comentario(comentario_id)
        if comentario is None or comentario.cuerpo == cuerpo:
            return
        publicado = comentario.github_comment_id is not None
        self._store.actualizar_comentario(
            comentario_id, cuerpo=cuerpo, pendiente_envio=publicado
        )
        if not publicado:
            return  # aún sin publicar: ya saldrá con el texto nuevo
        if en_segundo_plano:
            threading.Thread(
                target=self.push_edicion_comentario, args=(comentario_id,), daemon=True
            ).start()
        else:
            self.push_edicion_comentario(comentario_id)

    def push_edicion_comentario(self, comentario_id: int) -> bool:
        comentario = self._store.obtener_comentario(comentario_id)
        if comentario is None or comentario.github_comment_id is None:
            return False
        tarea = self._store.obtener_tarea(comentario.tarea_id)
        proyecto = self._store.obtener_proyecto(tarea.proyecto_id) if tarea else None
        if not (proyecto and proyecto.github_repo_owner and proyecto.github_repo_name):
            return False
        try:
            self._client.actualizar_comentario(
                proyecto.github_repo_owner,
                proyecto.github_repo_name,
                comentario.github_comment_id,
                comentario.cuerpo,
            )
        except Exception:
            log.exception("No se pudo enviar la edición del comentario %s", comentario_id)
            return False
        self._store.actualizar_comentario(comentario_id, pendiente_envio=False)
        return True

    def push_comentario(self, comentario_id: int) -> bool:
        """Publica un comentario local en el issue de su tarea. False si no se pudo."""
        comentario = self._store.obtener_comentario(comentario_id)
        if comentario is None or comentario.github_comment_id is not None:
            return False
        tarea = self._store.obtener_tarea(comentario.tarea_id)
        proyecto = self._store.obtener_proyecto(tarea.proyecto_id) if tarea else None
        if not (
            tarea
            and tarea.github_issue_number
            and proyecto
            and proyecto.github_repo_owner
            and proyecto.github_repo_name
        ):
            return False
        try:
            res = self._client.crear_comentario(
                proyecto.github_repo_owner,
                proyecto.github_repo_name,
                tarea.github_issue_number,
                comentario.cuerpo,
            )
        except Exception:
            log.exception("No se pudo publicar el comentario %s en GitHub", comentario_id)
            return False
        self._store.actualizar_comentario(
            comentario_id,
            autor=(res.get("user") or {}).get("login", comentario.autor),
            github_comment_id=res["id"],
        )
        return True

    def eliminar_comentario(self, comentario_id: int, *, en_segundo_plano: bool = True) -> None:
        """Elimina el comentario en local y, si estaba publicado, también en GitHub."""
        comentario = self._store.obtener_comentario(comentario_id)
        if comentario is None:
            return
        tarea = self._store.obtener_tarea(comentario.tarea_id)
        proyecto = self._store.obtener_proyecto(tarea.proyecto_id) if tarea else None
        self._store.eliminar_comentario(comentario_id)
        if not (
            comentario.github_comment_id
            and proyecto
            and proyecto.github_repo_owner
            and proyecto.github_repo_name
        ):
            return

        def _borrar() -> None:
            try:
                self._client.eliminar_comentario(
                    proyecto.github_repo_owner, proyecto.github_repo_name, comentario.github_comment_id
                )
            except Exception:
                log.exception("No se pudo borrar el comentario %s en GitHub", comentario.github_comment_id)

        if en_segundo_plano:
            threading.Thread(target=_borrar, daemon=True).start()
        else:
            _borrar()

    # -- Push (GnoMilestone -> GitHub) ---------------------------------------

    def push_tarea(self, tarea_id: int) -> bool:
        """Envía o actualiza una tarea local en GitHub (Issue o Item de Project V2)."""
        with _BLOQUEO_PROYECTO:
            return self._push_tarea(tarea_id)

    def _push_tarea(self, tarea_id: int) -> bool:
        tarea = self._store.obtener_tarea(tarea_id)
        if not tarea:
            return False

        proyecto = self._store.obtener_proyecto(tarea.proyecto_id)
        if not proyecto or not proyecto.github_repo_owner:
            return False

        owner = proyecto.github_repo_owner
        repo = proyecto.github_repo_name

        asignados = [r.nombre for r in self._store.listar_recursos_de_tarea(tarea_id)]

        try:
            # 1. Si ya tiene issue number asociado, actualizar el issue en GitHub
            if tarea.github_issue_number and repo:
                estado_issue = "closed" if tarea.porcentaje_completado >= 100 else "open"
                try:
                    remotas = [
                        e["name"]
                        for e in self._client.obtener_issue(
                            owner, repo, tarea.github_issue_number
                        ).get("labels", [])
                    ]
                    etiquetas: list[str] | None = self._etiquetas_para_issue(
                        owner, repo, tarea, remotas
                    )
                except GitHubError:
                    # Sin poder leer las etiquetas remotas no se tocan (la fusión necesita lo
                    # que GitHub tiene ahora), pero el resto de la tarea se envía igual.
                    log.warning("No se pudieron leer las etiquetas del issue; se omiten")
                    etiquetas = None
                self._client.actualizar_issue(
                    owner=owner,
                    repo=repo,
                    number=tarea.github_issue_number,
                    titulo=tarea.titulo,
                    body=tarea.descripcion,
                    state=estado_issue,
                    assignees=asignados or None,
                    labels=etiquetas,
                )
                if etiquetas is not None:
                    self._store.guardar_etiquetas_base_github(tarea.id, etiquetas)
            elif repo and not tarea.github_issue_number:
                # Si no tiene issue y el proyecto tiene repo vinculado, crearlo
                etiquetas = self._etiquetas_para_issue(owner, repo, tarea, [])
                res = self._client.crear_issue(
                    owner=owner,
                    repo=repo,
                    titulo=tarea.titulo,
                    body=tarea.descripcion,
                    assignees=asignados or None,
                    **({"labels": etiquetas} if etiquetas else {}),
                )
                self._store.guardar_etiquetas_base_github(tarea.id, etiquetas)
                # Solo el vínculo: reescribir toda la fila con la copia leída al empezar el envío
                # pisaría lo que el usuario haya editado mientras tanto.
                self._store.vincular_issue_github(tarea.id, res.get("number"), res.get("html_url"))

            # 2. Si hay Project V2 y la tarea tiene item_id asociado, sincronizar estado y
            # fechas (campos "Start Date"/"Target Date", si el proyecto los tiene)
            if proyecto.github_project_v2_id and tarea.github_item_id:
                num = (
                    int(proyecto.github_project_v2_id)
                    if proyecto.github_project_v2_id.isdigit()
                    else None
                )
                if num is not None:
                    meta, _opts, _items = self._client.obtener_detalles_proyecto_v2(owner, num)

                    if tarea.estado_id:
                        estado = next(
                            (
                                e
                                for e in self._store.listar_estados(proyecto.id)
                                if e.id == tarea.estado_id
                            ),
                            None,
                        )
                        status_field_id = meta.get("status_field_id")
                        if estado and estado.github_option_id and status_field_id:
                            self._client.actualizar_status_item_v2(
                                project_id=meta["id"],
                                item_id=tarea.github_item_id,
                                status_field_id=status_field_id,
                                single_select_option_id=estado.github_option_id,
                            )

                    opcion_prioridad = opcion_para_nivel(
                        tarea.prioridad, meta.get("priority_options", {})
                    )
                    if opcion_prioridad and meta.get("priority_field_id"):
                        self._client.actualizar_status_item_v2(
                            project_id=meta["id"],
                            item_id=tarea.github_item_id,
                            status_field_id=meta["priority_field_id"],
                            single_select_option_id=opcion_prioridad,
                        )

                    campos = meta.get("fields", {})
                    for fecha, nombre_campo in (
                        (tarea.fecha_inicio, "Start Date"),
                        (tarea.fecha_fin_planificada, "Target Date"),
                    ):
                        field_id = campos.get(nombre_campo)
                        if fecha and field_id:
                            self._client.actualizar_fecha_item_v2(
                                project_id=meta["id"],
                                item_id=tarea.github_item_id,
                                field_id=field_id,
                                fecha_iso=fecha,
                            )

            self._store.marcar_sincronizada_github(tarea_id)
            return True
        except Exception:
            log.exception("Error al hacer push de tarea %s hacia GitHub", tarea_id)
            return False
