from __future__ import annotations

import logging
import threading
from collections.abc import Callable
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
from gnomilestone.hitos import esta_conseguido
from gnomilestone.i18n import _
from gnomilestone.models import EstadoTablero, Hito, Recurso, Tarea
from gnomilestone.prioridad import nivel_desde_opcion, opcion_para_nivel
from gnomilestone.store import ESTADOS_POR_DEFECTO, CicloDependenciaError, Store
from gnomilestone.tipos import nombre_remoto, tipo_desde_github

log = logging.getLogger(__name__)

# Mientras se reemplazan las opciones del Status en GitHub (ids nuevos, items en blanco) no
# debe leerse ni escribirse nada del proyecto: un pull o un push en ese intervalo vería
# las tareas sin estado, o usaría ids viejos. Reentrante porque un push puede llamar a otro.
_BLOQUEO_PROYECTO = threading.RLock()

# Quien quiera enterarse de un envío suelto que falla (la ventana principal lo muestra como
# aviso). Se llama desde el hilo del envío, con el título de la tarea.
_oyentes_fallo_envio: list[Callable[[str], None]] = []


def al_fallar_envio(oyente: Callable[[str], None]) -> None:
    _oyentes_fallo_envio.append(oyente)


def _avisar_fallo_envio(titulo: str) -> None:
    for oyente in _oyentes_fallo_envio:
        try:
            oyente(titulo)
        except Exception:  # un oyente roto no debe tumbar el envío
            log.debug("Oyente de fallo de envío con error", exc_info=True)


@dataclass
class SyncResult:
    tareas_creadas: int = 0
    tareas_actualizadas: int = 0
    estados_creados: int = 0
    recursos_creados: int = 0
    documentos_actualizados: int = 0  # notas de «Contexto del proyecto» traídas del repositorio
    errores: list[str] | None = None
    conflictos: list[str] | None = None
    avisos: list[str] | None = None  # informativos: no bloquean ni señalan un fallo

    def __post_init__(self) -> None:
        if self.errores is None:
            self.errores = []
        if self.conflictos is None:
            self.conflictos = []
        if self.avisos is None:
            self.avisos = []


class GitHubSyncManager:
    """Gestiona la sincronización bidireccional entre GnoMilestone y GitHub."""

    def __init__(self, store: Store, client: GitHubClient | None = None) -> None:
        self._store = store
        self._client = client or GitHubClient()
        self._tipos_remotos: dict[tuple[str, str], list[str]] = {}

    def _tipo_para_issue(self, owner: str, repo: str, tarea: Tarea) -> dict[str, str]:
        """Argumento `tipo` para crear o actualizar el issue, con el nombre que el repositorio
        da a ese tipo. Vacío si la tarea no tiene tipo o el repositorio no tiene uno
        equivalente: enviar un nombre que no existe haría fallar todo el envío del issue."""
        if not tarea.tipo:
            return {}
        clave = (owner, repo)
        if clave not in self._tipos_remotos:
            try:
                nombres = self._client.listar_tipos_issue(owner, repo)
            except GitHubError:
                log.warning("No se pudieron leer los tipos de issue; se omite el tipo")
                return {}
            self._tipos_remotos[clave] = nombres if isinstance(nombres, list) else []
        nombre = nombre_remoto(tarea.tipo, self._tipos_remotos[clave])
        return {"tipo": nombre} if nombre else {}

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

    def columnas_sin_equivalente(
        self, proyecto_id: int
    ) -> tuple[list[tuple[EstadoTablero, int]], list[GitHubStatusOption]]:
        """Columnas locales con tareas que el tablero del Project V2 vinculado no reconoce
        (ni por id de opción ni por nombre), con su número de tareas, y las opciones remotas.
        Son las que el pull no sabría dónde migrar: la interfaz pregunta por ellas."""
        proyecto = self._store.obtener_proyecto(proyecto_id)
        if not (proyecto and proyecto.github_repo_owner and proyecto.github_project_v2_id):
            return [], []
        valor = proyecto.github_project_v2_id
        num = int(valor) if valor.isdigit() else None
        if num is None:
            for p in self._client.listar_proyectos_v2(proyecto.github_repo_owner):
                if p.id == valor:
                    num = p.number
                    break
        if num is None:
            return [], []
        _meta, remotas, _items = self._client.obtener_detalles_proyecto_v2(
            proyecto.github_repo_owner, num
        )
        ids = {o.id for o in remotas}
        nombres = {o.name.casefold() for o in remotas}
        sin_equivalente = []
        for estado in self._store.listar_estados(proyecto_id):
            n = self._store.contar_tareas_en_estado(estado.id)
            reconocida = estado.github_option_id in ids or estado.nombre.casefold() in nombres
            if reconocida:
                continue
            if n:
                sin_equivalente.append((estado, n))
        return sin_equivalente, list(remotas)

    @staticmethod
    def _tarea_pendiente_de_envio(tarea: Tarea, con_repo: bool) -> bool:
        """Pendiente de envío = editada en local después del último sync, o nueva y sin
        issue en un proyecto con repositorio. No necesita marca propia: `actualizado` y
        `github_synced_at` ya dicen si GitHub va por detrás."""
        if tarea.github_synced_at is None:
            return con_repo and tarea.github_issue_number is None
        return bool(tarea.actualizado and tarea.actualizado > tarea.github_synced_at)

    def tareas_pendientes_de_envio(self, proyecto_id: int) -> list[Tarea]:
        proyecto = self._store.obtener_proyecto(proyecto_id)
        if not proyecto or not proyecto.github_repo_owner:
            return []
        con_repo = bool(proyecto.github_repo_name)
        return [
            t
            for t in self._store.listar_tareas(proyecto_id)
            if self._tarea_pendiente_de_envio(t, con_repo)
        ]

    def enviar_pendientes(self, proyecto_id: int) -> list[str]:
        """Envía a GitHub las tareas con cambios locales sin enviar. Devuelve un aviso
        por cada tarea que no se pudo enviar (queda pendiente para el siguiente intento)."""
        fallos: list[str] = []
        with _BLOQUEO_PROYECTO:
            for tarea in self.tareas_pendientes_de_envio(proyecto_id):
                if not self._push_tarea(tarea.id, avisar=False):
                    fallos.append(
                        _("No se pudo enviar a GitHub la tarea «{titulo}»; sigue pendiente.").format(
                            titulo=tarea.titulo
                        )
                    )
        return fallos

    def pull_proyecto(
        self, proyecto_id: int, columnas_a_opciones: dict[int, str | None] | None = None
    ) -> SyncResult:
        """Sincroniza desde GitHub hacia el proyecto local. `columnas_a_opciones` (id de
        columna local -> id de opción remota, o None para dejarla sin columna) dice a dónde
        migrar las tareas de columnas sin equivalente; el resto se migra solo."""
        with _BLOQUEO_PROYECTO:
            resultado = self._pull_proyecto(proyecto_id, columnas_a_opciones or {})
        return self._resumir_errores_401(resultado)

    @staticmethod
    def _resumir_errores_401(resultado: SyncResult) -> SyncResult:
        """Con un token no válido cada recurso falla con el mismo 401: se muestra un solo
        aviso en vez de repetirlo seis veces."""
        auth = [e for e in resultado.errores if "(HTTP 401)" in e]
        if auth:
            resultado.errores = [e for e in resultado.errores if e not in auth]
            resultado.errores.append(
                _("El token de GitHub no es válido o ha caducado (HTTP 401). Revísalo en Preferencias.")
            )
        return resultado

    def _pull_proyecto(
        self, proyecto_id: int, columnas_a_opciones: dict[int, str | None]
    ) -> SyncResult:
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

        # 0. Antes de traer nada, se envía lo que quedó pendiente en local (envíos que
        # fallaron, cierre a medias, cambios hechos sin conexión). Lo que no se pueda
        # enviar se avisa y se respeta como conflicto en el pull.
        resultado.errores.extend(self.enviar_pendientes(proyecto_id))

        # 1. Si hay Project V2 vinculado, el tablero de GitHub sustituye por completo al
        # local: nunca se fusiona por nombre, siempre se recrean las columnas desde cero
        # con el id de opción de GitHub como única clave de identidad (espejo).
        items_v2: list[GitHubItem] = []
        status_map: dict[str, int] = {}  # github_option_id -> estado_id local
        cambios_en_tablero = False  # el Project V2 ya no es el esquema Todo/In Progress/Done
        tablero_v2_sincronizado = False  # se han traído columnas reales de un Project V2

        estados_existentes = self._store.listar_estados(proyecto_id)

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
                    tablero_v2_sincronizado = True

                    es_default_sin_cambiar = (
                        tuple(o.name for o in status_options) == ESTADOS_POR_DEFECTO
                    )
                    cambios_en_tablero = not es_default_sin_cambiar
                    opcion_final_anterior_id = next(
                        (
                            e.github_option_id
                            for e in estados_existentes
                            if e.es_final and e.github_option_id
                        ),
                        None,
                    )

                    # Se quita la columna a todas las tareas y se borran las columnas
                    # actuales antes de recrearlas: PRAGMA foreign_keys=ON impide borrar
                    # una columna con tareas (ON DELETE RESTRICT), de ahí el orden.
                    estado_previo = self._store.estados_de_tareas(proyecto_id)
                    estados_previos = {e.id: e for e in estados_existentes}
                    self._store.limpiar_estado_de_tareas(proyecto_id)
                    self._store.eliminar_estados_de_proyecto(proyecto_id)

                    estados_existentes = []
                    for opt in status_options:
                        if es_default_sin_cambiar:
                            # GitHub no expone qué opción es «la de cierre»: solo se puede
                            # confiar en ello cuando el tablero sigue siendo el de fábrica.
                            es_final = opt.name == "Done"
                        else:
                            es_final = opt.id == opcion_final_anterior_id
                        nuevo_estado = self._store.crear_estado(
                            proyecto_id=proyecto_id,
                            nombre=opt.name,
                            github_option_id=opt.id,
                            es_final=es_final,
                            descripcion=opt.description,
                        )
                        resultado.estados_creados += 1
                        estados_existentes.append(nuevo_estado)
                        status_map[opt.id] = nuevo_estado.id

                    # Migración de las tareas a su nueva columna: la elegida por el usuario,
                    # si no la de la misma opción de GitHub y, si no, la del mismo nombre.
                    # Si el item trae su propio Status, el de GitHub manda más abajo.
                    por_nombre = {e.nombre.casefold(): e.id for e in estados_existentes}
                    destino: dict[int, int] = {}
                    for viejo in estados_previos.values():
                        if viejo.id in columnas_a_opciones:
                            nuevo_id = status_map.get(columnas_a_opciones[viejo.id] or "")
                        else:
                            nuevo_id = status_map.get(viejo.github_option_id or "") or por_nombre.get(
                                viejo.nombre.casefold()
                            )
                        if nuevo_id:
                            destino[viejo.id] = nuevo_id
                    self._store.reasignar_estados(
                        {t: destino[e] for t, e in estado_previo.items() if e in destino}
                    )

                    if cambios_en_tablero and not any(e.es_final for e in estados_existentes):
                        resultado.avisos.append(
                            _(
                                "El tablero de GitHub ya no es el esquema por defecto "
                                "(Todo/In Progress/Done): decide a mano, en Ajustes del "
                                "tablero, qué columna completa las tareas."
                            )
                        )
            except Exception as e:
                log.exception("Error al sincronizar Project V2")
                resultado.errores.append(f"Error sincronizando GitHub Project V2: {e}")

        # Recurso / Assignees cache
        recursos_por_nombre: dict[str, Recurso] = {
            r.nombre.lower(): r for r in self._store.listar_recursos(proyecto_id)
        }
        # Una persona con otro nombre visible sigue siendo la del usuario de GitHub.
        for r in self._store.listar_recursos(proyecto_id):
            if r.github_login:
                recursos_por_nombre[r.github_login.lower()] = r

        def _asegurar_recurso(login: str) -> Recurso:
            login_lower = login.lower()
            if login_lower in recursos_por_nombre:
                return recursos_por_nombre[login_lower]
            avatar = f"https://github.com/{login}.png?size=64"
            nuevo_recurso = self._store.crear_recurso(
                proyecto_id=proyecto_id,
                nombre=login,
                avatar_url=avatar,
                github_login=login,
            )
            recursos_por_nombre[login_lower] = nuevo_recurso
            resultado.recursos_creados += 1
            return nuevo_recurso

        def _aplicar_asignados(tarea_id: int, remotos: list[str]) -> None:
            """Fusión a tres bandas de los asignados (base = los del último sync): se añade
            lo que GitHub añadió, se quita lo que GitHub quitó y se respeta lo que solo se
            tocó en local (ya sea porque aún está pendiente de envío)."""
            base = self._store.asignados_base_github(tarea_id)
            remotos_min = {login.lower() for login in remotos}
            locales = self._store.listar_recursos_de_tarea(tarea_id)
            ids_locales = {r.id for r in locales}
            for login in remotos:
                rec = _asegurar_recurso(login)
                if rec.id in ids_locales:
                    continue
                if base is not None and login.lower() in base:
                    continue  # lo quitó el usuario en local y aún no se ha enviado
                self._store.asignar_recurso(tarea_id, rec.id)
            if base is not None:
                for rec in locales:
                    login = (rec.github_login or "").lower()
                    if login and login in base and login not in remotos_min:
                        self._store.quitar_asignacion_tarea_recurso(tarea_id, rec.id)
            self._store.guardar_asignados_base_github(tarea_id, list(remotos_min))

        def _en_conflicto(tarea: Tarea) -> bool:
            # Si la tarea se editó en local después del último sync con GitHub, un pull
            # no debe pisar esos cambios en silencio: se deja para que el usuario decida
            # (el próximo push mandará la versión local, que es la que gana si no se toca).
            return bool(
                tarea.actualizado
                and tarea.github_synced_at
                and tarea.actualizado > tarea.github_synced_at
            )

        # Los Milestones se traen antes que las tareas para poder enlazar cada una con su Hito.
        if repo_name:
            self._pull_etiquetas_repo(proyecto_id, owner, repo_name, resultado)
            self._pull_milestones(proyecto_id, owner, repo_name, resultado)
        hitos_de = {}
        for h in self._store.listar_hitos(proyecto_id):
            if h.github_milestone_number:
                hitos_de[h.github_milestone_number] = h.id
            hitos_de[h.titulo.casefold()] = h.id

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

            # Solo por id de opción: nunca se adivina por nombre ni se usa una columna
            # arbitraria si no hay coincidencia (se queda sin columna, ver barrido final).
            estado_id = status_map.get(item.status_option_id) if item.status_option_id else None

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


            conflicto_item = False
            nivel_prioridad = nivel_desde_opcion(item.priority_name)
            tipo_remoto = tipo_desde_github(item.issue_type)
            if tarea_existente:
                if _en_conflicto(tarea_existente):
                    conflicto_item = True
                    remotos_item: dict[str, object] = {"titulo": item.title}
                    if item.body:
                        remotos_item["descripcion"] = item.body
                    if estado_id is not None:
                        remotos_item["estado_id"] = estado_id
                    if fecha_inicio:
                        remotos_item["fecha_inicio"] = fecha_inicio
                    remotos_item["duracion_dias"] = duracion_dias
                    if item.target_date:
                        remotos_item["fecha_fin_planificada"] = item.target_date
                    if nivel_prioridad is not None:
                        remotos_item["prioridad"] = nivel_prioridad
                    if tipo_remoto is not None:
                        remotos_item["tipo"] = tipo_remoto
                    if not self._fusionar_campos(
                        tarea_existente, remotos_item, estados_existentes, resultado
                    ):
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
                    if tipo_remoto is not None and tarea_existente.tipo != tipo_remoto:
                        tarea_existente.tipo = tipo_remoto
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
                    github_issue_number=item.issue_number,
                    github_item_id=item.id,
                    github_url=item.url,
                    prioridad=nivel_prioridad or 0,
                    tipo=tipo_remoto or "",
                )
                resultado.tareas_creadas += 1
                self._store.marcar_sincronizada_github(nueva.id)
                tarea_id = nueva.id

            if not conflicto_item and item.labels is not None:
                self._aplicar_etiquetas(
                    proyecto_id, tarea_id, item.labels, item.label_colors or {}
                )
            self._enlazar_hito(tarea_id, hitos_de, None, item.milestone_title, conflicto_item)

            # Asignaciones: fusión a tres bandas con la base del último sync
            if item.assignees is not None:
                _aplicar_asignados(tarea_id, item.assignees)

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

                    # Sin Project V2 no hay opción de estado que traer: una issue cerrada
                    # va a la columna marcada como final (es_final, nunca por nombre); si
                    # no hay ninguna marcada, se queda sin columna (ver barrido final).
                    estado_id = None
                    if is_closed:
                        estado_id = next((e.id for e in estados_existentes if e.es_final), None)

                    assignees = [a["login"] for a in issue.get("assignees", [])]
                    milestone = issue.get("milestone")
                    fecha_inicio = None
                    if milestone and milestone.get("due_on"):
                        fecha_inicio = milestone["due_on"][:10]

                    conflicto_issue = False
                    if tarea_existente:
                        if _en_conflicto(tarea_existente):
                            conflicto_issue = True
                            remotos_issue: dict[str, object] = {"titulo": title}
                            if body:
                                remotos_issue["descripcion"] = body
                            if is_closed:
                                remotos_issue["porcentaje_completado"] = 100
                            if not self._fusionar_campos(
                                tarea_existente, remotos_issue, estados_existentes, resultado
                            ):
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
                                    porcentaje_completado=100 if is_closed else 0,
                            github_issue_number=num,
                            github_url=url,
                        )
                        resultado.tareas_creadas += 1
                        self._store.marcar_sincronizada_github(nueva.id)
                        t_id = nueva.id

                    milestone_issue = issue.get("milestone") or {}
                    self._enlazar_hito(
                        t_id,
                        hitos_de,
                        milestone_issue.get("number"),
                        milestone_issue.get("title"),
                        conflicto_issue,
                    )
                    if not conflicto_issue:
                        etiquetas_issue = issue.get("labels") or []
                        self._aplicar_etiquetas(
                            proyecto_id,
                            t_id,
                            [e["name"] for e in etiquetas_issue],
                            {e["name"]: e["color"] for e in etiquetas_issue if e.get("color")},
                        )

                    _aplicar_asignados(t_id, assignees)
                self._archivar_borradas_en_github(
                    proyecto_id,
                    owner,
                    repo_name,
                    procesados_issues | {i.get("number") for i in issues_repo},
                    completo=len(issues_repo) < 100,
                    resultado=resultado,
                )
                self._pull_jerarquia_y_dependencias(
                    proyecto_id, owner, repo_name, issues_repo, resultado
                )
            except Exception as e:
                log.exception("Error al sincronizar issues de repositorio")
                resultado.errores.append(f"Error sincronizando issues de {owner}/{repo_name}: {e}")
            self._pull_comentarios(proyecto_id, owner, repo_name, resultado)
            self._pull_contexto(proyecto_id, owner, repo_name, resultado)

        if tablero_v2_sincronizado:
            # Tareas sin opción de estado real en GitHub (su propio cajón "No Status", o
            # las que no tenían ninguna tarea local que las representara): se agrupan,
            # cambie o no el esquema de columnas, para que no desaparezcan del Tablero.
            estado_temporal = self._store.obtener_o_crear_estado_temporal(proyecto_id)
            huerfanas = self._store.asignar_estado_a_huerfanas(proyecto_id, estado_temporal.id)
            if huerfanas:
                resultado.avisos.append(
                    _(
                        "{n} tareas se han quedado sin columna real de GitHub y se han "
                        "agrupado en «No Status»."
                    ).format(n=huerfanas)
                )
            else:
                self._store.purgar_estado_temporal_si_vacio(estado_temporal.id)

        return resultado

    @staticmethod
    def _etiquetas_campo() -> dict[str, str]:
        return {
            "titulo": _("título"),
            "descripcion": _("descripción"),
            "estado_id": _("columna"),
            "fecha_inicio": _("fecha de inicio"),
            "duracion_dias": _("duración"),
            "fecha_fin_planificada": _("fecha de fin"),
            "prioridad": _("prioridad"),
            "tipo": _("tipo"),
            "porcentaje_completado": _("avance"),
        }

    def _fusionar_campos(
        self,
        tarea: Tarea,
        remotos: dict[str, object],
        estados: list[EstadoTablero],
        resultado: SyncResult,
    ) -> bool:
        """Fusión por campo de una tarea editada en local desde el último sync. Con la base
        del último sync: lo que solo cambió en GitHub se trae, lo que solo cambió en local se
        conserva (se enviará) y solo lo cambiado en ambos lados, a valores distintos, es un
        conflicto real (gana lo local y se avisa). Devuelve False si no hay base (tarea
        anterior a esta función): el llamador mantiene el criterio de tarea completa."""
        base = self._store.base_campos_github(tarea.id)
        if base is None:
            return False
        modificada = False
        etiquetas = self._etiquetas_campo()
        en_conflicto: list[str] = []
        for campo, remoto in remotos.items():
            local = getattr(tarea, campo)
            if remoto == local:
                continue
            if campo in base and local == base[campo]:
                if campo == "estado_id":
                    completado.al_cambiar_de_columna(tarea, remoto, estados)
                setattr(tarea, campo, remoto)
                modificada = True
            elif campo in base and remoto == base[campo]:
                continue
            else:
                en_conflicto.append(etiquetas.get(campo, campo))
        if modificada:
            self._store.actualizar_tarea(tarea)
            resultado.tareas_actualizadas += 1
        self._store.guardar_base_campos_github(tarea.id, {**base, **remotos})
        if en_conflicto:
            resultado.conflictos.append(
                _(
                    "«{titulo}»: {campos} se cambió en local y en GitHub; se mantiene la "
                    "versión local."
                ).format(titulo=tarea.titulo, campos=", ".join(en_conflicto))
            )
        return True

    @staticmethod
    def _numero_de_url_issue(url: str | None, owner: str, repo: str) -> int | None:
        """Número de un issue de este repositorio a partir de su URL de API, o None."""
        prefijo = f"/repos/{owner}/{repo}/issues/".lower()
        if not url or prefijo not in url.lower():
            return None
        try:
            return int(url.rstrip("/").rsplit("/", 1)[1])
        except (IndexError, ValueError):
            return None

    def _pull_jerarquia_y_dependencias(
        self, proyecto_id: int, owner: str, repo: str, issues: list[dict], resultado: SyncResult
    ) -> None:
        """Trae de GitHub los subissues (padre de cada issue) y las dependencias («blocked
        by»). Solo añade o cambia: quitar un padre o una dependencia en GitHub no se
        refleja en local (sin base no se distingue de un enlace que nunca se llegó a
        enviar). Una tarea con cambios locales sin enviar conserva su padre."""
        try:
            tareas = self._store.listar_tareas(proyecto_id)
            por_numero = {t.github_issue_number: t for t in tareas if t.github_issue_number}
            for issue in issues:
                tarea = por_numero.get(issue.get("number"))
                num_padre = self._numero_de_url_issue(issue.get("parent_issue_url"), owner, repo)
                padre = por_numero.get(num_padre) if num_padre else None
                if not (tarea and padre) or padre.id in (tarea.id, tarea.padre_id):
                    continue
                if tarea.actualizado and (
                    not tarea.github_synced_at or tarea.actualizado > tarea.github_synced_at
                ):
                    continue
                if self._es_descendiente(tareas, padre.id, tarea.id):
                    continue  # el nuevo padre cuelga de la tarea: cerraría un ciclo
                tarea.padre_id = padre.id
                self._store.actualizar_tarea(tarea)
                self._store.marcar_sincronizada_github(tarea.id)
                resultado.tareas_actualizadas += 1

            existentes = {
                (d.tarea_origen_id, d.tarea_destino_id)
                for d in self._store.listar_dependencias(proyecto_id)
            }
            for issue in issues:
                destino = por_numero.get(issue.get("number"))
                if not destino or not (issue.get("issue_dependencies_summary") or {}).get(
                    "total_blocked_by"
                ):
                    continue
                for bloqueante in self._client.listar_bloqueos(owner, repo, destino.github_issue_number):
                    origen = por_numero.get(
                        self._numero_de_url_issue(bloqueante.get("url"), owner, repo)
                    )
                    if not origen or (origen.id, destino.id) in existentes:
                        continue
                    try:
                        self._store.crear_dependencia(origen.id, destino.id)
                        existentes.add((origen.id, destino.id))
                    except (CicloDependenciaError, ValueError):
                        log.info("Dependencia %s -> %s ignorada (ciclo)", origen.id, destino.id)
        except Exception as e:
            log.exception("Error al traer la jerarquía y las dependencias")
            resultado.errores.append(
                f"Error trayendo la jerarquía y las dependencias de {owner}/{repo}: {e}"
            )

    @staticmethod
    def _es_descendiente(tareas: list[Tarea], tarea_id: int, ancestro_id: int) -> bool:
        """`tarea_id` cuelga (a cualquier nivel) de `ancestro_id`."""
        padres = {t.id: t.padre_id for t in tareas}
        actual = padres.get(tarea_id)
        visitadas: set[int] = set()
        while actual is not None and actual not in visitadas:
            if actual == ancestro_id:
                return True
            visitadas.add(actual)
            actual = padres.get(actual)
        return False

    def _enviar_dependencias(self, owner: str, repo: str, tarea: Tarea) -> None:
        """Refleja en GitHub las dependencias locales de la tarea (las que la bloquean y las
        que ella bloquea) como «blocked by», si ambos extremos tienen issue. Un fallo aquí no
        invalida el resto del envío. Quitar una dependencia en local no la quita en GitHub."""
        try:
            tareas = {t.id: t for t in self._store.listar_tareas(tarea.proyecto_id)}
            remotos: dict[int, set[int]] = {}  # issue destino -> issues que ya la bloquean
            for dep in self._store.listar_dependencias(tarea.proyecto_id):
                if tarea.id not in (dep.tarea_origen_id, dep.tarea_destino_id):
                    continue
                origen, destino = tareas.get(dep.tarea_origen_id), tareas.get(dep.tarea_destino_id)
                if not (origen and destino and origen.github_issue_number and destino.github_issue_number):
                    continue
                num_destino = destino.github_issue_number
                if num_destino not in remotos:
                    remotos[num_destino] = {
                        b.get("number") for b in self._client.listar_bloqueos(owner, repo, num_destino)
                    }
                if origen.github_issue_number in remotos[num_destino]:
                    continue
                id_origen = self._client.obtener_issue(
                    owner, repo, origen.github_issue_number
                ).get("id")
                if id_origen:
                    self._client.anadir_bloqueo(owner, repo, num_destino, id_origen)
        except Exception:
            log.warning(
                "No se pudieron enviar las dependencias de la tarea %s", tarea.id, exc_info=True
            )

    def _archivar_borradas_en_github(
        self,
        proyecto_id: int,
        owner: str,
        repo_name: str,
        vistos: set[int | None],
        completo: bool,
        resultado: SyncResult,
    ) -> None:
        """Una tarea cuyo issue ya no existe en GitHub (borrado) se archiva en local, nunca se
        borra, y se avisa. Solo se actúa con el listado de issues completo (la API trae 100
        por llamada: con más, que falte un issue no prueba nada), y cada candidata se
        confirma pidiendo su issue (404/410). Las editadas en local sin enviar se respetan."""
        if not completo:
            log.info("Listado de issues truncado: no se buscan tareas borradas en GitHub")
            return
        for tarea in self._store.listar_tareas(proyecto_id):
            numero = tarea.github_issue_number
            if not numero or numero in vistos or not tarea.github_synced_at:
                continue
            if tarea.actualizado and tarea.actualizado > tarea.github_synced_at:
                continue
            try:
                self._client.obtener_issue(owner, repo_name, numero)
            except GitHubNotFoundError:
                self._store.archivar_tarea(tarea.id)
                resultado.avisos.append(
                    _(
                        "El issue #{numero} de la tarea «{titulo}» ya no existe en GitHub: "
                        "se ha archivado la tarea en local."
                    ).format(numero=numero, titulo=tarea.titulo)
                )
            except GitHubError:
                log.warning("No se pudo comprobar el issue #%s", numero, exc_info=True)

    def _pull_milestones(
        self, proyecto_id: int, owner: str, repo_name: str, resultado: SyncResult
    ) -> None:
        """Cada Milestone del repositorio es un Hito local: se crea si falta (o se empareja por
        título con un Hito local que aún no tenía Milestone) y, si ya existe, se le traen
        título, descripción, fecha y estado. Lo editado en local desde el último sync no se
        pisa: el siguiente envío manda."""
        try:
            hitos = self._store.listar_hitos(proyecto_id)
            por_numero = {h.github_milestone_number: h for h in hitos if h.github_milestone_number}
            sin_vincular = {h.titulo.casefold(): h for h in hitos if not h.github_milestone_number}
            for m in self._client.listar_milestones(owner, repo_name):
                numero = m.get("number")
                if not numero:
                    continue
                titulo = m.get("title") or f"Milestone {numero}"
                fecha = (m.get("due_on") or "")[:10] or None
                descripcion = m.get("description") or ""
                cerrado = m.get("state") == "closed"
                hito = por_numero.get(numero) or sin_vincular.pop(titulo.casefold(), None)
                if hito is None:
                    nuevo = self._store.crear_hito(
                        proyecto_id, titulo, fecha, descripcion, cerrado, numero
                    )
                    self._store.marcar_hito_sincronizado(nuevo.id)
                    resultado.tareas_creadas += 1
                    continue
                if not hito.github_milestone_number:
                    self._store.vincular_milestone_hito(hito.id, numero)
                if (
                    hito.actualizado
                    and hito.github_synced_at
                    and hito.actualizado > hito.github_synced_at
                ):
                    continue  # editado en local desde el último sync
                if (hito.titulo, hito.descripcion, hito.fecha, hito.conseguido) != (
                    titulo, descripcion, fecha, cerrado
                ):
                    hito.titulo, hito.descripcion = titulo, descripcion
                    hito.fecha, hito.conseguido = fecha, cerrado
                    self._store.actualizar_hito(hito)
                    resultado.tareas_actualizadas += 1
                self._store.marcar_hito_sincronizado(hito.id)
        except Exception as e:
            log.exception("Error al traer los Milestones del repositorio")
            resultado.errores.append(f"Error trayendo los Milestones de {owner}/{repo_name}: {e}")

    def _enlazar_hito(
        self,
        tarea_id: int,
        hitos: dict[int | str, int],
        numero: int | None,
        titulo: str | None,
        en_conflicto: bool,
    ) -> None:
        """La tarea contribuye al Hito cuyo Milestone contiene su issue. Si el issue ya no está
        en ningún Milestone, la tarea deja su Hito (salvo que se haya editado en local)."""
        if en_conflicto:
            return
        hito_id = hitos.get(numero) if numero else None
        if hito_id is None and titulo:
            hito_id = hitos.get(titulo.casefold())
        if hito_id is not None:
            self._store.vincular_hito_tarea(tarea_id, hito_id)
        elif not numero and not titulo:
            self._store.vincular_hito_tarea(tarea_id, None)

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
                    description=estado.descripcion,
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
                    self._client.crear_etiqueta(
                        *repo, etiqueta.nombre, color, etiqueta.descripcion
                    )

            self._en_remoto(_recolorear, "cambiar el color de la etiqueta", en_segundo_plano)

    def cambiar_descripcion_etiqueta(
        self, etiqueta_id: int, descripcion: str, *, en_segundo_plano: bool = True
    ) -> None:
        etiqueta = self._store.obtener_etiqueta(etiqueta_id)
        descripcion = descripcion.strip()
        if etiqueta is None or etiqueta.descripcion == descripcion:
            return
        self._store.actualizar_descripcion_etiqueta(etiqueta_id, descripcion)
        repo = self._repo_de(etiqueta.proyecto_id)
        if repo:
            def _describir() -> None:
                try:
                    self._client.actualizar_etiqueta(
                        *repo, etiqueta.nombre, descripcion=descripcion
                    )
                except GitHubNotFoundError:
                    # No existe todavía en el repositorio: se crea ya con su descripción.
                    self._client.crear_etiqueta(
                        *repo, etiqueta.nombre, etiqueta.color, descripcion
                    )

            self._en_remoto(_describir, "cambiar la descripción de la etiqueta", en_segundo_plano)

    def _pull_etiquetas_repo(
        self, proyecto_id: int, owner: str, repo_name: str, resultado: SyncResult
    ) -> None:
        """Trae las etiquetas del repositorio (también las que ningún issue lleva) con su color
        y descripción. Se emparejan con las locales por nombre, sin distinguir mayúsculas."""
        try:
            for remota in self._client.listar_etiquetas_repo(owner, repo_name):
                if not (remota.get("name") or "").strip():
                    continue
                self._store.asegurar_etiqueta(
                    proyecto_id,
                    remota["name"],
                    remota.get("color"),
                    remota.get("description") or None,
                )
        except Exception as e:
            log.exception("Error al traer las etiquetas del repositorio")
            resultado.errores.append(f"Error sincronizando etiquetas de {owner}/{repo_name}: {e}")

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

    # -- Hitos <-> Milestones de GitHub ---------------------------------------------

    def _asegurar_milestone(self, owner: str, repo: str, hito: Hito) -> tuple[int | None, bool]:
        """(número del Milestone del Hito, si ya existía en GitHub). Lo crea si el Hito aún no
        tiene; si GitHub ya tiene uno con ese título (p. ej. creado a mano), se vincula a él."""
        if hito.github_milestone_number:
            return hito.github_milestone_number, True
        tareas = [t for t in self._store.listar_tareas(hito.proyecto_id) if t.hito_id == hito.id]
        try:
            creado = self._client.crear_milestone(
                owner, repo, hito.titulo, hito.fecha, hito.descripcion,
                esta_conseguido(hito, tareas),
            )
            numero, existia = creado.get("number"), False
        except GitHubError as err:
            if "already_exists" not in str(err):
                raise
            existente = next(
                (
                    m
                    for m in self._client.listar_milestones(owner, repo)
                    if (m.get("title") or "").casefold() == hito.titulo.casefold()
                ),
                None,
            )
            if existente is None:
                raise
            numero, existia = existente.get("number"), True
        if numero:
            self._store.vincular_milestone_hito(hito.id, numero)
            hito.github_milestone_number = numero
        return numero, existia

    def push_hito(self, hito_id: int) -> bool:
        """Crea o actualiza el Milestone de un Hito y mete en él los issues de sus tareas."""
        with _BLOQUEO_PROYECTO:
            return self._push_hito(hito_id)

    def _push_hito(self, hito_id: int) -> bool:
        hito = self._store.obtener_hito(hito_id)
        if hito is None:
            return False
        proyecto = self._store.obtener_proyecto(hito.proyecto_id)
        if not (proyecto and proyecto.github_repo_owner and proyecto.github_repo_name):
            return True  # proyecto solo local: no hay nada que enviar
        owner, repo = proyecto.github_repo_owner, proyecto.github_repo_name
        try:
            tareas = [t for t in self._store.listar_tareas(hito.proyecto_id) if t.hito_id == hito.id]
            numero, existia = self._asegurar_milestone(owner, repo, hito)
            if numero and existia:
                self._client.actualizar_milestone(
                    owner, repo, numero, hito.titulo, hito.fecha,
                    hito.descripcion, esta_conseguido(hito, tareas),
                )
            for tarea in tareas:
                if numero and tarea.github_issue_number:
                    self._client.actualizar_issue(
                        owner, repo, tarea.github_issue_number, milestone=numero
                    )
            self._store.marcar_hito_sincronizado(hito.id)
            return True
        except Exception:
            log.exception("Error al enviar el Hito %s a GitHub", hito_id)
            return False

    def eliminar_hito(self, hito_id: int, *, en_segundo_plano: bool = True) -> None:
        """Borra el Hito en local (sus tareas se quedan, sin Hito) y su Milestone en GitHub."""
        hito = self._store.obtener_hito(hito_id)
        if hito is None:
            return
        proyecto = self._store.obtener_proyecto(hito.proyecto_id)
        self._store.eliminar_hito(hito_id)
        if not (
            hito.github_milestone_number
            and proyecto
            and proyecto.github_repo_owner
            and proyecto.github_repo_name
        ):
            return
        self._en_remoto(
            lambda: self._client.eliminar_milestone(
                proyecto.github_repo_owner, proyecto.github_repo_name, hito.github_milestone_number
            ),
            "eliminar el Milestone",
            en_segundo_plano,
        )

    def _enviar_milestone_de_tarea(self, owner: str, repo: str, tarea: Tarea) -> None:
        """Mete el issue de la tarea en el Milestone de su Hito (o lo saca del de un Hito
        local si ya no tiene). Un fallo aquí no invalida el resto del envío."""
        if not tarea.github_issue_number:
            return
        try:
            hito = self._store.obtener_hito(tarea.hito_id) if tarea.hito_id else None
            if hito is None:
                self._sacar_de_milestone_de_hito(owner, repo, tarea)
                return
            numero, _existia = self._asegurar_milestone(owner, repo, hito)
            if numero:
                self._client.actualizar_issue(
                    owner, repo, tarea.github_issue_number, milestone=numero
                )
        except Exception:
            log.warning(
                "No se pudo sincronizar el Milestone de la tarea %s", tarea.id, exc_info=True
            )

    def _sacar_de_milestone_de_hito(self, owner: str, repo: str, tarea: Tarea) -> None:
        """Una tarea sin Hito sale del Milestone de un Hito local. Los Milestones que no son de
        ningún Hito se dejan como estén."""
        actual = (self._client.obtener_issue(owner, repo, tarea.github_issue_number) or {}).get(
            "milestone"
        )
        if not actual:
            return
        numeros = {
            h.github_milestone_number
            for h in self._store.listar_hitos(tarea.proyecto_id)
            if h.github_milestone_number
        }
        if actual.get("number") in numeros:
            self._client.quitar_milestone_issue(owner, repo, tarea.github_issue_number)

    def _enviar_jerarquia(self, owner: str, repo: str, tarea: Tarea) -> None:
        """Refleja en GitHub la jerarquía local como subissues: la tarea bajo su padre y sus
        hijas bajo ella (si ya tienen issue). Un padre sin issue se enlazará cuando lo tenga.
        Un fallo aquí no invalida el resto del envío."""
        try:
            pares: list[tuple[Tarea, Tarea]] = []  # (padre, hija)
            if tarea.padre_id:
                padre = self._store.obtener_tarea(tarea.padre_id)
                if padre and padre.github_issue_number:
                    pares.append((padre, tarea))
            hijas = [
                t
                for t in self._store.listar_tareas(tarea.proyecto_id)
                if t.padre_id == tarea.id and t.github_issue_number
            ]
            pares.extend((tarea, hija) for hija in hijas)
            for padre, hija in pares:
                # Un par que falla (o que ya estaba enlazado) no debe impedir enlazar los demás.
                try:
                    id_hija = self._client.obtener_issue(
                        owner, repo, hija.github_issue_number
                    ).get("id")
                    if id_hija:
                        self._client.vincular_subissue(
                            owner, repo, padre.github_issue_number, id_hija
                        )
                except GitHubError as error:
                    if "duplicate sub-issues" in str(error):
                        continue  # ya era subissue de ese padre: nada que hacer
                    log.warning(
                        "No se pudo enlazar la tarea %s como subissue de la %s",
                        hija.id, padre.id, exc_info=True,
                    )
        except Exception:
            log.warning(
                "No se pudo enviar la jerarquía de subissues de la tarea %s", tarea.id, exc_info=True
            )

    def _enviar_campos_issue(self, owner: str, repo: str, tarea: Tarea) -> None:
        """Envía prioridad y fechas a los campos de issue (Priority, Start date, Target date)
        si el repositorio los tiene. Un fallo aquí no invalida el resto del envío."""
        try:
            campos = self._client.listar_campos_issue(owner, repo)
            if not campos:
                return
            valores: list[dict] = []
            prioridad = campos.get("priority") or campos.get("prioridad")
            if prioridad:
                opcion = opcion_para_nivel(tarea.prioridad, prioridad["options"])
                if opcion:
                    valores.append({"fieldId": prioridad["id"], "singleSelectOptionId": opcion})
            for fecha, nombre in (
                (tarea.fecha_inicio, "start date"),
                (tarea.fecha_fin_planificada, "target date"),
            ):
                if fecha and nombre in campos:
                    valores.append({"fieldId": campos[nombre]["id"], "dateValue": fecha})
            if not valores:
                return
            node_id = self._client.obtener_issue(owner, repo, tarea.github_issue_number).get(
                "node_id"
            )
            if node_id:
                self._client.establecer_campos_issue(node_id, valores)
        except Exception:
            log.warning(
                "No se pudieron enviar los campos de issue de la tarea %s", tarea.id, exc_info=True
            )

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
                    self._client.crear_etiqueta(
                        owner, repo, etiqueta.nombre, etiqueta.color, etiqueta.descripcion
                    )
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

    def _readjuntar_item(self, proyecto, owner: str, repo: str, tarea) -> bool:
        """Vuelve a añadir el issue de la tarea a su Project V2 y guarda el item nuevo.
        Devuelve False si no se pudo (sin Project numérico o sin `node_id` del issue)."""
        v2 = proyecto.github_project_v2_id
        if not (v2 and v2.isdigit()):
            return False
        meta_v2, _o, _i = self._client.obtener_detalles_proyecto_v2(owner, int(v2))
        node_id = self._client.obtener_issue(owner, repo, tarea.github_issue_number).get("node_id")
        if not node_id:
            return False
        item_id = self._client.anadir_item_v2(meta_v2["id"], node_id)
        self._store.vincular_item_github(tarea.id, item_id)
        tarea.github_item_id = item_id
        return True

    def _asignados_para_issue(
        self, tarea_id: int, locales: list[str], remotos_raw: list[dict] | None
    ) -> list[str] | None:
        """Asignados que se mandan al issue: lo que hay en GitHub ahora, sin lo que el
        usuario quitó en local desde el último sync, más lo que añadió. Así una
        desasignación local se propaga y un asignado puesto en GitHub no se pisa. Si no se
        pudo leer lo remoto, se manda solo lo local (como antes)."""
        if not isinstance(remotos_raw, list):
            return locales or None
        remotos = [a["login"] for a in remotos_raw if isinstance(a, dict) and a.get("login")]
        base = self._store.asignados_base_github(tarea_id) or set()
        locales_min = {login.lower() for login in locales}
        quitados = base - locales_min
        finales = [login for login in remotos if login.lower() not in quitados]
        presentes = {login.lower() for login in finales}
        finales += [login for login in locales if login.lower() not in presentes]
        return finales

    def push_tarea(self, tarea_id: int) -> bool:
        """Envía o actualiza una tarea local en GitHub (Issue o Item de Project V2)."""
        with _BLOQUEO_PROYECTO:
            return self._push_tarea(tarea_id)

    def _push_tarea(self, tarea_id: int, avisar: bool = True) -> bool:
        tarea = self._store.obtener_tarea(tarea_id)
        if not tarea:
            return False

        proyecto = self._store.obtener_proyecto(tarea.proyecto_id)
        if not proyecto or not proyecto.github_repo_owner:
            return False

        owner = proyecto.github_repo_owner
        repo = proyecto.github_repo_name

        # GitHub solo acepta logins: un recurso sin `github_login` (p. ej. un nombre completo)
        # haría fallar el envío entero con un 422, así que no se manda.
        asignados = [
            r.github_login
            for r in self._store.listar_recursos_de_tarea(tarea_id)
            if r.github_login
        ]

        try:
            # 1. Si ya tiene issue number asociado, actualizar el issue en GitHub
            if tarea.github_issue_number and repo:
                estado_issue = "closed" if tarea.porcentaje_completado >= 100 else "open"
                asignados_envio: list[str] | None = asignados or None
                try:
                    issue_remoto = self._client.obtener_issue(
                        owner, repo, tarea.github_issue_number
                    )
                    remotas = [e["name"] for e in issue_remoto.get("labels", [])]
                    asignados_envio = self._asignados_para_issue(
                        tarea.id, asignados, issue_remoto.get("assignees")
                    )
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
                    assignees=asignados_envio,
                    labels=etiquetas,
                    **self._tipo_para_issue(owner, repo, tarea),
                )
                self._store.guardar_asignados_base_github(tarea.id, asignados)
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
                    **self._tipo_para_issue(owner, repo, tarea),
                    **({"labels": etiquetas} if etiquetas else {}),
                )
                self._store.guardar_etiquetas_base_github(tarea.id, etiquetas)
                self._store.guardar_asignados_base_github(tarea.id, asignados)
                # Solo el vínculo: reescribir toda la fila con la copia leída al empezar el envío
                # pisaría lo que el usuario haya editado mientras tanto.
                self._store.vincular_issue_github(tarea.id, res.get("number"), res.get("html_url"))
                tarea.github_issue_number = res.get("number")

            # 1b. Sin item en el Project V2 no habría Status que enviar (GitHub dejaría la tarea
            # en «No Status»): se añade el issue al proyecto (idempotente) y se guarda el item.
            # Se reintenta en cada envío mientras la tarea no tenga item.
            v2 = proyecto.github_project_v2_id
            if v2 and v2.isdigit() and repo and tarea.github_issue_number and not tarea.github_item_id:
                try:
                    meta_v2, _o, items_v2 = self._client.obtener_detalles_proyecto_v2(owner, int(v2))
                    node_id = self._client.obtener_issue(
                        owner, repo, tarea.github_issue_number
                    ).get("node_id")
                    if node_id:
                        try:
                            item_id = self._client.anadir_item_v2(meta_v2["id"], node_id)
                        except GitHubError as error:
                            # GitHub a veces rechaza añadir un issue que ya está en el proyecto
                            # («Content already exists»): en ese caso se reutiliza su item.
                            if "already exists" not in str(error):
                                raise
                            item_id = next(
                                (
                                    i.id
                                    for i in items_v2
                                    if i.issue_number == tarea.github_issue_number
                                ),
                                None,
                            )
                            if item_id is None:
                                raise
                        self._store.vincular_item_github(tarea.id, item_id)
                        tarea.github_item_id = item_id
                except GitHubError:
                    log.exception("No se pudo añadir el issue %s al Project V2", tarea.github_issue_number)

            # 2. Si hay Project V2 y la tarea tiene item_id asociado, sincronizar estado y
            # fechas (campos "Start date"/"Target date", si el proyecto los tiene)
            def _enviar_al_project() -> None:
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

                    campos = {(n or "").casefold(): i for n, i in meta.get("fields", {}).items()}
                    for fecha, nombre_campo in (
                        (tarea.fecha_inicio, "start date"),
                        (tarea.fecha_fin_planificada, "target date"),
                    ):
                        field_id = campos.get(nombre_campo)
                        if fecha and field_id:
                            try:
                                self._client.actualizar_fecha_item_v2(
                                    project_id=meta["id"],
                                    item_id=tarea.github_item_id,
                                    field_id=field_id,
                                    fecha_iso=fecha,
                                )
                            except GitHubError as err:
                                # Los campos de issue (Start/Target date nativos) aparecen en el
                                # proyecto pero solo se escriben desde el issue: ya se envían en
                                # `_enviar_campos_issue`.
                                if "Issue field values" not in str(err):
                                    raise
                                log.debug("«%s» es un campo de issue; se envía por el issue", nombre_campo)

            if proyecto.github_project_v2_id and tarea.github_item_id:
                try:
                    _enviar_al_project()
                except GitHubError as err:
                    # El item guardado ya no está en el Project (se quitó o se borró en GitHub):
                    # se vuelve a añadir el issue, se guarda el item nuevo y se reintenta una vez.
                    if "does not exist in the project" not in str(err):
                        raise
                    if not (repo and tarea.github_issue_number and self._readjuntar_item(
                        proyecto, owner, repo, tarea
                    )):
                        raise
                    _enviar_al_project()

            if repo:
                self._enviar_milestone_de_tarea(owner, repo, tarea)
            if repo and tarea.github_issue_number:
                self._enviar_campos_issue(owner, repo, tarea)
                self._enviar_jerarquia(owner, repo, tarea)
                self._enviar_dependencias(owner, repo, tarea)

            self._store.marcar_sincronizada_github(tarea_id)
            return True
        except Exception:
            log.exception("Error al hacer push de tarea %s hacia GitHub", tarea_id)
            if avisar:
                _avisar_fallo_envio(tarea.titulo)
            return False
