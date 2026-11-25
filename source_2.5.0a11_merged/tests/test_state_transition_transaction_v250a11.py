from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from iteration_wallet import server
from iteration_wallet.canonical_evidence import CanonicalEvidenceAdapter
from iteration_wallet.notification_manager import ActorKind, NotificationManager
from iteration_wallet.promotion_transaction import PromotionTransactionCoordinator
from iteration_wallet.state_transition_transaction import (
    SimulatedStateTransitionCrash,
    StateTransitionTransactionCoordinator,
    StateTransitionTransactionError,
)
from iteration_wallet.vault_v21 import VaultEngine


def _source(tmp_path: Path, name: str, body: str) -> Path:
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return path


def _runtime(tmp_path: Path):
    evidence = CanonicalEvidenceAdapter(tmp_path, session_id="state-transition-tests")
    vault = VaultEngine(tmp_path, blackbox=evidence, strict_ceremony_tokens=True)
    humans = NotificationManager(tmp_path, blackbox=evidence)
    promotion = PromotionTransactionCoordinator(vault, evidence, humans)
    transitions = StateTransitionTransactionCoordinator(vault, evidence, humans)
    vault.state_transition_coordinator = transitions
    project = vault.create_project("Preservation Project")
    section = vault.create_section(project["id"], "Core")
    identity = humans.issue_identity_session(
        "josie",
        ActorKind.HUMAN,
        device_id="local-console",
        verified_methods=["human_ceremony", "typing_challenge"],
    )
    vault.open_vault()
    return evidence, vault, humans, promotion, transitions, project, section, identity


def _token(
    vault: VaultEngine,
    *,
    action_key: str,
    project_id: str,
    section_id: str,
    object_id: str,
    session_id: str,
) -> str:
    return vault.issue_ceremony_token(
        action_key,
        session_id,
        actor_id="josie",
        project_id=project_id,
        section_id=section_id,
        object_id=object_id,
    )["ceremony_token"]


def _candidate(runtime, tmp_path: Path, name: str = "candidate.txt", body: str = "candidate"):
    _, vault, _, _, _, project, section, _ = runtime
    return vault.add_candidate(
        project["id"], section["id"], str(_source(tmp_path, name, body))
    )


def _retire(runtime, record: dict, reason: str = "reviewed and preserved"):
    _, vault, _, _, transitions, project, section, identity = runtime
    token = _token(
        vault,
        action_key="retire_object",
        project_id=project["id"],
        section_id=section["id"],
        object_id=record["id"],
        session_id=identity.session_id,
    )
    return transitions.retire(
        project_id=project["id"],
        section_id=section["id"],
        object_id=record["id"],
        ceremony_token=token,
        session_id=identity.session_id,
        reason=reason,
    )


def test_candidate_retire_and_restore_preserve_exact_bytes_and_receipts(tmp_path: Path):
    runtime = _runtime(tmp_path)
    evidence, vault, _, _, transitions, project, section, identity = runtime
    candidate = _candidate(runtime, tmp_path, body="irreplaceable bytes")
    original_path = Path(candidate["vault_path"])
    expected = original_path.read_bytes()

    retired = _retire(runtime, candidate)
    retired_record = retired["result"]
    retired_path = Path(retired_record["vault_path"])
    retire_evidence = Path(retired_record["transition_evidence_path"])

    assert retired_record["state"] == "retired"
    assert retired_record["retired_from_state"] == "candidate"
    assert retired_path.read_bytes() == expected
    assert retire_evidence.read_bytes() == expected
    assert not original_path.exists()
    assert retired["verification"]["ok"] is True
    assert transitions.verify_receipt(retired["receipt"]["receipt_id"])["ok"] is True

    restore_token = _token(
        vault,
        action_key="restore_retired_object",
        project_id=project["id"],
        section_id=section["id"],
        object_id=candidate["id"],
        session_id=identity.session_id,
    )
    restored = transitions.restore(
        project_id=project["id"],
        section_id=section["id"],
        object_id=candidate["id"],
        ceremony_token=restore_token,
        session_id=identity.session_id,
        reason="return to active candidate review",
    )
    restored_record = restored["result"]
    restore_evidence = Path(restored_record["transition_evidence_path"])

    assert restored_record["state"] == "candidate"
    assert Path(restored_record["vault_path"]).read_bytes() == expected
    assert restore_evidence.read_bytes() == expected
    assert retired_path.exists() is False
    assert len(restored_record["state_history"]) == 2
    assert all(item["protected_content_preserved"] is True for item in restored_record["state_history"])
    assert restored["verification"]["ok"] is True
    assert evidence.verify_chain()["ok"] is True


def test_archived_object_retire_restore_updates_only_current_archive_projection(tmp_path: Path):
    runtime = _runtime(tmp_path)
    _, vault, _, promotion, transitions, project, section, identity = runtime
    first = _candidate(runtime, tmp_path, "first.txt", "first")
    first_token = _token(
        vault,
        action_key="promote_candidate_to_prime",
        project_id=project["id"],
        section_id=section["id"],
        object_id=first["id"],
        session_id=identity.session_id,
    )
    promotion.promote_to_prime(
        project_id=project["id"], section_id=section["id"], candidate_id=first["id"],
        ceremony_token=first_token, session_id=identity.session_id, reason="first prime"
    )
    second = _candidate(runtime, tmp_path, "second.txt", "second")
    second_token = _token(
        vault,
        action_key="promote_candidate_to_prime",
        project_id=project["id"],
        section_id=section["id"],
        object_id=second["id"],
        session_id=identity.session_id,
    )
    promotion.promote_to_prime(
        project_id=project["id"], section_id=section["id"], candidate_id=second["id"],
        ceremony_token=second_token, session_id=identity.session_id, reason="replacement prime"
    )
    assert vault._find_file(project["id"], section["id"], first["id"])["state"] == "archived"
    assert first["id"] in vault.get_section(project["id"], section["id"])["archive"]

    retired = _retire(runtime, first)
    assert retired["result"]["state"] == "retired"
    assert first["id"] not in vault.get_section(project["id"], section["id"])["archive"]

    token = _token(
        vault,
        action_key="restore_retired_object",
        project_id=project["id"], section_id=section["id"], object_id=first["id"],
        session_id=identity.session_id,
    )
    restored = transitions.restore(
        project_id=project["id"], section_id=section["id"], object_id=first["id"],
        ceremony_token=token, session_id=identity.session_id, reason="restore archive projection"
    )
    assert restored["result"]["state"] == "archived"
    assert first["id"] in vault.get_section(project["id"], section["id"])["archive"]
    assert [h["from_state"] for h in restored["result"]["state_history"]] == ["archived", "retired"]


def test_current_prime_cannot_be_retired_and_token_is_not_consumed(tmp_path: Path):
    runtime = _runtime(tmp_path)
    _, vault, _, promotion, transitions, project, section, identity = runtime
    candidate = _candidate(runtime, tmp_path)
    promote_token = _token(
        vault, action_key="promote_candidate_to_prime", project_id=project["id"],
        section_id=section["id"], object_id=candidate["id"], session_id=identity.session_id,
    )
    promotion.promote_to_prime(
        project_id=project["id"], section_id=section["id"], candidate_id=candidate["id"],
        ceremony_token=promote_token, session_id=identity.session_id, reason="prime"
    )
    token = _token(
        vault, action_key="retire_object", project_id=project["id"], section_id=section["id"],
        object_id=candidate["id"], session_id=identity.session_id,
    )
    token_id = vault.ceremony_ledger.parse_token_id(token)
    before = vault.ceremony_ledger.get_record(token_id)
    with pytest.raises(StateTransitionTransactionError, match="Prime cannot be retired"):
        transitions.retire(
            project_id=project["id"], section_id=section["id"], object_id=candidate["id"],
            ceremony_token=token, session_id=identity.session_id,
        )
    after = vault.ceremony_ledger.get_record(token_id)
    assert before["consumed_at"] is None
    assert after["consumed_at"] is None


def test_no_public_engine_bypass_exists(tmp_path: Path):
    runtime = _runtime(tmp_path)
    _, vault, *_ = runtime
    for name in ("retire_object", "restore_object", "restore_retired_object", "retire_file"):
        assert not hasattr(vault, name)


def test_wrong_scope_fails_before_mutation(tmp_path: Path):
    runtime = _runtime(tmp_path)
    _, vault, _, _, transitions, project, section, identity = runtime
    candidate = _candidate(runtime, tmp_path)
    other = _candidate(runtime, tmp_path, "other.txt", "other")
    token = _token(
        vault, action_key="retire_object", project_id=project["id"], section_id=section["id"],
        object_id=other["id"], session_id=identity.session_id,
    )
    before = dict(candidate)
    with pytest.raises(Exception, match="scope|object"):
        transitions.retire(
            project_id=project["id"], section_id=section["id"], object_id=candidate["id"],
            ceremony_token=token, session_id=identity.session_id,
        )
    current = vault._find_file(project["id"], section["id"], candidate["id"])
    assert current["state"] == before["state"]
    assert current["vault_path"] == before["vault_path"]
    assert Path(current["vault_path"]).is_file()


def test_restart_after_custody_publication_completes_without_reducing_content(tmp_path: Path):
    runtime = _runtime(tmp_path)
    evidence, vault, _, _, transitions, project, section, identity = runtime
    candidate = _candidate(runtime, tmp_path, body="crash-safe")
    token = _token(
        vault, action_key="retire_object", project_id=project["id"], section_id=section["id"],
        object_id=candidate["id"], session_id=identity.session_id,
    )
    with pytest.raises(SimulatedStateTransitionCrash, match="custody_published"):
        transitions.retire(
            project_id=project["id"], section_id=section["id"], object_id=candidate["id"],
            ceremony_token=token, session_id=identity.session_id, fault_after="custody_published",
        )

    restarted_evidence = CanonicalEvidenceAdapter(tmp_path, session_id="state-transition-tests")
    restarted_vault = VaultEngine(tmp_path, blackbox=restarted_evidence, strict_ceremony_tokens=True)
    restarted_humans = NotificationManager(tmp_path, blackbox=restarted_evidence)
    restarted = StateTransitionTransactionCoordinator(
        restarted_vault, restarted_evidence, restarted_humans
    )
    report = restarted.reconcile_pending()
    assert report["reconciled"] == 1
    assert report["ambiguous"] == 0
    record = restarted_vault._find_file(project["id"], section["id"], candidate["id"])
    assert record["state"] == "retired"
    assert Path(record["vault_path"]).read_text(encoding="utf-8") == "crash-safe"
    assert Path(record["transition_evidence_path"]).read_text(encoding="utf-8") == "crash-safe"
    assert restarted.verify_receipt(report["receipts"][0])["ok"] is True
    assert restarted_evidence.verify_chain()["ok"] is True


def test_restart_after_catalog_commit_finalizes_exact_receipt(tmp_path: Path):
    runtime = _runtime(tmp_path)
    _, vault, _, _, transitions, project, section, identity = runtime
    candidate = _candidate(runtime, tmp_path, body="committed")
    token = _token(
        vault, action_key="retire_object", project_id=project["id"], section_id=section["id"],
        object_id=candidate["id"], session_id=identity.session_id,
    )
    with pytest.raises(SimulatedStateTransitionCrash, match="mutation_committed"):
        transitions.retire(
            project_id=project["id"], section_id=section["id"], object_id=candidate["id"],
            ceremony_token=token, session_id=identity.session_id, fault_after="mutation_committed",
        )
    pending = transitions.journal.pending()
    assert len(pending) == 1
    operation_id = pending[0]["operation_id"]

    restarted_evidence = CanonicalEvidenceAdapter(tmp_path, session_id="state-transition-tests")
    restarted_vault = VaultEngine(tmp_path, blackbox=restarted_evidence, strict_ceremony_tokens=True)
    restarted = StateTransitionTransactionCoordinator(
        restarted_vault,
        restarted_evidence,
        NotificationManager(tmp_path, blackbox=restarted_evidence),
    )
    report = restarted.reconcile_pending()
    assert report["reconciled"] == 1
    receipt_id = report["receipts"][0]
    assert restarted.verify_receipt(receipt_id)["ok"] is True
    assert len(restarted_evidence.records_for_operation(operation_id)) == 5
    assert restarted.journal.pending() == []


def test_ambiguous_destination_is_frozen_for_human_reconciliation(tmp_path: Path):
    runtime = _runtime(tmp_path)
    _, vault, _, _, transitions, project, section, identity = runtime
    candidate = _candidate(runtime, tmp_path, body="preserve me")
    token = _token(
        vault, action_key="retire_object", project_id=project["id"], section_id=section["id"],
        object_id=candidate["id"], session_id=identity.session_id,
    )
    with pytest.raises(SimulatedStateTransitionCrash, match="authorized"):
        transitions.retire(
            project_id=project["id"], section_id=section["id"], object_id=candidate["id"],
            ceremony_token=token, session_id=identity.session_id, fault_after="authorized",
        )
    pending = transitions.journal.pending()[0]
    destination = Path(pending["destination_path"])
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text("conflicting bytes", encoding="utf-8")

    restarted_evidence = CanonicalEvidenceAdapter(tmp_path, session_id="state-transition-tests")
    restarted_vault = VaultEngine(tmp_path, blackbox=restarted_evidence, strict_ceremony_tokens=True)
    restarted = StateTransitionTransactionCoordinator(
        restarted_vault,
        restarted_evidence,
        NotificationManager(tmp_path, blackbox=restarted_evidence),
    )
    report = restarted.reconcile_pending()
    assert report["ambiguous"] == 1
    record = restarted_vault._find_file(project["id"], section["id"], candidate["id"])
    assert record["trust_locked"] is True
    assert record["state_transition_reconciliation_required"]["transaction_id"] == pending["operation_id"]
    assert restarted.journal.pending() == []


def test_receipt_tampering_is_detected(tmp_path: Path):
    runtime = _runtime(tmp_path)
    _, _, _, _, transitions, _, _, _ = runtime
    candidate = _candidate(runtime, tmp_path)
    completed = _retire(runtime, candidate)
    receipt_id = completed["receipt"]["receipt_id"]
    path = transitions.receipts.receipt_dir / f"{receipt_id}.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["target_state"] = "candidate"
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert transitions.verify_receipt(receipt_id)["ok"] is False



def test_journal_reservation_retry_returns_exact_existing_record(tmp_path: Path):
    runtime = _runtime(tmp_path)
    _, _, _, _, transitions, project, section, _ = runtime
    record = {
        **transitions._ids(),
        "action_key": "retire_object",
        "project_id": project["id"],
        "section_id": section["id"],
        "object_id": "object-identity",
        "source_state": "candidate",
        "target_state": "retired",
        "source_path": str(tmp_path / "source"),
        "destination_path": str(tmp_path / "destination"),
        "expected_hash": "0" * 64,
        "expected_size": 0,
    }
    first = transitions.journal.reserve(record)
    second = transitions.journal.reserve(record)
    assert first == second
    conflicting = dict(record)
    conflicting["target_state"] = "archived"
    with pytest.raises(StateTransitionTransactionError, match="reservation conflicts"):
        transitions.journal.reserve(conflicting)


@pytest.mark.parametrize("fault_stage", ["anchor_recorded", "receipt_written"])
def test_finalization_restart_reuses_exact_evidence_and_receipt(tmp_path: Path, fault_stage: str):
    runtime = _runtime(tmp_path)
    _, vault, _, _, transitions, project, section, identity = runtime
    candidate = _candidate(runtime, tmp_path, f"{fault_stage}.txt", fault_stage)
    token = _token(
        vault, action_key="retire_object", project_id=project["id"], section_id=section["id"],
        object_id=candidate["id"], session_id=identity.session_id,
    )
    with pytest.raises(SimulatedStateTransitionCrash, match=fault_stage):
        transitions.retire(
            project_id=project["id"], section_id=section["id"], object_id=candidate["id"],
            ceremony_token=token, session_id=identity.session_id, fault_after=fault_stage,
        )
    pending = transitions.journal.pending()[0]
    operation_id = pending["operation_id"]
    receipt_id = pending["receipt_id"]
    before = transitions.evidence.records_for_operation(operation_id)
    assert len(before) == 5

    evidence = CanonicalEvidenceAdapter(tmp_path, session_id="state-transition-tests")
    vault = VaultEngine(tmp_path, blackbox=evidence, strict_ceremony_tokens=True)
    restarted = StateTransitionTransactionCoordinator(
        vault, evidence, NotificationManager(tmp_path, blackbox=evidence)
    )
    report = restarted.reconcile_pending()
    assert report["reconciled"] == 1
    assert report["receipts"] == [receipt_id]
    assert restarted.verify_receipt(receipt_id)["ok"] is True
    after = evidence.records_for_operation(operation_id)
    assert [item["record_id"] for item in after] == [item["record_id"] for item in before]
    assert restarted.journal.pending() == []

def test_exact_http_routes_complete_retire_and_restore(tmp_path: Path):
    evidence, vault, humans, promotion = server.build_canonical_v21_runtime(
        tmp_path, oubliette_mode="transaction"
    )
    project = vault.create_project("HTTP Project")
    section = vault.create_section(project["id"], "Core")
    candidate = vault.add_candidate(
        project["id"], section["id"], str(_source(tmp_path, "http.txt", "http bytes"))
    )
    identity = humans.issue_identity_session(
        "josie", ActorKind.HUMAN, verified_methods=["human_ceremony", "typing_challenge"]
    )
    vault.open_vault()
    old = {
        "blackbox21": server.blackbox21,
        "canonical_evidence21": server.canonical_evidence21,
        "vault21": server.vault21,
        "human_access": server.human_access,
        "promotion21": server.promotion21,
    }
    server.blackbox21 = evidence
    server.canonical_evidence21 = evidence
    server.vault21 = vault
    server.human_access = humans
    server.promotion21 = promotion
    try:
        token = _token(
            vault, action_key="retire_object", project_id=project["id"], section_id=section["id"],
            object_id=candidate["id"], session_id=identity.session_id,
        )
        with TestClient(server.app) as client:
            response = client.post(
                f"/api/v21/projects/{project['id']}/sections/{section['id']}/objects/{candidate['id']}/retire",
                json={"ceremony_token": token, "session_id": identity.session_id, "reason": "HTTP retire"},
            )
            assert response.status_code == 200, response.text
            assert response.json()["result"]["state"] == "retired"
            assert response.json()["verification"]["ok"] is True

            restore_token = _token(
                vault, action_key="restore_retired_object", project_id=project["id"],
                section_id=section["id"], object_id=candidate["id"], session_id=identity.session_id,
            )
            response = client.post(
                f"/api/v21/projects/{project['id']}/sections/{section['id']}/objects/{candidate['id']}/restore",
                json={"ceremony_token": restore_token, "session_id": identity.session_id, "reason": "HTTP restore"},
            )
            assert response.status_code == 200, response.text
            assert response.json()["result"]["state"] == "candidate"
            assert response.json()["verification"]["ok"] is True

            paths = {route.path for route in server.app.routes}
            assert "/api/v21/projects/{project_id}/sections/{section_id}/objects/{object_id}/retire" in paths
            assert "/api/v21/projects/{project_id}/sections/{section_id}/objects/{object_id}/restore" in paths
            assert not any("restore-from-removed" in path for path in paths)
    finally:
        for key, value in old.items():
            setattr(server, key, value)
