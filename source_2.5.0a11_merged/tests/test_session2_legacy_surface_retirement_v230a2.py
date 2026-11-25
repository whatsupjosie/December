from pathlib import Path

from iteration_wallet import server


def _route_paths() -> set[str]:
    return {getattr(route, "path", "") for route in server.app.routes}


def test_legacy_v2_http_routes_are_not_mounted() -> None:
    paths = _route_paths()
    forbidden = {
        "/api/state",
        "/api/projects",
        "/api/files",
        "/api/files/{file_id}/remove",
        "/api/files/{file_id}/release",
        "/api/files/{file_id}/restore",
        "/api/vault/open",
        "/api/vault/lock",
        "/api/projects/{project_id}/promote",
        "/api/drives",
        "/api/drives/mark",
        "/api/events",
    }
    assert not (paths & forbidden)


def test_server_import_does_not_instantiate_retired_v2_vault() -> None:
    assert getattr(server, "vault", None) is None


def test_active_ui_targets_only_canonical_v21_api() -> None:
    html = (Path(server.__file__).parent / "static" / "app.html").read_text(encoding="utf-8")
    assert "/api/v21" in html
    assert "canonical promotion" in html.lower()
    assert "File watcher active" not in html
    assert "const API_BASE = 'http://localhost:7432/api';" not in html
