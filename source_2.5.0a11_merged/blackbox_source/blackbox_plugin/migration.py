"""Read-only migration of legacy compact BBX1 evidence into the canonical chain.

Migration preserves the source byte-for-byte, verifies the legacy local chain,
and records imported facts with explicit provenance.  It never rewrites the
legacy source and never upgrades locally self-authenticated evidence into an
independent witness claim.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any, Mapping
from uuid import uuid4

from .models import Coverage, EvidenceEvent, ObservationMode, utc_now
from .recorder import SegmentedBlackBoxRecorder
from .schema import ZERO_HASH, canonical_json, validate_json_value

_MIGRATION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.@+\-]{0,127}$")
_EXPECTED_FIELDS = ("seq", "t", "ch", "src", "act", "ev", "cov", "sid", "rid", "ph", "h", "p")
_MAX_SOURCE_BYTES = 128 * 1024 * 1024
_HEX_64_RE = re.compile(r"^[0-9a-f]{64}$")
_MAX_FIELD_CHARS = 512


class LegacyMigrationError(Exception):
    """Raised when legacy evidence cannot be preserved and verified honestly."""


@dataclass(frozen=True, slots=True)
class LegacyRecord:
    sequence: int
    observed_at: str
    channel: str
    source: str
    actor: str
    event_code: str
    coverage: str
    session_id: str
    record_id: str
    previous_hash: str
    record_hash: str
    payload: Any


@dataclass(frozen=True, slots=True)
class MigrationResult:
    migration_id: str
    source_sha256: str
    source_size: int
    legacy_record_count: int
    imported_record_count: int
    canonical_session_id: str
    canonical_anchor_hash: str
    raw_archive_path: str
    seal_path: str
    source_capture_stable: bool
    independently_authenticated: bool = False
    authentication_scope: str = "local_consistency_only"
    proof_strength: str = "legacy_local_chain"
    resumed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _fsync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _exclusive_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.parent.is_symlink() or path.is_symlink():
        raise LegacyMigrationError("migration output path cannot be a symlink")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o600)
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        os.close(descriptor)
    _fsync_directory(path.parent)


def _exclusive_json(path: Path, payload: Mapping[str, Any]) -> None:
    encoded = json.dumps(
        dict(payload), indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False
    ).encode("utf-8", errors="strict")
    _exclusive_bytes(path, encoded)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise LegacyMigrationError(f"legacy payload contains duplicate key {key!r}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise LegacyMigrationError(f"legacy payload contains non-finite number {value}")




def _validate_legacy_text(name: str, value: str, *, allow_blank: bool = False) -> str:
    if not isinstance(value, str):
        raise LegacyMigrationError(f"legacy {name} must be text")
    if not value and allow_blank:
        return value
    if not value or len(value) > _MAX_FIELD_CHARS:
        raise LegacyMigrationError(f"legacy {name} is missing or unbounded")
    if "|" in value or "\x00" in value or any(ord(ch) < 32 for ch in value):
        raise LegacyMigrationError(f"legacy {name} contains unsafe framing characters")
    return value


def _validate_legacy_timestamp(value: str) -> str:
    _validate_legacy_text("timestamp", value)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise LegacyMigrationError("legacy timestamp is not ISO-8601") from exc
    if parsed.tzinfo is None:
        raise LegacyMigrationError("legacy timestamp does not include a timezone")
    return value


def _strict_object(text: str, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(
            text,
            parse_constant=_reject_constant,
            object_pairs_hook=_unique_object,
        )
    except LegacyMigrationError:
        raise
    except Exception as exc:
        raise LegacyMigrationError(f"{label} is not strict JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise LegacyMigrationError(f"{label} must be an object")
    return value


def _parse_payload(text: str) -> Any:
    try:
        payload = json.loads(
            text,
            parse_constant=_reject_constant,
            object_pairs_hook=_unique_object,
        )
        validate_json_value(payload)
        return payload
    except LegacyMigrationError:
        raise
    except Exception as exc:
        raise LegacyMigrationError(f"legacy payload is not strict JSON: {exc}") from exc


def _parse_field(part: str, expected: str) -> str:
    prefix = expected + "="
    if not part.startswith(prefix):
        raise LegacyMigrationError(f"legacy field order mismatch: expected {expected}")
    return part[len(prefix):]


def _legacy_record_hash(record: LegacyRecord) -> str:
    body = {
        "seq": record.sequence,
        "t": record.observed_at,
        "ch": record.channel,
        "src": record.source,
        "act": record.actor,
        "ev": record.event_code,
        "cov": record.coverage,
        "sid": record.session_id,
        "rid": record.record_id,
        "ph": record.previous_hash,
        "p": record.payload,
    }
    encoded = json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def parse_legacy_compact_record(line: str) -> LegacyRecord:
    """Parse the Phase 1/1.2 pipe-framed BBX1 record without executing code."""
    if not isinstance(line, str):
        raise LegacyMigrationError("legacy record must be text")
    parts = line.rstrip("\r\n").split("|", 12)
    if len(parts) != 13 or parts[0] != "BBX1":
        raise LegacyMigrationError("legacy record frame is malformed")
    values = {
        field: _parse_field(part, field)
        for field, part in zip(_EXPECTED_FIELDS, parts[1:], strict=True)
    }
    try:
        sequence = int(values["seq"])
    except ValueError as exc:
        raise LegacyMigrationError("legacy sequence is not an integer") from exc
    if sequence < 0:
        raise LegacyMigrationError("legacy sequence cannot be negative")
    payload = _parse_payload(values["p"])
    observed_at = _validate_legacy_timestamp(values["t"])
    channel = _validate_legacy_text("channel", values["ch"])
    source = _validate_legacy_text("source", values["src"])
    actor = _validate_legacy_text("actor", values["act"])
    event_code = _validate_legacy_text("event code", values["ev"])
    coverage = _validate_legacy_text("coverage", values["cov"])
    session_id = _validate_legacy_text("session id", values["sid"])
    record_id = _validate_legacy_text("record id", values["rid"])
    previous_hash = values["ph"]
    record_hash = values["h"]
    if not _HEX_64_RE.fullmatch(previous_hash) or not _HEX_64_RE.fullmatch(record_hash):
        raise LegacyMigrationError("legacy chain hashes must be lowercase SHA-256 digests")
    record = LegacyRecord(
        sequence=sequence,
        observed_at=observed_at,
        channel=channel,
        source=source,
        actor=actor,
        event_code=event_code,
        coverage=coverage,
        session_id=session_id,
        record_id=record_id,
        previous_hash=previous_hash,
        record_hash=record_hash,
        payload=payload,
    )
    if record.record_hash != _legacy_record_hash(record):
        raise LegacyMigrationError(f"legacy record hash mismatch at sequence {sequence}")
    return record


def verify_legacy_compact_bytes(data: bytes) -> tuple[LegacyRecord, ...]:
    try:
        text = data.decode("utf-8-sig", errors="strict")
    except UnicodeDecodeError as exc:
        raise LegacyMigrationError(f"legacy evidence is not valid UTF-8: {exc}") from exc
    records: list[LegacyRecord] = []
    record_ids: set[str] = set()
    expected_hash = ZERO_HASH
    expected_sequence = 0
    session_id: str | None = None
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            record = parse_legacy_compact_record(line)
        except LegacyMigrationError as exc:
            raise LegacyMigrationError(f"line {line_number}: {exc}") from exc
        if record.sequence != expected_sequence:
            raise LegacyMigrationError(
                f"line {line_number}: sequence gap; expected {expected_sequence}, got {record.sequence}"
            )
        if record.previous_hash != expected_hash:
            raise LegacyMigrationError(
                f"line {line_number}: previous hash mismatch at sequence {record.sequence}"
            )
        if session_id is None:
            session_id = record.session_id
        elif record.session_id != session_id:
            raise LegacyMigrationError(f"line {line_number}: mixed legacy session identifiers")
        if record.record_id in record_ids:
            raise LegacyMigrationError(f"line {line_number}: duplicate legacy record id {record.record_id!r}")
        record_ids.add(record.record_id)
        records.append(record)
        expected_sequence += 1
        expected_hash = record.record_hash
    if not records:
        raise LegacyMigrationError("legacy evidence contains no records")
    return tuple(records)


def _coverage(value: str) -> Coverage:
    return {
        "F": Coverage.FULL,
        "P": Coverage.PARTIAL,
        "S": Coverage.SUMMARY,
        "U": Coverage.UNKNOWN,
    }.get(value, Coverage.UNKNOWN)


def _bounded_payload(value: Any) -> tuple[Any | None, str, int, bool]:
    wrapped = {"value": value}
    encoded = canonical_json(wrapped)
    digest = hashlib.sha256(encoded).hexdigest()
    if len(encoded) <= 24 * 1024:
        return value, digest, len(encoded), False
    return None, digest, len(encoded), True


def _seal_hash(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json(payload)).hexdigest()


def _record_failure(migration_dir: Path, *, stage: str, error: Exception, source_sha256: str) -> None:
    failure_dir = migration_dir / "failures"
    payload = {
        "version": 1,
        "recorded_at": utc_now(),
        "stage": stage,
        "error_type": type(error).__name__,
        "error": str(error),
        "source_sha256": source_sha256,
        "source_preserved": (migration_dir / "raw" / "legacy_source.bbx").exists(),
        "automatic_rollback_attempted": False,
        "source_rewritten": False,
    }
    try:
        _exclusive_json(failure_dir / f"failure_{uuid4().hex}.json", payload)
    except Exception as report_error:
        # Preserve the original exception while making the secondary evidence
        # gap visible to callers that render exception notes.
        if hasattr(error, "add_note"):
            error.add_note(
                f"migration failure report could not be persisted: "
                f"{type(report_error).__name__}: {report_error}"
            )


def _safe_archive_path(recorder: SegmentedBlackBoxRecorder, relative_text: str) -> Path:
    pure = PurePosixPath(relative_text)
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        raise LegacyMigrationError("migration seal contains an unsafe raw archive path")
    candidate = recorder.session_dir.joinpath(*pure.parts)
    if candidate.is_symlink():
        raise LegacyMigrationError("preserved raw archive cannot be a symlink")
    resolved_root = recorder.session_dir.resolve()
    resolved_candidate = candidate.resolve(strict=True)
    try:
        resolved_candidate.relative_to(resolved_root)
    except ValueError as exc:
        raise LegacyMigrationError("preserved raw archive escapes the canonical session") from exc
    if not resolved_candidate.is_file():
        raise LegacyMigrationError("preserved raw archive is not a regular file")
    return resolved_candidate


def _validate_existing_seal(
    path: Path,
    *,
    source_sha256: str,
    session_id: str,
    recorder: SegmentedBlackBoxRecorder,
) -> MigrationResult:
    if path.is_symlink():
        raise LegacyMigrationError("migration seal cannot be a symlink")
    try:
        payload = _strict_object(path.read_text(encoding="utf-8", errors="strict"), label="migration seal")
    except OSError as exc:
        raise LegacyMigrationError(f"existing migration seal cannot be read: {exc}") from exc
    supplied_hash = payload.pop("seal_hash", None)
    if not isinstance(supplied_hash, str) or supplied_hash != _seal_hash(payload):
        raise LegacyMigrationError("existing migration seal hash mismatch")
    required = {
        "migration_id", "source_sha256", "source_size", "legacy_record_count",
        "imported_record_count", "canonical_session_id", "canonical_anchor_hash",
        "canonical_anchor_record_id", "raw_archive_path", "source_capture_stable",
        "source_rewritten", "independently_authenticated", "authentication_scope",
        "proof_strength", "automatic_trust_upgrade",
    }
    missing = sorted(required - set(payload))
    if missing:
        raise LegacyMigrationError(f"migration seal is missing required fields: {missing}")
    if payload.get("source_sha256") != source_sha256:
        raise LegacyMigrationError("migration identifier collides with a different source")
    if payload.get("canonical_session_id") != session_id:
        raise LegacyMigrationError("migration seal belongs to a different canonical session")
    if payload.get("source_rewritten") is not False or payload.get("automatic_trust_upgrade") is not False:
        raise LegacyMigrationError("migration seal makes a forbidden rewrite or trust-upgrade claim")
    if payload.get("independently_authenticated") is not False:
        raise LegacyMigrationError("legacy migration cannot claim independent authentication")
    if payload.get("authentication_scope") != "local_consistency_only":
        raise LegacyMigrationError("legacy migration authentication scope is overstated")

    raw_path = _safe_archive_path(recorder, str(payload["raw_archive_path"]))
    raw_data = raw_path.read_bytes()
    if hashlib.sha256(raw_data).hexdigest() != source_sha256:
        raise LegacyMigrationError("preserved raw archive hash no longer matches the migration source")
    if len(raw_data) != int(payload["source_size"]):
        raise LegacyMigrationError("preserved raw archive size no longer matches the migration seal")
    legacy_records = verify_legacy_compact_bytes(raw_data)
    if len(legacy_records) != int(payload["legacy_record_count"]):
        raise LegacyMigrationError("legacy record count no longer matches the preserved source")

    verification = recorder.verify()
    if not verification.ok:
        raise LegacyMigrationError("canonical recorder failed verification while resuming migration")
    canonical_records = tuple(recorder.iter_records())
    anchor_record_id = str(payload["canonical_anchor_record_id"])
    anchor_hash = str(payload["canonical_anchor_hash"])
    migration_id = str(payload["migration_id"])
    anchors = [
        record for record in canonical_records
        if str(record.get("record_id")) == anchor_record_id
        and str(record.get("hash")) == anchor_hash
        and record.get("event_type") == "migration.legacy_session_sealed"
        and (record.get("payload") or {}).get("migration_id") == migration_id
        and (record.get("payload") or {}).get("source_file_sha256") == source_sha256
    ]
    if len(anchors) != 1:
        raise LegacyMigrationError("migration seal is not anchored to exactly one verified canonical record")
    imported_records = [
        record for record in canonical_records
        if record.get("event_type") == "migration.legacy_record_imported"
        and (record.get("payload") or {}).get("migration_id") == migration_id
        and (record.get("payload") or {}).get("source_file_sha256") == source_sha256
    ]
    imported_count = int(payload["imported_record_count"])
    if imported_count != len(legacy_records) or len(imported_records) != imported_count:
        raise LegacyMigrationError("migration seal import count is not supported by the canonical chain")
    source_sequences = sorted(int(record.get("source_sequence")) for record in imported_records)
    if source_sequences != list(range(len(legacy_records))):
        raise LegacyMigrationError("canonical imported records do not cover the complete legacy sequence")

    return MigrationResult(
        migration_id=migration_id,
        source_sha256=source_sha256,
        source_size=int(payload["source_size"]),
        legacy_record_count=len(legacy_records),
        imported_record_count=imported_count,
        canonical_session_id=session_id,
        canonical_anchor_hash=anchor_hash,
        raw_archive_path=str(raw_path),
        seal_path=str(path),
        source_capture_stable=bool(payload["source_capture_stable"]),
        independently_authenticated=False,
        authentication_scope="local_consistency_only",
        proof_strength="legacy_local_chain",
        resumed=True,
    )


def migrate_legacy_compact_session(
    source_path: Path | str,
    recorder: SegmentedBlackBoxRecorder,
    *,
    migration_id: str | None = None,
) -> MigrationResult:
    """Preserve, verify, and import one legacy Phase 1/1.2 compact session.

    The stable operation IDs make retries safe after partial interruption.  A
    source that fails local hash/chain verification is preserved but not
    imported as verified fact.
    """
    source = Path(source_path).expanduser()
    if source.is_symlink():
        raise LegacyMigrationError("legacy source cannot be a symlink")
    try:
        before = source.stat(follow_symlinks=False)
    except OSError as exc:
        raise LegacyMigrationError(f"legacy source is unavailable: {exc}") from exc
    if not source.is_file():
        raise LegacyMigrationError("legacy source must be a regular file")
    if before.st_size > _MAX_SOURCE_BYTES:
        raise LegacyMigrationError(f"legacy source exceeds {_MAX_SOURCE_BYTES} bytes")
    try:
        data = source.read_bytes()
        after = source.stat(follow_symlinks=False)
    except OSError as exc:
        raise LegacyMigrationError(f"legacy source could not be captured: {exc}") from exc
    stable_before = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
    stable_after = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
    if stable_before != stable_after or len(data) != before.st_size:
        raise LegacyMigrationError("legacy source changed during capture")

    source_sha256 = hashlib.sha256(data).hexdigest()
    selected_id = migration_id or f"phase12_{source_sha256[:24]}"
    if not _MIGRATION_ID_RE.fullmatch(selected_id):
        raise LegacyMigrationError(f"invalid migration_id: {selected_id!r}")
    migration_root = recorder.session_dir / "migrations"
    migration_dir = migration_root / selected_id
    migration_dir.mkdir(parents=True, exist_ok=True)
    if migration_dir.is_symlink():
        raise LegacyMigrationError("migration directory cannot be a symlink")
    raw_path = migration_dir / "raw" / "legacy_source.bbx"
    seal_path = migration_dir / "migration_seal.json"

    if raw_path.exists():
        if raw_path.is_symlink() or not raw_path.is_file():
            raise LegacyMigrationError("preserved raw source is not a regular non-symlink file")
        if hashlib.sha256(raw_path.read_bytes()).hexdigest() != source_sha256:
            raise LegacyMigrationError("preserved raw source hash mismatch")
    else:
        _exclusive_bytes(raw_path, data)

    if seal_path.exists():
        return _validate_existing_seal(
            seal_path,
            source_sha256=source_sha256,
            session_id=recorder.session_id,
            recorder=recorder,
        )

    try:
        records = verify_legacy_compact_bytes(data)
    except Exception as exc:
        _record_failure(migration_dir, stage="legacy_verification", error=exc, source_sha256=source_sha256)
        raise

    imported = 0
    try:
        for record in records:
            legacy_payload, payload_hash, payload_size, payload_omitted = _bounded_payload(record.payload)
            payload: dict[str, Any] = {
                "migration_id": selected_id,
                "legacy_format": "phase1_2_compact_bbx1",
                "legacy_session_id": record.session_id,
                "legacy_record_id": record.record_id,
                "legacy_record_hash": record.record_hash,
                "legacy_previous_hash": record.previous_hash,
                "legacy_channel": record.channel,
                "legacy_source": record.source,
                "legacy_actor": record.actor,
                "legacy_event_code": record.event_code,
                "legacy_coverage": record.coverage,
                "legacy_payload_sha256": payload_hash,
                "legacy_payload_encoded_bytes": payload_size,
                "legacy_payload_omitted_from_envelope": payload_omitted,
                "source_file_sha256": source_sha256,
                "source_capture_stable": True,
                "independently_authenticated": False,
                "authentication_scope": "local_consistency_only",
                "proof_strength": "legacy_local_chain",
            }
            if not payload_omitted:
                payload["legacy_payload"] = legacy_payload
            receipt = recorder.append(
                EvidenceEvent(
                    event_type="migration.legacy_record_imported",
                    source="legacy_phase1_2",
                    actor="system:migration",
                    subject_id=f"legacy:{source_sha256[:12]}:{record.sequence}",
                    observation_mode=ObservationMode.IMPORTED,
                    coverage=_coverage(record.coverage),
                    payload=payload,
                    operation_id=f"migration:{selected_id}:record:{record.sequence}",
                    session_id=recorder.session_id,
                    source_sequence=record.sequence,
                    observed_at=record.observed_at or utc_now(),
                    channel="MIG",
                    event_code="IMP",
                )
            )
            if receipt.event_hash:
                imported += 1

        summary_receipt = recorder.append(
            EvidenceEvent(
                event_type="migration.legacy_session_sealed",
                source="legacy_phase1_2",
                actor="system:migration",
                subject_id=f"legacy-session:{source_sha256[:24]}",
                observation_mode=ObservationMode.IMPORTED,
                coverage=Coverage.FULL,
                payload={
                    "migration_id": selected_id,
                    "legacy_format": "phase1_2_compact_bbx1",
                    "source_file_sha256": source_sha256,
                    "source_size": len(data),
                    "legacy_record_count": len(records),
                    "raw_archive_path": str(raw_path.relative_to(recorder.session_dir)),
                    "source_capture_stable": True,
                    "source_rewritten": False,
                    "independently_authenticated": False,
                    "authentication_scope": "local_consistency_only",
                    "proof_strength": "legacy_local_chain",
                    "gaps": ["no independent external witness was present in the legacy format"],
                },
                operation_id=f"migration:{selected_id}:seal",
                session_id=recorder.session_id,
                channel="MIG",
                event_code="SEA",
            )
        )
    except Exception as exc:
        _record_failure(migration_dir, stage="canonical_import", error=exc, source_sha256=source_sha256)
        raise

    seal_body = {
        "version": 1,
        "migration_id": selected_id,
        "created_at": utc_now(),
        "source_sha256": source_sha256,
        "source_size": len(data),
        "source_capture_stable": True,
        "source_rewritten": False,
        "legacy_record_count": len(records),
        "imported_record_count": imported,
        "canonical_session_id": recorder.session_id,
        "canonical_anchor_hash": summary_receipt.event_hash,
        "canonical_anchor_record_id": summary_receipt.record_id,
        "raw_archive_path": str(raw_path.relative_to(recorder.session_dir)),
        "legacy_verification": "local_hash_and_chain_verified",
        "independently_authenticated": False,
        "authentication_scope": "local_consistency_only",
        "proof_strength": "legacy_local_chain",
        "automatic_trust_upgrade": False,
    }
    sealed = {**seal_body, "seal_hash": _seal_hash(seal_body)}
    try:
        _exclusive_json(seal_path, sealed)
    except FileExistsError:
        return _validate_existing_seal(
            seal_path,
            source_sha256=source_sha256,
            session_id=recorder.session_id,
            recorder=recorder,
        )

    return MigrationResult(
        migration_id=selected_id,
        source_sha256=source_sha256,
        source_size=len(data),
        legacy_record_count=len(records),
        imported_record_count=imported,
        canonical_session_id=recorder.session_id,
        canonical_anchor_hash=summary_receipt.event_hash,
        raw_archive_path=str(raw_path),
        seal_path=str(seal_path),
        source_capture_stable=True,
    )


__all__ = [
    "LegacyMigrationError",
    "LegacyRecord",
    "MigrationResult",
    "migrate_legacy_compact_session",
    "parse_legacy_compact_record",
    "verify_legacy_compact_bytes",
]
