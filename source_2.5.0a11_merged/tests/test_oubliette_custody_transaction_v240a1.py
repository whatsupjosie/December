from __future__ import annotations

import json
from pathlib import Path

import pytest

from iteration_wallet.canonical_evidence import CanonicalEvidenceAdapter
from iteration_wallet.notification_manager import ActorKind, NotificationManager
from iteration_wallet.oubliette_transaction import (
    OublietteTransactionCoordinator,
    OublietteTransactionError,
    SimulatedOublietteCrash,
)
from iteration_wallet.promotion_transaction import PromotionTransactionCoordinator
from iteration_wallet.vault_v21 import VaultEngine, VaultError


def _runtime(tmp_path: Path):
    evidence = CanonicalEvidenceAdapter(tmp_path, session_id="wallet-main")
    vault = VaultEngine(tmp_path, blackbox=evidence, strict_ceremony_tokens=True)
    humans = NotificationManager(tmp_path, blackbox=evidence)
    promotion = PromotionTransactionCoordinator(vault, evidence, humans)
    oubliette = OublietteTransactionCoordinator(vault, evidence, humans, participation_mode="transaction")
    vault.oubliette_coordinator = oubliette
    project = vault.create_project("Oubliette Project")
    section = vault.create_section(project["id"], "Intake")
    identity = humans.issue_identity_session(
        "josie",
        ActorKind.HUMAN,
        device_id="review-machine",
        verified_methods=["human_ceremony", "typing_challenge"],
    )
    vault.open_vault()
    return evidence, vault, humans, promotion, oubliette, project, section, identity


def _candidate(vault: VaultEngine, project: dict, section: dict, tmp_path: Path, name="unknown.py"):
    marker = tmp_path / "must_not_execute.txt"
    source = tmp_path / name
    source.write_text(
        f"from pathlib import Path\nPath({str(marker)!r}).write_text('executed')\n"
        "import subprocess\nsubprocess.run(['echo', 'unsafe'])\n",
        encoding="utf-8",
    )
    return vault.add_candidate(project["id"], section["id"], str(source)), marker


def _token(vault: VaultEngine, project: dict, section: dict, object_id: str, session_id: str):
    record = vault._find_file(project["id"], section["id"], object_id)
    report_id = str(record.get("latest_oubliette_report_id") or "")
    scope = {}
    if report_id:
        proposal = vault.oubliette_coordinator.quarantine_proposal(
            project_id=project["id"],
            section_id=section["id"],
            object_id=object_id,
            report_id=report_id,
        )
        scope = {
            "proposal_id": proposal["proposal_id"],
            "proposal_hash": proposal["proposal_hash"],
        }
    return vault.issue_ceremony_token(
        "quarantine",
        session_id,
        actor_id="josie",
        project_id=project["id"],
        section_id=section["id"],
        object_id=object_id,
        **scope,
    )["ceremony_token"]


def test_static_intake_report_is_write_once_scoped_and_canonical(tmp_path: Path):
    evidence, vault, _, _, oubliette, project, section, _ = _runtime(tmp_path)
    candidate, marker = _candidate(vault, project, section, tmp_path)
    before = Path(candidate["vault_path"]).read_bytes()

    result = oubliette.inspect_object(
        project_id=project["id"],
        section_id=section["id"],
        object_id=candidate["id"],
        actor_kind="human",
    )

    assert marker.exists() is False
    assert Path(candidate["vault_path"]).read_bytes() == before
    assert result["authority"] == {
        "custody_changed": False,
        "trust_decided": False,
        "quarantine_requires_human_intent": True,
    }
    report = result["report"]
    assert report["object_id"] == candidate["id"]
    assert report["target_sha256"] == candidate["hash"]
    assert report["canonical_event_id"]
    assert report["canonical_event_hash"]
    assert report["malware_determined"] is False
    assert report["custody_changed"] is False

    stored = vault._find_file(project["id"], section["id"], candidate["id"])
    assert stored["latest_oubliette_report_id"] == report["report_id"]
    assert stored["state"] == "candidate"
    event = evidence.record_by_id(report["canonical_event_id"])
    assert event["event_type"] == "OUBLIETTE_STATIC_INSPECTION_COMPLETED"
    assert event["payload"]["target_executed"] is False
    assert event["payload"]["malware_determined"] is False

    repeated = oubliette.inspect_object(
        project_id=project["id"],
        section_id=section["id"],
        object_id=candidate["id"],
        actor_kind="human",
    )
    assert repeated["report"]["report_id"] == report["report_id"]
    assert len(vault._find_file(project["id"], section["id"], candidate["id"])["oubliette_inspections"]) == 1


def test_ai_or_bot_cannot_operate_custodied_oubliette_inspection(tmp_path: Path):
    _, vault, _, _, oubliette, project, section, _ = _runtime(tmp_path)
    candidate, _ = _candidate(vault, project, section, tmp_path)
    for actor in ("ai", "bot"):
        with pytest.raises(OublietteTransactionError, match="prohibited"):
            oubliette.inspect_object(
                project_id=project["id"],
                section_id=section["id"],
                object_id=candidate["id"],
                actor_kind=actor,
            )


def test_quarantine_requires_exact_registered_report_and_scoped_human_intent(tmp_path: Path):
    evidence, vault, _, _, oubliette, project, section, identity = _runtime(tmp_path)
    candidate_a, _ = _candidate(vault, project, section, tmp_path, "a.py")
    candidate_b, _ = _candidate(vault, project, section, tmp_path, "b.py")
    inspection = oubliette.inspect_object(
        project_id=project["id"], section_id=section["id"], object_id=candidate_a["id"], actor_kind="human"
    )
    token = _token(vault, project, section, candidate_b["id"], identity.session_id)

    with pytest.raises(OublietteTransactionError, match="scope"):
        oubliette.quarantine(
            project_id=project["id"],
            section_id=section["id"],
            object_id=candidate_b["id"],
            report_id=inspection["report"]["report_id"],
            ceremony_token=token,
            session_id=identity.session_id,
            reason="wrong report probe",
        )

    assert vault._find_file(project["id"], section["id"], candidate_b["id"])["state"] == "candidate"
    token_id = vault.ceremony_ledger.parse_token_id(token)
    assert vault.ceremony_ledger.get_record(token_id)["consumed_at"] is None
    assert evidence.verify_chain()["ok"] is True


def test_wallet_owned_quarantine_preserves_bytes_and_mints_verifiable_receipt(tmp_path: Path):
    evidence, vault, _, _, oubliette, project, section, identity = _runtime(tmp_path)
    candidate, marker = _candidate(vault, project, section, tmp_path)
    original_path = Path(candidate["vault_path"])
    original_bytes = original_path.read_bytes()
    inspection = oubliette.inspect_object(
        project_id=project["id"], section_id=section["id"], object_id=candidate["id"], actor_kind="human"
    )
    token = _token(vault, project, section, candidate["id"], identity.session_id)

    completed = oubliette.quarantine(
        project_id=project["id"],
        section_id=section["id"],
        object_id=candidate["id"],
        report_id=inspection["report"]["report_id"],
        ceremony_token=token,
        session_id=identity.session_id,
        reason="static indicators require fenced review",
    )

    result = completed["result"]
    quarantined_path = Path(result["vault_path"])
    assert marker.exists() is False
    assert original_path.exists() is False
    assert quarantined_path.is_file()
    assert quarantined_path.read_bytes() == original_bytes
    assert result["state"] == "quarantined"
    assert result["execution_allowed"] is False
    assert result["quarantine_report_id"] == inspection["report"]["report_id"]
    assert completed["verification"]["ok"] is True
    assert evidence.verify_human_intent_receipt(completed["receipt"]["receipt_id"])["ok"] is True

    events = [
        record["event_type"]
        for record in evidence.records_for_operation(completed["receipt"]["operation_id"])
    ]
    assert events == [
        "HUMAN_INTENT_RESERVED",
        "HUMAN_INTENT_AUTHORIZED",
        "OBJECT_QUARANTINED",
        "HUMAN_INTENT_COMPLETED",
        "HUMAN_INTENT_RECEIPT_ANCHORED",
    ]
    assert not (tmp_path / "blackbox" / "events").exists()


def test_direct_engine_quarantine_cannot_bypass_coordinator(tmp_path: Path):
    _, vault, _, _, _, project, section, identity = _runtime(tmp_path)
    candidate, _ = _candidate(vault, project, section, tmp_path)
    token = _token(vault, project, section, candidate["id"], identity.session_id)
    with pytest.raises(VaultError, match="transaction coordinator"):
        vault.quarantine_file(
            project["id"], section["id"], candidate["id"], token, reason="bypass"
        )


def test_crash_after_quarantine_move_reconciles_without_replaying_move(tmp_path: Path):
    evidence, vault, _, _, oubliette, project, section, identity = _runtime(tmp_path)
    candidate, _ = _candidate(vault, project, section, tmp_path)
    inspection = oubliette.inspect_object(
        project_id=project["id"], section_id=section["id"], object_id=candidate["id"], actor_kind="human"
    )
    token = _token(vault, project, section, candidate["id"], identity.session_id)

    with pytest.raises(SimulatedOublietteCrash):
        oubliette.quarantine(
            project_id=project["id"],
            section_id=section["id"],
            object_id=candidate["id"],
            report_id=inspection["report"]["report_id"],
            ceremony_token=token,
            session_id=identity.session_id,
            reason="fault campaign",
            fault_after="mutation_committed",
        )

    after = vault._find_file(project["id"], section["id"], candidate["id"])
    path_after = Path(after["vault_path"])
    assert after["state"] == "quarantined"
    assert path_after.is_file()

    restarted_vault = VaultEngine(tmp_path, blackbox=evidence, strict_ceremony_tokens=True)
    restarted_humans = NotificationManager(tmp_path, blackbox=evidence)
    PromotionTransactionCoordinator(restarted_vault, evidence, restarted_humans)
    restarted = OublietteTransactionCoordinator(restarted_vault, evidence, restarted_humans, participation_mode="transaction")
    report = restarted.reconcile_pending()

    assert report["reconciled"] == 1
    assert report["ambiguous"] == 0
    final = restarted_vault._find_file(project["id"], section["id"], candidate["id"])
    assert Path(final["vault_path"]) == path_after
    assert final["state"] == "quarantined"
    assert restarted.verify_receipt(report["receipts"][0])["ok"] is True


def test_authorized_crash_before_move_reconciles_as_failed_noop(tmp_path: Path):
    evidence, vault, _, _, oubliette, project, section, identity = _runtime(tmp_path)
    candidate, _ = _candidate(vault, project, section, tmp_path)
    original_path = Path(candidate["vault_path"])
    inspection = oubliette.inspect_object(
        project_id=project["id"], section_id=section["id"], object_id=candidate["id"], actor_kind="human"
    )
    token = _token(vault, project, section, candidate["id"], identity.session_id)

    with pytest.raises(SimulatedOublietteCrash):
        oubliette.quarantine(
            project_id=project["id"],
            section_id=section["id"],
            object_id=candidate["id"],
            report_id=inspection["report"]["report_id"],
            ceremony_token=token,
            session_id=identity.session_id,
            reason="authorized crash",
            fault_after="authorized",
        )

    restarted_vault = VaultEngine(tmp_path, blackbox=evidence, strict_ceremony_tokens=True)
    restarted_humans = NotificationManager(tmp_path, blackbox=evidence)
    PromotionTransactionCoordinator(restarted_vault, evidence, restarted_humans)
    restarted = OublietteTransactionCoordinator(restarted_vault, evidence, restarted_humans, participation_mode="transaction")
    report = restarted.reconcile_pending()

    assert report["failed"] == 1
    final = restarted_vault._find_file(project["id"], section["id"], candidate["id"])
    assert final["state"] == "candidate"
    assert Path(final["vault_path"]) == original_path
    assert original_path.is_file()


def test_tampered_report_fails_before_custody_or_token_consumption(tmp_path: Path):
    _, vault, _, _, oubliette, project, section, identity = _runtime(tmp_path)
    candidate, _ = _candidate(vault, project, section, tmp_path)
    inspection = oubliette.inspect_object(
        project_id=project["id"], section_id=section["id"], object_id=candidate["id"], actor_kind="human"
    )
    report_id = inspection["report"]["report_id"]
    token = _token(vault, project, section, candidate["id"], identity.session_id)
    report_path = oubliette.reports._path(report_id)
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    payload["finding_codes"] = ["forged_safe_claim"]
    report_path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")

    with pytest.raises(OublietteTransactionError, match="hash mismatch"):
        oubliette.quarantine(
            project_id=project["id"],
            section_id=section["id"],
            object_id=candidate["id"],
            report_id=report_id,
            ceremony_token=token,
            session_id=identity.session_id,
            reason="tamper probe",
        )
    token_id = vault.ceremony_ledger.parse_token_id(token)
    assert vault.ceremony_ledger.get_record(token_id)["consumed_at"] is None
    assert vault._find_file(project["id"], section["id"], candidate["id"])["state"] == "candidate"


def _quarantined_parent(tmp_path: Path):
    evidence, vault, humans, promotion, oubliette, project, section, identity = _runtime(tmp_path)
    candidate, marker = _candidate(vault, project, section, tmp_path, "parent_unknown.py")
    original_bytes = Path(candidate["vault_path"]).read_bytes()
    inspection = oubliette.inspect_object(
        project_id=project["id"],
        section_id=section["id"],
        object_id=candidate["id"],
        actor_kind="human",
    )
    token = _token(vault, project, section, candidate["id"], identity.session_id)
    completed = oubliette.quarantine(
        project_id=project["id"],
        section_id=section["id"],
        object_id=candidate["id"],
        report_id=inspection["report"]["report_id"],
        ceremony_token=token,
        session_id=identity.session_id,
        reason="preserve unknown original while a derivative is reviewed",
    )
    return (
        evidence,
        vault,
        humans,
        promotion,
        oubliette,
        project,
        section,
        identity,
        completed["result"],
        original_bytes,
        marker,
    )


def _derivative_token(
    vault: VaultEngine,
    project: dict,
    section: dict,
    parent_id: str,
    session_id: str,
    proposal: dict,
) -> str:
    return vault.issue_ceremony_token(
        "admit_oubliette_derivative_as_candidate",
        session_id,
        actor_id="josie",
        project_id=project["id"],
        section_id=section["id"],
        object_id=parent_id,
        proposal_id=proposal["proposal_id"],
        proposal_hash=proposal["proposal_hash"],
    )["ceremony_token"]


def test_derivative_enters_only_as_new_candidate_while_original_stays_quarantined(tmp_path: Path):
    (
        evidence,
        vault,
        _,
        _,
        oubliette,
        project,
        section,
        identity,
        parent,
        original_bytes,
        marker,
    ) = _quarantined_parent(tmp_path)
    lab = tmp_path / "external_lab"
    lab.mkdir()
    derivative = lab / "reviewed_derivative.py"
    derivative.write_text("print('reviewed copy; still external until admitted')\n", encoding="utf-8")
    derivative_bytes = derivative.read_bytes()

    inspection = oubliette.inspect_derivative(
        project_id=project["id"],
        section_id=section["id"],
        quarantined_object_id=parent["id"],
        derivative_path=derivative,
        allowed_root=lab,
        actor_kind="human",
    )
    token = _derivative_token(vault, project, section, parent["id"], identity.session_id, inspection["admission_proposal"])
    completed = oubliette.admit_derivative_as_candidate(
        project_id=project["id"],
        section_id=section["id"],
        parent_object_id=parent["id"],
        derivative_path=derivative,
        report_id=inspection["report"]["report_id"],
        ceremony_token=token,
        session_id=identity.session_id,
        reason="human reviewed the static findings and admits only this derivative",
    )

    admitted = completed["result"]
    preserved_parent = vault._find_file(project["id"], section["id"], parent["id"])
    assert marker.exists() is False
    assert preserved_parent["state"] == "quarantined"
    assert Path(preserved_parent["vault_path"]).read_bytes() == original_bytes
    assert admitted["id"] != parent["id"]
    assert admitted["state"] == "candidate"
    assert admitted["promoted"] is False
    assert admitted["trust_status"] == "candidate_only_no_automatic_trust"
    assert admitted["parent_quarantined_id"] == parent["id"]
    assert admitted["parent_quarantined_sha256"] == parent["hash"]
    assert admitted["oubliette_derivative_report_id"] == inspection["report"]["report_id"]
    assert Path(admitted["vault_path"]).read_bytes() == derivative_bytes
    assert derivative.read_bytes() == derivative_bytes
    assert completed["verification"]["ok"] is True
    assert evidence.verify_human_intent_receipt(completed["receipt"]["receipt_id"])["ok"] is True
    events = [
        record["event_type"]
        for record in evidence.records_for_operation(completed["receipt"]["operation_id"])
    ]
    assert events == [
        "HUMAN_INTENT_RESERVED",
        "HUMAN_INTENT_AUTHORIZED",
        "WALLET_INTAKE_CAPSULE_ADMITTED_AS_CANDIDATE",
        "HUMAN_INTENT_COMPLETED",
        "HUMAN_INTENT_RECEIPT_ANCHORED",
    ]


def test_external_source_change_after_capture_cannot_change_admitted_capsule(tmp_path: Path):
    _, vault, _, _, oubliette, project, section, identity, parent, _, _ = _quarantined_parent(tmp_path)
    lab = tmp_path / "external_lab"
    lab.mkdir()
    derivative = lab / "reviewed.txt"
    derivative.write_text("first bytes", encoding="utf-8")
    inspection = oubliette.inspect_derivative(
        project_id=project["id"],
        section_id=section["id"],
        quarantined_object_id=parent["id"],
        derivative_path=derivative,
        allowed_root=lab,
        actor_kind="human",
    )
    derivative.write_text("changed after capture", encoding="utf-8")
    token = _derivative_token(
        vault, project, section, parent["id"], identity.session_id,
        inspection["admission_proposal"],
    )

    completed = oubliette.admit_derivative_as_candidate(
        project_id=project["id"],
        section_id=section["id"],
        parent_object_id=parent["id"],
        derivative_path=derivative,
        report_id=inspection["report"]["report_id"],
        ceremony_token=token,
        session_id=identity.session_id,
        reason="admit exact captured bytes, not the later path contents",
    )

    assert Path(completed["result"]["vault_path"]).read_bytes() == b"first bytes"
    assert derivative.read_text(encoding="utf-8") == "changed after capture"
    assert completed["result"]["wallet_intake_capsule_id"] == inspection["capsule"]["capsule_id"]
    token_id = vault.ceremony_ledger.parse_token_id(token)
    assert vault.ceremony_ledger.get_record(token_id)["consumed_at"] is not None

def test_derivative_report_cannot_be_reused_for_another_parent(tmp_path: Path):
    _, vault, _, _, oubliette, project, section, identity, parent_a, _, _ = _quarantined_parent(tmp_path)
    candidate_b, _ = _candidate(vault, project, section, tmp_path, "second_parent.py")
    second_inspection = oubliette.inspect_object(
        project_id=project["id"], section_id=section["id"], object_id=candidate_b["id"], actor_kind="human"
    )
    second_token = _token(vault, project, section, candidate_b["id"], identity.session_id)
    parent_b = oubliette.quarantine(
        project_id=project["id"],
        section_id=section["id"],
        object_id=candidate_b["id"],
        report_id=second_inspection["report"]["report_id"],
        ceremony_token=second_token,
        session_id=identity.session_id,
        reason="second parent",
    )["result"]
    lab = tmp_path / "external_lab"
    lab.mkdir()
    derivative = lab / "derived.txt"
    derivative.write_text("derived from parent a", encoding="utf-8")
    report = oubliette.inspect_derivative(
        project_id=project["id"],
        section_id=section["id"],
        quarantined_object_id=parent_a["id"],
        derivative_path=derivative,
        allowed_root=lab,
        actor_kind="human",
    )
    token = _derivative_token(vault, project, section, parent_b["id"], identity.session_id, report["admission_proposal"])

    with pytest.raises(OublietteTransactionError, match="scope"):
        oubliette.admit_derivative_as_candidate(
            project_id=project["id"],
            section_id=section["id"],
            parent_object_id=parent_b["id"],
            derivative_path=derivative,
            report_id=report["report"]["report_id"],
            ceremony_token=token,
            session_id=identity.session_id,
            reason="cross-parent replay probe",
        )
    token_id = vault.ceremony_ledger.parse_token_id(token)
    assert vault.ceremony_ledger.get_record(token_id)["consumed_at"] is None


def test_ai_or_bot_cannot_inspect_external_derivative(tmp_path: Path):
    _, _, _, _, oubliette, project, section, _, parent, _, _ = _quarantined_parent(tmp_path)
    lab = tmp_path / "external_lab"
    lab.mkdir()
    derivative = lab / "derived.txt"
    derivative.write_text("copy", encoding="utf-8")
    for actor in ("ai", "bot"):
        with pytest.raises(OublietteTransactionError, match="prohibited"):
            oubliette.inspect_derivative(
                project_id=project["id"],
                section_id=section["id"],
                quarantined_object_id=parent["id"],
                derivative_path=derivative,
                allowed_root=lab,
                actor_kind=actor,
            )


def test_crash_after_derivative_copy_reconciles_without_external_source(tmp_path: Path):
    evidence, vault, _, _, oubliette, project, section, identity, parent, _, _ = _quarantined_parent(tmp_path)
    lab = tmp_path / "external_lab"
    lab.mkdir()
    derivative = lab / "derived.txt"
    derivative.write_text("copy survives external source loss", encoding="utf-8")
    derivative_hash = vault._sha256(derivative)
    report = oubliette.inspect_derivative(
        project_id=project["id"],
        section_id=section["id"],
        quarantined_object_id=parent["id"],
        derivative_path=derivative,
        allowed_root=lab,
        actor_kind="human",
    )
    token = _derivative_token(vault, project, section, parent["id"], identity.session_id, report["admission_proposal"])

    with pytest.raises(SimulatedOublietteCrash):
        oubliette.admit_derivative_as_candidate(
            project_id=project["id"],
            section_id=section["id"],
            parent_object_id=parent["id"],
            derivative_path=derivative,
            report_id=report["report"]["report_id"],
            ceremony_token=token,
            session_id=identity.session_id,
            reason="copy-only crash campaign",
            fault_after="file_copied",
        )

    moved_external = lab / "source_removed_after_copy.txt"
    derivative.rename(moved_external)
    restarted_vault = VaultEngine(tmp_path, blackbox=evidence, strict_ceremony_tokens=True)
    restarted_humans = NotificationManager(tmp_path, blackbox=evidence)
    PromotionTransactionCoordinator(restarted_vault, evidence, restarted_humans)
    restarted = OublietteTransactionCoordinator(restarted_vault, evidence, restarted_humans, participation_mode="transaction")
    reconciliation = restarted.reconcile_pending()

    assert reconciliation["reconciled"] == 1
    assert reconciliation["ambiguous"] == 0
    receipt_id = reconciliation["receipts"][0]
    assert restarted.verify_receipt(receipt_id)["ok"] is True
    receipt = restarted.receipts.get(receipt_id)
    admitted = restarted_vault._find_file(project["id"], section["id"], receipt["result_object_id"])
    assert admitted["state"] == "candidate"
    assert admitted["hash"] == derivative_hash
    assert Path(admitted["vault_path"]).is_file()
    assert restarted_vault._find_file(project["id"], section["id"], parent["id"])["state"] == "quarantined"


def test_authorized_derivative_crash_before_copy_reconciles_as_failed_noop(tmp_path: Path):
    evidence, vault, _, _, oubliette, project, section, identity, parent, _, _ = _quarantined_parent(tmp_path)
    lab = tmp_path / "external_lab"
    lab.mkdir()
    derivative = lab / "derived.txt"
    derivative.write_text("copy was never admitted", encoding="utf-8")
    report = oubliette.inspect_derivative(
        project_id=project["id"],
        section_id=section["id"],
        quarantined_object_id=parent["id"],
        derivative_path=derivative,
        allowed_root=lab,
        actor_kind="human",
    )
    token = _derivative_token(vault, project, section, parent["id"], identity.session_id, report["admission_proposal"])

    with pytest.raises(SimulatedOublietteCrash):
        oubliette.admit_derivative_as_candidate(
            project_id=project["id"],
            section_id=section["id"],
            parent_object_id=parent["id"],
            derivative_path=derivative,
            report_id=report["report"]["report_id"],
            ceremony_token=token,
            session_id=identity.session_id,
            reason="authorized pre-copy crash",
            fault_after="authorized",
        )

    restarted_vault = VaultEngine(tmp_path, blackbox=evidence, strict_ceremony_tokens=True)
    restarted_humans = NotificationManager(tmp_path, blackbox=evidence)
    PromotionTransactionCoordinator(restarted_vault, evidence, restarted_humans)
    restarted = OublietteTransactionCoordinator(restarted_vault, evidence, restarted_humans, participation_mode="transaction")
    reconciliation = restarted.reconcile_pending()
    assert reconciliation["failed"] == 1
    files = restarted_vault.get_section(project["id"], section["id"])["files"]
    assert [item for item in files if item.get("parent_quarantined_id") == parent["id"]] == []
    assert restarted_vault._find_file(project["id"], section["id"], parent["id"])["state"] == "quarantined"


def test_proposal_scoped_token_cannot_be_swapped_between_two_valid_capsules(tmp_path: Path):
    _, vault, _, _, oubliette, project, section, identity, parent, _, _ = _quarantined_parent(tmp_path)
    lab = tmp_path / "external_lab"
    lab.mkdir()
    a = lab / "a.txt"
    b = lab / "b.txt"
    a.write_text("capsule a", encoding="utf-8")
    b.write_text("capsule b", encoding="utf-8")
    inspected_a = oubliette.inspect_derivative(
        project_id=project["id"], section_id=section["id"],
        quarantined_object_id=parent["id"], derivative_path=a, allowed_root=lab,
        actor_kind="human",
    )
    inspected_b = oubliette.inspect_derivative(
        project_id=project["id"], section_id=section["id"],
        quarantined_object_id=parent["id"], derivative_path=b, allowed_root=lab,
        actor_kind="human",
    )
    token = _derivative_token(
        vault, project, section, parent["id"], identity.session_id,
        inspected_a["admission_proposal"],
    )
    with pytest.raises(OublietteTransactionError, match="proposal_id"):
        oubliette.admit_intake_capsule_as_candidate(
            project_id=project["id"], section_id=section["id"],
            parent_object_id=parent["id"],
            capsule_id=inspected_b["capsule"]["capsule_id"],
            report_id=inspected_b["report"]["report_id"],
            ceremony_token=token, session_id=identity.session_id,
            reason="token swap probe",
        )
    token_id = vault.ceremony_ledger.parse_token_id(token)
    assert vault.ceremony_ledger.get_record(token_id)["consumed_at"] is None


def test_capsule_admission_is_semantically_idempotent(tmp_path: Path):
    _, vault, _, _, oubliette, project, section, identity, parent, _, _ = _quarantined_parent(tmp_path)
    lab = tmp_path / "external_lab"
    lab.mkdir()
    derivative = lab / "result.txt"
    derivative.write_text("one logical result", encoding="utf-8")
    inspected = oubliette.inspect_derivative(
        project_id=project["id"], section_id=section["id"],
        quarantined_object_id=parent["id"], derivative_path=derivative,
        allowed_root=lab, actor_kind="human",
    )
    token = _derivative_token(
        vault, project, section, parent["id"], identity.session_id,
        inspected["admission_proposal"],
    )
    first = oubliette.admit_intake_capsule_as_candidate(
        project_id=project["id"], section_id=section["id"],
        parent_object_id=parent["id"], capsule_id=inspected["capsule"]["capsule_id"],
        report_id=inspected["report"]["report_id"], ceremony_token=token,
        session_id=identity.session_id, reason="first admission",
    )
    second = oubliette.admit_intake_capsule_as_candidate(
        project_id=project["id"], section_id=section["id"],
        parent_object_id=parent["id"], capsule_id=inspected["capsule"]["capsule_id"],
        report_id=inspected["report"]["report_id"], ceremony_token="not-used-on-retry",
        session_id=identity.session_id, reason="semantic retry",
    )
    assert second["idempotent_existing"] is True
    assert second["result"]["id"] == first["result"]["id"]
    assert second["receipt"]["receipt_id"] == first["receipt"]["receipt_id"]
    derived = [
        item for item in vault.get_section(project["id"], section["id"])["files"]
        if item.get("wallet_intake_capsule_id") == inspected["capsule"]["capsule_id"]
    ]
    assert len(derived) == 1


def test_capsule_admission_survives_external_source_deletion_before_ceremony(tmp_path: Path):
    _, vault, _, _, oubliette, project, section, identity, parent, _, _ = _quarantined_parent(tmp_path)
    lab = tmp_path / "external_lab"
    lab.mkdir()
    derivative = lab / "result.txt"
    derivative.write_text("preserved before source loss", encoding="utf-8")
    inspected = oubliette.inspect_derivative(
        project_id=project["id"], section_id=section["id"],
        quarantined_object_id=parent["id"], derivative_path=derivative,
        allowed_root=lab, actor_kind="human",
    )
    derivative.unlink()
    token = _derivative_token(
        vault, project, section, parent["id"], identity.session_id,
        inspected["admission_proposal"],
    )
    completed = oubliette.admit_intake_capsule_as_candidate(
        project_id=project["id"], section_id=section["id"],
        parent_object_id=parent["id"], capsule_id=inspected["capsule"]["capsule_id"],
        report_id=inspected["report"]["report_id"], ceremony_token=token,
        session_id=identity.session_id, reason="source is no longer required",
    )
    assert Path(completed["result"]["vault_path"]).read_text(encoding="utf-8") == "preserved before source loss"


def test_capsule_blob_tamper_fails_before_human_intent_consumption(tmp_path: Path):
    _, vault, _, _, oubliette, project, section, identity, parent, _, _ = _quarantined_parent(tmp_path)
    lab = tmp_path / "external_lab"
    lab.mkdir()
    derivative = lab / "result.txt"
    derivative.write_text("preserved bytes", encoding="utf-8")
    inspected = oubliette.inspect_derivative(
        project_id=project["id"], section_id=section["id"],
        quarantined_object_id=parent["id"], derivative_path=derivative,
        allowed_root=lab, actor_kind="human",
    )
    Path(inspected["capsule"]["absolute_blob_path"]).write_text("tampered", encoding="utf-8")
    token = _derivative_token(
        vault, project, section, parent["id"], identity.session_id,
        inspected["admission_proposal"],
    )
    with pytest.raises(OublietteTransactionError, match="blob"):
        oubliette.admit_intake_capsule_as_candidate(
            project_id=project["id"], section_id=section["id"],
            parent_object_id=parent["id"], capsule_id=inspected["capsule"]["capsule_id"],
            report_id=inspected["report"]["report_id"], ceremony_token=token,
            session_id=identity.session_id, reason="tamper probe",
        )
    token_id = vault.ceremony_ledger.parse_token_id(token)
    assert vault.ceremony_ledger.get_record(token_id)["consumed_at"] is None
