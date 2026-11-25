from __future__ import annotations

from pathlib import Path
import os

from fastapi.testclient import TestClient

from iteration_wallet import server


def _install_isolated_runtime(root: Path):
    previous = {
        "blackbox21": server.blackbox21,
        "canonical_evidence21": server.canonical_evidence21,
        "vault21": server.vault21,
        "human_access": server.human_access,
        "promotion21": server.promotion21,
        "startup_reconciliation21": server.startup_reconciliation21,
    }
    prior_mode = os.environ.get("IW_OUBLIETTE_MODE")
    os.environ["IW_OUBLIETTE_MODE"] = "transaction"
    try:
        evidence, vault, humans, promotion = server.build_canonical_v21_runtime(root)
    finally:
        if prior_mode is None:
            os.environ.pop("IW_OUBLIETTE_MODE", None)
        else:
            os.environ["IW_OUBLIETTE_MODE"] = prior_mode
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


def test_http_static_inspection_quarantine_and_derivative_candidate_flow(tmp_path: Path):
    previous = _install_isolated_runtime(tmp_path / "wallet")
    try:
        with TestClient(server.app) as client:
            project = client.post("/api/v21/projects", json={"name": "Oubliette API"}).json()
            section = client.post(
                f"/api/v21/projects/{project['id']}/sections",
                json={"name": "Intake"},
            ).json()
            marker = tmp_path / "must_not_execute.txt"
            unknown = tmp_path / "unknown.py"
            unknown.write_text(
                f"from pathlib import Path\nPath({str(marker)!r}).write_text('executed')\n",
                encoding="utf-8",
            )
            candidate = client.post(
                f"/api/v21/projects/{project['id']}/sections/{section['id']}/candidates",
                json={"path": str(unknown)},
            ).json()
            session = client.post(
                "/api/v21/identity/sessions",
                json={
                    "actor_id": "josie",
                    "actor_kind": "human",
                    "verified_methods": ["human_ceremony", "typing_challenge"],
                },
            ).json()
            assert client.post("/api/v21/vault/open", json={"session_id": session["session_id"]}).status_code == 200

            inspected = client.post(
                f"/api/v21/projects/{project['id']}/sections/{section['id']}/files/{candidate['id']}/oubliette/inspect",
                json={"actor_kind": "human"},
            )
            assert inspected.status_code == 200, inspected.text
            inspection = inspected.json()
            assert inspection["authority"]["custody_changed"] is False
            assert marker.exists() is False

            token = client.post(
                "/api/v21/ceremony/tokens",
                json={
                    "action_key": "quarantine",
                    "session_id": session["session_id"],
                    "project_id": project["id"],
                    "section_id": section["id"],
                    "object_id": candidate["id"],
                    "proposal_id": inspection["quarantine_proposal"]["proposal_id"],
                    "proposal_hash": inspection["quarantine_proposal"]["proposal_hash"],
                },
            )
            assert token.status_code == 201, token.text
            quarantined = client.post(
                f"/api/v21/projects/{project['id']}/sections/{section['id']}/files/{candidate['id']}/quarantine",
                json={
                    "report_id": inspection["report"]["report_id"],
                    "ceremony_token": token.json()["ceremony_token"],
                    "session_id": session["session_id"],
                    "reason": "static indicators require fenced review",
                },
            )
            assert quarantined.status_code == 200, quarantined.text
            quarantine_body = quarantined.json()
            assert quarantine_body["result"]["state"] == "quarantined"
            assert quarantine_body["verification"]["ok"] is True
            assert marker.exists() is False

            lab = tmp_path / "external_lab"
            lab.mkdir()
            derivative = lab / "reviewed.py"
            derivative.write_text("print('separately reviewed derivative')\n", encoding="utf-8")
            derivative_inspection = client.post(
                f"/api/v21/projects/{project['id']}/sections/{section['id']}/files/{candidate['id']}/oubliette/derivatives/inspect",
                json={
                    "derivative_path": str(derivative),
                    "allowed_root": str(lab),
                    "actor_kind": "human",
                },
            )
            assert derivative_inspection.status_code == 200, derivative_inspection.text
            derivative_body = derivative_inspection.json()
            derivative_report = derivative_body["report"]
            derivative_capsule = derivative_body["capsule"]
            derivative_proposal = derivative_body["admission_proposal"]

            derivative_token = client.post(
                "/api/v21/ceremony/tokens",
                json={
                    "action_key": "admit_oubliette_derivative_as_candidate",
                    "session_id": session["session_id"],
                    "project_id": project["id"],
                    "section_id": section["id"],
                    "object_id": candidate["id"],
                    "proposal_id": derivative_proposal["proposal_id"],
                    "proposal_hash": derivative_proposal["proposal_hash"],
                },
            )
            assert derivative_token.status_code == 201, derivative_token.text
            admitted = client.post(
                f"/api/v21/projects/{project['id']}/sections/{section['id']}/files/{candidate['id']}/oubliette/derivatives/admit",
                json={
                    "derivative_path": str(derivative),
                    "capsule_id": derivative_capsule["capsule_id"],
                    "proposal_id": derivative_proposal["proposal_id"],
                    "proposal_hash": derivative_proposal["proposal_hash"],
                    "report_id": derivative_report["report_id"],
                    "ceremony_token": derivative_token.json()["ceremony_token"],
                    "session_id": session["session_id"],
                    "reason": "admit the reviewed derivative only",
                },
            )
            assert admitted.status_code == 200, admitted.text
            admitted_body = admitted.json()
            assert admitted_body["result"]["state"] == "candidate"
            assert admitted_body["result"]["parent_quarantined_id"] == candidate["id"]
            assert admitted_body["result"]["trust_status"] == "candidate_only_no_automatic_trust"
            assert admitted_body["result"]["origin"] == "wallet_intake_capsule"
            assert admitted_body["result"]["wallet_intake_capsule_id"] == derivative_capsule["capsule_id"]
            assert admitted_body["verification"]["ok"] is True

            state = client.get("/api/v21/state").json()
            files = state["projects"][0]["sections"][0]["files"]
            parent = next(item for item in files if item["id"] == candidate["id"])
            child = next(item for item in files if item["id"] == admitted_body["result"]["id"])
            assert parent["state"] == "quarantined"
            assert child["state"] == "candidate"
            assert marker.exists() is False
    finally:
        _restore(previous)
