from __future__ import annotations

import json
import os
import threading
import time
import zipfile
from pathlib import Path

import pytest

from iteration_wallet import server
from iteration_wallet.canonical_evidence import CanonicalEvidenceAdapter
from iteration_wallet.intake_capsule import IntakeCapsuleError, WalletIntakeCapsuleStore
from iteration_wallet.notification_manager import ActorKind, NotificationManager
from iteration_wallet.oubliette import Coverage, inspect_static
from iteration_wallet.oubliette_transaction import (
    OublietteJournal,
    OublietteReportStore,
    OublietteTransactionCoordinator,
    OublietteTransactionError,
)
from iteration_wallet.promotion_transaction import PromotionJournal, PromotionTransactionCoordinator
from iteration_wallet.vault_v21 import VaultEngine


def _runtime(tmp_path: Path, *, mode: str = "transaction"):
    evidence = CanonicalEvidenceAdapter(tmp_path, session_id="hardening")
    vault = VaultEngine(tmp_path, blackbox=evidence, strict_ceremony_tokens=True)
    humans = NotificationManager(tmp_path, blackbox=evidence)
    promotion = PromotionTransactionCoordinator(vault, evidence, humans)
    oubliette = OublietteTransactionCoordinator(
        vault, evidence, humans, participation_mode=mode
    )
    project = vault.create_project("Hardening")
    section = vault.create_section(project["id"], "Main")
    identity = humans.issue_identity_session(
        "josie",
        ActorKind.HUMAN,
        device_id="hardening-machine",
        verified_methods=["typed_human_ceremony"],
    )
    vault.open_vault()
    return evidence, vault, humans, promotion, oubliette, project, section, identity


def _candidate(vault: VaultEngine, project: dict, section: dict, root: Path, name: str = "x.py"):
    source = root / name
    source.write_text("print('static only')\n", encoding="utf-8")
    return vault.add_candidate(project["id"], section["id"], str(source))


def test_optional_oubliette_defaults_to_disabled(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("IW_OUBLIETTE_MODE", raising=False)
    _, vault, _, _ = server.build_canonical_v21_runtime(tmp_path / "default")
    assert vault.oubliette_requested_mode == "disabled"
    assert vault.oubliette_coordinator is None

    # Direct library use must also fail safe: transaction participation is explicit.
    evidence = CanonicalEvidenceAdapter(tmp_path / "direct", session_id="direct")
    direct_vault = VaultEngine(tmp_path / "direct", blackbox=evidence, strict_ceremony_tokens=True)
    humans = NotificationManager(tmp_path / "direct", blackbox=evidence)
    coordinator = OublietteTransactionCoordinator(direct_vault, evidence, humans)
    assert coordinator.participation_mode == "inspect"
    assert coordinator.capability()["wallet_owned_crossings"] is False


def test_quarantine_ceremony_is_bound_to_exact_report_proposal(tmp_path: Path):
    _, vault, _, _, oubliette, project, section, identity = _runtime(tmp_path)
    candidate = _candidate(vault, project, section, tmp_path)
    report_a = oubliette.inspect_object(
        project_id=project["id"], section_id=section["id"], object_id=candidate["id"], actor_kind="human"
    )["report"]
    report_b = oubliette.inspect_object(
        project_id=project["id"], section_id=section["id"], object_id=candidate["id"], actor_kind="local_system"
    )["report"]
    proposal_a = oubliette.quarantine_proposal(
        project_id=project["id"], section_id=section["id"], object_id=candidate["id"], report_id=report_a["report_id"]
    )
    token = vault.issue_ceremony_token(
        "quarantine",
        identity.session_id,
        actor_id="josie",
        project_id=project["id"],
        section_id=section["id"],
        object_id=candidate["id"],
        proposal_id=proposal_a["proposal_id"],
        proposal_hash=proposal_a["proposal_hash"],
    )["ceremony_token"]

    with pytest.raises(OublietteTransactionError, match="proposal"):
        oubliette.quarantine(
            project_id=project["id"],
            section_id=section["id"],
            object_id=candidate["id"],
            report_id=report_b["report_id"],
            ceremony_token=token,
            session_id=identity.session_id,
            reason="report swap must fail",
        )
    token_id = vault.ceremony_ledger.parse_token_id(token)
    assert vault.ceremony_ledger.get_record(token_id)["consumed_at"] is None
    assert vault._find_file(project["id"], section["id"], candidate["id"])["state"] == "candidate"


def test_report_binding_metadata_is_sealed(tmp_path: Path):
    _, vault, _, _, oubliette, project, section, _ = _runtime(tmp_path)
    candidate = _candidate(vault, project, section, tmp_path)
    report = oubliette.inspect_object(
        project_id=project["id"], section_id=section["id"], object_id=candidate["id"], actor_kind="human"
    )["report"]
    path = oubliette.reports._path(report["report_id"])
    data = json.loads(path.read_text(encoding="utf-8"))
    data["canonical_event_id"] = "forged-event"
    data["canonical_event_hash"] = "f" * 64
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(OublietteTransactionError, match="stored-record hash"):
        oubliette.reports.get(report["report_id"])


def test_report_binding_is_single_winner_under_concurrency(tmp_path: Path, monkeypatch):
    from iteration_wallet import oubliette_transaction as module
    from iteration_wallet.oubliette import ActorKind as OActor, OublietteInspectionReport

    store = OublietteReportStore(tmp_path / "wallet")
    report = OublietteInspectionReport(
        report_id="report-race",
        generated_at="2026-07-20T00:00:00+00:00",
        target_label="x",
        target_sha256="a" * 64,
        size_bytes=1,
        coverage=Coverage.FULL,
        bytes_sampled=1,
        archive_members_observed=0,
        findings=(),
        warnings=(),
        actor_kind=OActor.HUMAN,
    )
    store.create(report, project_id="p", section_id="s", object_id="o")
    original_atomic = module.atomic_json

    def slow_atomic(path, payload):
        time.sleep(0.08)
        return original_atomic(path, payload)

    monkeypatch.setattr(module, "atomic_json", slow_atomic)
    outcomes: list[str] = []

    def bind(event_id: str, event_hash: str):
        try:
            store.bind_canonical_event(report.report_id, event_id=event_id, event_hash=event_hash)
            outcomes.append("ok")
        except OublietteTransactionError:
            outcomes.append("conflict")

    threads = [
        threading.Thread(target=bind, args=("event-a", "a" * 64)),
        threading.Thread(target=bind, args=("event-b", "b" * 64)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=3)
    assert sorted(outcomes) == ["conflict", "ok"]


def test_authority_journals_detect_tampering_and_symlink_records(tmp_path: Path):
    oubliette = OublietteJournal(tmp_path / "ow")
    oubliette.reserve({"operation_id": "op1", "action_key": "quarantine"})
    path = oubliette.active_dir / "op1.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["action_key"] = "forged"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(OublietteTransactionError, match="journal record hash"):
        oubliette.get("op1")

    promotion = PromotionJournal(tmp_path / "pw")
    promotion.reserve({"operation_id": "op2", "action_key": "promote_candidate_to_prime"})
    ppath = promotion.active_dir / "op2.json"
    pdata = json.loads(ppath.read_text(encoding="utf-8"))
    pdata["action_key"] = "forged"
    ppath.write_text(json.dumps(pdata), encoding="utf-8")
    with pytest.raises(Exception, match="journal record hash"):
        promotion.get("op2")


def test_small_zip_is_partial_because_member_content_is_not_inspected(tmp_path: Path):
    archive = tmp_path / "small.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("hello.txt", "hello")
    report = inspect_static(archive, actor_kind="human", allowed_root=tmp_path)
    assert report.coverage is Coverage.PARTIAL
    assert any("member content" in warning.lower() for warning in report.warnings)


def test_static_inspection_uses_one_open_identity_for_hash_sample_and_archive(tmp_path: Path, monkeypatch):
    from iteration_wallet import oubliette as module

    target = tmp_path / "sample.txt"
    target.write_bytes(b"safe content")
    original_open = module.os.open
    target_opens = 0

    def counted_open(path, flags, *args):
        nonlocal target_opens
        if Path(path) == target:
            target_opens += 1
        return original_open(path, flags, *args)

    monkeypatch.setattr(module.os, "open", counted_open)
    report = module.inspect_static(target, actor_kind="human", allowed_root=tmp_path)
    assert report.target_sha256
    assert target_opens == 1


def test_capture_operation_id_and_candidate_label_are_portable_and_bounded(tmp_path: Path):
    store = WalletIntakeCapsuleStore(tmp_path / "wallet")
    lab = tmp_path / "lab"
    lab.mkdir()
    source = lab / "result.bin"
    source.write_bytes(b"x")
    with pytest.raises(IntakeCapsuleError, match="capture_operation_id"):
        store.capture(
            project_id="p",
            section_id="s",
            parent_object_id="o",
            parent_sha256="a" * 64,
            source_path=source,
            allowed_root=lab,
            capture_operation_id="../escape",
        )


def test_capsule_admission_binding_rejects_wrong_candidate_hash(tmp_path: Path):
    store = WalletIntakeCapsuleStore(tmp_path / "wallet")
    lab = tmp_path / "lab"
    lab.mkdir()
    source = lab / "result.bin"
    source.write_bytes(b"right")
    capsule = store.capture(
        project_id="p", section_id="s", parent_object_id="o", parent_sha256="a" * 64,
        source_path=source, allowed_root=lab,
    )
    with pytest.raises(IntakeCapsuleError, match="candidate_sha256"):
        store.bind_admission(
            capsule["capsule_id"], candidate_id="candidate1", operation_id="operation1",
            receipt_id="receipt1", candidate_sha256="b" * 64,
        )


def test_optional_capture_does_not_hold_global_catalog_lock_during_copy(tmp_path: Path, monkeypatch):
    from iteration_wallet import intake_capsule as module

    _, vault, _, _, oubliette, project, section, identity = _runtime(tmp_path)
    candidate = _candidate(vault, project, section, tmp_path)
    report = oubliette.inspect_object(
        project_id=project["id"], section_id=section["id"], object_id=candidate["id"], actor_kind="human"
    )["report"]
    proposal = oubliette.quarantine_proposal(
        project_id=project["id"], section_id=section["id"], object_id=candidate["id"], report_id=report["report_id"]
    )
    token = vault.issue_ceremony_token(
        "quarantine", identity.session_id, actor_id="josie", project_id=project["id"],
        section_id=section["id"], object_id=candidate["id"], proposal_id=proposal["proposal_id"],
        proposal_hash=proposal["proposal_hash"],
    )["ceremony_token"]
    oubliette.quarantine(
        project_id=project["id"], section_id=section["id"], object_id=candidate["id"],
        report_id=report["report_id"], ceremony_token=token, session_id=identity.session_id, reason="setup",
    )
    lab = tmp_path / "lab"
    lab.mkdir()
    source = lab / "large.bin"
    source.write_bytes(b"copy me")
    entered = threading.Event()
    release = threading.Event()
    original_copy = module._copy_exact

    def blocked_copy(*args, **kwargs):
        entered.set()
        assert release.wait(3)
        return original_copy(*args, **kwargs)

    monkeypatch.setattr(module, "_copy_exact", blocked_copy)
    errors: list[BaseException] = []

    def capture():
        try:
            oubliette.capture_intake_capsule(
                project_id=project["id"], section_id=section["id"], quarantined_object_id=candidate["id"],
                source_path=source, allowed_root=lab, actor_kind="human",
            )
        except BaseException as exc:
            errors.append(exc)

    worker = threading.Thread(target=capture)
    worker.start()
    assert entered.wait(3)
    mutation_done = threading.Event()

    def unrelated_mutation():
        vault.create_project("Unrelated while Oubliette copies")
        mutation_done.set()

    other = threading.Thread(target=unrelated_mutation)
    other.start()
    assert mutation_done.wait(0.5), "optional Oubliette capture blocked the Wallet catalog"
    release.set()
    worker.join(timeout=5)
    other.join(timeout=5)
    assert not errors


def test_intake_capture_rejects_zero_progress_write(tmp_path: Path, monkeypatch):
    from iteration_wallet import custody_io

    store = WalletIntakeCapsuleStore(tmp_path / "wallet")
    lab = tmp_path / "lab"
    lab.mkdir()
    source = lab / "result.bin"
    source.write_bytes(b"must not loop forever")
    monkeypatch.setattr(custody_io.os, "write", lambda *_args, **_kwargs: 0)

    with pytest.raises(IntakeCapsuleError, match="no forward progress"):
        store.capture(
            project_id="p",
            section_id="s",
            parent_object_id="o",
            parent_sha256="a" * 64,
            source_path=source,
            allowed_root=lab,
        )
    failed = list((tmp_path / "wallet" / "intake_capsules" / "failed_captures").glob("*"))
    assert failed, "interrupted intake evidence was not preserved"


def test_quarantine_publication_race_never_overwrites_and_freezes(tmp_path: Path, monkeypatch):
    from iteration_wallet import custody_io

    _, vault, _, _, oubliette, project, section, identity = _runtime(tmp_path)
    candidate = _candidate(vault, project, section, tmp_path, "race.py")
    inspected = oubliette.inspect_object(
        project_id=project["id"], section_id=section["id"], object_id=candidate["id"], actor_kind="human"
    )
    proposal = inspected["quarantine_proposal"]
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
    attacker_paths: list[Path] = []

    def racing_link(_source, destination, **_kwargs):
        target = Path(destination)
        target.write_bytes(b"attacker destination")
        attacker_paths.append(target)
        raise FileExistsError(str(target))

    monkeypatch.setattr(custody_io.os, "link", racing_link)
    with pytest.raises(Exception):
        oubliette.quarantine(
            project_id=project["id"],
            section_id=section["id"],
            object_id=candidate["id"],
            report_id=inspected["report"]["report_id"],
            ceremony_token=token,
            session_id=identity.session_id,
            reason="hostile destination race",
        )

    assert attacker_paths and attacker_paths[0].read_bytes() == b"attacker destination"
    current = vault._find_file(project["id"], section["id"], candidate["id"])
    assert current["state"] == "candidate"
    assert Path(current["vault_path"]).read_text(encoding="utf-8") == "print('static only')\n"
    assert current.get("custody_locked") or current.get("trust_locked")


def test_capsule_candidate_race_never_overwrites_and_does_not_create_candidate(tmp_path: Path, monkeypatch):
    from iteration_wallet import custody_io

    _, vault, _, _, oubliette, project, section, identity = _runtime(tmp_path)
    candidate = _candidate(vault, project, section, tmp_path, "parent.py")
    inspected_parent = oubliette.inspect_object(
        project_id=project["id"], section_id=section["id"], object_id=candidate["id"], actor_kind="human"
    )
    qproposal = inspected_parent["quarantine_proposal"]
    qtoken = vault.issue_ceremony_token(
        "quarantine", identity.session_id, actor_id="josie", project_id=project["id"],
        section_id=section["id"], object_id=candidate["id"], proposal_id=qproposal["proposal_id"],
        proposal_hash=qproposal["proposal_hash"],
    )["ceremony_token"]
    parent = oubliette.quarantine(
        project_id=project["id"], section_id=section["id"], object_id=candidate["id"],
        report_id=inspected_parent["report"]["report_id"], ceremony_token=qtoken,
        session_id=identity.session_id, reason="parent setup",
    )["result"]

    lab = tmp_path / "lab"
    lab.mkdir()
    # Construct through join because Windows-like punctuation is legal on this test host.
    derivative = lab / ("CON:" + "x" * 220 + ".txt")
    derivative.write_bytes(b"reviewed derivative")
    inspected = oubliette.inspect_derivative(
        project_id=project["id"], section_id=section["id"], quarantined_object_id=parent["id"],
        derivative_path=derivative, allowed_root=lab, actor_kind="human",
    )
    proposal = inspected["admission_proposal"]
    token = vault.issue_ceremony_token(
        oubliette.DERIVATIVE_ACTION, identity.session_id, actor_id="josie", project_id=project["id"],
        section_id=section["id"], object_id=parent["id"], proposal_id=proposal["proposal_id"],
        proposal_hash=proposal["proposal_hash"],
    )["ceremony_token"]
    attacker_paths: list[Path] = []

    def racing_link(_source, destination, **_kwargs):
        target = Path(destination)
        target.write_bytes(b"attacker candidate")
        attacker_paths.append(target)
        raise FileExistsError(str(target))

    monkeypatch.setattr(custody_io.os, "link", racing_link)
    with pytest.raises(Exception):
        oubliette.admit_derivative_as_candidate(
            project_id=project["id"], section_id=section["id"], parent_object_id=parent["id"],
            derivative_path=derivative, report_id=inspected["report"]["report_id"],
            ceremony_token=token, session_id=identity.session_id, reason="hostile candidate race",
            proposal_id=proposal["proposal_id"], proposal_hash=proposal["proposal_hash"],
        )

    assert attacker_paths and attacker_paths[0].read_bytes() == b"attacker candidate"
    files = vault.get_section(project["id"], section["id"])["files"]
    assert [item for item in files if item.get("parent_quarantined_id") == parent["id"]] == []
    assert len(attacker_paths[0].name.encode("utf-8")) <= 180
