from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from iteration_wallet.canonical_evidence import CanonicalEvidenceAdapter
from iteration_wallet.notification_manager import ActorKind, NotificationManager
from iteration_wallet.oubliette_transaction import OublietteTransactionCoordinator, OublietteTransactionError
from iteration_wallet.vault_v21 import VaultEngine


def _runtime(tmp_path: Path):
    evidence = CanonicalEvidenceAdapter(tmp_path, session_id="wallet-main")
    vault = VaultEngine(tmp_path, blackbox=evidence, strict_ceremony_tokens=True)
    humans = NotificationManager(tmp_path, blackbox=evidence)
    oubliette = OublietteTransactionCoordinator(
        vault, evidence, humans, participation_mode="transaction"
    )
    vault.oubliette_coordinator = oubliette
    project = vault.create_project("Quarantine Pipeline")
    section = vault.create_section(project["id"], "Inbound")
    identity = humans.issue_identity_session(
        "josie",
        ActorKind.HUMAN,
        device_id="review-machine",
        verified_methods=["human_ceremony", "typing_challenge"],
    )
    vault.open_vault()
    return evidence, vault, oubliette, project, section, identity


def _quarantine_one(tmp_path: Path):
    evidence, vault, oubliette, project, section, identity = _runtime(tmp_path)
    source = tmp_path / "suspect.bin"
    source.write_bytes(b"unknown inbound bytes\n")
    candidate = vault.add_candidate(project["id"], section["id"], str(source))
    inspection = oubliette.inspect_object(
        project_id=project["id"],
        section_id=section["id"],
        object_id=candidate["id"],
        actor_kind="human",
    )
    report_id = inspection["report"]["report_id"]
    proposal = oubliette.quarantine_proposal(
        project_id=project["id"],
        section_id=section["id"],
        object_id=candidate["id"],
        report_id=report_id,
    )
    token = vault.issue_ceremony_token(
        "quarantine",
        identity.session_id,
        actor_id="josie",
        project_id=project["id"],
        section_id=section["id"],
        object_id=candidate["id"],
        proposal_id=proposal["proposal_id"],
        proposal_hash=proposal["proposal_hash"],
    )["ceremony_token"]
    completed = oubliette.quarantine(
        project_id=project["id"],
        section_id=section["id"],
        object_id=candidate["id"],
        report_id=report_id,
        ceremony_token=token,
        session_id=identity.session_id,
        reason="bounded static indicators require fenced review",
    )
    return evidence, vault, oubliette, project, section, identity, candidate, completed


def test_quarantine_compartment_is_owner_only_payload_not_status_store(tmp_path: Path):
    evidence, vault, _, project, section, _, candidate, completed = _quarantine_one(tmp_path)
    result = completed["result"]
    quarantine_root = vault._compartment_dir(project["id"], section["id"], "quarantine")

    entries = list(quarantine_root.iterdir())
    assert len(entries) == 1
    assert entries[0] == Path(result["vault_path"])
    assert entries[0].is_file() and not entries[0].is_symlink()
    assert entries[0].read_bytes() == b"unknown inbound bytes\n"
    assert not any(path.suffix.lower() in {".json", ".log", ".status"} for path in entries)

    if os.name == "posix":
        assert stat.S_IMODE(quarantine_root.stat().st_mode) == 0o700
        assert stat.S_IMODE(entries[0].stat().st_mode) & 0o077 == 0

    stored = vault._find_file(project["id"], section["id"], candidate["id"])
    assert stored["state"] == "quarantined"
    assert stored["quarantine_report_id"]
    assert stored["quarantine_operation_id"]
    records = evidence.records()
    assert any(record.get("event_type") == "OBJECT_QUARANTINED" for record in records)
    assert evidence.verify_chain()["ok"] is True


def test_quarantine_transition_evidence_parent_is_owner_only(tmp_path: Path):
    _, vault, _, project, section, _, _, completed = _quarantine_one(tmp_path)
    evidence_path = Path(completed["result"]["quarantine_transition_evidence_path"])
    evidence_root = vault._transition_evidence_root(project["id"], section["id"])
    assert evidence_path.is_file()
    assert evidence_path.parent.parent == evidence_root
    if os.name == "posix":
        assert stat.S_IMODE(evidence_root.stat().st_mode) == 0o700
        assert stat.S_IMODE(evidence_path.parent.stat().st_mode) == 0o700


def test_second_quarantine_attempt_cannot_restage_or_duplicate_payload(tmp_path: Path):
    _, vault, oubliette, project, section, identity, candidate, completed = _quarantine_one(tmp_path)
    quarantine_root = vault._compartment_dir(project["id"], section["id"], "quarantine")
    before = {path.name: path.read_bytes() for path in quarantine_root.iterdir()}

    with pytest.raises(OublietteTransactionError, match="Raw Source or Candidate"):
        oubliette.quarantine_proposal(
            project_id=project["id"],
            section_id=section["id"],
            object_id=candidate["id"],
            report_id=completed["result"]["quarantine_report_id"],
        )

    after = {path.name: path.read_bytes() for path in quarantine_root.iterdir()}
    assert after == before
    assert len(after) == 1


def test_unchanged_static_inspection_retry_is_idempotent_across_timestamp_change(tmp_path: Path, monkeypatch):
    _, vault, oubliette, project, section, _, = _runtime(tmp_path)
    source = tmp_path / "stable.bin"
    source.write_bytes(b"stable bytes")
    candidate = vault.add_candidate(project["id"], section["id"], str(source))

    import iteration_wallet.oubliette as inspector_module
    moments = iter(["2026-07-21T12:00:00+00:00", "2026-07-21T12:00:05+00:00"])
    monkeypatch.setattr(inspector_module, "_utc_now", lambda: next(moments))

    first = oubliette.inspect_object(
        project_id=project["id"], section_id=section["id"],
        object_id=candidate["id"], actor_kind="human",
    )
    second = oubliette.inspect_object(
        project_id=project["id"], section_id=section["id"],
        object_id=candidate["id"], actor_kind="human",
    )
    assert second["report"]["report_id"] == first["report"]["report_id"]
    assert second["report"]["generated_at"] == first["report"]["generated_at"]
