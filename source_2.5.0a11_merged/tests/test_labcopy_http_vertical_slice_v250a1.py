from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from iteration_wallet import server


def _install(root: Path):
    previous = {
        "blackbox21": server.blackbox21,
        "canonical_evidence21": server.canonical_evidence21,
        "vault21": server.vault21,
        "human_access": server.human_access,
        "promotion21": server.promotion21,
        "startup_reconciliation21": server.startup_reconciliation21,
    }
    evidence, vault, humans, promotion = server.build_canonical_v21_runtime(
        root, oubliette_mode="disabled"
    )
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


def _issue(client, *, action, session, project, section, object_id, proposal):
    response = client.post(
        "/api/v21/ceremony/tokens",
        json={
            "action_key": action,
            "session_id": session["session_id"],
            "project_id": project["id"],
            "section_id": section["id"],
            "object_id": object_id,
            "proposal_id": proposal["proposal_id"],
            "proposal_hash": proposal["proposal_hash"],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["ceremony_token"]


def test_http_labcopy_export_capture_and_candidate_only_return(tmp_path: Path):
    previous = _install(tmp_path / "wallet")
    try:
        with TestClient(server.app) as client:
            project = client.post("/api/v21/projects", json={"name": "LabCopy API"}).json()
            section = client.post(
                f"/api/v21/projects/{project['id']}/sections", json={"name": "Main"}
            ).json()
            source = tmp_path / "app.py"
            marker = tmp_path / "executed.txt"
            source.write_text(
                f"from pathlib import Path\nPath({str(marker)!r}).write_text('ran')\n",
                encoding="utf-8",
            )
            candidate = client.post(
                f"/api/v21/projects/{project['id']}/sections/{section['id']}/candidates",
                json={"path": str(source)},
            ).json()
            session = client.post(
                "/api/v21/identity/sessions",
                json={
                    "actor_id": "josie",
                    "actor_kind": "human",
                    "verified_methods": ["human_ceremony"],
                },
            ).json()
            assert client.post("/api/v21/vault/open", json={"session_id": session["session_id"]}).status_code == 200
            outside = tmp_path / "external"
            outside.mkdir()
            proposal_response = client.post(
                f"/api/v21/projects/{project['id']}/sections/{section['id']}/files/{candidate['id']}/labcopy/proposal",
                json={
                    "output_dir": str(outside),
                    "lab_policy": "manual tests outside Wallet",
                    "requested_label": "app.py",
                },
            )
            assert proposal_response.status_code == 200, proposal_response.text
            proposal = proposal_response.json()
            token = _issue(
                client,
                action="export_working_copy",
                session=session,
                project=project,
                section=section,
                object_id=candidate["id"],
                proposal=proposal,
            )
            exported = client.post(
                f"/api/v21/projects/{project['id']}/sections/{section['id']}/files/{candidate['id']}/export-working-copy",
                json={
                    "proposal_id": proposal["proposal_id"],
                    "proposal_hash": proposal["proposal_hash"],
                    "ceremony_token": token,
                    "session_id": session["session_id"],
                    "reason": "external review",
                },
            )
            assert exported.status_code == 200, exported.text
            assert exported.json()["verification"]["ok"] is True
            assert marker.exists() is False
            assert Path(proposal["external_package_path"]).is_file()

            results = tmp_path / "results"
            results.mkdir()
            changed = results / "app-fixed.py"
            changed.write_text("print('reviewed result')\n", encoding="utf-8")
            captured_response = client.post(
                f"/api/v21/labcopy/{proposal['lab_id']}/results/capture",
                json={
                    "result_path": str(changed),
                    "allowed_root": str(results),
                    "source_label": "app-fixed.py",
                    "external_assertions": [
                        {"type": "test_claim", "claim": "external review passed"}
                    ],
                },
            )
            assert captured_response.status_code == 200, captured_response.text
            capsule = captured_response.json()["capsule"]
            changed.write_text("changed again after capture\n", encoding="utf-8")

            admission_response = client.post(
                f"/api/v21/labcopy/{proposal['lab_id']}/results/{capsule['capsule_id']}/admission-proposal"
            )
            assert admission_response.status_code == 200, admission_response.text
            admission = admission_response.json()
            admit_token = _issue(
                client,
                action="admit_labcopy_result_as_candidate",
                session=session,
                project=project,
                section=section,
                object_id=candidate["id"],
                proposal=admission,
            )
            admitted = client.post(
                f"/api/v21/labcopy/{proposal['lab_id']}/results/{capsule['capsule_id']}/admit",
                json={
                    "proposal_id": admission["proposal_id"],
                    "proposal_hash": admission["proposal_hash"],
                    "ceremony_token": admit_token,
                    "session_id": session["session_id"],
                    "reason": "admit reviewed result as Candidate only",
                },
            )
            assert admitted.status_code == 200, admitted.text
            body = admitted.json()
            assert body["result"]["state"] == "candidate"
            assert body["result"]["origin"] == "labcopy_result_intake_capsule"
            assert body["result"]["trust_status"] == "candidate_only_no_automatic_trust"
            assert Path(body["result"]["vault_path"]).read_bytes() == b"print('reviewed result')\n"
            assert body["verification"]["ok"] is True
            capabilities = client.get("/api/v21/capabilities").json()
            assert capabilities["labcopy"]["candidate_only_return"] is True
            assert capabilities["oubliette"]["participation_mode"] == "disabled"
            assert marker.exists() is False
    finally:
        _restore(previous)
