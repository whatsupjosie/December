from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from iteration_wallet import server
from iteration_wallet.canonical_evidence import (
    CanonicalEvidenceAdapter,
    CanonicalEvidenceError,
    HumanIntentReceiptStore,
)
from iteration_wallet.ceremony import CeremonyTokenError, CeremonyTokenLedger
from iteration_wallet.notification_manager import ActorKind, NotificationManager
from iteration_wallet.promotion_transaction import (
    PromotionJournal,
    PromotionTransactionCoordinator,
    PromotionTransactionError,
)
from iteration_wallet.vault_v21 import VaultEngine, VaultError


def _source(root: Path, name: str, text: str = "candidate") -> Path:
    path = root / name
    path.write_text(text, encoding="utf-8")
    return path


def _integrated(root: Path):
    evidence = CanonicalEvidenceAdapter(root, session_id="audit")
    vault = VaultEngine(root, blackbox=evidence, strict_ceremony_tokens=True)
    humans = NotificationManager(root, blackbox=evidence)
    coordinator = PromotionTransactionCoordinator(vault, evidence, humans)
    project = vault.create_project("Audit")
    section = vault.create_section(project["id"], "Core")
    identity = humans.issue_identity_session(
        "josie",
        ActorKind.HUMAN,
        verified_methods=["human_ceremony", "typing_challenge"],
    )
    vault.open_vault()
    return evidence, vault, humans, coordinator, project, section, identity


def _token(vault: VaultEngine, project: dict, section: dict, candidate: dict, session_id: str) -> str:
    return vault.issue_ceremony_token(
        "promote_candidate_to_prime",
        session_id,
        actor_id="josie",
        project_id=project["id"],
        section_id=section["id"],
        object_id=candidate["id"],
    )["ceremony_token"]


def test_default_server_does_not_silently_fall_back_to_legacy_promotion_authority():
    assert server.promotion21 is not None
    assert isinstance(server.blackbox21, CanonicalEvidenceAdapter)


def test_strict_engine_direct_promotion_cannot_bypass_transaction_coordinator(tmp_path: Path):
    evidence, vault, humans, coordinator, project, section, identity = _integrated(tmp_path)
    candidate = vault.add_candidate(
        project["id"], section["id"], str(_source(tmp_path, "direct.txt"))
    )
    token = _token(vault, project, section, candidate, identity.session_id)
    with pytest.raises(VaultError, match="transaction coordinator"):
        vault.promote_to_prime(
            project["id"],
            section["id"],
            candidate["id"],
            token,
            session_id=identity.session_id,
        )


def test_scoped_action_rejects_token_whose_required_object_scope_is_missing(tmp_path: Path):
    ledger = CeremonyTokenLedger(tmp_path)
    issued = ledger.issue_token(
        action_key="promote_candidate_to_prime",
        session_id="session-1",
        open_session_id="open-1",
        actor_id="josie",
        project_id="project-1",
        section_id="section-1",
        object_id=None,
    )
    with pytest.raises(CeremonyTokenError, match="object_id"):
        ledger.validate_and_consume(
            issued["ceremony_token"],
            action_key="promote_candidate_to_prime",
            session_id="session-1",
            open_session_id="open-1",
            project_id="project-1",
            section_id="section-1",
            object_id="candidate-1",
        )
    assert ledger.get_record(issued["token_id"])["consumed_at"] is None


def test_one_time_ceremony_token_is_single_consumer_under_a_forced_race(tmp_path: Path):
    issuer = CeremonyTokenLedger(tmp_path)
    issued = issuer.issue_token(
        action_key="promote_candidate_to_prime",
        session_id="session-1",
        open_session_id="open-1",
        actor_id="josie",
        project_id="project-1",
        section_id="section-1",
        object_id="candidate-1",
    )
    contenders = 8
    barrier = threading.Barrier(contenders)
    outcomes: list[str] = []
    outcome_lock = threading.Lock()

    def worker() -> None:
        ledger = CeremonyTokenLedger(tmp_path)
        barrier.wait(timeout=5)
        try:
            ledger.validate_and_consume(
                issued["ceremony_token"],
                action_key="promote_candidate_to_prime",
                session_id="session-1",
                open_session_id="open-1",
                project_id="project-1",
                section_id="section-1",
                object_id="candidate-1",
            )
        except CeremonyTokenError:
            outcome = "denied"
        except Exception as exc:  # any storage race is itself a regression
            outcome = f"error:{type(exc).__name__}"
        else:
            outcome = "consumed"
        with outcome_lock:
            outcomes.append(outcome)

    threads = [threading.Thread(target=worker) for _ in range(contenders)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
    assert not any(thread.is_alive() for thread in threads)
    assert outcomes.count("consumed") == 1
    assert outcomes.count("denied") == contenders - 1
    assert not [outcome for outcome in outcomes if outcome.startswith("error:")]


def test_consumed_ceremony_record_is_immutable_and_receipt_binding_stays_stable(tmp_path: Path):
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
    ledger.validate_and_consume(
        issued["ceremony_token"],
        action_key="promote_candidate_to_prime",
        session_id="session-1",
        open_session_id="open-1",
        project_id="project-1",
        section_id="section-1",
        object_id="candidate-1",
    )
    before = ledger.record_hash(issued["token_id"])
    with pytest.raises(CeremonyTokenError, match="consumed"):
        ledger.revoke_token(issued["ceremony_token"], "too late")
    assert ledger.record_hash(issued["token_id"]) == before


def test_receipt_storage_ids_cannot_escape_receipt_root(tmp_path: Path):
    store = HumanIntentReceiptStore(tmp_path)
    (tmp_path / "outside.json").write_text('{"receipt_id":"outside"}', encoding="utf-8")
    with pytest.raises(CanonicalEvidenceError, match="invalid receipt_id"):
        store.get("../outside")
    with pytest.raises(CanonicalEvidenceError, match="invalid receipt_id"):
        store.create({"receipt_id": "../escape", "value": "bad"})


def test_journal_operation_ids_cannot_escape_active_directory(tmp_path: Path):
    journal = PromotionJournal(tmp_path)
    with pytest.raises(PromotionTransactionError, match="invalid operation_id"):
        journal.reserve({"operation_id": "../../escape"})
    assert not (tmp_path / "recovery_journal" / "escape.json").exists()


def test_receipt_reader_rejects_duplicate_json_keys(tmp_path: Path):
    store = HumanIntentReceiptStore(tmp_path)
    path = store.receipt_dir / "dup.json"
    path.write_text('{"receipt_id":"dup","receipt_id":"other"}', encoding="utf-8")
    with pytest.raises(CanonicalEvidenceError, match="duplicate"):
        store.get("dup")


def test_receipt_verifier_rejects_extra_conflicting_terminal_stage(tmp_path: Path):
    evidence, vault, humans, coordinator, project, section, identity = _integrated(tmp_path)
    candidate = vault.add_candidate(
        project["id"], section["id"], str(_source(tmp_path, "extra-stage.txt"))
    )
    result = coordinator.promote_to_prime(
        project_id=project["id"],
        section_id=section["id"],
        candidate_id=candidate["id"],
        ceremony_token=_token(vault, project, section, candidate, identity.session_id),
        session_id=identity.session_id,
        reason="valid before conflicting stage",
    )
    receipt = result["receipt"]
    evidence.append_fact(
        event_type="HUMAN_INTENT_FAILED",
        summary="contradictory terminal stage",
        transaction_id=receipt["operation_id"],
        stage_key=f"{receipt['operation_id']}:FAILED-CONTRADICTORY",
        actor="wallet:tamper-probe",
        subject_id=f"candidate:{candidate['id']}",
        payload={
            "transaction_id": receipt["operation_id"],
            "result_status": "failed",
            "object_id": candidate["id"],
        },
    )
    verification = coordinator.verify_receipt(receipt["receipt_id"])
    assert verification["ok"] is False
    assert "contradictory" in verification["reason"] or "duplicate" in verification["reason"]
