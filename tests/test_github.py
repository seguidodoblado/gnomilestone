from unittest.mock import MagicMock, patch

import pytest

from gnomilestone.github import (
    GitHubAuthError,
    GitHubClient,
    GitHubProjectV2,
    GitHubRepo,
    GitHubUser,
    obtener_token,
)


def test_obtener_token_desde_settings(monkeypatch):
    monkeypatch.setattr("gnomilestone.settings.read_settings", lambda: {"github_token": "ghp_mypassword"})
    assert obtener_token() == "ghp_mypassword"


def test_obtener_token_desde_gh_cli(monkeypatch):
    monkeypatch.setattr("gnomilestone.settings.read_settings", dict)
    monkeypatch.setattr("shutil.which", lambda cmd: "/usr/bin/gh")

    mock_run = MagicMock()
    mock_run.returncode = 0
    mock_run.stdout = "gho_clitoken\n"
    monkeypatch.setattr("subprocess.run", lambda *a, **kw: mock_run)

    assert obtener_token() == "gho_clitoken"


def test_sin_token_lanza_github_auth_error(monkeypatch):
    monkeypatch.setattr("gnomilestone.settings.read_settings", dict)
    monkeypatch.setattr("shutil.which", lambda cmd: None)

    client = GitHubClient()
    with pytest.raises(GitHubAuthError):
        _ = client.token


def test_obtener_usuario_actual():
    client = GitHubClient(token="fake_token")
    mock_resp = {"login": "testuser", "name": "Test User", "avatar_url": "https://example.com/avatar.png"}

    with patch.object(client, "_request", return_value=mock_resp):
        user = client.obtener_usuario_actual()
        assert isinstance(user, GitHubUser)
        assert user.login == "testuser"
        assert user.name == "Test User"
        assert user.avatar_url == "https://example.com/avatar.png"


def test_listar_repositorios():
    client = GitHubClient(token="fake_token")
    mock_repos = [
        {
            "owner": {"login": "testuser"},
            "name": "myrepo",
            "full_name": "testuser/myrepo",
            "description": "Repo desc",
            "default_branch": "main",
        }
    ]
    with patch.object(client, "_request", return_value=mock_repos):
        repos = client.listar_repositorios()
        assert len(repos) == 1
        assert isinstance(repos[0], GitHubRepo)
        assert repos[0].name == "myrepo"
        assert repos[0].owner == "testuser"


def test_listar_proyectos_v2():
    client = GitHubClient(token="fake_token")
    mock_graphql_data = {
        "user": {
            "projectsV2": {
                "nodes": [
                    {"id": "PVT_1", "number": 1, "title": "Mi Proyecto", "url": "https://github.com/..."}
                ]
            }
        }
    }
    with patch.object(client, "graphql", return_value=mock_graphql_data):
        projs = client.listar_proyectos_v2("testuser")
        assert len(projs) == 1
        assert isinstance(projs[0], GitHubProjectV2)
        assert projs[0].title == "Mi Proyecto"
        assert projs[0].number == 1


def test_obtener_detalles_proyecto_v2():
    client = GitHubClient(token="fake_token")
    mock_graphql_data = {
        "user": {
            "projectV2": {
                "id": "PVT_123",
                "title": "Bloguero",
                "fields": {
                    "nodes": [
                        {
                            "id": "F_STATUS",
                            "name": "Status",
                            "options": [
                                {"id": "OPT_1", "name": "Todo"},
                                {"id": "OPT_2", "name": "Done"},
                            ],
                        },
                        {"id": "F_START", "name": "Start Date", "dataType": "DATE"},
                    ]
                },
                "items": {
                    "nodes": [
                        {
                            "id": "ITEM_1",
                            "type": "Issue",
                            "content": {
                                "number": 42,
                                "title": "Diseñar interfaz",
                                "body": "Detalles",
                                "url": "https://github.com/test/repo/issues/42",
                                "state": "OPEN",
                                "repository": {"nameWithOwner": "test/repo"},
                                "assignees": {"nodes": [{"login": "ana"}]},
                                "milestone": {"title": "v1.0", "dueOn": "2026-11-30"},
                                "labels": {"nodes": [{"name": "ui"}]},
                            },
                            "fieldValues": {
                                "nodes": [
                                    {
                                        "name": "Todo",
                                        "optionId": "OPT_1",
                                        "field": {"name": "Status", "id": "F_STATUS"},
                                    },
                                    {
                                        "date": "2026-11-01",
                                        "field": {"name": "Start Date", "id": "F_START"},
                                    },
                                ]
                            },
                        }
                    ]
                },
            }
        }
    }

    with patch.object(client, "graphql", return_value=mock_graphql_data):
        meta, options, items = client.obtener_detalles_proyecto_v2("testuser", 1)
        assert meta["id"] == "PVT_123"
        assert len(options) == 2
        assert options[0].name == "Todo"
        assert len(items) == 1
        item = items[0]
        assert item.title == "Diseñar interfaz"
        assert item.issue_number == 42
        assert item.status_name == "Todo"
        assert item.start_date == "2026-11-01"
        assert item.assignees == ["ana"]
        assert item.milestone_title == "v1.0"


def test_crear_y_actualizar_issue():
    client = GitHubClient(token="fake_token")
    mock_created = {"number": 10, "title": "Nuevo", "state": "open"}
    with patch.object(client, "_request", return_value=mock_created) as req_mock:
        res = client.crear_issue("user", "repo", "Nuevo", "Desc")
        assert res["number"] == 10
        req_mock.assert_called_with("repos/user/repo/issues", method="POST", data={"title": "Nuevo", "body": "Desc"})

    with patch.object(client, "_request", return_value={"number": 10, "state": "closed"}) as req_mock:
        res = client.actualizar_issue("user", "repo", 10, state="closed")
        assert res["state"] == "closed"
        req_mock.assert_called_with("repos/user/repo/issues/10", method="PATCH", data={"state": "closed"})
