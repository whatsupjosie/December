"""Segmented append-only BlackBox recorder with crash-tail recovery.

The recorder never rewrites or reduces an evidence segment. A malformed final tail
is preserved in place and later appends rotate to a new segment. Corruption in
any non-tail position fails closed.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping
from uuid import uuid4

from .errors import RecorderIntegrityError, RecorderSealedError, RecordValidationError
from .models import AppendReceipt, EvidenceEvent, RecorderHealth, RecorderState, VerificationResult, utc_now
from .schema import ZERO_HASH, canonical_json, decode_record, encode_record

_SEGMENT_RE = re.compile(r"^segment_(\d{6})\.bbx$")
_STORAGE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.@+\-]{0,127}$")
_WINDOWS_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def _validate_storage_id(name: str, value: str) -> str:
    """Validate a single portable path component used for evidence storage.

    Human-facing identifiers may contain richer syntax, but storage identifiers
    are deliberately narrower so they cannot become paths on POSIX or Windows.
    """
    if not isinstance(value, str) or not _STORAGE_ID_RE.fullmatch(value):
        raise RecordValidationError(f"invalid storage {name}: {value!r}")
    if value in {".", ".."} or value.endswith((".", " ")):
        raise RecordValidationError(f"invalid storage {name}: {value!r}")
    stem = value.split(".", 1)[0].upper()
    if stem in _WINDOWS_RESERVED_NAMES:
        raise RecordValidationError(f"reserved storage {name}: {value!r}")
    return value


def _ensure_within(root: Path, candidate: Path, *, label: str) -> Path:
    root_resolved = root.resolve()
    candidate_resolved = candidate.resolve()
    try:
        candidate_resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise RecordValidationError(f"{label} escapes storage root") from exc
    return candidate_resolved


def _fsync_directory(path: Path) -> None:
    """Persist directory metadata where the platform exposes directory fsync."""
    if os.name == "nt":
        return
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    fd = os.open(path, flags)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    """Crash-aware replacement for derived metadata only.

    Canonical immutable evidence must use ``_exclusive_json`` instead.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.{uuid4().hex}.tmp")
    data = json.dumps(dict(payload), indent=2, sort_keys=True, ensure_ascii=False).encode("utf-8")
    with tmp.open("xb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)
    _fsync_directory(path.parent)


def _exclusive_json(path: Path, payload: Mapping[str, Any]) -> None:
    """Create a canonical JSON object exactly once; never replace it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(dict(payload), indent=2, sort_keys=True, ensure_ascii=False).encode("utf-8")
    with path.open("xb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    _fsync_directory(path.parent)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@contextmanager
def _file_lock(path: Path) -> Iterator[None]:
    """Cross-process append authority lock for cooperating writers."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise RecorderIntegrityError("append lock path is a symlink")
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


def _segment_number(path: Path) -> int:
    match = _SEGMENT_RE.match(path.name)
    if not match:
        raise ValueError(path.name)
    return int(match.group(1))


def _segment_paths(session_dir: Path) -> list[Path]:
    segment_dir = session_dir / "segments"
    if not segment_dir.exists():
        return []
    return sorted((p for p in segment_dir.iterdir() if p.is_file() and _SEGMENT_RE.match(p.name)), key=_segment_number)


def _read_lines_preserve_tail(path: Path) -> tuple[list[str], bool]:
    raw = path.read_bytes()
    ended_with_newline = raw.endswith(b"\n")
    text = raw.decode("utf-8", errors="replace")
    return text.splitlines(), ended_with_newline


def _record_body(event: EvidenceEvent, *, sequence: int, previous_hash: str) -> dict[str, Any]:
    return {
        "version": "BBX1",
        "seq": sequence,
        "observed_at": event.observed_at,
        "channel": event.channel,
        "source": event.source,
        "actor": event.actor,
        "event": event.event_code,
        "event_type": event.event_type,
        "coverage": event.coverage.value,
        "observation_mode": event.observation_mode.value,
        "session_id": event.session_id,
        "record_id": event.event_id,
        "subject_id": event.subject_id,
        "operation_id": event.operation_id,
        "source_sequence": event.source_sequence,
        "previous_hash": previous_hash,
        "payload": dict(event.payload),
        "semantic_fingerprint": event.semantic_fingerprint(),
    }


def inspect_session(session_dir: Path | str, *, allow_recoverable_tail: bool = True) -> tuple[list[dict[str, Any]], VerificationResult]:
    """Recalculate all hashes, chain links, segment order, and source sequences."""
    session_dir = Path(session_dir)
    errors: list[str] = []
    warnings: list[str] = []
    records: list[dict[str, Any]] = []
    paths = _segment_paths(session_dir)
    seal_path = session_dir / "seal.json"
    sealed = seal_path.exists()
    expected_segment_numbers = list(range(1, len(paths) + 1))
    actual_segment_numbers = [_segment_number(p) for p in paths]
    if actual_segment_numbers != expected_segment_numbers:
        errors.append(f"segment sequence gap or reorder: {actual_segment_numbers}")

    previous_hash = ZERO_HASH
    expected_seq = 0
    source_sequences: dict[str, int] = {}
    recoverable_tail = False
    recovery_warnings: list[str] = []
    recovery_path = session_dir / "recovery.json"
    if recovery_path.exists():
        try:
            recovery_warnings = list(json.loads(recovery_path.read_text(encoding="utf-8")).get("warnings") or [])
        except Exception:
            errors.append("unreadable recovery marker")

    for path_index, path in enumerate(paths):
        try:
            lines, ended_with_newline = _read_lines_preserve_tail(path)
        except Exception as exc:
            errors.append(f"unreadable segment {path.name}: {type(exc).__name__}: {exc}")
            continue
        nonblank_indexes = [i for i, line in enumerate(lines) if line.strip()]
        last_nonblank = nonblank_indexes[-1] if nonblank_indexes else -1
        for line_index, line in enumerate(lines):
            if not line.strip():
                continue
            is_final_position = path_index == len(paths) - 1 and line_index == last_nonblank
            try:
                record = decode_record(line)
            except Exception as exc:
                location = f"{path.name}:{line_index + 1}"
                previously_marked_tail = any(location in warning for warning in recovery_warnings)
                frame_parts = line.rstrip("\r\n").split("|")
                incomplete_frame = len(frame_parts) < 3 or (len(frame_parts) == 3 and len(frame_parts[2]) < 64)
                may_be_crash_tail = allow_recoverable_tail and (
                    previously_marked_tail
                    or (not sealed and is_final_position and not ended_with_newline and incomplete_frame)
                )
                if may_be_crash_tail:
                    recoverable_tail = True
                    warnings.append(f"preserved recoverable crash tail in {path.name}:{line_index + 1}")
                    continue
                errors.append(f"invalid record {path.name}:{line_index + 1}: {exc}")
                continue
            record["_segment_name"] = path.name
            supplied_seq = record.get("seq")
            if supplied_seq != expected_seq:
                errors.append(f"sequence mismatch at {path.name}:{line_index + 1}: expected {expected_seq}, got {supplied_seq}")
            if record.get("previous_hash") != previous_hash:
                errors.append(f"previous hash mismatch at sequence {supplied_seq}")
            previous_hash = str(record.get("hash") or "")
            expected_seq += 1
            source_sequence = record.get("source_sequence")
            source = str(record.get("source") or "")
            if source_sequence is not None:
                try:
                    current = int(source_sequence)
                except (TypeError, ValueError):
                    errors.append(f"invalid source sequence at sequence {supplied_seq}")
                else:
                    prior = source_sequences.get(source)
                    if prior is not None and current <= prior:
                        errors.append(f"source sequence replay or reorder for {source}: {prior} -> {current}")
                    source_sequences[source] = current
            records.append(record)

    if sealed:
        try:
            seal = json.loads(seal_path.read_text(encoding="utf-8"))
        except Exception as exc:
            errors.append(f"unreadable seal: {exc}")
        else:
            supplied_seal_hash = seal.pop("seal_hash", None)
            expected_seal_hash = hashlib.sha256(canonical_json(seal)).hexdigest()
            if supplied_seal_hash != expected_seal_hash:
                errors.append("seal hash mismatch")
            manifest = seal.get("segments") or []
            manifest_names = [item.get("name") for item in manifest]
            actual_names = [p.name for p in paths]
            if manifest_names != actual_names:
                errors.append("sealed segment order or membership mismatch")
            for item, path in zip(manifest, paths):
                if item.get("sha256") != _sha256_file(path):
                    errors.append(f"sealed segment hash mismatch: {path.name}")
            if seal.get("record_count") != len(records):
                errors.append("seal record count mismatch")
            if seal.get("chain_head") != previous_hash:
                errors.append("seal chain head mismatch")

    result = VerificationResult(
        ok=not errors,
        checked=len(records),
        errors=tuple(errors),
        warnings=tuple(warnings),
        sealed=sealed,
        session_id=session_dir.name if session_dir.exists() else None,
        segment_count=len(paths),
        recoverable_tail=recoverable_tail,
    )
    return records, result


def verify_session(session_dir: Path | str) -> VerificationResult:
    return inspect_session(session_dir)[1]


class SegmentedBlackBoxRecorder:
    """Single append authority for one BlackBox session."""

    def __init__(
        self,
        storage_root: Path | str,
        session_id: str,
        *,
        checkpoint_every_events: int = 64,
        max_records_per_segment: int = 512,
        fsync: bool = True,
    ) -> None:
        if checkpoint_every_events <= 0 or max_records_per_segment <= 0:
            raise ValueError("checkpoint and segment limits must be positive")
        self.storage_root = Path(storage_root).expanduser().resolve()
        self.session_id = _validate_storage_id("session_id", session_id)
        sessions_root = self.storage_root / "sessions"
        sessions_root.mkdir(parents=True, exist_ok=True)
        if sessions_root.is_symlink():
            raise RecordValidationError("sessions root cannot be a symlink")
        sessions_root = sessions_root.resolve()
        proposed_session_dir = sessions_root / self.session_id
        if proposed_session_dir.is_symlink():
            raise RecordValidationError("session directory cannot be a symlink")
        proposed_session_dir.mkdir(parents=False, exist_ok=True)
        self.session_dir = _ensure_within(sessions_root, proposed_session_dir, label="session directory")
        if self.session_dir.parent != sessions_root:
            raise RecordValidationError("session directory must be one storage component")
        self.segment_dir = self.session_dir / "segments"
        self.checkpoint_dir = self.session_dir / "checkpoints"
        self.state_path = self.session_dir / "active_state.json"
        self.seal_path = self.session_dir / "seal.json"
        self.recovery_path = self.session_dir / "recovery.json"
        self.lock_path = self.session_dir / ".append.lock"
        self.segment_dir.mkdir(parents=True, exist_ok=True)
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)
        for label, directory in (("segment directory", self.segment_dir), ("checkpoint directory", self.checkpoint_dir)):
            if directory.is_symlink():
                raise RecordValidationError(f"{label} cannot be a symlink")
            _ensure_within(self.session_dir, directory, label=label)
        self.checkpoint_every_events = checkpoint_every_events
        self.max_records_per_segment = max_records_per_segment
        self.fsync = fsync
        self._thread_lock = threading.RLock()
        self._sequence = 0
        self._previous_hash = ZERO_HASH
        self._segment_no = 1
        self._segment_record_count = 0
        self._last_success_at: str | None = None
        self._operation_index: dict[str, tuple[str, AppendReceipt]] = {}
        with self._thread_lock, _file_lock(self.lock_path):
            self._restore()

    @property
    def next_sequence(self) -> int:
        return self._sequence

    @property
    def previous_hash(self) -> str:
        return self._previous_hash

    def _restore(self) -> None:
        """Reload authoritative state from verified canonical segments.

        Callers that can race with another process must hold ``_file_lock``.
        ``active_state.json`` is deliberately ignored because it is a derived
        cache, not an evidence authority.
        """
        self._operation_index = {}
        records, verification = inspect_session(self.session_dir)
        if verification.sealed:
            self._sequence = len(records)
            self._previous_hash = str(records[-1]["hash"]) if records else ZERO_HASH
            self._last_success_at = str(records[-1].get("observed_at")) if records else None
            return
        if not verification.ok:
            raise RecorderIntegrityError("existing BlackBox session failed verification: " + "; ".join(verification.errors))
        self._sequence = len(records)
        self._previous_hash = str(records[-1]["hash"]) if records else ZERO_HASH
        self._last_success_at = str(records[-1].get("observed_at")) if records else None
        for record in records:
            operation_id = record.get("operation_id")
            if operation_id:
                receipt = AppendReceipt(
                    record_id=str(record["record_id"]),
                    sequence=int(record["seq"]),
                    event_hash=str(record["hash"]),
                    previous_hash=str(record["previous_hash"]),
                    accepted_at=str(record["observed_at"]),
                    segment=int(record.get("segment", 0) or 0),
                    duplicate=True,
                )
                self._operation_index[str(operation_id)] = (str(record.get("semantic_fingerprint") or ""), receipt)
        paths = _segment_paths(self.session_dir)
        if not paths:
            self._segment_no = 1
            self._segment_record_count = 0
        else:
            last = paths[-1]
            last_no = _segment_number(last)
            valid_last_count = sum(1 for record in records if record.get("_segment_name") == last.name)
            if verification.recoverable_tail or valid_last_count >= self.max_records_per_segment:
                self._segment_no = last_no + 1
                self._segment_record_count = 0
            else:
                self._segment_no = last_no
                try:
                    lines, _ = _read_lines_preserve_tail(last)
                    self._segment_record_count = sum(1 for line in lines if line.strip())
                except Exception:
                    self._segment_no = last_no + 1
                    self._segment_record_count = 0
        if verification.recoverable_tail:
            _atomic_json(
                self.recovery_path,
                {
                    "status": "crash_tail_preserved",
                    "observed_at": utc_now(),
                    "previous_valid_sequence": self._sequence - 1,
                    "next_segment": self._segment_no,
                    "warnings": list(verification.warnings),
                },
            )
        self._write_state()

    def _write_state(self) -> None:
        _atomic_json(
            self.state_path,
            {
                "version": 1,
                "session_id": self.session_id,
                "next_sequence": self._sequence,
                "chain_head": self._previous_hash,
                "active_segment": self._segment_no,
                "active_segment_records": self._segment_record_count,
                "last_success_at": self._last_success_at,
                "sealed": self.seal_path.exists(),
            },
        )

    def _active_segment_path(self) -> Path:
        return self.segment_dir / f"segment_{self._segment_no:06d}.bbx"

    def _rotate_if_needed(self) -> None:
        if self._segment_record_count >= self.max_records_per_segment:
            self._segment_no += 1
            self._segment_record_count = 0

    def append(self, event: EvidenceEvent, *, expected_previous_hash: str | None = None) -> AppendReceipt:
        with self._thread_lock, _file_lock(self.lock_path):
            self._restore()
            if self.seal_path.exists():
                raise RecorderSealedError("BlackBox session is sealed")
            if event.session_id and event.session_id != self.session_id:
                raise RecordValidationError("event session_id does not match recorder session")
            if expected_previous_hash is not None and expected_previous_hash != self._previous_hash:
                raise RecorderIntegrityError("expected previous hash does not match current chain head")
            if event.operation_id and event.operation_id in self._operation_index:
                prior_fingerprint, prior_receipt = self._operation_index[event.operation_id]
                if prior_fingerprint != event.semantic_fingerprint():
                    raise RecorderIntegrityError("operation_id was reused for a different fact")
                return AppendReceipt(**{**prior_receipt.to_dict(), "duplicate": True})

            self._rotate_if_needed()
            body = _record_body(event, sequence=self._sequence, previous_hash=self._previous_hash)
            body["segment"] = self._segment_no
            line = encode_record(body) + "\n"
            path = self._active_segment_path()
            with path.open("ab") as handle:
                handle.write(line.encode("utf-8"))
                handle.flush()
                if self.fsync:
                    os.fsync(handle.fileno())
            decoded = decode_record(line)
            accepted_at = utc_now()
            receipt = AppendReceipt(
                record_id=event.event_id,
                sequence=self._sequence,
                event_hash=str(decoded["hash"]),
                previous_hash=self._previous_hash,
                accepted_at=accepted_at,
                segment=self._segment_no,
            )
            self._sequence += 1
            self._previous_hash = receipt.event_hash
            self._segment_record_count += 1
            self._last_success_at = accepted_at
            if event.operation_id:
                self._operation_index[event.operation_id] = (event.semantic_fingerprint(), receipt)
            if self._sequence % self.checkpoint_every_events == 0:
                checkpoint_id = self._checkpoint_locked()
                receipt = AppendReceipt(**{**receipt.to_dict(), "checkpoint_id": checkpoint_id})
            self._write_state()
            return receipt

    def _checkpoint_locked(self) -> str:
        checkpoint_id = f"checkpoint_{self._sequence:012d}_{uuid4().hex}"
        segments = [
            {"name": path.name, "sha256": _sha256_file(path), "size": path.stat().st_size}
            for path in _segment_paths(self.session_dir)
        ]
        payload = {
            "version": 1,
            "checkpoint_id": checkpoint_id,
            "session_id": self.session_id,
            "created_at": utc_now(),
            "record_count": self._sequence,
            "chain_head": self._previous_hash,
            "segments": segments,
        }
        payload["checkpoint_hash"] = hashlib.sha256(canonical_json(payload)).hexdigest()
        try:
            _exclusive_json(self.checkpoint_dir / f"{checkpoint_id}.json", payload)
        except FileExistsError as exc:
            raise RecorderIntegrityError("checkpoint identifier collision") from exc
        return checkpoint_id

    def checkpoint(self) -> str:
        with self._thread_lock, _file_lock(self.lock_path):
            self._restore()
            if self.seal_path.exists():
                raise RecorderSealedError("sealed BlackBox session cannot create a new checkpoint")
            return self._checkpoint_locked()

    def seal(self, reason: str = "manual") -> Path:
        with self._thread_lock, _file_lock(self.lock_path):
            self._restore()
            if self.seal_path.exists():
                verification = verify_session(self.session_dir)
                if not verification.ok:
                    raise RecorderIntegrityError("existing BlackBox seal is invalid: " + "; ".join(verification.errors))
                return self.seal_path
            verification = verify_session(self.session_dir)
            if not verification.ok:
                raise RecorderIntegrityError("cannot seal an invalid session: " + "; ".join(verification.errors))
            checkpoint_id = self._checkpoint_locked()
            segments = [
                {"name": path.name, "sha256": _sha256_file(path), "size": path.stat().st_size}
                for path in _segment_paths(self.session_dir)
            ]
            payload: dict[str, Any] = {
                "version": 1,
                "session_id": self.session_id,
                "sealed_at": utc_now(),
                "reason": reason,
                "record_count": self._sequence,
                "chain_head": self._previous_hash,
                "checkpoint_id": checkpoint_id,
                "segments": segments,
                "recovery_marker_present": self.recovery_path.exists(),
            }
            payload["seal_hash"] = hashlib.sha256(canonical_json(payload)).hexdigest()
            try:
                _exclusive_json(self.seal_path, payload)
            except FileExistsError as exc:
                raise RecorderIntegrityError("seal appeared during exclusive creation") from exc
            self._write_state()
            return self.seal_path

    def verify(self) -> VerificationResult:
        return verify_session(self.session_dir)

    def iter_records(self) -> Iterable[dict[str, Any]]:
        records, result = inspect_session(self.session_dir)
        if not result.ok:
            raise RecorderIntegrityError("cannot read invalid session: " + "; ".join(result.errors))
        return tuple(records)

    def health(self) -> RecorderHealth:
        verification = self.verify()
        if self.seal_path.exists():
            state = RecorderState.SEALED
        elif verification.ok and verification.recoverable_tail:
            state = RecorderState.DEGRADED
        elif verification.ok:
            state = RecorderState.HEALTHY
        else:
            state = RecorderState.UNAVAILABLE
        return RecorderHealth(
            state=state,
            session_id=self.session_id,
            sequence=self._sequence,
            last_record_hash=self._previous_hash,
            last_success_at=self._last_success_at,
            details={
                "segment_count": verification.segment_count,
                "verified": verification.ok,
                "recoverable_tail": verification.recoverable_tail,
            },
        )
