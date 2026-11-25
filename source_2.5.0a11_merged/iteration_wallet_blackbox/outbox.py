"""Hash-chained, cross-process durable outbox for Wallet-to-BlackBox delivery.

Queue, failure, and acknowledgement are append-only transitions. Records are
hash-chained, operation IDs are semantically idempotent, and an abrupt partial
final line is preserved while later writes rotate to a new segment. No outbox
record is edited or deleted.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping

from blackbox_plugin.models import utc_now
from blackbox_plugin.schema import ZERO_HASH, canonical_json
from .models import WalletFact

_SEGMENT_RE = re.compile(r"\.segment_(\d{6})\.jsonl$")
_MAX_RECORD_BYTES = 256 * 1024
_MAX_RECORDS_PER_SEGMENT = 10_000


class OutboxIntegrityError(RuntimeError):
    """Raised when outbox history is corrupt, ambiguous, or conflicting."""


@dataclass(frozen=True, slots=True)
class PendingFact:
    fact: WalletFact
    attempts: int = 0
    last_error: str | None = None


@dataclass(frozen=True, slots=True)
class OutboxVerification:
    ok: bool
    checked: int
    segment_count: int
    recoverable_tail: bool
    legacy_prefix_records: int
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "checked": self.checked,
            "segment_count": self.segment_count,
            "recoverable_tail": self.recoverable_tail,
            "legacy_prefix_records": self.legacy_prefix_records,
            "errors": list(self.errors),
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True, slots=True)
class _OperationState:
    fact: WalletFact
    fingerprint: str
    attempts: int = 0
    last_error: str | None = None
    acknowledged_record_id: str | None = None
    rejected_reason: str | None = None


@dataclass(frozen=True, slots=True)
class _ParsedState:
    operations: Mapping[str, _OperationState]
    next_sequence: int
    previous_hash: str
    active_segment_number: int
    active_segment_records: int
    recoverable_tail: bool
    verification: OutboxVerification


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


@contextmanager
def _file_lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise OutboxIntegrityError("outbox lock path is a symlink")
    handle = path.open("a+b")
    locked = False
    try:
        if os.name == "nt":
            import msvcrt

            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"\0")
                handle.flush()
                os.fsync(handle.fileno())
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        locked = True
        yield
    finally:
        try:
            if locked:
                if os.name == "nt":
                    import msvcrt

                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()


def _strict_object(raw: bytes, *, label: str) -> dict[str, Any]:
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise OutboxIntegrityError(f"{label} contains duplicate key {key!r}")
            result[key] = value
        return result

    def reject(value: str) -> None:
        raise OutboxIntegrityError(f"{label} contains non-finite number {value}")

    try:
        parsed = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=unique,
            parse_constant=reject,
        )
    except OutboxIntegrityError:
        raise
    except Exception as exc:
        raise OutboxIntegrityError(f"{label} is unreadable: {exc}") from exc
    if not isinstance(parsed, dict):
        raise OutboxIntegrityError(f"{label} must be a JSON object")
    return parsed


def _record_hash(record: Mapping[str, Any]) -> str:
    body = {key: value for key, value in dict(record).items() if key != "record_hash"}
    return hashlib.sha256(canonical_json(body)).hexdigest()


class DurableOutbox:
    def __init__(self, path: Path | str, *, fsync: bool = True) -> None:
        self.path = Path(path).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.parent.is_symlink() or self.path.is_symlink():
            raise OutboxIntegrityError("outbox path cannot be a symlink")
        self.fsync = fsync
        self.lock_path = self.path.with_name(self.path.name + ".lock")
        if not self.path.exists():
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            descriptor = os.open(self.path, flags, 0o600)
            os.close(descriptor)
            _fsync_directory(self.path.parent)
        elif not self.path.is_file():
            raise OutboxIntegrityError("outbox path must be a regular file")
        # Fail closed immediately if existing history is corrupt.
        self.verify(raise_on_error=True)

    def _segment_path(self, number: int) -> Path:
        if number == 1:
            return self.path
        return self.path.with_name(f"{self.path.name}.segment_{number:06d}.jsonl")

    def _segment_paths(self) -> list[Path]:
        paths: dict[int, Path] = {1: self.path}
        for candidate in self.path.parent.glob(f"{self.path.name}.segment_*.jsonl"):
            match = _SEGMENT_RE.search(candidate.name)
            if match:
                number = int(match.group(1))
                if number in paths:
                    raise OutboxIntegrityError(f"duplicate outbox segment number {number}")
                paths[number] = candidate
        numbers = sorted(paths)
        if numbers != list(range(1, max(numbers) + 1)):
            raise OutboxIntegrityError(f"outbox segment gap or reorder: {numbers}")
        for path in paths.values():
            if path.is_symlink() or not path.is_file():
                raise OutboxIntegrityError(f"outbox segment is not a regular non-symlink file: {path.name}")
        return [paths[number] for number in numbers]

    def _parse(self) -> _ParsedState:
        operations: dict[str, _OperationState] = {}
        errors: list[str] = []
        warnings: list[str] = []
        segments = self._segment_paths()
        v2_started = False
        legacy_digest = hashlib.sha256()
        legacy_count = 0
        previous_hash = ZERO_HASH
        expected_sequence = 0
        checked = 0
        recoverable_tail = False
        final_segment_recoverable_tail = False
        active_segment_records = 0

        for segment_index, path in enumerate(segments, 1):
            raw = path.read_bytes()
            lines = raw.splitlines(keepends=True)
            segment_valid_records = 0
            for line_index, framed in enumerate(lines, 1):
                has_newline = framed.endswith((b"\n", b"\r"))
                content = framed.rstrip(b"\r\n")
                if not content.strip():
                    continue
                is_segment_tail = line_index == len(lines)
                try:
                    record = _strict_object(content, label=f"{path.name}:{line_index}")
                except OutboxIntegrityError as exc:
                    if is_segment_tail and not has_newline:
                        recoverable_tail = True
                        if segment_index == len(segments):
                            final_segment_recoverable_tail = True
                        warnings.append(f"recoverable partial final outbox line preserved in {path.name}")
                        break
                    errors.append(str(exc))
                    continue
                version = int(record.get("version", 1))
                if version == 1:
                    if v2_started:
                        errors.append("legacy unchained outbox record appears after hash-chained records")
                        continue
                    legacy_digest.update(content + (b"\n" if has_newline else b""))
                    legacy_count += 1
                elif version == 2:
                    if not v2_started:
                        v2_started = True
                        previous_hash = legacy_digest.hexdigest() if legacy_count else ZERO_HASH
                    try:
                        sequence = int(record["sequence"])
                        supplied_previous = str(record["previous_hash"])
                        supplied_hash = str(record["record_hash"])
                    except (KeyError, ValueError, TypeError) as exc:
                        errors.append(f"{path.name}:{line_index}: malformed hash-chain fields: {exc}")
                        continue
                    if sequence != expected_sequence:
                        errors.append(
                            f"{path.name}:{line_index}: sequence mismatch; expected {expected_sequence}, got {sequence}"
                        )
                    if supplied_previous != previous_hash:
                        errors.append(f"{path.name}:{line_index}: previous hash mismatch")
                    calculated = _record_hash(record)
                    if supplied_hash != calculated:
                        errors.append(f"{path.name}:{line_index}: record hash mismatch")
                    previous_hash = supplied_hash
                    expected_sequence += 1
                else:
                    errors.append(f"{path.name}:{line_index}: unsupported outbox version {version}")
                    continue

                try:
                    self._apply_transition(operations, record, label=f"{path.name}:{line_index}")
                except OutboxIntegrityError as exc:
                    errors.append(str(exc))
                checked += 1
                segment_valid_records += 1
            if segment_index == len(segments):
                active_segment_records = segment_valid_records

        # A pre-v2 outbox is preserved as a byte-anchored prefix. The first
        # v2 transition must commit to those exact legacy bytes rather than
        # silently starting a fresh chain at ZERO_HASH.
        if legacy_count and not v2_started:
            previous_hash = legacy_digest.hexdigest()

        verification = OutboxVerification(
            ok=not errors,
            checked=checked,
            segment_count=len(segments),
            recoverable_tail=recoverable_tail,
            legacy_prefix_records=legacy_count,
            errors=tuple(errors),
            warnings=tuple(warnings),
        )
        active_segment_number = len(segments) + (
            1 if final_segment_recoverable_tail or active_segment_records >= _MAX_RECORDS_PER_SEGMENT else 0
        )
        if active_segment_number > len(segments):
            active_segment_records = 0
        return _ParsedState(
            operations=operations,
            next_sequence=expected_sequence,
            previous_hash=previous_hash,
            active_segment_number=active_segment_number,
            active_segment_records=active_segment_records,
            recoverable_tail=recoverable_tail,
            verification=verification,
        )

    @staticmethod
    def _apply_transition(
        operations: dict[str, _OperationState],
        record: Mapping[str, Any],
        *,
        label: str,
    ) -> None:
        operation_id = str(record.get("operation_id") or "")
        transition = str(record.get("transition") or "")
        if not operation_id:
            raise OutboxIntegrityError(f"{label}: transition has no operation_id")
        if transition == "queued":
            try:
                fact = WalletFact.from_dict(record["fact"])
            except (KeyError, ValueError, TypeError) as exc:
                raise OutboxIntegrityError(f"{label}: invalid queued fact: {exc}") from exc
            if fact.operation_id != operation_id:
                raise OutboxIntegrityError(f"{label}: operation_id disagrees with queued fact")
            fingerprint = str(record.get("fact_fingerprint") or fact.semantic_fingerprint())
            if fingerprint != fact.semantic_fingerprint():
                raise OutboxIntegrityError(f"{label}: queued fact fingerprint mismatch")
            existing = operations.get(operation_id)
            if existing is None:
                operations[operation_id] = _OperationState(fact=fact, fingerprint=fingerprint)
            elif existing.fingerprint != fingerprint:
                raise OutboxIntegrityError(f"{label}: operation_id was reused for a different fact")
        elif transition == "failed":
            existing = operations.get(operation_id)
            if existing is None or existing.acknowledged_record_id is not None or existing.rejected_reason is not None:
                raise OutboxIntegrityError(f"{label}: failure transition does not refer to a pending operation")
            operations[operation_id] = _OperationState(
                fact=existing.fact,
                fingerprint=existing.fingerprint,
                attempts=existing.attempts + 1,
                last_error=str(record.get("error") or "delivery_failed"),
            )
        elif transition == "rejected":
            existing = operations.get(operation_id)
            reason = str(record.get("reason") or "evidence_rejected")
            if existing is None or existing.acknowledged_record_id is not None:
                raise OutboxIntegrityError(f"{label}: rejection does not refer to an unacknowledged operation")
            if existing.rejected_reason not in {None, reason}:
                raise OutboxIntegrityError(f"{label}: conflicting rejection reason for operation_id")
            operations[operation_id] = _OperationState(
                fact=existing.fact,
                fingerprint=existing.fingerprint,
                attempts=existing.attempts,
                last_error=existing.last_error,
                rejected_reason=reason,
            )
        elif transition == "acknowledged":
            existing = operations.get(operation_id)
            record_id = str(record.get("record_id") or "")
            if existing is None or not record_id:
                raise OutboxIntegrityError(f"{label}: acknowledgement does not refer to a known operation")
            if existing.rejected_reason is not None:
                raise OutboxIntegrityError(f"{label}: rejected operation cannot be acknowledged")
            if existing.acknowledged_record_id not in {None, record_id}:
                raise OutboxIntegrityError(f"{label}: conflicting acknowledgement for operation_id")
            operations[operation_id] = _OperationState(
                fact=existing.fact,
                fingerprint=existing.fingerprint,
                attempts=existing.attempts,
                last_error=existing.last_error,
                acknowledged_record_id=record_id,
                rejected_reason=None,
            )
        else:
            raise OutboxIntegrityError(f"{label}: unsupported transition {transition!r}")

    def _append_locked(self, record: dict[str, Any], state: _ParsedState) -> None:
        if not state.verification.ok:
            raise OutboxIntegrityError("outbox history failed verification: " + "; ".join(state.verification.errors))
        material = {
            "version": 2,
            "sequence": state.next_sequence,
            "previous_hash": state.previous_hash,
            **record,
        }
        material["record_hash"] = _record_hash(material)
        encoded = json.dumps(
            material,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8", errors="strict") + b"\n"
        if len(encoded) > _MAX_RECORD_BYTES:
            raise OutboxIntegrityError(f"outbox record exceeds {_MAX_RECORD_BYTES} bytes")
        path = self._segment_path(state.active_segment_number)
        if path.is_symlink():
            raise OutboxIntegrityError("active outbox segment is a symlink")
        flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(path, flags, 0o600)
        try:
            remaining = memoryview(encoded)
            while remaining:
                written = os.write(descriptor, remaining)
                if written <= 0:
                    raise OutboxIntegrityError("outbox append made no forward progress")
                remaining = remaining[written:]
            if self.fsync:
                os.fsync(descriptor)
        finally:
            os.close(descriptor)
        if state.active_segment_records == 0:
            _fsync_directory(path.parent)

    def verify(self, *, raise_on_error: bool = False) -> OutboxVerification:
        with _file_lock(self.lock_path):
            result = self._parse().verification
        if raise_on_error and not result.ok:
            raise OutboxIntegrityError("outbox history failed verification: " + "; ".join(result.errors))
        return result

    def enqueue(self, fact: WalletFact | Mapping[str, Any]) -> None:
        if not isinstance(fact, WalletFact):
            fact = WalletFact.from_dict(fact)
        with _file_lock(self.lock_path):
            state = self._parse()
            if not state.verification.ok:
                raise OutboxIntegrityError("outbox history failed verification: " + "; ".join(state.verification.errors))
            existing = state.operations.get(fact.operation_id)
            fingerprint = fact.semantic_fingerprint()
            if existing is not None:
                if existing.fingerprint != fingerprint:
                    raise OutboxIntegrityError("operation_id was reused for a different Wallet fact")
                if existing.rejected_reason is not None:
                    raise OutboxIntegrityError(
                        "operation was permanently rejected; create a new operation only after correcting the fact or policy"
                    )
                return
            self._append_locked(
                {
                    "transition": "queued",
                    "at": utc_now(),
                    "operation_id": fact.operation_id,
                    "fact_fingerprint": fingerprint,
                    "fact": fact.to_dict(),
                },
                state,
            )

    def pending(self) -> Iterable[PendingFact]:
        with _file_lock(self.lock_path):
            state = self._parse()
        if not state.verification.ok:
            raise OutboxIntegrityError("outbox history failed verification: " + "; ".join(state.verification.errors))
        return tuple(
            PendingFact(item.fact, item.attempts, item.last_error)
            for operation_id, item in sorted(state.operations.items())
            if item.acknowledged_record_id is None and item.rejected_reason is None
        )

    def acknowledge(self, operation_id: str, record_id: str) -> None:
        with _file_lock(self.lock_path):
            state = self._parse()
            if not state.verification.ok:
                raise OutboxIntegrityError("outbox history failed verification: " + "; ".join(state.verification.errors))
            existing = state.operations.get(operation_id)
            if existing is None:
                raise OutboxIntegrityError("cannot acknowledge an unknown outbox operation")
            if existing.rejected_reason is not None:
                raise OutboxIntegrityError("cannot acknowledge a rejected outbox operation")
            if existing.acknowledged_record_id is not None:
                if existing.acknowledged_record_id != record_id:
                    raise OutboxIntegrityError("operation already has a different acknowledgement")
                return
            if not record_id:
                raise OutboxIntegrityError("acknowledgement record_id is required")
            self._append_locked(
                {
                    "transition": "acknowledged",
                    "at": utc_now(),
                    "operation_id": operation_id,
                    "record_id": record_id,
                },
                state,
            )

    def fail(self, operation_id: str, error: str) -> None:
        safe_error = str(error).replace("\r", " ").replace("\n", " ")[:500]
        with _file_lock(self.lock_path):
            state = self._parse()
            if not state.verification.ok:
                raise OutboxIntegrityError("outbox history failed verification: " + "; ".join(state.verification.errors))
            existing = state.operations.get(operation_id)
            if existing is None or existing.acknowledged_record_id is not None or existing.rejected_reason is not None:
                raise OutboxIntegrityError("cannot fail an unknown, acknowledged, or rejected outbox operation")
            self._append_locked(
                {
                    "transition": "failed",
                    "at": utc_now(),
                    "operation_id": operation_id,
                    "error": safe_error or "delivery_failed",
                },
                state,
            )

    def reject(self, operation_id: str, reason: str) -> None:
        safe_reason = str(reason).replace("\r", " ").replace("\n", " ")[:500]
        with _file_lock(self.lock_path):
            state = self._parse()
            if not state.verification.ok:
                raise OutboxIntegrityError("outbox history failed verification: " + "; ".join(state.verification.errors))
            existing = state.operations.get(operation_id)
            if existing is None or existing.acknowledged_record_id is not None:
                raise OutboxIntegrityError("cannot reject an unknown or acknowledged outbox operation")
            if existing.rejected_reason is not None:
                if existing.rejected_reason != (safe_reason or "evidence_rejected"):
                    raise OutboxIntegrityError("operation already has a different rejection reason")
                return
            self._append_locked(
                {
                    "transition": "rejected",
                    "at": utc_now(),
                    "operation_id": operation_id,
                    "reason": safe_reason or "evidence_rejected",
                },
                state,
            )

    def closed_status(self) -> dict[str, object]:
        with _file_lock(self.lock_path):
            state = self._parse()
        pending = [item for item in state.operations.values() if item.acknowledged_record_id is None and item.rejected_reason is None]
        rejected = [item for item in state.operations.values() if item.rejected_reason is not None]
        return {
            "view_mode": "closed_outbox_status",
            "verified": state.verification.ok,
            "pending_count": len(pending),
            "acknowledged_count": sum(
                1 for item in state.operations.values() if item.acknowledged_record_id is not None
            ),
            "rejected_count": len(rejected),
            "attempt_count": sum(item.attempts for item in pending),
            "coverage_gap_count": sum(1 for item in pending if item.attempts > 0),
            "recoverable_tail": state.verification.recoverable_tail,
            "segment_count": state.verification.segment_count,
            "legacy_prefix_records": state.verification.legacy_prefix_records,
            "errors": list(state.verification.errors),
            "warnings": list(state.verification.warnings),
            "raw_payloads_exposed": False,
            "outbox_path_exposed": False,
        }
