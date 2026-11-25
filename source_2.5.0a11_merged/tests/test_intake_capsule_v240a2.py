import json
from pathlib import Path

import pytest

from iteration_wallet.intake_capsule import IntakeCapsuleError, WalletIntakeCapsuleStore


def test_capture_is_immutable_idempotent_and_survives_source_loss(tmp_path: Path):
    store = WalletIntakeCapsuleStore(tmp_path / "vault")
    lab = tmp_path / "lab"
    lab.mkdir()
    source = lab / "result.txt"
    source.write_bytes(b"reviewed result")

    first = store.capture(
        project_id="project1",
        section_id="section1",
        parent_object_id="parent1",
        parent_sha256="a" * 64,
        source_path=source,
        allowed_root=lab,
    )
    repeated = store.capture(
        project_id="project1",
        section_id="section1",
        parent_object_id="parent1",
        parent_sha256="a" * 64,
        source_path=source,
        allowed_root=lab,
    )
    assert repeated["capsule_id"] == first["capsule_id"]
    assert repeated["manifest_hash"] == first["manifest_hash"]
    source.write_bytes(b"replacement")
    source.unlink()
    loaded = store.get(first["capsule_id"])
    assert Path(loaded["absolute_blob_path"]).read_bytes() == b"reviewed result"
    assert loaded["state"] == "intake"
    assert loaded["execution_allowed"] is False


def test_capsules_separate_logical_lineage_from_blob_identity(tmp_path: Path):
    store = WalletIntakeCapsuleStore(tmp_path / "vault")
    lab = tmp_path / "lab"
    lab.mkdir()
    source = lab / "same.bin"
    source.write_bytes(b"same bytes")
    a = store.capture(
        project_id="project1", section_id="section1", parent_object_id="parent1",
        parent_sha256="a" * 64, source_path=source, allowed_root=lab,
    )
    b = store.capture(
        project_id="project1", section_id="section1", parent_object_id="parent2",
        parent_sha256="b" * 64, source_path=source, allowed_root=lab,
    )
    assert a["blob_sha256"] == b["blob_sha256"]
    assert a["capsule_id"] != b["capsule_id"]
    assert Path(a["absolute_blob_path"]) == Path(b["absolute_blob_path"])


def test_capture_rejects_symlink_and_root_escape(tmp_path: Path):
    store = WalletIntakeCapsuleStore(tmp_path / "vault")
    lab = tmp_path / "lab"
    lab.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("outside")
    link = lab / "link.txt"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symlinks unavailable")
    with pytest.raises(IntakeCapsuleError, match="symlink"):
        store.capture(
            project_id="p", section_id="s", parent_object_id="o", parent_sha256="a" * 64,
            source_path=link, allowed_root=lab,
        )
    with pytest.raises(IntakeCapsuleError, match="escapes"):
        store.capture(
            project_id="p", section_id="s", parent_object_id="o", parent_sha256="a" * 64,
            source_path=outside, allowed_root=lab,
        )


def test_manifest_or_blob_tampering_fails_closed(tmp_path: Path):
    store = WalletIntakeCapsuleStore(tmp_path / "vault")
    lab = tmp_path / "lab"
    lab.mkdir()
    source = lab / "result.txt"
    source.write_text("good")
    capsule = store.capture(
        project_id="p", section_id="s", parent_object_id="o", parent_sha256="a" * 64,
        source_path=source, allowed_root=lab,
    )
    Path(capsule["absolute_blob_path"]).write_text("tampered")
    with pytest.raises(IntakeCapsuleError, match="blob"):
        store.get(capsule["capsule_id"])


def test_admission_binding_is_write_once_and_idempotent(tmp_path: Path):
    store = WalletIntakeCapsuleStore(tmp_path / "vault")
    lab = tmp_path / "lab"
    lab.mkdir()
    source = lab / "result.txt"
    source.write_text("good")
    capsule = store.capture(
        project_id="p", section_id="s", parent_object_id="o", parent_sha256="a" * 64,
        source_path=source, allowed_root=lab,
    )
    first = store.bind_admission(
        capsule["capsule_id"], candidate_id="candidate1", operation_id="operation1",
        receipt_id="receipt1", candidate_sha256=capsule["blob_sha256"],
    )
    assert store.bind_admission(
        capsule["capsule_id"], candidate_id="candidate1", operation_id="operation1",
        receipt_id="receipt1", candidate_sha256=capsule["blob_sha256"],
    ) == first
    with pytest.raises(IntakeCapsuleError, match="different admission"):
        store.bind_admission(
            capsule["capsule_id"], candidate_id="candidate2", operation_id="operation2",
            receipt_id="receipt2", candidate_sha256=capsule["blob_sha256"],
        )


def test_complete_manifest_record_metadata_is_sealed(tmp_path: Path):
    store = WalletIntakeCapsuleStore(tmp_path / "wallet")
    source_root = tmp_path / "external"
    source_root.mkdir()
    source = source_root / "result.bin"
    source.write_bytes(b"sealed provenance")
    capsule = store.capture(
        project_id="project1",
        section_id="section1",
        parent_object_id="parent1",
        parent_sha256="a" * 64,
        source_path=source,
        allowed_root=source_root,
    )
    manifest_path = store.manifest_dir / f"{capsule['capsule_id']}.json"
    record = json.loads(manifest_path.read_text(encoding="utf-8"))
    record["capture_operation_id"] = "forged-operation"
    manifest_path.write_text(json.dumps(record), encoding="utf-8")
    with pytest.raises(IntakeCapsuleError, match="stored-record hash mismatch"):
        store.get(capsule["capsule_id"])


def test_admission_binding_record_is_sealed(tmp_path: Path):
    store = WalletIntakeCapsuleStore(tmp_path / "wallet")
    source_root = tmp_path / "external"
    source_root.mkdir()
    source = source_root / "result.bin"
    source.write_bytes(b"admission seal")
    capsule = store.capture(
        project_id="project1",
        section_id="section1",
        parent_object_id="parent1",
        parent_sha256="b" * 64,
        source_path=source,
        allowed_root=source_root,
    )
    store.bind_admission(
        capsule["capsule_id"],
        candidate_id="candidate1",
        operation_id="operation1",
        receipt_id="receipt1",
        candidate_sha256=capsule["blob_sha256"],
    )
    admission_path = store.admission_dir / f"{capsule['capsule_id']}.json"
    record = json.loads(admission_path.read_text(encoding="utf-8"))
    record["candidate_id"] = "forged-candidate"
    admission_path.write_text(json.dumps(record), encoding="utf-8")
    with pytest.raises(IntakeCapsuleError, match="admission record hash mismatch"):
        store.admission(capsule["capsule_id"])


def test_external_assertions_are_bounded_and_never_authority(tmp_path: Path):
    store = WalletIntakeCapsuleStore(tmp_path / "wallet")
    source_root = tmp_path / "external"
    source_root.mkdir()
    source = source_root / "result.bin"
    source.write_bytes(b"external assertion")
    capsule = store.capture(
        project_id="project1",
        section_id="section1",
        parent_object_id="parent1",
        parent_sha256="c" * 64,
        source_path=source,
        allowed_root=source_root,
        external_assertions=[{"issuer": "outside-lab", "claim": "tests passed"}],
    )
    assert capsule["external_assertions"][0]["authority"] == "external_assertion_only"
    with pytest.raises(IntakeCapsuleError, match="too many external assertions"):
        store.capture(
            project_id="project1",
            section_id="section1",
            parent_object_id="parent1",
            parent_sha256="c" * 64,
            source_path=source,
            allowed_root=source_root,
            external_assertions=[{"claim": str(i)} for i in range(33)],
        )
