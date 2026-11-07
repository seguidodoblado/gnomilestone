from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date

from gnomilestone.github import GitHubClient, GitHubItem
from gnomilestone.models import Recurso, Tarea
from gnomilestone.store import Store

log = logging.getLogger(__name__)


@dataclass
class SyncResult:
    tareas_creadas: int = 0
    tareas_actualizadas: int = 0
    estados_creados: int = 0
    recursos_creados: int = 0
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

    # -- Pull (GitHub -> GnoMilestone) ---------------------------------------

    def pull_proyecto(self, proyecto_id: int) -> SyncResult:
        """Sincroniza desde GitHub hacia el proyecto local."""
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
                    duracion_dias = max((f_fin - f_ini).days, 1)
                except ValueError:
                    duracion_dias = 1
            elif not fecha_inicio and item.target_date:
                fecha_inicio = item.target_date

            es_hito = False
            if item.milestone_title and not item.start_date and item.target_date:
                # O si tiene etiqueta milestone
                pass

            if tarea_existente:
                if _en_conflicto(tarea_existente):
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
                        tarea_existente.estado_id = estado_id
                        modificada = True
                    if fecha_inicio and tarea_existente.fecha_inicio != fecha_inicio:
                        tarea_existente.fecha_inicio = fecha_inicio
                        modificada = True
                    if duracion_dias != tarea_existente.duracion_dias:
                        tarea_existente.duracion_dias = duracion_dias
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
                    duracion_dias=duracion_dias,
                    es_hito=es_hito,
                    github_issue_number=item.issue_number,
                    github_item_id=item.id,
                    github_url=item.url,
                )
                resultado.tareas_creadas += 1
                self._store.marcar_sincronizada_github(nueva.id)
                tarea_id = nueva.id

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

                    if tarea_existente:
                        if _en_conflicto(tarea_existente):
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
                            es_hito=es_hito,
                            porcentaje_completado=100 if is_closed else 0,
                            github_issue_number=num,
                            github_url=url,
                        )
                        resultado.tareas_creadas += 1
                        self._store.marcar_sincronizada_github(nueva.id)
                        t_id = nueva.id

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

        return resultado

    # -- Push (GnoMilestone -> GitHub) ---------------------------------------

    def push_tarea(self, tarea_id: int) -> bool:
        """Envía o actualiza una tarea local en GitHub (Issue o Item de Project V2)."""
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
                self._client.actualizar_issue(
                    owner=owner,
                    repo=repo,
                    number=tarea.github_issue_number,
                    titulo=tarea.titulo,
                    body=tarea.descripcion,
                    state=estado_issue,
                    assignees=asignados or None,
                )
            elif repo and not tarea.github_issue_number:
                # Si no tiene issue y el proyecto tiene repo vinculado, crearlo
                res = self._client.crear_issue(
                    owner=owner,
                    repo=repo,
                    titulo=tarea.titulo,
                    body=tarea.descripcion,
                    assignees=asignados or None,
                )
                tarea.github_issue_number = res.get("number")
                tarea.github_url = res.get("html_url")
                self._store.actualizar_tarea(tarea)

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
