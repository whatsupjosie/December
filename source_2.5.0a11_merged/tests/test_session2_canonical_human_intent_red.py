from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from blackbox_plugin.errors import RecordValidationError
from blackbox_plugin.models import EvidenceEvent
from blackbox_plugin.schema import canonical_json
from iteration_wallet import server
from iteration_wallet.canonical_evidence import CanonicalEvidenceAdapter
from iteration_wallet.gatekeeper import evaluate_protected_action, get_protected_action_policy
from iteration_wallet.notification_manager import ActorKind, NotificationManager
from iteration_wallet.promotion_transaction import (
    PromotionTransactionCoordinator,
    SimulatedPromotionCrash,
)
from iteration_wallet.vault_v21 import VaultEngine


def _source(tmp_path: Path, name: str, text: str) -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def _integrated_wallet(tmp_path: Path):
    evidence = CanonicalEvidenceAdapter(tmp_path, session_id="wallet-main")
    vault = VaultEngine(tmp_path, blackbox=evidence, strict_ceremony_tokens=True)
    humans = NotificationManager(tmp_path, blackbox=evidence)
    coordinator = PromotionTransactionCoordinator(vault, evidence, humans)
    project = vault.create_project("Canonical Project")
    section = vault.create_section(project["id"], "Core")
    identity = humans.issue_identity_session(
        "josie",
        ActorKind.HUMAN,
        device_id="review-machine",
        verified_methods=["human_ceremony", "typing_challenge"],
    )
    vault.open_vault()
    return evidence, vault, humans, coordinator, project, section, identity


def _candidate(vault: VaultEngine, project: dict, section: dict, tmp_path: Path, name: str, text: str):
    return vault.add_candidate(project["id"], section["id"], str(_source(tmp_path, name, text)))


def _scoped_token(vault: VaultEngine, project: dict, section: dict, candidate: dict, session_id: str) -> str:
    return vault.issue_ceremony_token(
        "promote_candidate_to_prime",
        session_id,
        actor_id="josie",
        project_id=project["id"],
        section_id=section["id"],
        object_id=candidate["id"],
    )["ceremony_token"]


def test_strict_canonical_json_rejects_non_finite_surrogates_non_string_keys_and_unsafe_ints():
    bad_values = [
        {"confidence": float("nan")},
        {"confidence": float("inf")},
        {"confidence": float("-inf")},
        {"text": "\ud800"},
        {1: "not-a-string-key"},
        {"unsafe_integer": 2**53},
    ]
    for payload in bad_values:
        with pytest.raises(RecordValidationError):
            canonical_json(payload)
        with pytest.raises(RecordValidationError):
            EvidenceEvent(
                event_type="STRICT_JSON_PROBE",
                source="test",
                actor="human:josie",
                subject_id="candidate:1",
                payload=payload,
            )


def test_canonical_adapter_exposes_receipt_reads_but_cannot_mint_authority(tmp_path: Path):
    evidence = CanonicalEvidenceAdapter(tmp_path, session_id="read-only-authority")
    with pytest.raises(PermissionError, match="cannot mint Human Intent receipts"):
        evidence.issue_human_intent_receipt(
            action_key="promote_candidate_to_prime",
            object_id="candidate:forged",
        )


def test_retirement_policy_is_exact_human_only_and_does_not_invent_other_meanings(tmp_path: Path):
    evidence = CanonicalEvidenceAdapter(tmp_path, session_id="policy")
    humans = NotificationManager(tmp_path, blackbox=evidence)
    human = humans.issue_identity_session(
        "human", ActorKind.HUMAN, verified_methods=["human_ceremony"]
    )
    policy = get_protected_action_policy("retire_object")
    assert policy.label == "retire protected object"
    assert policy.allows_bot_direct_access is False

    denied = evaluate_protected_action(
        "retire_object",
        ActorKind.AI_ASSISTANT,
        human_ceremony_passed=True,
        gate=humans,
    )
    assert denied["allowed"] is False

    allowed = evaluate_protected_action(
        "retire_object",
        ActorKind.HUMAN,
        actor_identity=human,
        human_ceremony_passed=True,
        gate=humans,
    )
    assert allowed["allowed"] is True

    restore = get_protected_action_policy("restore_retired_object")
    assert restore.label == "restore retired object"
    assert restore.action_key != policy.action_key


def test_token_consumption_contract_is_explicit_not_a_dead_boolean():
    signature = inspect.signature(VaultEngine._require_open_token)
    assert "consume" not in signature.parameters


def test_canonical_promotion_emits_one_authoritative_graph_and_portable_receipt(tmp_path: Path):
    evidence, vault, humans, coordinator, project, section, identity = _integrated_wallet(tmp_path)

    old = _candidate(vault, project, section, tmp_path, "v1.txt", "trusted v1")
    old_token = _scoped_token(vault, project, section, old, identity.session_id)
    first = coordinator.promote_to_prime(
        project_id=project["id"],
        section_id=section["id"],
        candidate_id=old["id"],
        ceremony_token=old_token,
        session_id=identity.session_id,
        reason="initial prime",
    )
    assert first["verification"]["ok"] is True

    candidate = _candidate(vault, project, section, tmp_path, "v2.txt", "candidate v2")
    token = _scoped_token(vault, project, section, candidate, identity.session_id)
    result = coordinator.promote_to_prime(
        project_id=project["id"],
        section_id=section["id"],
        candidate_id=candidate["id"],
        ceremony_token=token,
        session_id=identity.session_id,
        reason="reviewed candidate",
    )

    assert result["result"]["state"] == "prime"
    assert vault._find_file(project["id"], section["id"], old["id"])["state"] == "archived"
    assert result["verification"]["ok"] is True
    assert result["verification"]["status"] == "complete"
    assert result["receipt"]["ceremony_token_id"]
    assert result["receipt"]["ceremony_consumption_hash"]
    assert "ceremony_token" not in result["receipt"]
    assert token not in json.dumps(result["receipt"])

    operation_id = result["receipt"]["operation_id"]
    operation_records = evidence.records_for_operation(operation_id)
    event_types = [record["event_type"] for record in operation_records]
    assert event_types == [
        "HUMAN_INTENT_RESERVED",
        "HUMAN_INTENT_AUTHORIZED",
        "PRIME_PROMOTED",
        "HUMAN_INTENT_COMPLETED",
        "HUMAN_INTENT_RECEIPT_ANCHORED",
    ]

    # The retired Wallet-native recorder must not receive a parallel write.
    assert not (tmp_path / "blackbox" / "events").exists()
    assert evidence.verify_chain()["ok"] is True


def test_crash_after_mutation_is_reconciled_without_replaying_the_move(tmp_path: Path):
    evidence, vault, humans, coordinator, project, section, identity = _integrated_wallet(tmp_path)
    candidate = _candidate(vault, project, section, tmp_path, "crash.txt", "crash candidate")
    token = _scoped_token(vault, project, section, candidate, identity.session_id)

    with pytest.raises(SimulatedPromotionCrash):
        coordinator.promote_to_prime(
            project_id=project["id"],
            section_id=section["id"],
            candidate_id=candidate["id"],
            ceremony_token=token,
            session_id=identity.session_id,
            reason="fault injection",
            fault_after="mutation_committed",
        )

    candidate_after_crash = vault._find_file(project["id"], section["id"], candidate["id"])
    promoted_path = Path(candidate_after_crash["vault_path"])
    assert candidate_after_crash["state"] == "prime"
    assert promoted_path.exists()

    restarted_vault = VaultEngine(tmp_path, blackbox=evidence, strict_ceremony_tokens=True)
    restarted_humans = NotificationManager(tmp_path, blackbox=evidence)
    restarted = PromotionTransactionCoordinator(restarted_vault, evidence, restarted_humans)
    report = restarted.reconcile_pending()

    assert report["reconciled"] == 1
    assert report["ambiguous"] == 0
    final_record = restarted_vault._find_file(project["id"], section["id"], candidate["id"])
    assert Path(final_record["vault_path"]) == promoted_path
    assert final_record["state"] == "prime"
    receipt = restarted.receipts.get(report["receipts"][0])
    assert restarted.verify_receipt(receipt["receipt_id"])["ok"] is True


def test_partial_filesystem_mutation_freezes_trust_instead_of_auto_rollback(tmp_path: Path):
    evidence, vault, humans, coordinator, project, section, identity = _integrated_wallet(tmp_path)
    old = _candidate(vault, project, section, tmp_path, "old.txt", "old prime")
    token1 = _scoped_token(vault, project, section, old, identity.session_id)
    coordinator.promote_to_prime(
        project_id=project["id"],
        section_id=section["id"],
        candidate_id=old["id"],
        ceremony_token=token1,
        session_id=identity.session_id,
        reason="setup",
    )

    new = _candidate(vault, project, section, tmp_path, "new.txt", "new candidate")
    token2 = _scoped_token(vault, project, section, new, identity.session_id)
    with pytest.raises(SimulatedPromotionCrash):
        coordinator.promote_to_prime(
            project_id=project["id"],
            section_id=section["id"],
            candidate_id=new["id"],
            ceremony_token=token2,
            session_id=identity.session_id,
            reason="partial fault",
            fault_after="old_prime_archived",
        )

    restarted_vault = VaultEngine(tmp_path, blackbox=evidence, strict_ceremony_tokens=True)
    restarted = PromotionTransactionCoordinator(
        restarted_vault,
        evidence,
        NotificationManager(tmp_path, blackbox=evidence),
    )
    report = restarted.reconcile_pending()

    assert report["ambiguous"] == 1
    affected = restarted_vault._find_file(project["id"], section["id"], new["id"])
    assert affected["trust_locked"] is True
    assert affected["trust_lock_reason"] == "promotion_reconciliation_required"
    section_after = restarted_vault.get_section(project["id"], section["id"])
    assert section_after.get("reconciliation_required") is True
    assert any(r["event_type"] == "PROMOTION_RECONCILIATION_REQUIRED" for r in evidence.records())


def test_live_server_promotion_route_is_the_law003_path(tmp_path: Path):
    old = {
        "vault21": server.vault21,
        "human_access": server.human_access,
        "blackbox21": getattr(server, "blackbox21", None),
        "canonical_evidence21": getattr(server, "canonical_evidence21", None),
        "promotion21": getattr(server, "promotion21", None),
    }
    try:
        evidence = CanonicalEvidenceAdapter(tmp_path, session_id="server-live")
        vault = VaultEngine(tmp_path, blackbox=evidence, strict_ceremony_tokens=True)
        humans = NotificationManager(tmp_path, blackbox=evidence)
        coordinator = PromotionTransactionCoordinator(vault, evidence, humans)
        server.blackbox21 = evidence
        server.vault21 = vault
        server.human_access = humans
        server.canonical_evidence21 = evidence
        server.promotion21 = coordinator
        client = TestClient(server.app)

        project = client.post("/api/v21/projects", json={"name": "Live LAW-003"}).json()
        section = client.post(
            f"/api/v21/projects/{project['id']}/sections", json={"name": "Core"}
        ).json()
        candidate = client.post(
            f"/api/v21/projects/{project['id']}/sections/{section['id']}/candidates",
            json={"path": str(_source(tmp_path, "live.txt", "live route")), "notes": ""},
        ).json()
        identity = humans.issue_identity_session(
            "josie", ActorKind.HUMAN, verified_methods=["human_ceremony"]
        )
        client.post("/api/v21/vault/open", json={"session_id": identity.session_id})
        token = client.post(
            "/api/v21/ceremony/tokens",
            json={
                "action_key": "promote_candidate_to_prime",
                "session_id": identity.session_id,
                "project_id": project["id"],
                "section_id": section["id"],
                "object_id": candidate["id"],
            },
        ).json()["ceremony_token"]

        response = client.post(
            f"/api/v21/projects/{project['id']}/sections/{section['id']}/candidates/{candidate['id']}/promote",
            json={
                "ceremony_token": token,
                "reason": "live gate",
                "actor_kind": "human",
                "session_id": identity.session_id,
                "human_ceremony_passed": True,
            },
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["human_intent_receipt"]["receipt_type"] == "human_intent_receipt_v2"
        receipt_id = body["human_intent_receipt"]["receipt_id"]
        assert coordinator.verify_receipt(receipt_id)["ok"] is True
        assert evidence.verify_chain()["ok"] is True

        listed = client.get("/api/v21/blackbox/receipts")
        assert listed.status_code == 200, listed.text
        assert [item["receipt_id"] for item in listed.json()["receipts"]] == [receipt_id]
        detail = client.get(f"/api/v21/blackbox/receipts/{receipt_id}")
        assert detail.status_code == 200, detail.text
        assert detail.json()["verification"]["ok"] is True
        report = client.get("/api/v21/blackbox/receipts/report")
        assert report.status_code == 200, report.text
        assert report.json()["all_receipts_valid"] is True
        assert report.json()["chain"]["ok"] is True
        status = client.get("/api/v21/private-alpha/status")
        assert status.status_code == 200, status.text
        assert status.json()["receipt_count"] == 1
    finally:
        server.vault21 = old["vault21"]
        server.human_access = old["human_access"]
        if old["blackbox21"] is not None:
            server.blackbox21 = old["blackbox21"]
        if old["canonical_evidence21"] is not None:
            server.canonical_evidence21 = old["canonical_evidence21"]
        if old["promotion21"] is not None:
            server.promotion21 = old["promotion21"]


def test_wrong_object_token_fails_before_mutation_and_closes_journal(tmp_path: Path):
    evidence, vault, humans, coordinator, project, section, identity = _integrated_wallet(tmp_path)
    first = _candidate(vault, project, section, tmp_path, "scope-a.txt", "A")
    second = _candidate(vault, project, section, tmp_path, "scope-b.txt", "B")
    token = _scoped_token(vault, project, section, first, identity.session_id)

    with pytest.raises(Exception, match="not valid for this object_id"):
        coordinator.promote_to_prime(
            project_id=project["id"],
            section_id=section["id"],
            candidate_id=second["id"],
            ceremony_token=token,
            session_id=identity.session_id,
            reason="wrong scope",
        )

    assert vault._find_file(project["id"], section["id"], second["id"])["state"] == "candidate"
    assert coordinator.journal.pending() == []
    completed = list(coordinator.journal.completed_dir.glob("*.json"))
    assert len(completed) == 1
    journal = json.loads(completed[0].read_text(encoding="utf-8"))
    assert journal["stage"] == "FAILED"


def test_authorized_crash_with_no_mutation_reconciles_as_failed(tmp_path: Path):
    evidence, vault, humans, coordinator, project, section, identity = _integrated_wallet(tmp_path)
    candidate = _candidate(vault, project, section, tmp_path, "authorized.txt", "candidate")
    token = _scoped_token(vault, project, section, candidate, identity.session_id)
    with pytest.raises(SimulatedPromotionCrash):
        coordinator.promote_to_prime(
            project_id=project["id"],
            section_id=section["id"],
            candidate_id=candidate["id"],
            ceremony_token=token,
            session_id=identity.session_id,
            reason="authorized crash",
            fault_after="authorized",
        )

    restarted = PromotionTransactionCoordinator(
        VaultEngine(tmp_path, blackbox=evidence, strict_ceremony_tokens=True),
        evidence,
        NotificationManager(tmp_path, blackbox=evidence),
    )
    report = restarted.reconcile_pending()
    assert report["failed"] == 1
    assert report["reconciled"] == 0
    assert restarted.journal.pending() == []


def test_receipt_and_ceremony_record_tampering_are_detected(tmp_path: Path):
    evidence, vault, humans, coordinator, project, section, identity = _integrated_wallet(tmp_path)
    candidate = _candidate(vault, project, section, tmp_path, "tamper.txt", "candidate")
    token = _scoped_token(vault, project, section, candidate, identity.session_id)
    completed = coordinator.promote_to_prime(
        project_id=project["id"],
        section_id=section["id"],
        candidate_id=candidate["id"],
        ceremony_token=token,
        session_id=identity.session_id,
        reason="tamper proof",
    )
    receipt = completed["receipt"]
    receipt_path = coordinator.receipts.receipt_dir / f"{receipt['receipt_id']}.json"
    data = json.loads(receipt_path.read_text(encoding="utf-8"))
    data["actor_id"] = "attacker"
    receipt_path.write_text(json.dumps(data), encoding="utf-8")
    assert coordinator.verify_receipt(receipt["receipt_id"])["reason"] == "receipt hash mismatch"

    # Restore the receipt, then tamper the consumed ceremony record.
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    token_path = vault.ceremony_ledger._path(receipt["ceremony_token_id"])
    token_data = json.loads(token_path.read_text(encoding="utf-8"))
    token_data["object_id"] = "different-object"
    token_path.write_text(json.dumps(token_data), encoding="utf-8")
    assert coordinator.verify_receipt(receipt["receipt_id"])["reason"] == "ceremony consumption hash mismatch"


def test_integrated_token_replay_cannot_create_second_promotion(tmp_path: Path):
    evidence, vault, humans, coordinator, project, section, identity = _integrated_wallet(tmp_path)
    candidate = _candidate(vault, project, section, tmp_path, "replay.txt", "candidate")
    token = _scoped_token(vault, project, section, candidate, identity.session_id)
    coordinator.promote_to_prime(
        project_id=project["id"],
        section_id=section["id"],
        candidate_id=candidate["id"],
        ceremony_token=token,
        session_id=identity.session_id,
        reason="first",
    )
    with pytest.raises(Exception, match="already been used"):
        coordinator.promote_to_prime(
            project_id=project["id"],
            section_id=section["id"],
            candidate_id=candidate["id"],
            ceremony_token=token,
            session_id=identity.session_id,
            reason="replay",
        )
    receipts = coordinator.receipts.list()
    assert len(receipts) == 1

@pytest.mark.parametrize("fault_stage", ["anchor_recorded", "receipt_written"])
def test_finalization_crash_retries_exact_receipt_without_duplicate_evidence(
    tmp_path: Path, fault_stage: str
):
    evidence, vault, humans, coordinator, project, section, identity = _integrated_wallet(tmp_path)
    candidate = _candidate(vault, project, section, tmp_path, f"{fault_stage}.txt", "candidate")
    token = _scoped_token(vault, project, section, candidate, identity.session_id)

    with pytest.raises(SimulatedPromotionCrash, match=fault_stage):
        coordinator.promote_to_prime(
            project_id=project["id"],
            section_id=section["id"],
            candidate_id=candidate["id"],
            ceremony_token=token,
            session_id=identity.session_id,
            reason="finalization crash proof",
            fault_after=fault_stage,
        )

    pending = coordinator.journal.pending()
    assert len(pending) == 1
    operation_id = pending[0]["operation_id"]
    receipt_id = pending[0]["receipt_id"]
    before = evidence.records_for_operation(operation_id)
    assert [record["event_type"] for record in before] == [
        "HUMAN_INTENT_RESERVED",
        "HUMAN_INTENT_AUTHORIZED",
        "PRIME_PROMOTED",
        "HUMAN_INTENT_COMPLETED",
        "HUMAN_INTENT_RECEIPT_ANCHORED",
    ]
    if fault_stage == "anchor_recorded":
        assert not (coordinator.receipts.receipt_dir / f"{receipt_id}.json").exists()
    else:
        assert (coordinator.receipts.receipt_dir / f"{receipt_id}.json").is_file()

    # Reconstruct every runtime object to prove restart safety rather than
    # relying on in-memory recorder state from before the simulated crash.
    restarted_evidence = CanonicalEvidenceAdapter(tmp_path, session_id="wallet-main")
    restarted_vault = VaultEngine(
        tmp_path, blackbox=restarted_evidence, strict_ceremony_tokens=True
    )
    restarted_humans = NotificationManager(tmp_path, blackbox=restarted_evidence)
    restarted = PromotionTransactionCoordinator(
        restarted_vault, restarted_evidence, restarted_humans
    )
    report = restarted.reconcile_pending()

    assert report["reconciled"] == 1
    assert report["ambiguous"] == 0
    assert report["receipts"] == [receipt_id]
    assert restarted.verify_receipt(receipt_id)["ok"] is True
    after = restarted_evidence.records_for_operation(operation_id)
    assert len(after) == 5
    assert [record["record_id"] for record in after] == [
        record["record_id"] for record in before
    ]
    assert restarted.journal.pending() == []
