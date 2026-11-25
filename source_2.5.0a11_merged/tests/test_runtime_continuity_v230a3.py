from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from iteration_wallet.runtime_continuity import (
    ContinuityPolicy,
    DivergenceCategory,
    EvidenceVerification,
    RuntimeContinuityError,
    capture_snapshot,
    compare_snapshots,
    load_snapshot,
    save_snapshot,
)


def _category_map(assessment):
    return {item.relative_path: item.category for item in assessment.findings}


def test_capture_is_static_deterministic_and_does_not_execute_target(tmp_path: Path):
    active = tmp_path / "active"
    active.mkdir()
    marker = tmp_path / "executed.txt"
    (active / "danger.py").write_text(
        f"from pathlib import Path\nPath({str(marker)!r}).write_text('executed')\n",
        encoding="utf-8",
    )
    (active / "data.bin").write_bytes(b"abc")

    snapshot = capture_snapshot(active, root_label="active-program")

    assert marker.exists() is False
    assert [entry.relative_path for entry in snapshot.entries] == ["danger.py", "data.bin"]
    assert snapshot.hashed_files == 2
    assert snapshot.coverage == 1.0
    assert all(entry.sha256 for entry in snapshot.entries)


def test_divergence_precedence_and_explicit_evidence(tmp_path: Path):
    active = tmp_path / "active"
    active.mkdir()
    files = {
        "unchanged.txt": "same",
        "cache/item.tmp": "old",
        "state/session.json": "old",
        "config.ini": "old",
        "vendor.dll": "old",
        "exception.txt": "old",
        "gatekeeper.py": "old",
        "blocked.bin": "old",
    }
    for relative, value in files.items():
        path = active / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value, encoding="utf-8")
    reference = capture_snapshot(active, root_label="program")

    for relative in files:
        if relative != "unchanged.txt":
            (active / relative).write_text("new", encoding="utf-8")
    observed = capture_snapshot(active, root_label="program", previous_snapshot_id=reference.snapshot_id)
    policy = ContinuityPolicy(prohibited_patterns=("blocked.bin",))
    evidence = {
        "receipt:config": EvidenceVerification(
            evidence_id="receipt:config", verified=True, authority="iteration_wallet",
            evidence_kind="configuration_authorization", subject_path="config.ini",
        ),
        "vendor-proof:1": EvidenceVerification(
            evidence_id="vendor-proof:1", verified=True, authority="iteration_wallet",
            evidence_kind="verified_update_receipt", subject_path="vendor.dll",
        ),
        "exception:1": EvidenceVerification(
            evidence_id="exception:1", verified=True, authority="iteration_wallet",
            evidence_kind="approved_exception", subject_path="exception.txt",
        ),
    }
    assessment = compare_snapshots(
        reference,
        observed,
        policy=policy,
        authorized_configuration={"config.ini": "receipt:config"},
        verified_updates={"vendor.dll": "vendor-proof:1"},
        approved_exceptions={"exception.txt": "exception:1"},
        evidence_resolver=evidence.__getitem__,
    )
    categories = _category_map(assessment)
    assert categories["unchanged.txt"] is DivergenceCategory.UNCHANGED
    assert categories["cache/item.tmp"] is DivergenceCategory.DISPOSABLE
    assert categories["state/session.json"] is DivergenceCategory.EXPECTED_MUTABLE
    assert categories["config.ini"] is DivergenceCategory.AUTHORIZED_CONFIGURATION
    assert categories["vendor.dll"] is DivergenceCategory.VERIFIED_UPDATE
    assert categories["exception.txt"] is DivergenceCategory.APPROVED_EXCEPTION
    assert categories["gatekeeper.py"] is DivergenceCategory.UNEXPLAINED
    assert categories["blocked.bin"] is DivergenceCategory.PROHIBITED
    gatekeeper = next(item for item in assessment.findings if item.relative_path == "gatekeeper.py")
    assert gatekeeper.severity.value == "high"
    report = assessment.to_dict()
    assert report["custody_decision_made"] is False
    assert report["repair_attempted"] is False
    assert report["trust_inferred"] is False


def test_symlink_is_not_followed_and_reduces_confidence(tmp_path: Path):
    if not hasattr(os, "symlink"):
        pytest.skip("symlinks unavailable")
    active = tmp_path / "active"
    outside = tmp_path / "outside"
    active.mkdir()
    outside.mkdir()
    secret = outside / "secret.txt"
    secret.write_text("outside", encoding="utf-8")
    try:
        (active / "link.txt").symlink_to(secret)
    except OSError:
        pytest.skip("symlink creation not permitted")

    first = capture_snapshot(active, root_label="program")
    second = capture_snapshot(active, root_label="program", previous_snapshot_id=first.snapshot_id)
    assessment = compare_snapshots(first, second)

    assert first.entries[0].sha256 is None
    assert first.entries[0].observation == "unverifiable:symlink_not_followed"
    assert assessment.findings[0].category is DivergenceCategory.UNVERIFIABLE
    assert assessment.confidence != "high_static_coverage"
    assert secret.read_text(encoding="utf-8") == "outside"


def test_snapshot_persistence_is_exactly_once_and_round_trips(tmp_path: Path):
    active = tmp_path / "active"
    active.mkdir()
    (active / "file.txt").write_text("content", encoding="utf-8")
    snapshot = capture_snapshot(active, root_label="program")
    target = tmp_path / "snapshots" / "snapshot.json"

    save_snapshot(snapshot, target)
    loaded = load_snapshot(target)

    assert loaded.snapshot_id == snapshot.snapshot_id
    assert loaded.entries == snapshot.entries
    with pytest.raises(RuntimeContinuityError, match="silent overwrite"):
        save_snapshot(snapshot, target)


def test_added_removed_and_permission_changes_are_never_silently_explained(tmp_path: Path):
    active = tmp_path / "active"
    active.mkdir()
    removed = active / "removed.txt"
    permissions = active / "permissions.txt"
    removed.write_text("old", encoding="utf-8")
    permissions.write_text("same", encoding="utf-8")
    reference = capture_snapshot(active, root_label="program")

    removed.rename(active / "preserved_removed_copy.txt")
    (active / "added.txt").write_text("new", encoding="utf-8")
    permissions.chmod(0o600)
    observed = capture_snapshot(active, root_label="program", previous_snapshot_id=reference.snapshot_id)
    assessment = compare_snapshots(reference, observed)
    by_path = {item.relative_path: item for item in assessment.findings}

    assert by_path["removed.txt"].change == "missing"
    assert by_path["removed.txt"].category is DivergenceCategory.UNEXPLAINED
    assert by_path["added.txt"].change == "added"
    assert by_path["added.txt"].category is DivergenceCategory.UNEXPLAINED
    assert by_path["permissions.txt"].change == "permissions_changed"
    assert by_path["permissions.txt"].category is DivergenceCategory.UNEXPLAINED
    assert (active / "preserved_removed_copy.txt").exists()


def test_evidence_id_without_authority_verification_never_authorizes(tmp_path: Path):
    active = tmp_path / "active"
    active.mkdir()
    target = active / "config.ini"
    target.write_text("mode=old\n", encoding="utf-8")
    reference = capture_snapshot(active, root_label="program")
    target.write_text("mode=new\n", encoding="utf-8")
    observed = capture_snapshot(active, root_label="program", previous_snapshot_id=reference.snapshot_id)

    assessment = compare_snapshots(
        reference,
        observed,
        authorized_configuration={"config.ini": "fabricated-receipt-id"},
    )
    finding = assessment.findings[0]
    assert finding.category is DivergenceCategory.UNEXPLAINED
    assert finding.evidence_id == "fabricated-receipt-id"
    assert finding.evidence_verified is False
    assert "no authority resolver" in str(finding.evidence_limitation)


def test_wrong_authority_kind_or_subject_cannot_authorize(tmp_path: Path):
    active = tmp_path / "active"
    active.mkdir()
    target = active / "config.ini"
    target.write_text("old", encoding="utf-8")
    reference = capture_snapshot(active, root_label="program")
    target.write_text("new", encoding="utf-8")
    observed = capture_snapshot(active, root_label="program", previous_snapshot_id=reference.snapshot_id)

    wrong = {
        "bad": EvidenceVerification(
            evidence_id="bad",
            verified=True,
            authority="blackbox",
            evidence_kind="configuration_authorization",
            subject_path="other.ini",
        )
    }
    assessment = compare_snapshots(
        reference,
        observed,
        authorized_configuration={"config.ini": "bad"},
        evidence_resolver=wrong.__getitem__,
    )
    finding = assessment.findings[0]
    assert finding.category is DivergenceCategory.UNEXPLAINED
    assert finding.evidence_verified is False
    assert finding.evidence_authority == "blackbox"


def test_snapshot_identity_covers_counters_warnings_and_entries(tmp_path: Path):
    active = tmp_path / "active"
    active.mkdir()
    (active / "file.txt").write_text("content", encoding="utf-8")
    snapshot = capture_snapshot(active, root_label="program")
    target = tmp_path / "snapshot.json"
    save_snapshot(snapshot, target)

    payload = json.loads(target.read_text(encoding="utf-8"))
    payload["hashed_files"] = 0
    target.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(RuntimeContinuityError, match="coverage counters|identity"):
        load_snapshot(target)


def test_compare_requires_same_root_and_explicit_lineage(tmp_path: Path):
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    first_root.mkdir()
    second_root.mkdir()
    (first_root / "file.txt").write_text("a", encoding="utf-8")
    (second_root / "file.txt").write_text("a", encoding="utf-8")
    reference = capture_snapshot(first_root, root_label="program-a")
    wrong_root = capture_snapshot(second_root, root_label="program-b", previous_snapshot_id=reference.snapshot_id)
    with pytest.raises(RuntimeContinuityError, match="different roots"):
        compare_snapshots(reference, wrong_root)

    unlinked = capture_snapshot(first_root, root_label="program-a")
    with pytest.raises(RuntimeContinuityError, match="not explicitly linked"):
        compare_snapshots(reference, unlinked)


def test_walk_error_is_represented_as_coverage_gap(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import iteration_wallet.runtime_continuity as rc

    active = tmp_path / "active"
    active.mkdir()

    def fake_walk(root, topdown=True, followlinks=False, onerror=None):
        assert onerror is not None
        error = PermissionError("denied")
        error.filename = str(Path(root) / "blocked")
        onerror(error)
        return iter(())

    monkeypatch.setattr(rc.os, "walk", fake_walk)
    snapshot = capture_snapshot(active, root_label="program")
    assert snapshot.attempted_entries == 1
    assert snapshot.unreadable_entries == 1
    assert snapshot.coverage == 0.0
    assert snapshot.entries[0].kind == "unreadable_directory"
    assert snapshot.warnings
