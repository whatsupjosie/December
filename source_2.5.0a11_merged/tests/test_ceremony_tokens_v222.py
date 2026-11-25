from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from iteration_wallet import server
from iteration_wallet.canonical_evidence import CanonicalEvidenceAdapter
from iteration_wallet.ceremony import CeremonyTokenError, CeremonyTokenLedger
from iteration_wallet.vault_v21 import VaultEngine


def _source(tmp_path: Path, name: str = "candidate.txt") -> Path:
    path = tmp_path / name
    path.write_text("candidate", encoding="utf-8")
    return path


def _vault_with_candidate(tmp_path: Path):
    evidence = CanonicalEvidenceAdapter(tmp_path, session_id="ceremony-test")
    vault = VaultEngine(tmp_path, blackbox=evidence, ceremony_token_ttl_seconds=60)
    project = vault.create_project("Ceremony Project")
    section = vault.create_section(project["id"], "Core")
    candidate = vault.add_candidate(project["id"], section["id"], str(_source(tmp_path)))
    opened = vault.open_vault()
    return evidence, vault, project, section, candidate, opened


def test_scoped_promotion_token_is_hashed_not_stored_raw_and_single_use(tmp_path: Path):
    _, vault, project, section, candidate, opened = _vault_with_candidate(tmp_path)
    token = vault.issue_ceremony_token(
        "promote_candidate_to_prime",
        "session-1",
        actor_id="josie",
        project_id=project["id"],
        section_id=section["id"],
        object_id=candidate["id"],
    )
    raw = token["ceremony_token"]
    token_file = tmp_path / "ceremony_tokens" / f"{token['token_id']}.json"
    stored_text = token_file.read_text(encoding="utf-8")
    assert raw not in stored_text
    assert "token_hash" in json.loads(stored_text)

    consumed = vault.ceremony_ledger.validate_and_consume(
        raw,
        action_key="promote_candidate_to_prime",
        session_id="session-1",
        open_session_id=opened["open_session_id"],
        project_id=project["id"],
        section_id=section["id"],
        object_id=candidate["id"],
    )
    assert consumed["consumed_by_action"] == "promote_candidate_to_prime"
    with pytest.raises(CeremonyTokenError, match="already been used"):
        vault.ceremony_ledger.validate_and_consume(
            raw,
            action_key="promote_candidate_to_prime",
            session_id="session-1",
            open_session_id=opened["open_session_id"],
            project_id=project["id"],
            section_id=section["id"],
            object_id=candidate["id"],
        )


def test_wrong_scope_expiry_and_vault_lock_fail_closed(tmp_path: Path):
    ledger = CeremonyTokenLedger(tmp_path)
    issued = ledger.issue_token(
        action_key="promote_candidate_to_prime",
        session_id="session-1",
        open_session_id="open-1",
        actor_id="josie",
        project_id="project-1",
        section_id="section-1",
        object_id="candidate-1",
    )
    raw = issued["ceremony_token"]
    with pytest.raises(CeremonyTokenError, match="not valid for this action"):
        ledger.validate_and_consume(raw, action_key="retire_object")
    with pytest.raises(CeremonyTokenError, match="identity session"):
        ledger.validate_and_consume(
            raw, action_key="promote_candidate_to_prime", session_id="session-2"
        )

    record = ledger._load_record(issued["token_id"])
    record["expires_at"] = "2000-01-01T00:00:00+00:00"
    ledger._save_record(record)
    with pytest.raises(CeremonyTokenError, match="expired"):
        ledger.validate_and_consume(
            raw, action_key="promote_candidate_to_prime", session_id="session-1"
        )

    live = ledger.issue_token(
        action_key="promote_candidate_to_prime",
        session_id="session-1",
        open_session_id="open-2",
        project_id="project-1",
        section_id="section-1",
        object_id="candidate-1",
    )
    assert ledger.revoke_for_open_session("open-2") == 1
    with pytest.raises(CeremonyTokenError, match="revoked"):
        ledger.validate_and_consume(
            live["ceremony_token"],
            action_key="promote_candidate_to_prime",
            session_id="session-1",
            open_session_id="open-2",
        )


def test_server_issues_only_canonical_migrated_action_tokens(tmp_path: Path):
    evidence, vault, humans, promotion = server.build_canonical_v21_runtime(tmp_path)
    previous = (
        server.blackbox21,
        server.canonical_evidence21,
        server.vault21,
        server.human_access,
        server.promotion21,
    )
    server.blackbox21 = evidence
    server.canonical_evidence21 = evidence
    server.vault21 = vault
    server.human_access = humans
    server.promotion21 = promotion
    try:
        with TestClient(server.app) as client:
            project = client.post("/api/v21/projects", json={"name": "API Ceremony"}).json()
            section = client.post(
                f"/api/v21/projects/{project['id']}/sections", json={"name": "Core"}
            ).json()
            candidate = client.post(
                f"/api/v21/projects/{project['id']}/sections/{section['id']}/candidates",
                json={"path": str(_source(tmp_path, "api.txt"))},
            ).json()
            session = client.post(
                "/api/v21/identity/sessions",
                json={
                    "actor_id": "josie",
                    "actor_kind": "human",
                    "verified_methods": ["human_ceremony", "typing_challenge"],
                },
            ).json()
            client.post("/api/v21/vault/open", json={"session_id": session["session_id"]})

            retired_action = client.post(
                "/api/v21/ceremony/tokens",
                json={
                    "action_key": "retire_object",
                    "session_id": session["session_id"],
                    "project_id": project["id"],
                    "section_id": section["id"],
                    "object_id": candidate["id"],
                },
            )
            assert retired_action.status_code == 201, retired_action.text
            assert retired_action.json()["action_key"] == "retire_object"
            assert len(vault.list_ceremony_tokens()) == 1

            issued = client.post(
                "/api/v21/ceremony/tokens",
                json={
                    "action_key": "promote_candidate_to_prime",
                    "session_id": session["session_id"],
                    "project_id": project["id"],
                    "section_id": section["id"],
                    "object_id": candidate["id"],
                },
            )
            assert issued.status_code == 201, issued.text
            assert len(vault.list_ceremony_tokens()) == 2
    finally:
        (
            server.blackbox21,
            server.canonical_evidence21,
            server.vault21,
            server.human_access,
            server.promotion21,
        ) = previous
