"""Current bounded private-alpha API proof.

The historical v2.2.3 broad-flow test is preserved under historical_sources.
This active test reflects the shipped runtime truth: canonical promotion, exact
Retire and Restore transitions, LabCopy, and the bounded Oubliette intake crossing
are live. Legacy ambiguous custody routes remain absent.
"""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from iteration_wallet import server


def _source(root: Path, name: str, text: str) -> Path:
    path = root / name
    path.write_text(text, encoding="utf-8")
    return path


def _install_isolated_runtime(root: Path):
    previous = {
        "blackbox21": server.blackbox21,
        "canonical_evidence21": server.canonical_evidence21,
        "vault21": server.vault21,
        "human_access": server.human_access,
        "promotion21": server.promotion21,
        "startup_reconciliation21": server.startup_reconciliation21,
    }
    evidence, vault, humans, promotion = server.build_canonical_v21_runtime(root)
    server.blackbox21 = evidence
    server.canonical_evidence21 = evidence
    server.vault21 = vault
    server.human_access = humans
    server.promotion21 = promotion
    server.startup_reconciliation21 = {"status": "not_run", "checked": 0}
    return previous


def _restore(previous):
    for key, value in previous.items():
        setattr(server, key, value)


def test_bounded_canonical_promotion_retire_restore_and_legacy_routes_absent(tmp_path: Path):
    previous = _install_isolated_runtime(tmp_path)
    try:
        with TestClient(server.app) as client:
            project = client.post("/api/v21/projects", json={"name": "Bounded Alpha"}).json()
            section = client.post(
                f"/api/v21/projects/{project['id']}/sections",
                json={"name": "Core"},
            ).json()
            candidate = client.post(
                f"/api/v21/projects/{project['id']}/sections/{section['id']}/candidates",
                json={"path": str(_source(tmp_path, "candidate.txt", "candidate"))},
            ).json()
            session = client.post(
                "/api/v21/identity/sessions",
                json={
                    "actor_id": "josie",
                    "actor_kind": "human",
                    "verified_methods": ["human_ceremony", "typing_challenge"],
                    "role_claims": {"head_user": True},
                },
            ).json()
            assert client.post("/api/v21/vault/open", json={"session_id": session["session_id"]}).status_code == 200

            def issue(action: str, object_id: str | None = None):
                response = client.post(
                    "/api/v21/ceremony/tokens",
                    json={
                        "action_key": action,
                        "session_id": session["session_id"],
                        "project_id": project["id"],
                        "section_id": section["id"],
                        "object_id": object_id or candidate["id"],
                    },
                )
                assert response.status_code == 201, response.text
                return response.json()

            promote_token = issue("promote_candidate_to_prime")
            promoted = client.post(
                f"/api/v21/projects/{project['id']}/sections/{section['id']}/candidates/{candidate['id']}/promote",
                json={
                    "ceremony_token": promote_token["ceremony_token"],
                    "session_id": session["session_id"],
                    "reason": "bounded proof",
                },
            )
            assert promoted.status_code == 200, promoted.text
            body = promoted.json()
            assert body["result"]["state"] == "prime"
            assert body["verification"]["ok"] is True

            transition_candidate = client.post(
                f"/api/v21/projects/{project['id']}/sections/{section['id']}/candidates",
                json={"path": str(_source(tmp_path, "transition.txt", "transition candidate"))},
            ).json()
            retire_token = issue("retire_object", transition_candidate["id"])
            retired = client.post(
                f"/api/v21/projects/{project['id']}/sections/{section['id']}/objects/{transition_candidate['id']}/retire",
                json={
                    "ceremony_token": retire_token["ceremony_token"],
                    "session_id": session["session_id"],
                    "reason": "bounded preservation proof",
                },
            )
            assert retired.status_code == 200, retired.text
            assert retired.json()["result"]["state"] == "retired"
            assert retired.json()["verification"]["ok"] is True

            restore_token = issue("restore_retired_object", transition_candidate["id"])
            restored = client.post(
                f"/api/v21/projects/{project['id']}/sections/{section['id']}/objects/{transition_candidate['id']}/restore",
                json={
                    "ceremony_token": restore_token["ceremony_token"],
                    "session_id": session["session_id"],
                    "reason": "bounded restoration proof",
                },
            )
            assert restored.status_code == 200, restored.text
            assert restored.json()["result"]["state"] == "candidate"
            assert restored.json()["verification"]["ok"] is True

            paths = set(client.get("/openapi.json").json()["paths"])
            assert "/api/v21/projects/{project_id}/sections/{section_id}/objects/{object_id}/retire" in paths
            assert "/api/v21/projects/{project_id}/sections/{section_id}/objects/{object_id}/restore" in paths
            assert not any("/files/{file_id}/remove" in path for path in paths)
            assert not any("/files/{file_id}/release" in path for path in paths)
            assert not any("restore-from-removed" in path for path in paths)
    finally:
        _restore(previous)


def test_private_alpha_status_is_bounded_and_does_not_claim_full_cutover(tmp_path: Path):
    previous = _install_isolated_runtime(tmp_path)
    try:
        with TestClient(server.app) as client:
            body = client.get("/api/v21/private-alpha/status").json()
            from iteration_wallet.version import WALLET_VERSION
            assert body["version"] == WALLET_VERSION
            assert body["runtime_mode"] == "canonical_wallet_blackbox_core"
            assert body["ready_for_bounded_promotion_alpha"] is True
            assert body["ready_for_private_alpha_flow"] is False
            assert body["ready_for_full_private_alpha_flow"] is False
            assert body["migrated_protected_actions"] == [
                "admit_labcopy_result_as_candidate",
                "admit_oubliette_derivative_as_candidate",
                "export_working_copy",
                "promote_candidate_to_prime",
                "quarantine",
                "restore_retired_object",
                "retire_object",
            ]
            assert body["unmigrated_protected_actions"] == []
            assert body["startup_reconciliation"]["status"] == "complete"
    finally:
        _restore(previous)
