from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from blackbox_plugin.migration import LegacyMigrationError, migrate_legacy_compact_session
from blackbox_plugin.recorder import SegmentedBlackBoxRecorder

ZERO_HASH = "0" * 64


def _wire(seq: int, previous: str, *, payload=None, session="legacy-session", record_id=None):
    payload = payload if payload is not None else {"state": f"v{seq}"}
    body = {
        "seq": seq,
        "t": f"2026-07-19T00:00:0{seq}+00:00",
        "ch": "ACT",
        "src": "SYS",
        "act": "legacy:actor",
        "ev": "OBS",
        "cov": "F",
        "sid": session,
        "rid": record_id or f"{session}:{seq}",
        "ph": previous,
        "p": payload,
    }
    digest = hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    parts = [
        "BBX1",
        f"seq={body['seq']}",
        f"t={body['t']}",
        f"ch={body['ch']}",
        f"src={body['src']}",
        f"act={body['act']}",
        f"ev={body['ev']}",
        f"cov={body['cov']}",
        f"sid={body['sid']}",
        f"rid={body['rid']}",
        f"ph={body['ph']}",
        f"h={digest}",
        f"p={json.dumps(body['p'], sort_keys=True, separators=(',', ':'))}",
    ]
    return "|".join(parts), digest


def _legacy_file(path: Path):
    first, first_hash = _wire(0, ZERO_HASH, payload={"text": "contains|pipe", "n": 1})
    second, second_hash = _wire(1, first_hash, payload={"state": "candidate"})
    data = (first + "\n" + second + "\n").encode("utf-8")
    path.write_bytes(data)
    return data, second_hash


def test_migration_preserves_raw_bytes_and_marks_legacy_proof_as_local_only(tmp_path: Path):
    source = tmp_path / "legacy.bbx"
    original, _ = _legacy_file(source)
    recorder = SegmentedBlackBoxRecorder(tmp_path / "canonical", "canonical-session")

    result = migrate_legacy_compact_session(source, recorder)

    assert source.read_bytes() == original
    assert Path(result.raw_archive_path).read_bytes() == original
    assert result.legacy_record_count == 2
    assert result.imported_record_count == 2
    assert result.independently_authenticated is False
    records = tuple(recorder.iter_records())
    assert len(records) == 3
    assert [item["observation_mode"] for item in records] == ["imported", "imported", "imported"]
    assert records[0]["payload"]["legacy_payload"]["text"] == "contains|pipe"
    assert records[0]["payload"]["authentication_scope"] == "local_consistency_only"
    seal = json.loads(Path(result.seal_path).read_text(encoding="utf-8"))
    supplied = seal.pop("seal_hash")
    from blackbox_plugin.schema import canonical_json
    assert supplied == hashlib.sha256(canonical_json(seal)).hexdigest()
    assert seal["source_rewritten"] is False
    assert recorder.verify().ok is True


def test_corrupt_legacy_chain_is_preserved_but_not_imported(tmp_path: Path):
    source = tmp_path / "corrupt.bbx"
    original, _ = _legacy_file(source)
    text = original.decode("utf-8").replace("h=", "h=f", 1)
    source.write_text(text, encoding="utf-8")
    recorder = SegmentedBlackBoxRecorder(tmp_path / "canonical", "canonical-session")

    with pytest.raises(LegacyMigrationError, match="hash mismatch"):
        migrate_legacy_compact_session(source, recorder)

    migration_dirs = list((recorder.session_dir / "migrations").iterdir())
    assert len(migration_dirs) == 1
    assert (migration_dirs[0] / "raw" / "legacy_source.bbx").read_bytes() == source.read_bytes()
    assert list((migration_dirs[0] / "failures").glob("*.json"))
    assert tuple(recorder.iter_records()) == ()
    assert source.read_text(encoding="utf-8") == text


def test_interrupted_import_resumes_idempotently_without_duplicate_facts(tmp_path: Path, monkeypatch):
    source = tmp_path / "legacy.bbx"
    _legacy_file(source)
    recorder = SegmentedBlackBoxRecorder(tmp_path / "canonical", "canonical-session")
    original_append = recorder.append
    calls = {"count": 0}

    def fail_second(event, **kwargs):
        calls["count"] += 1
        if calls["count"] == 2:
            raise OSError("simulated interruption")
        return original_append(event, **kwargs)

    monkeypatch.setattr(recorder, "append", fail_second)
    with pytest.raises(OSError, match="simulated interruption"):
        migrate_legacy_compact_session(source, recorder)
    monkeypatch.setattr(recorder, "append", original_append)

    result = migrate_legacy_compact_session(source, recorder)
    retry = migrate_legacy_compact_session(source, recorder)

    assert result.legacy_record_count == 2
    assert retry.resumed is True
    records = tuple(recorder.iter_records())
    assert len(records) == 3
    operation_ids = [record["operation_id"] for record in records]
    assert len(operation_ids) == len(set(operation_ids))
    assert recorder.verify().ok is True


def test_migration_id_cannot_escape_session_storage(tmp_path: Path):
    source = tmp_path / "legacy.bbx"
    _legacy_file(source)
    recorder = SegmentedBlackBoxRecorder(tmp_path / "canonical", "canonical-session")
    with pytest.raises(LegacyMigrationError, match="invalid migration_id"):
        migrate_legacy_compact_session(source, recorder, migration_id="../escape")
    assert not (tmp_path / "canonical" / "escape").exists()


def test_empty_legacy_evidence_is_not_sealed_as_full_migration(tmp_path: Path):
    source = tmp_path / "empty.bbx"
    source.write_bytes(b"\n")
    recorder = SegmentedBlackBoxRecorder(tmp_path / "canonical", "canonical-session")

    with pytest.raises(LegacyMigrationError, match="contains no records"):
        migrate_legacy_compact_session(source, recorder)
    assert tuple(recorder.iter_records()) == ()


def test_duplicate_legacy_record_ids_are_rejected(tmp_path: Path):
    source = tmp_path / "duplicate.bbx"
    first, first_hash = _wire(0, ZERO_HASH, record_id="duplicate-id")
    second, _ = _wire(1, first_hash, record_id="duplicate-id")
    source.write_text(first + "\n" + second + "\n", encoding="utf-8")
    recorder = SegmentedBlackBoxRecorder(tmp_path / "canonical", "canonical-session")

    with pytest.raises(LegacyMigrationError, match="duplicate legacy record id"):
        migrate_legacy_compact_session(source, recorder)
    assert tuple(recorder.iter_records()) == ()


def test_resume_revalidates_raw_archive_and_canonical_anchor(tmp_path: Path):
    from blackbox_plugin.schema import canonical_json

    source = tmp_path / "legacy.bbx"
    _legacy_file(source)
    recorder = SegmentedBlackBoxRecorder(tmp_path / "canonical", "canonical-session")
    result = migrate_legacy_compact_session(source, recorder)

    # A locally recomputed seal hash cannot hide a changed raw archive.
    raw = Path(result.raw_archive_path)
    raw.write_bytes(raw.read_bytes() + b"tampered")
    with pytest.raises(LegacyMigrationError, match="raw (archive|source) hash"):
        migrate_legacy_compact_session(source, recorder)

    # Restore raw bytes, then forge the anchor fields and recompute the local seal.
    raw.write_bytes(source.read_bytes())
    seal_path = Path(result.seal_path)
    seal = json.loads(seal_path.read_text(encoding="utf-8"))
    seal["canonical_anchor_hash"] = "f" * 64
    seal["seal_hash"] = hashlib.sha256(
        canonical_json({key: value for key, value in seal.items() if key != "seal_hash"})
    ).hexdigest()
    seal_path.write_text(json.dumps(seal, sort_keys=True), encoding="utf-8")
    with pytest.raises(LegacyMigrationError, match="not anchored"):
        migrate_legacy_compact_session(source, recorder)


def test_resume_rejects_symlinked_raw_archive(tmp_path: Path):
    if not hasattr(Path, "symlink_to"):
        pytest.skip("symlinks unavailable")
    source = tmp_path / "legacy.bbx"
    _legacy_file(source)
    recorder = SegmentedBlackBoxRecorder(tmp_path / "canonical", "canonical-session")
    result = migrate_legacy_compact_session(source, recorder)
    raw = Path(result.raw_archive_path)
    preserved = raw.with_name("preserved-real.bbx")
    raw.rename(preserved)
    try:
        raw.symlink_to(preserved)
    except OSError:
        pytest.skip("symlink creation unavailable")
    with pytest.raises(LegacyMigrationError, match="symlink"):
        migrate_legacy_compact_session(source, recorder)
