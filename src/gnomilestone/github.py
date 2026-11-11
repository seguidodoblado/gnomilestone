from __future__ import annotations

import base64
import json
import logging
import shutil
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

from gnomilestone import settings

log = logging.getLogger(__name__)

GITHUB_API_URL = "https://api.github.com"
GITHUB_GRAPHQL_URL = "https://api.github.com/graphql"


class GitHubError(Exception):
    """Error al comunicarse con la API de GitHub."""


class GitHubNotFoundError(GitHubError):
    """HTTP 404: el recurso (etiqueta, issue…) no existe en GitHub."""


class GitHubAuthError(GitHubError):
    """Falta token o credenciales inválidas."""


@dataclass
class GitHubUser:
    login: str
    name: str = ""
    avatar_url: str = ""


@dataclass
class GitHubRepo:
    owner: str
    name: str
    full_name: str
    description: str = ""
    default_branch: str = "main"


@dataclass
class GitHubProjectV2:
    id: str
    number: int
    title: str
    owner: str
    url: str = ""


@dataclass
class GitHubStatusOption:
    id: str
    name: str
    color: str = "GRAY"  # enum de GitHub: GRAY, BLUE, GREEN, YELLOW, ORANGE, RED, PINK, PURPLE
    description: str = ""


@dataclass
class GitHubItem:
    id: str
    title: str
    body: str = ""
    item_type: str = "Issue"
    issue_number: int | None = None
    repository: str | None = None
    status_name: str | None = None
    status_option_id: str | None = None
    url: str | None = None
    start_date: str | None = None
    target_date: str | None = None
    assignees: list[str] | None = None
    milestone_title: str | None = None
    milestone_due: str | None = None
    labels: list[str] | None = None
    label_colors: dict[str, str] | None = None
    priority_name: str | None = None


def obtener_token() -> str | None:
    """Busca el token de GitHub: primero en settings.json (PAT), luego en gh CLI."""
    config = settings.read_settings()
    pat = config.get("github_token")
    if pat and isinstance(pat, str) and pat.strip():
        return pat.strip()

    gh_path = shutil.which("gh")
    if gh_path:
        try:
            resultado = subprocess.run(
                [gh_path, "auth", "token"],
                capture_output=True,
                text=True,
                check=False,
                timeout=5,
            )
            token = resultado.stdout.strip()
            if token and resultado.returncode == 0:
                return token
        except (subprocess.SubprocessError, OSError) as e:
            log.debug("No se pudo obtener token vía gh CLI: %s", e)

    return None


class GitHubClient:
    """Cliente para las APIs REST y GraphQL de GitHub."""

    def __init__(self, token: str | None = None) -> None:
        self._token = token

    @property
    def token(self) -> str:
        if self._token:
            return self._token
        token = obtener_token()
        if not token:
            raise GitHubAuthError(
                "No hay credenciales de GitHub configuradas (inicia sesión con `gh auth login` o configura un Personal Access Token)."
            )
        return token

    def _request(
        self,
        endpoint_or_url: str,
        method: str = "GET",
        data: dict[str, Any] | None = None,
    ) -> Any:
        url = (
            endpoint_or_url
            if endpoint_or_url.startswith("http")
            else f"{GITHUB_API_URL}/{endpoint_or_url.lstrip('/')}"
        )
        token = self.token
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "GnoMilestone/0.1.0",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        body_bytes = None
        if data is not None:
            body_bytes = json.dumps(data).encode("utf-8")
            headers["Content-Type"] = "application/json; charset=utf-8"

        req = urllib.request.Request(url, data=body_bytes, headers=headers, method=method)
        # Las lecturas (GET) son idempotentes: un fallo de red puntual se reintenta una vez.
        intentos = 2 if method == "GET" else 1
        for intento in range(1, intentos + 1):
            try:
                return self._abrir(req)
            except urllib.error.HTTPError as err:
                self._lanzar_http(err, url)
            except Exception as e:
                if intento < intentos:
                    log.warning("Fallo de red llamando a %s (%s); se reintenta", url, e)
                    continue
                log.error("Fallo de red llamando a %s: %s", url, e)
                raise GitHubError(f"Fallo de conexión con GitHub: {e}") from e
        raise AssertionError("inalcanzable")  # pragma: no cover

    @staticmethod
    def _abrir(req: urllib.request.Request) -> Any:
        with urllib.request.urlopen(req, timeout=15) as resp:
            resp_text = resp.read().decode("utf-8")
            if not resp_text:
                return None
            return json.loads(resp_text)

    @staticmethod
    def _lanzar_http(err: urllib.error.HTTPError, url: str) -> None:
        err_body = err.read().decode("utf-8", errors="replace")
        # 404 y 422 los trata el llamador (p. ej. «la etiqueta no existe» o «ya existe»): no
        # son un error por sí mismos, así que no ensucian la terminal.
        nivel = logging.DEBUG if err.code in (404, 422) else logging.ERROR
        log.log(nivel, "HTTP %s llamando a GitHub %s: %s", err.code, url, err_body)
        if err.code in (401, 403):
            raise GitHubAuthError(
                f"Error de autenticación con GitHub (HTTP {err.code}): {err_body}"
            ) from err
        if err.code == 404:
            raise GitHubNotFoundError(f"Error de GitHub API (HTTP {err.code}): {err_body}") from err
        raise GitHubError(f"Error de GitHub API (HTTP {err.code}): {err_body}") from err

    def graphql(self, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {"query": query}
        if variables:
            payload["variables"] = variables
        resp = self._request(GITHUB_GRAPHQL_URL, method="POST", data=payload)
        if not resp:
            raise GitHubError("Respuesta vacía de GraphQL")
        if resp.get("errors"):
            msg = "; ".join(e.get("message", "Error") for e in resp["errors"])
            raise GitHubError(f"GraphQL error: {msg}")
        return resp.get("data", {})

    # -- Métodos de usuario y repos ------------------------------------------

    def obtener_usuario_actual(self) -> GitHubUser:
        datos = self._request("user")
        return GitHubUser(
            login=datos["login"],
            name=datos.get("name") or datos["login"],
            avatar_url=datos.get("avatar_url") or "",
        )

    def listar_repositorios(self, per_page: int = 100) -> list[GitHubRepo]:
        datos = self._request(f"user/repos?per_page={per_page}&sort=updated")
        return [
            GitHubRepo(
                owner=repo["owner"]["login"],
                name=repo["name"],
                full_name=repo["full_name"],
                description=repo.get("description") or "",
                default_branch=repo.get("default_branch") or "main",
            )
            for repo in datos
        ]

    # -- GitHub Projects V2 --------------------------------------------------

    def listar_proyectos_v2(self, owner: str) -> list[GitHubProjectV2]:
        """Lista proyectos V2 de un usuario u organización."""
        query = """
        query($login: String!) {
          user(login: $login) {
            projectsV2(first: 50) {
              nodes {
                id
                number
                title
                url
              }
            }
          }
        }
        """
        try:
            data = self.graphql(query, {"login": owner})
            nodes = data.get("user", {}).get("projectsV2", {}).get("nodes", [])
        except GitHubError:
            # Si no es usuario, probar organización
            query_org = """
            query($login: String!) {
              organization(login: $login) {
                projectsV2(first: 50) {
                  nodes {
                    id
                    number
                    title
                    url
                  }
                }
              }
            }
            """
            data = self.graphql(query_org, {"login": owner})
            nodes = data.get("organization", {}).get("projectsV2", {}).get("nodes", [])

        return [
            GitHubProjectV2(
                id=node["id"],
                number=node["number"],
                title=node["title"],
                owner=owner,
                url=node.get("url") or "",
            )
            for node in nodes
        ]

    def obtener_detalles_proyecto_v2(
        self, owner: str, project_number: int
    ) -> tuple[dict[str, Any], list[GitHubStatusOption], list[GitHubItem]]:
        """Obtiene metadatos del proyecto, opciones de Status y sus items con fechas."""
        query = """
        query($login: String!, $number: Int!) {
          user(login: $login) {
            projectV2(number: $number) {
              id
              title
              fields(first: 50) {
                nodes {
                  ... on ProjectV2SingleSelectField {
                    id
                    name
                    options {
                      id
                      name
                      color
                      description
                    }
                  }
                  ... on ProjectV2Field {
                    id
                    name
                    dataType
                  }
                }
              }
              items(first: 100) {
                nodes {
                  id
                  type
                  fieldValues(first: 30) {
                    nodes {
                      ... on ProjectV2ItemFieldSingleSelectValue {
                        name
                        optionId
                        field {
                          ... on ProjectV2SingleSelectField {
                            name
                            id
                          }
                        }
                      }
                      ... on ProjectV2ItemFieldDateValue {
                        date
                        field {
                          ... on ProjectV2Field {
                            name
                            id
                          }
                        }
                      }
                    }
                  }
                  content {
                    ... on Issue {
                      number
                      title
                      body
                      url
                      state
                      repository {
                        nameWithOwner
                      }
                      assignees(first: 10) {
                        nodes {
                          login
                        }
                      }
                      milestone {
                        title
                        dueOn
                      }
                      labels(first: 20) {
                        nodes {
                          name
                          color
                        }
                      }
                    }
                  }
                }
              }
            }
          }
        }
        """
        try:
            data = self.graphql(query, {"login": owner, "number": project_number})
            proj = data.get("user", {}).get("projectV2")
        except GitHubError:
            proj = None

        if not proj:
            # Probar organización
            query_org = query.replace("user(login:", "organization(login:")
            data = self.graphql(query_org, {"login": owner, "number": project_number})
            proj = data.get("organization", {}).get("projectV2")

        if not proj:
            raise GitHubError(f"No se encontró el Project V2 #{project_number} de {owner}")

        meta: dict[str, Any] = {
            "id": proj["id"],
            "title": proj["title"],
            "fields": {},
        }
        status_options: list[GitHubStatusOption] = []
        for field in proj.get("fields", {}).get("nodes", []):
            fname = field.get("name")
            fid = field.get("id")
            meta["fields"][fname] = fid
            if fname == "Status" and "options" in field:
                meta["status_field_id"] = fid
                for opt in field["options"]:
                    status_options.append(
                        GitHubStatusOption(
                            id=opt["id"],
                            name=opt["name"],
                            color=opt.get("color") or "GRAY",
                            description=opt.get("description") or "",
                        )
                    )
            elif (fname or "").casefold() in ("priority", "prioridad") and "options" in field:
                meta["priority_field_id"] = fid
                meta["priority_options"] = {o["name"]: o["id"] for o in field["options"]}

        items: list[GitHubItem] = []
        for item_node in proj.get("items", {}).get("nodes", []):
            item_id = item_node["id"]
            content = item_node.get("content") or {}
            title = content.get("title", "")
            body = content.get("body", "")
            issue_number = content.get("number")
            url = content.get("url")
            repo_name = content.get("repository", {}).get("nameWithOwner")

            assignees = [a["login"] for a in content.get("assignees", {}).get("nodes", [])]
            label_nodes = content.get("labels", {}).get("nodes", [])
            labels = [n["name"] for n in label_nodes]
            label_colors = {n["name"]: n.get("color") for n in label_nodes if n.get("color")}
            m_title = content.get("milestone", {}).get("title") if content.get("milestone") else None
            m_due = content.get("milestone", {}).get("dueOn") if content.get("milestone") else None

            status_name = None
            status_option_id = None
            start_date = None
            target_date = None
            priority_name = None

            for fval in item_node.get("fieldValues", {}).get("nodes", []):
                field_info = fval.get("field") or {}
                fname = field_info.get("name")
                if fname == "Status":
                    status_name = fval.get("name")
                    status_option_id = fval.get("optionId")
                elif (fname or "").casefold() in ("priority", "prioridad"):
                    priority_name = fval.get("name")
                elif fname == "Start Date":
                    start_date = fval.get("date")
                elif fname == "Target Date":
                    target_date = fval.get("date")

            items.append(
                GitHubItem(
                    id=item_id,
                    title=title,
                    body=body,
                    item_type=item_node.get("type", "Issue"),
                    issue_number=issue_number,
                    repository=repo_name,
                    status_name=status_name,
                    status_option_id=status_option_id,
                    url=url,
                    start_date=start_date,
                    target_date=target_date,
                    assignees=assignees,
                    milestone_title=m_title,
                    milestone_due=m_due,
                    labels=labels,
                    label_colors=label_colors,
                    priority_name=priority_name,
                )
            )

        return meta, status_options, items

    def anadir_item_v2(self, project_id: str, content_node_id: str) -> str:
        """Añade un issue (por su node_id) a un Project V2 y devuelve el id del item.
        Es idempotente: si ya estaba (p. ej. por el auto-add de GitHub), devuelve el existente."""
        query = """
        mutation($projectId: ID!, $contentId: ID!) {
          addProjectV2ItemById(input: {projectId: $projectId, contentId: $contentId}) {
            item { id }
          }
        }
        """
        datos = self.graphql(query, {"projectId": project_id, "contentId": content_node_id})
        return datos["addProjectV2ItemById"]["item"]["id"]

    def actualizar_status_item_v2(
        self, project_id: str, item_id: str, status_field_id: str, single_select_option_id: str
    ) -> None:
        """Cambia la columna (Status) de un item de Project V2 en GitHub."""
        query = """
        mutation($projectId: ID!, $itemId: ID!, $fieldId: ID!, $optionId: String!) {
          updateProjectV2ItemFieldValue(
            input: {
              projectId: $projectId
              itemId: $itemId
              fieldId: $fieldId
              value: {
                singleSelectOptionId: $optionId
              }
            }
          ) {
            projectV2Item {
              id
            }
          }
        }
        """
        self.graphql(
            query,
            {
                "projectId": project_id,
                "itemId": item_id,
                "fieldId": status_field_id,
                "optionId": single_select_option_id,
            },
        )

    def actualizar_fecha_item_v2(
        self, project_id: str, item_id: str, field_id: str, fecha_iso: str
    ) -> None:
        """Cambia un campo de fecha (p.ej. "Start Date"/"Target Date") de un item de
        Project V2 en GitHub. `fecha_iso` en formato "YYYY-MM-DD"."""
        query = """
        mutation($projectId: ID!, $itemId: ID!, $fieldId: ID!, $date: Date!) {
          updateProjectV2ItemFieldValue(
            input: {
              projectId: $projectId
              itemId: $itemId
              fieldId: $fieldId
              value: {
                date: $date
              }
            }
          ) {
            projectV2Item {
              id
            }
          }
        }
        """
        self.graphql(
            query,
            {
                "projectId": project_id,
                "itemId": item_id,
                "fieldId": field_id,
                "date": fecha_iso,
            },
        )

    # -- GitHub Issues (REST) ------------------------------------------------

    def listar_issues(
        self, owner: str, repo: str, state: str = "all", per_page: int = 100
    ) -> list[dict[str, Any]]:
        return self._request(f"repos/{owner}/{repo}/issues?state={state}&per_page={per_page}")

    def crear_issue(
        self,
        owner: str,
        repo: str,
        titulo: str,
        body: str = "",
        assignees: list[str] | None = None,
        labels: list[str] | None = None,
    ) -> dict[str, Any]:
        data: dict[str, Any] = {"title": titulo, "body": body}
        if assignees:
            data["assignees"] = assignees
        if labels:
            data["labels"] = labels
        return self._request(f"repos/{owner}/{repo}/issues", method="POST", data=data)

    def actualizar_issue(
        self,
        owner: str,
        repo: str,
        number: int,
        titulo: str | None = None,
        body: str | None = None,
        state: str | None = None,
        assignees: list[str] | None = None,
        labels: list[str] | None = None,
    ) -> dict[str, Any]:
        data: dict[str, Any] = {}
        if titulo is not None:
            data["title"] = titulo
        if body is not None:
            data["body"] = body
        if state is not None:
            data["state"] = state
        if assignees is not None:
            data["assignees"] = assignees
        if labels is not None:
            data["labels"] = labels
        return self._request(f"repos/{owner}/{repo}/issues/{number}", method="PATCH", data=data)

    def obtener_issue(self, owner: str, repo: str, number: int) -> dict[str, Any]:
        return self._request(f"repos/{owner}/{repo}/issues/{number}")

    def obtener_fichero_repo(self, owner: str, repo: str, ruta: str) -> str | None:
        """Texto de un fichero del repositorio (rama por defecto), o None si no existe, es
        una carpeta o no se puede leer como texto (p. ej. pesa más de 1 MB)."""
        try:
            datos = self._request(f"repos/{owner}/{repo}/contents/{urllib.parse.quote(ruta)}")
        except GitHubNotFoundError:
            return None
        if not isinstance(datos, dict) or datos.get("type") != "file":
            return None
        contenido = datos.get("content")
        if datos.get("encoding") != "base64" or not isinstance(contenido, str):
            return None
        try:
            return base64.b64decode(contenido).decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            return None

    def crear_etiqueta(self, owner: str, repo: str, nombre: str, color: str) -> None:
        """Crea la etiqueta en el repositorio con su color; si ya existe (422) no hace nada."""
        try:
            self._request(
                f"repos/{owner}/{repo}/labels",
                method="POST",
                data={"name": nombre, "color": color.lstrip("#")},
            )
        except GitHubError as e:
            if "422" not in str(e):
                raise

    def eliminar_issue(self, owner: str, repo: str, number: int) -> str:
        """Borra el issue en GitHub (GraphQL `deleteIssue`, exige permisos de administrador).

        Si no se puede borrar, lo cierra como «no planificado». Devuelve "eliminado" o "cerrado".
        """
        try:
            node_id = self._request(f"repos/{owner}/{repo}/issues/{number}")["node_id"]
            self.graphql(
                "mutation($id: ID!) { deleteIssue(input: {issueId: $id}) { clientMutationId } }",
                {"id": node_id},
            )
            return "eliminado"
        except GitHubError:
            log.warning("No se pudo borrar el issue #%s; se cierra como no planificado", number)
            self._request(
                f"repos/{owner}/{repo}/issues/{number}",
                method="PATCH",
                data={"state": "closed", "state_reason": "not_planned"},
            )
            return "cerrado"

    def eliminar_item_v2(self, project_id: str, item_id: str) -> None:
        """Quita un item de un Project V2 (no borra el issue al que apunte)."""
        self.graphql(
            "mutation($p: ID!, $i: ID!) { deleteProjectV2Item(input: {projectId: $p, itemId: $i})"
            " { deletedItemId } }",
            {"p": project_id, "i": item_id},
        )

    def listar_comentarios_repo(self, owner: str, repo: str) -> list[dict[str, Any]]:
        """Todos los comentarios de issues del repositorio (paginado)."""
        comentarios: list[dict[str, Any]] = []
        pagina = 1
        while True:
            lote = self._request(
                f"repos/{owner}/{repo}/issues/comments?per_page=100&page={pagina}"
            )
            if not lote:
                break
            comentarios.extend(lote)
            if len(lote) < 100:
                break
            pagina += 1
        return comentarios

    def crear_comentario(self, owner: str, repo: str, number: int, cuerpo: str) -> dict[str, Any]:
        return self._request(
            f"repos/{owner}/{repo}/issues/{number}/comments", method="POST", data={"body": cuerpo}
        )

    def eliminar_comentario(self, owner: str, repo: str, comment_id: int) -> None:
        self._request(f"repos/{owner}/{repo}/issues/comments/{comment_id}", method="DELETE")

    def actualizar_comentario(
        self, owner: str, repo: str, comment_id: int, cuerpo: str
    ) -> dict[str, Any]:
        return self._request(
            f"repos/{owner}/{repo}/issues/comments/{comment_id}",
            method="PATCH",
            data={"body": cuerpo},
        )

    def actualizar_etiqueta(
        self,
        owner: str,
        repo: str,
        nombre: str,
        nuevo_nombre: str | None = None,
        color: str | None = None,
    ) -> None:
        data: dict[str, Any] = {}
        if nuevo_nombre is not None:
            data["new_name"] = nuevo_nombre
        if color is not None:
            data["color"] = color.lstrip("#")
        self._request(
            f"repos/{owner}/{repo}/labels/{urllib.parse.quote(nombre, safe='')}",
            method="PATCH",
            data=data,
        )

    def eliminar_etiqueta(self, owner: str, repo: str, nombre: str) -> None:
        """Borra la etiqueta del repositorio (y, con ella, de todos sus issues)."""
        self._request(
            f"repos/{owner}/{repo}/labels/{urllib.parse.quote(nombre, safe='')}", method="DELETE"
        )

    def reemplazar_opciones_status(
        self, field_id: str, opciones: list[GitHubStatusOption]
    ) -> None:
        """Deja las opciones del campo Status exactamente con esta lista y este orden.

        GitHub las recrea con ids nuevos, así que los items pierden su valor de Status:
        quien llame debe releer los ids y volver a enviar el estado de cada item."""
        self.graphql(
            "mutation($fieldId: ID!, $options: [ProjectV2SingleSelectFieldOptionInput!]!) {"
            " updateProjectV2Field(input: {fieldId: $fieldId, singleSelectOptions: $options}) {"
            " projectV2Field { ... on ProjectV2SingleSelectField { id } } } }",
            {
                "fieldId": field_id,
                "options": [
                    {"name": o.name, "color": o.color, "description": o.description}
                    for o in opciones
                ],
            },
        )
