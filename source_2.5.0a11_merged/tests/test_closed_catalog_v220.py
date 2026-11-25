import json
from pathlib import Path

from fastapi.testclient import TestClient

from iteration_wallet.canonical_evidence import CanonicalEvidenceAdapter
from iteration_wallet.vault_v21 import VaultEngine
from iteration_wallet import server


FORBIDDEN_CLOSED_KEYS = {
    "vault_path",
    "original_path",
    "hash",
    "notes",
    "reviews",
    "external_test_results",
    "output_path",
    "contents",
    "preview",
}


def _source(tmp_path: Path, name: str, text: str) -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def test_closed_section_view_exposes_catalog_only_and_preserves_closed_note(tmp_path: Path):
    evidence = CanonicalEvidenceAdapter(tmp_path, session_id="closed-catalog-unit")
    vault = VaultEngine(tmp_path, blackbox=evidence)
    project = vault.create_project("Catalog Project")
    section = vault.create_section(project["id"], "Cradle")
    candidate = vault.add_candidate(
        project["id"],
        section["id"],
        str(_source(tmp_path, "candidate.py", "print('hidden')")),
        notes="Safe closed-view note",
    )
    candidate["reviews"] = [{"summary": "protected review"}]
    candidate["external_test_results"] = [{"summary": "protected test result"}]

    view = vault.get_section_view(project["id"], section["id"])

    assert view["view_mode"] == "closed_catalog"
    assert view["protected_contents_visible"] is False
    assert view["is_vault_open"] is False
    record = view["candidates"][0]
    assert record["name"] == "candidate.py"
    assert record["size_bytes"] == len("print('hidden')")
    assert record["created_at"]
    assert record["last_accessed_at"]
    assert record["last_accessed_by"] == "system:add_material"
    assert record["closed_view_note"] == "Safe closed-view note"
    assert FORBIDDEN_CLOSED_KEYS.isdisjoint(record.keys())
    rendered = json.dumps(view)
    assert "hidden" not in rendered
    assert "protected review" not in rendered
    assert "protected test result" not in rendered
    assert "vault_path" not in rendered
    assert "original_path" not in rendered


def test_open_section_view_still_returns_full_records_for_authorized_open_vault(tmp_path: Path):
    evidence = CanonicalEvidenceAdapter(tmp_path, session_id="open-catalog-unit")
    vault = VaultEngine(tmp_path, blackbox=evidence)
    project = vault.create_project("Open Project")
    section = vault.create_section(project["id"], "Core")
    vault.add_candidate(
        project["id"], section["id"],
        str(_source(tmp_path, "candidate.txt", "visible when open")),
    )

    closed = vault.get_section_view(project["id"], section["id"])
    assert "vault_path" not in closed["candidates"][0]

    opened = vault.open_vault()
    assert opened["is_open"] is True
    assert opened["general_authority_token_issued"] is False
    open_view = vault.get_section_view(project["id"], section["id"])
    assert open_view["view_mode"] == "open_full"
    assert open_view["protected_contents_visible"] is True
    assert "vault_path" in open_view["candidates"][0]
    assert "hash" in open_view["candidates"][0]


def test_closed_catalog_includes_safe_canonical_evidence_surface(tmp_path: Path):
    evidence = CanonicalEvidenceAdapter(tmp_path, session_id="safe-evidence-unit")
    vault = VaultEngine(tmp_path, blackbox=evidence)
    project = vault.create_project("Evidence Project")
    section = vault.create_section(project["id"], "Core")
    vault.add_raw_source(
        project["id"], section["id"],
        str(_source(tmp_path, "raw.txt", "raw data")),
    )

    view = vault.get_closed_catalog_view(project["id"], section["id"])
    section_evidence = view["blackbox"]
    record_evidence = view["raw_sources"][0]["blackbox"]

    assert section_evidence["chain_ok"] is True
    assert section_evidence["event_count"] >= 2
    assert record_evidence["chain_ok"] is True
    assert record_evidence["event_count"] >= 1
    assert record_evidence["protected_values_exposed"] is False
    assert {"event_type", "observed_at", "coverage"}.issubset(
        record_evidence["recent_events"][0].keys()
    )
    rendered = json.dumps(view)
    assert "record_hash" not in rendered
    assert "previous_hash" not in rendered
    assert "raw data" not in rendered


def test_closed_catalog_route_uses_coherent_canonical_runtime(tmp_path: Path):
    old = (server.blackbox21, server.vault21, server.human_access, server.promotion21)
    runtime = server.build_canonical_v21_runtime(tmp_path)
    server.blackbox21, server.vault21, server.human_access, server.promotion21 = runtime
    try:
        with TestClient(server.app) as client:
            project = client.post("/api/v21/projects", json={"name": "API Catalog"}).json()
            section = client.post(
                f"/api/v21/projects/{project['id']}/sections", json={"name": "Core"}
            ).json()
            src = _source(tmp_path, "api_secret.txt", "do not reveal")
            created = client.post(
                f"/api/v21/projects/{project['id']}/sections/{section['id']}/candidates",
                json={"path": str(src), "notes": "show this note"},
            ).json()
            assert created["id"]

            response = client.get(
                f"/api/v21/projects/{project['id']}/sections/{section['id']}/closed-catalog"
            )
            assert response.status_code == 200
            view = response.json()
            assert view["view_mode"] == "closed_catalog"
            assert view["candidates"][0]["closed_view_note"] == "show this note"
            rendered = json.dumps(view)
            assert "do not reveal" not in rendered
            assert "vault_path" not in rendered
            assert '"hash"' not in rendered
    finally:
        server.blackbox21, server.vault21, server.human_access, server.promotion21 = old
