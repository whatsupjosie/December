from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from iteration_wallet.canonical_evidence import CanonicalEvidenceAdapter
from iteration_wallet.labcopy_transaction import (
    LabCopyTransactionCoordinator,
    LabCopyTransactionError,
    SimulatedLabCopyCrash,
)
from iteration_wallet.notification_manager import ActorKind, NotificationManager
from iteration_wallet.vault_v21 import VaultEngine


def _runtime(tmp_path: Path):
    root = tmp_path / "wallet"
    evidence = CanonicalEvidenceAdapter(root, session_id="labcopy-tests")
    vault = VaultEngine(root, blackbox=evidence, strict_ceremony_tokens=True)
    humans = NotificationManager(root, blackbox=evidence)
    coordinator = LabCopyTransactionCoordinator(vault, evidence, humans)
    vault.labcopy_coordinator = coordinator
    project = vault.create_project("LabCopy")
    section = vault.create_section(project["id"], "Main")
    identity = humans.issue_identity_session(
        "josie",
        ActorKind.HUMAN,
        device_id="labcopy-machine",
        verified_methods=["human_ceremony"],
    )
    vault.open_vault()
    source = tmp_path / "source.txt"
    source.write_text("trusted working bytes\n", encoding="utf-8")
    candidate = vault.add_candidate(project["id"], section["id"], str(source))
    return evidence, vault, humans, coordinator, project, section, identity, candidate


def _token(vault: VaultEngine, action: str, identity, project, section, object_id, proposal):
    return vault.issue_ceremony_token(
        action,
        identity.session_id,
        actor_id="josie",
        project_id=project["id"],
        section_id=section["id"],
        object_id=object_id,
        proposal_id=proposal["proposal_id"],
        proposal_hash=proposal["proposal_hash"],
    )["ceremony_token"]


def _export(tmp_path: Path):
    evidence, vault, humans, labcopy, project, section, identity, candidate = _runtime(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    proposal = labcopy.export_proposal(
        project_id=project["id"],
        section_id=section["id"],
        object_id=candidate["id"],
        output_root=outside,
        lab_policy="manual static review and external tests",
    )
    token = _token(
        vault, labcopy.EXPORT_ACTION, identity, project, section, candidate["id"], proposal
    )
    completed = labcopy.export(
        project_id=project["id"],
        section_id=section["id"],
        object_id=candidate["id"],
        proposal_id=proposal["proposal_id"],
        proposal_hash=proposal["proposal_hash"],
        ceremony_token=token,
        session_id=identity.session_id,
        reason="bounded external review",
    )
    return evidence, vault, humans, labcopy, project, section, identity, candidate, outside, proposal, completed


def test_labcopy_export_is_traceable_nonexecuting_and_verifiable(tmp_path: Path):
    evidence, vault, _, labcopy, project, section, _, candidate, _, proposal, completed = _export(tmp_path)
    result = completed["result"]
    external = Path(result["external_package_path"])
    assert external.is_file()
    assert vault._find_file(project["id"], section["id"], candidate["id"])["state"] == "candidate"
    assert Path(candidate["vault_path"]).read_text(encoding="utf-8") == "trusted working bytes\n"
    with zipfile.ZipFile(external) as archive:
        assert archive.namelist() == ["manifest.json", "README.txt", "payload/source.txt"]
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["source"]["sha256"] == candidate["hash"]
        assert manifest["external_execution_authority"] == "outside_wallet_only"
        assert archive.read(manifest["payload_entry"]) == b"trusted working bytes\n"
    assert labcopy.verify_receipt(completed["receipt"]["receipt_id"])["ok"] is True
    assert evidence.verify_chain()["ok"] is True
    assert proposal["external_package_path"] == str(external)


def test_labcopy_exact_proposal_cannot_be_swapped(tmp_path: Path):
    _, vault, _, labcopy, project, section, identity, candidate = _runtime(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    a = labcopy.export_proposal(
        project_id=project["id"], section_id=section["id"], object_id=candidate["id"],
        output_root=outside, lab_policy="policy a", lab_id="lab-a",
    )
    b = labcopy.export_proposal(
        project_id=project["id"], section_id=section["id"], object_id=candidate["id"],
        output_root=outside, lab_policy="policy b", lab_id="lab-b",
    )
    token = _token(vault, labcopy.EXPORT_ACTION, identity, project, section, candidate["id"], a)
    with pytest.raises(Exception):
        labcopy.export(
            project_id=project["id"], section_id=section["id"], object_id=candidate["id"],
            proposal_id=b["proposal_id"], proposal_hash=b["proposal_hash"],
            ceremony_token=token, session_id=identity.session_id,
        )
    token_id = vault.ceremony_ledger.parse_token_id(token)
    assert vault.ceremony_ledger.get_record(token_id)["consumed_at"] is None


def test_labcopy_return_is_intake_then_deterministic_candidate(tmp_path: Path):
    evidence, vault, _, labcopy, project, section, identity, candidate, outside, proposal, completed = _export(tmp_path)
    result_root = tmp_path / "lab-results"
    result_root.mkdir()
    result_file = result_root / "source-fixed.txt"
    result_file.write_text("externally revised bytes\n", encoding="utf-8")
    captured = labcopy.capture_result(
        lab_id=proposal["lab_id"],
        result_path=result_file,
        allowed_root=result_root,
        source_label="source-fixed.txt",
        external_assertions=[{"type": "test_claim", "claim": "external tests passed"}],
    )
    capsule = captured["capsule"]
    result_file.write_text("replaced after capture\n", encoding="utf-8")
    admission = labcopy.result_admission_proposal(lab_id=proposal["lab_id"], capsule_id=capsule["capsule_id"])
    token = _token(vault, labcopy.ADMIT_ACTION, identity, project, section, candidate["id"], admission)
    admitted = labcopy.admit_result(
        lab_id=proposal["lab_id"], capsule_id=capsule["capsule_id"],
        proposal_id=admission["proposal_id"], proposal_hash=admission["proposal_hash"],
        ceremony_token=token, session_id=identity.session_id,
        reason="reviewed external result",
    )
    created = admitted["result"]
    assert created["state"] == "candidate"
    assert created["origin"] == "labcopy_result_intake_capsule"
    assert created["trust_status"] == "candidate_only_no_automatic_trust"
    assert Path(created["vault_path"]).read_bytes() == b"externally revised bytes\n"
    assert vault._find_file(project["id"], section["id"], candidate["id"])["hash"] == candidate["hash"]
    assert labcopy.verify_receipt(admitted["receipt"]["receipt_id"])["ok"] is True
    assert evidence.verify_chain()["ok"] is True

    # A semantic retry uses the same proposal/candidate identity; a new scoped
    # token may re-enter without creating a duplicate Candidate.
    token2 = _token(vault, labcopy.ADMIT_ACTION, identity, project, section, candidate["id"], admission)
    repeated = labcopy.admit_result(
        lab_id=proposal["lab_id"], capsule_id=capsule["capsule_id"],
        proposal_id=admission["proposal_id"], proposal_hash=admission["proposal_hash"],
        ceremony_token=token2, session_id=identity.session_id,
        reason="idempotent retry",
    )
    assert repeated["result"]["id"] == created["id"]
    files = vault.get_section(project["id"], section["id"])["files"]
    assert sum(1 for item in files if item["id"] == created["id"]) == 1


def test_labcopy_export_destination_never_clobbers(tmp_path: Path):
    _, vault, _, labcopy, project, section, identity, candidate = _runtime(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    proposal = labcopy.export_proposal(
        project_id=project["id"], section_id=section["id"], object_id=candidate["id"],
        output_root=outside, lab_policy="manual review", lab_id="collision",
    )
    destination = Path(proposal["external_package_path"])
    destination.write_bytes(b"competing bytes")
    token = _token(vault, labcopy.EXPORT_ACTION, identity, project, section, candidate["id"], proposal)
    with pytest.raises(LabCopyTransactionError, match="conflicts"):
        labcopy.export(
            project_id=project["id"], section_id=section["id"], object_id=candidate["id"],
            proposal_id=proposal["proposal_id"], proposal_hash=proposal["proposal_hash"],
            ceremony_token=token, session_id=identity.session_id,
        )
    assert destination.read_bytes() == b"competing bytes"


def test_labcopy_crash_after_publish_reconciles_without_duplicate(tmp_path: Path):
    _, vault, _, labcopy, project, section, identity, candidate = _runtime(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    proposal = labcopy.export_proposal(
        project_id=project["id"], section_id=section["id"], object_id=candidate["id"],
        output_root=outside, lab_policy="manual review",
    )
    token = _token(vault, labcopy.EXPORT_ACTION, identity, project, section, candidate["id"], proposal)
    with pytest.raises(SimulatedLabCopyCrash):
        labcopy.export(
            project_id=project["id"], section_id=section["id"], object_id=candidate["id"],
            proposal_id=proposal["proposal_id"], proposal_hash=proposal["proposal_hash"],
            ceremony_token=token, session_id=identity.session_id, fault_after="external_published",
        )
    assert Path(proposal["external_package_path"]).is_file()
    report = labcopy.reconcile_pending()
    assert report["reconciled"] == 1
    assert labcopy.reconcile_pending()["checked"] == 0
