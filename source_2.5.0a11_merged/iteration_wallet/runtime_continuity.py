"""Static Runtime Continuity observations for active programs outside Wallet.

Runtime Continuity does not execute, import, repair, restore, promote, or mutate
an observed program. It records bounded static observations and classifies
changes against explicit policy and evidence verified by an authority resolver.
Unknown, unreadable, unstable, or merely asserted facts remain inconclusive;
they are never promoted into reassuring guesses.
"""
from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import re
import stat
import unicodedata
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterable, Mapping

from .durable_io import DurableIOError, exclusive_json, strict_json_read


_SNAPSHOT_FORMAT_VERSION = 2
_POLICY_VERSION = "runtime-continuity-v2"
_HEX_64 = re.compile(r"^[0-9a-f]{64}$")
_ROOT_LABEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@+\- /]{0,191}$")
_ALLOWED_KINDS = {
    "file",
    "symlink_directory",
    "symlink_file",
    "special",
    "unknown",
    "unreadable_directory",
}
_ALLOWED_EVIDENCE_KINDS = {
    "authorized_configuration": {"human_intent_receipt", "configuration_authorization"},
    "verified_update": {"verified_update_receipt", "vendor_update_attestation"},
    "approved_exception": {"human_intent_receipt", "approved_exception"},
}


class RuntimeContinuityError(Exception):
    """Raised when a static continuity observation cannot be represented safely."""


class ObservationMode(str, Enum):
    DIRECT_STATIC = "direct_static"
    IMPORTED = "imported"
    EXTERNAL_ASSERTED = "external_asserted"


class DivergenceCategory(str, Enum):
    UNCHANGED = "unchanged"
    DISPOSABLE = "disposable"
    EXPECTED_MUTABLE = "expected_mutable"
    AUTHORIZED_CONFIGURATION = "authorized_configuration"
    VERIFIED_UPDATE = "verified_update"
    APPROVED_EXCEPTION = "approved_exception"
    UNEXPLAINED = "unexplained"
    PROHIBITED = "prohibited"
    UNVERIFIABLE = "unverifiable"
    UNSTABLE_OBSERVATION = "unstable_observation"


class Severity(str, Enum):
    INFO = "info"
    REVIEW = "review"
    HIGH = "high"
    CRITICAL = "critical"


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _validate_timestamp(value: str, *, label: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise RuntimeContinuityError(f"{label} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise RuntimeContinuityError(f"{label} must include a timezone")
    return value


def _validate_root_label(value: str) -> str:
    if not isinstance(value, str) or not _ROOT_LABEL.fullmatch(value):
        raise RuntimeContinuityError("root_label must be a portable bounded identifier")
    return value


def _validate_relative_path(value: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 4096:
        raise RuntimeContinuityError("snapshot relative path is missing or unbounded")
    if "\x00" in value or "\\" in value or any(ord(ch) < 32 for ch in value):
        raise RuntimeContinuityError(f"snapshot path is not portable: {value!r}")
    value = unicodedata.normalize("NFC", value)
    pure = PurePosixPath(value)
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        raise RuntimeContinuityError(f"snapshot path is not a normalized relative path: {value!r}")
    normalized = pure.as_posix()
    if normalized != value:
        raise RuntimeContinuityError(f"snapshot path is not canonical: {value!r}")
    return value


def _validate_sha256(value: str | None, *, label: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not _HEX_64.fullmatch(value):
        raise RuntimeContinuityError(f"{label} must be a lowercase SHA-256 digest")
    return value


def _portable_relative(path: Path, root: Path) -> str:
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise RuntimeContinuityError("observed path escaped the declared root") from exc
    return _validate_relative_path(relative.as_posix())


def _hash_file_stably(path: Path, *, chunk_size: int = 1024 * 1024) -> tuple[str | None, str | None]:
    """Hash one stable regular file without following links or blocking on FIFOs."""
    descriptor: int | None = None
    try:
        path_before = path.stat(follow_symlinks=False)
        flags = os.O_RDONLY
        for name in ("O_CLOEXEC", "O_NOFOLLOW", "O_NONBLOCK"):
            flags |= int(getattr(os, name, 0))
        descriptor = os.open(path, flags)
        before = os.fstat(descriptor)
        if not stat.S_ISREG(path_before.st_mode) or not stat.S_ISREG(before.st_mode):
            return None, "unverifiable:non_regular_file"
        path_identity = (
            path_before.st_dev,
            path_before.st_ino,
            path_before.st_size,
            path_before.st_mtime_ns,
            path_before.st_ctime_ns,
            path_before.st_mode,
            path_before.st_nlink,
        )
        descriptor_identity = (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
            before.st_mode,
            before.st_nlink,
        )
        if path_identity != descriptor_identity:
            return None, "unstable_observation:file_identity_changed_before_read"
        digest = hashlib.sha256()
        while True:
            chunk = os.read(descriptor, chunk_size)
            if not chunk:
                break
            digest.update(chunk)
        after = os.fstat(descriptor)
    except OSError as exc:
        return None, f"unreadable:{type(exc).__name__}"
    finally:
        if descriptor is not None:
            os.close(descriptor)
    stable_fields_before = (
        before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns,
        before.st_ctime_ns, before.st_mode, before.st_nlink,
    )
    stable_fields_after = (
        after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns,
        after.st_ctime_ns, after.st_mode, after.st_nlink,
    )
    if stable_fields_before != stable_fields_after:
        return None, "unstable_observation:file_changed_during_read"
    return digest.hexdigest(), None


@dataclass(frozen=True, slots=True)
class SnapshotEntry:
    relative_path: str
    kind: str
    size: int | None
    sha256: str | None
    mode: int | None
    readable: bool
    observation: str = "observed"

    def __post_init__(self) -> None:
        _validate_relative_path(self.relative_path)
        if self.kind not in _ALLOWED_KINDS:
            raise RuntimeContinuityError(f"unsupported snapshot entry kind: {self.kind}")
        if self.size is not None and (not isinstance(self.size, int) or self.size < 0):
            raise RuntimeContinuityError("snapshot entry size must be a non-negative integer")
        _validate_sha256(self.sha256, label="snapshot entry sha256")
        if self.mode is not None and (not isinstance(self.mode, int) or not 0 <= self.mode <= 0o7777):
            raise RuntimeContinuityError("snapshot entry mode is outside the portable permission range")
        if not isinstance(self.observation, str) or not self.observation or len(self.observation) > 256:
            raise RuntimeContinuityError("snapshot observation label is invalid")
        if self.readable:
            if self.kind != "file" or self.sha256 is None or self.observation != "observed":
                raise RuntimeContinuityError("readable snapshot entries require an observed regular-file digest")
        elif self.sha256 is not None:
            raise RuntimeContinuityError("unreadable snapshot entries cannot claim a digest")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SnapshotEntry":
        if not isinstance(data, Mapping):
            raise RuntimeContinuityError("snapshot entry must be an object")
        relative_path = data.get("relative_path")
        kind = data.get("kind")
        readable = data.get("readable")
        observation = data.get("observation", "observed")
        if not isinstance(relative_path, str):
            raise RuntimeContinuityError("snapshot entry relative_path must be a string")
        if not isinstance(kind, str):
            raise RuntimeContinuityError("snapshot entry kind must be a string")
        if not isinstance(readable, bool):
            raise RuntimeContinuityError("snapshot entry readable must be a boolean")
        if not isinstance(observation, str):
            raise RuntimeContinuityError("snapshot entry observation must be a string")
        size = data.get("size")
        mode = data.get("mode")
        if size is not None and (not isinstance(size, int) or isinstance(size, bool)):
            raise RuntimeContinuityError("snapshot entry size must be an integer or null")
        if mode is not None and (not isinstance(mode, int) or isinstance(mode, bool)):
            raise RuntimeContinuityError("snapshot entry mode must be an integer or null")
        sha256 = data.get("sha256")
        if sha256 is not None and not isinstance(sha256, str):
            raise RuntimeContinuityError("snapshot entry sha256 must be a string or null")
        return cls(
            relative_path=relative_path,
            kind=kind,
            size=size,
            sha256=sha256,
            mode=mode,
            readable=readable,
            observation=observation,
        )


@dataclass(frozen=True, slots=True)
class RuntimeSnapshot:
    snapshot_id: str
    root_label: str
    captured_at: str
    observation_mode: ObservationMode
    entries: tuple[SnapshotEntry, ...]
    attempted_entries: int
    hashed_files: int
    unreadable_entries: int
    unstable_entries: int
    warnings: tuple[str, ...] = ()
    previous_snapshot_id: str | None = None
    policy_version: str = _POLICY_VERSION
    format_version: int = _SNAPSHOT_FORMAT_VERSION

    def __post_init__(self) -> None:
        if self.format_version != _SNAPSHOT_FORMAT_VERSION:
            raise RuntimeContinuityError(
                f"unsupported Runtime Continuity snapshot format {self.format_version}; migrate explicitly"
            )
        _validate_sha256(self.snapshot_id, label="snapshot_id")
        _validate_root_label(self.root_label)
        _validate_timestamp(self.captured_at, label="captured_at")
        if not isinstance(self.observation_mode, ObservationMode):
            raise RuntimeContinuityError("snapshot observation_mode must be an ObservationMode")
        if self.previous_snapshot_id is not None:
            _validate_sha256(self.previous_snapshot_id, label="previous_snapshot_id")
            if self.previous_snapshot_id == self.snapshot_id:
                raise RuntimeContinuityError("snapshot cannot cite itself as its previous snapshot")
        if not isinstance(self.policy_version, str) or not self.policy_version or len(self.policy_version) > 128:
            raise RuntimeContinuityError("policy_version is invalid")
        paths = [entry.relative_path for entry in self.entries]
        if paths != sorted(paths) or len(paths) != len(set(paths)):
            raise RuntimeContinuityError("snapshot entries must be uniquely sorted by relative path")
        if self.attempted_entries != len(self.entries):
            raise RuntimeContinuityError("attempted_entries does not match the represented entry count")
        actual_hashed = sum(1 for entry in self.entries if entry.readable and entry.sha256 is not None)
        actual_unreadable = sum(
            1
            for entry in self.entries
            if not entry.readable and not entry.observation.startswith("unstable_observation")
        )
        actual_unstable = sum(
            1 for entry in self.entries if entry.observation.startswith("unstable_observation")
        )
        if (self.hashed_files, self.unreadable_entries, self.unstable_entries) != (
            actual_hashed,
            actual_unreadable,
            actual_unstable,
        ):
            raise RuntimeContinuityError("snapshot coverage counters do not match represented entries")
        for warning in self.warnings:
            if not isinstance(warning, str) or not warning or len(warning) > 4608:
                raise RuntimeContinuityError("snapshot warning is invalid")
        if tuple(sorted(set(self.warnings))) != self.warnings:
            raise RuntimeContinuityError("snapshot warnings must be unique and sorted")
        expected = _snapshot_identity(self.identity_payload())
        if self.snapshot_id != expected:
            raise RuntimeContinuityError("snapshot identity does not match its complete represented content")

    @property
    def coverage(self) -> float:
        if self.attempted_entries == 0:
            return 1.0
        conclusive = self.attempted_entries - self.unreadable_entries - self.unstable_entries
        return max(0.0, min(1.0, conclusive / self.attempted_entries))

    def identity_payload(self) -> dict[str, Any]:
        return {
            "format_version": self.format_version,
            "root_label": self.root_label,
            "captured_at": self.captured_at,
            "observation_mode": self.observation_mode.value,
            "entries": [entry.to_dict() for entry in self.entries],
            "attempted_entries": self.attempted_entries,
            "hashed_files": self.hashed_files,
            "unreadable_entries": self.unreadable_entries,
            "unstable_entries": self.unstable_entries,
            "warnings": list(self.warnings),
            "previous_snapshot_id": self.previous_snapshot_id,
            "policy_version": self.policy_version,
        }

    def to_dict(self) -> dict[str, Any]:
        return {"snapshot_id": self.snapshot_id, **self.identity_payload(), "coverage": self.coverage}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RuntimeSnapshot":
        if not isinstance(data, Mapping):
            raise RuntimeContinuityError("snapshot payload must be an object")
        format_version = data.get("format_version", 1)
        if not isinstance(format_version, int) or isinstance(format_version, bool):
            raise RuntimeContinuityError("snapshot format_version must be an integer")
        if format_version != _SNAPSHOT_FORMAT_VERSION:
            raise RuntimeContinuityError(
                "legacy Runtime Continuity snapshots are not silently trusted; explicit migration is required"
            )
        raw_mode = data.get("observation_mode")
        if not isinstance(raw_mode, str):
            raise RuntimeContinuityError("snapshot observation_mode must be a string")
        try:
            observation_mode = ObservationMode(raw_mode)
        except ValueError as exc:
            raise RuntimeContinuityError("snapshot observation_mode is invalid") from exc
        entries = data.get("entries")
        warnings = data.get("warnings")
        if not isinstance(entries, list):
            raise RuntimeContinuityError("snapshot entries must be an array")
        if not isinstance(warnings, list) or not all(isinstance(item, str) for item in warnings):
            raise RuntimeContinuityError("snapshot warnings must be an array of strings")
        integers: dict[str, int] = {}
        for field in ("attempted_entries", "hashed_files", "unreadable_entries", "unstable_entries"):
            value = data.get(field)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise RuntimeContinuityError(f"snapshot {field} must be a non-negative integer")
            integers[field] = value
        for field in ("snapshot_id", "root_label", "captured_at"):
            if not isinstance(data.get(field), str):
                raise RuntimeContinuityError(f"snapshot {field} must be a string")
        previous = data.get("previous_snapshot_id")
        if previous is not None and not isinstance(previous, str):
            raise RuntimeContinuityError("snapshot previous_snapshot_id must be a string or null")
        policy_version = data.get("policy_version", _POLICY_VERSION)
        if not isinstance(policy_version, str):
            raise RuntimeContinuityError("snapshot policy_version must be a string")
        return cls(
            snapshot_id=data["snapshot_id"],
            root_label=data["root_label"],
            captured_at=data["captured_at"],
            observation_mode=observation_mode,
            entries=tuple(SnapshotEntry.from_dict(item) for item in entries),
            attempted_entries=integers["attempted_entries"],
            hashed_files=integers["hashed_files"],
            unreadable_entries=integers["unreadable_entries"],
            unstable_entries=integers["unstable_entries"],
            warnings=tuple(warnings),
            previous_snapshot_id=previous,
            policy_version=policy_version,
            format_version=format_version,
        )


@dataclass(frozen=True, slots=True)
class ContinuityPolicy:
    version: str = _POLICY_VERSION
    disposable_patterns: tuple[str, ...] = (
        "**/__pycache__/**",
        "**/*.pyc",
        "**/.pytest_cache/**",
        "**/*.log",
        "**/*.tmp",
        "**/cache/**",
    )
    expected_mutable_patterns: tuple[str, ...] = (
        "**/runtime_state/**",
        "**/state/**",
        "**/logs/**",
    )
    prohibited_patterns: tuple[str, ...] = ()
    protected_patterns: tuple[str, ...] = (
        "**/gatekeeper.py",
        "**/ceremony.py",
        "**/blackbox.py",
        "**/canonical_evidence.py",
        "**/promotion_transaction.py",
        "**/server.py",
        "**/*.service",
        "**/*.socket",
    )

    def __post_init__(self) -> None:
        if not self.version or len(self.version) > 128:
            raise RuntimeContinuityError("continuity policy version is invalid")
        for family in (
            self.disposable_patterns,
            self.expected_mutable_patterns,
            self.prohibited_patterns,
            self.protected_patterns,
        ):
            for pattern in family:
                if not isinstance(pattern, str) or not pattern or "\x00" in pattern or len(pattern) > 1024:
                    raise RuntimeContinuityError("continuity policy contains an invalid path pattern")

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "disposable_patterns": list(self.disposable_patterns),
            "expected_mutable_patterns": list(self.expected_mutable_patterns),
            "prohibited_patterns": list(self.prohibited_patterns),
            "protected_patterns": list(self.protected_patterns),
        }


@dataclass(frozen=True, slots=True)
class EvidenceVerification:
    """Result returned by the authority that actually owns an evidence record."""

    evidence_id: str
    verified: bool
    authority: str
    evidence_kind: str
    subject_path: str | None = None
    detail: str = ""

    def __post_init__(self) -> None:
        for label, value, maximum in (
            ("evidence_id", self.evidence_id, 512),
            ("authority", self.authority, 128),
            ("evidence_kind", self.evidence_kind, 128),
            ("detail", self.detail, 1024),
        ):
            if not isinstance(value, str) or len(value) > maximum or any(ord(ch) < 32 for ch in value):
                raise RuntimeContinuityError(f"evidence verification {label} is invalid")
        if not isinstance(self.verified, bool):
            raise RuntimeContinuityError("evidence verification verified must be a boolean")
        if self.subject_path is not None:
            _validate_relative_path(self.subject_path)

    @classmethod
    def from_value(cls, value: "EvidenceVerification | Mapping[str, Any]") -> "EvidenceVerification":
        if isinstance(value, cls):
            return value
        if not isinstance(value, Mapping):
            raise RuntimeContinuityError("evidence resolver returned an unsupported value")
        required_strings = {}
        for field in ("evidence_id", "authority", "evidence_kind"):
            item = value.get(field)
            if not isinstance(item, str):
                raise RuntimeContinuityError(f"evidence resolver field {field} must be a string")
            required_strings[field] = item
        verified = value.get("verified")
        if not isinstance(verified, bool):
            raise RuntimeContinuityError("evidence resolver field verified must be a boolean")
        subject = value.get("subject_path")
        if subject is not None and not isinstance(subject, str):
            raise RuntimeContinuityError("evidence resolver field subject_path must be a string or null")
        detail = value.get("detail", "")
        if not isinstance(detail, str):
            raise RuntimeContinuityError("evidence resolver field detail must be a string")
        return cls(
            evidence_id=required_strings["evidence_id"],
            verified=verified,
            authority=required_strings["authority"],
            evidence_kind=required_strings["evidence_kind"],
            subject_path=subject,
            detail=detail,
        )


EvidenceResolver = Callable[[str], EvidenceVerification | Mapping[str, Any]]


@dataclass(frozen=True, slots=True)
class DivergenceFinding:
    relative_path: str
    change: str
    category: DivergenceCategory
    severity: Severity
    evidence_id: str | None
    evidence_verified: bool
    evidence_authority: str | None
    evidence_kind: str | None
    evidence_limitation: str | None
    basis: str
    reference_sha256: str | None
    observed_sha256: str | None

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["category"] = self.category.value
        result["severity"] = self.severity.value
        return result


@dataclass(frozen=True, slots=True)
class DivergenceAssessment:
    assessment_id: str
    reference_snapshot_id: str
    observed_snapshot_id: str
    root_label: str
    policy_version: str
    created_at: str
    findings: tuple[DivergenceFinding, ...]
    coverage: float
    confidence: str
    limitations: tuple[str, ...]

    @property
    def unexplained_count(self) -> int:
        return sum(item.category is DivergenceCategory.UNEXPLAINED for item in self.findings)

    @property
    def prohibited_count(self) -> int:
        return sum(item.category is DivergenceCategory.PROHIBITED for item in self.findings)

    def to_dict(self) -> dict[str, Any]:
        counts: dict[str, int] = {category.value: 0 for category in DivergenceCategory}
        for item in self.findings:
            counts[item.category.value] += 1
        return {
            "assessment_id": self.assessment_id,
            "reference_snapshot_id": self.reference_snapshot_id,
            "observed_snapshot_id": self.observed_snapshot_id,
            "root_label": self.root_label,
            "policy_version": self.policy_version,
            "created_at": self.created_at,
            "findings": [item.to_dict() for item in self.findings],
            "counts": counts,
            "coverage": self.coverage,
            "confidence": self.confidence,
            "limitations": list(self.limitations),
            "custody_decision_made": False,
            "repair_attempted": False,
            "trust_inferred": False,
        }


def _snapshot_identity(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8", errors="strict")
    return hashlib.sha256(encoded).hexdigest()


def capture_snapshot(
    root: Path | str,
    *,
    root_label: str,
    previous_snapshot_id: str | None = None,
    observation_mode: ObservationMode = ObservationMode.DIRECT_STATIC,
    policy_version: str = _POLICY_VERSION,
) -> RuntimeSnapshot:
    """Capture a byte-oriented static observation without activating targets."""
    root_label = _validate_root_label(root_label)
    if previous_snapshot_id is not None:
        _validate_sha256(previous_snapshot_id, label="previous_snapshot_id")
    declared = Path(root).expanduser()
    if declared.is_symlink():
        raise RuntimeContinuityError("observation root cannot be a symlink")
    try:
        resolved = declared.resolve(strict=True)
    except OSError as exc:
        raise RuntimeContinuityError(f"observation root is unavailable: {exc}") from exc
    if not resolved.is_dir():
        raise RuntimeContinuityError("observation root must be a directory")

    entries_by_path: dict[str, SnapshotEntry] = {}
    warnings: set[str] = set()

    def store_entry(entry: SnapshotEntry) -> None:
        existing = entries_by_path.get(entry.relative_path)
        if existing is not None and existing != entry:
            raise RuntimeContinuityError(
                f"multiple observed paths collide after portable Unicode normalization: {entry.relative_path}"
            )
        entries_by_path[entry.relative_path] = entry

    def add_special(path: Path, kind: str, observation: str) -> None:
        try:
            relative = _portable_relative(path, resolved)
        except RuntimeContinuityError:
            relative = f"__unmapped__/{hashlib.sha256(str(path).encode('utf-8', errors='replace')).hexdigest()[:24]}"
        try:
            info = path.lstat()
            mode = stat.S_IMODE(info.st_mode)
            size = info.st_size
        except OSError:
            mode = None
            size = None
        store_entry(
            SnapshotEntry(
                relative_path=relative,
                kind=kind,
                size=size,
                sha256=None,
                mode=mode,
                readable=False,
                observation=observation,
            )
        )
        warnings.add(f"{relative}:{observation}")

    def walk_error(exc: OSError) -> None:
        raw = getattr(exc, "filename", None)
        path = Path(raw) if raw else resolved / "__unknown_walk_error__"
        add_special(path, "unreadable_directory", f"unverifiable:walk:{type(exc).__name__}")

    for current_root, directory_names, file_names in os.walk(
        resolved,
        topdown=True,
        followlinks=False,
        onerror=walk_error,
    ):
        current = Path(current_root)
        safe_directories: list[str] = []
        for name in sorted(directory_names):
            path = current / name
            if path.is_symlink():
                add_special(path, "symlink_directory", "unverifiable:symlink_not_followed")
            else:
                safe_directories.append(name)
        directory_names[:] = safe_directories

        for name in sorted(file_names):
            path = current / name
            relative = _portable_relative(path, resolved)
            if path.is_symlink():
                add_special(path, "symlink_file", "unverifiable:symlink_not_followed")
                continue
            try:
                info = path.stat(follow_symlinks=False)
            except OSError as exc:
                add_special(path, "unknown", f"unverifiable:{type(exc).__name__}")
                continue
            if not stat.S_ISREG(info.st_mode):
                add_special(path, "special", "unverifiable:non_regular_file")
                continue
            digest, limitation = _hash_file_stably(path)
            readable = limitation is None
            observation = "observed" if limitation is None else limitation
            if limitation is not None:
                warnings.add(f"{relative}:{limitation}")
            store_entry(
                SnapshotEntry(
                    relative_path=relative,
                    kind="file",
                    size=info.st_size,
                    sha256=digest,
                    mode=stat.S_IMODE(info.st_mode),
                    readable=readable,
                    observation=observation,
                )
            )

    entries = tuple(sorted(entries_by_path.values(), key=lambda item: item.relative_path))
    hashed_files = sum(1 for entry in entries if entry.readable and entry.sha256 is not None)
    unreadable = sum(
        1
        for entry in entries
        if not entry.readable and not entry.observation.startswith("unstable_observation")
    )
    unstable = sum(1 for entry in entries if entry.observation.startswith("unstable_observation"))
    captured_at = _utc_now()
    warnings_tuple = tuple(sorted(warnings))
    identity_payload = {
        "format_version": _SNAPSHOT_FORMAT_VERSION,
        "root_label": root_label,
        "captured_at": captured_at,
        "observation_mode": observation_mode.value,
        "entries": [entry.to_dict() for entry in entries],
        "attempted_entries": len(entries),
        "hashed_files": hashed_files,
        "unreadable_entries": unreadable,
        "unstable_entries": unstable,
        "warnings": list(warnings_tuple),
        "previous_snapshot_id": previous_snapshot_id,
        "policy_version": policy_version,
    }
    return RuntimeSnapshot(
        snapshot_id=_snapshot_identity(identity_payload),
        root_label=root_label,
        captured_at=captured_at,
        observation_mode=observation_mode,
        entries=entries,
        attempted_entries=len(entries),
        hashed_files=hashed_files,
        unreadable_entries=unreadable,
        unstable_entries=unstable,
        warnings=warnings_tuple,
        previous_snapshot_id=previous_snapshot_id,
        policy_version=policy_version,
        format_version=_SNAPSHOT_FORMAT_VERSION,
    )


def save_snapshot(snapshot: RuntimeSnapshot, path: Path | str) -> Path:
    """Persist a validated snapshot exactly once; an existing record is never replaced."""
    # Reconstructing validates counters and the complete identity before storage.
    RuntimeSnapshot.from_dict(snapshot.to_dict())
    target = Path(path)
    try:
        exclusive_json(target, snapshot.to_dict())
    except FileExistsError:
        raise RuntimeContinuityError("snapshot destination already exists; silent overwrite is forbidden")
    except (OSError, DurableIOError) as exc:
        raise RuntimeContinuityError(f"snapshot could not be persisted: {exc}") from exc
    return target


def load_snapshot(path: Path | str) -> RuntimeSnapshot:
    try:
        payload = strict_json_read(Path(path))
    except DurableIOError as exc:
        raise RuntimeContinuityError(str(exc)) from exc
    if not isinstance(payload, Mapping):
        raise RuntimeContinuityError("snapshot payload must be an object")
    return RuntimeSnapshot.from_dict(payload)


def _matches(path: str, patterns: Iterable[str], *, security_sensitive: bool = False) -> bool:
    normalized_path = unicodedata.normalize("NFC", path)
    for supplied_pattern in patterns:
        pattern = unicodedata.normalize("NFC", supplied_pattern)
        candidates = (pattern, pattern[3:]) if pattern.startswith("**/") else (pattern,)
        for candidate in candidates:
            if fnmatch.fnmatchcase(normalized_path, candidate):
                return True
            # Security policies must not be downgraded by case variation on a
            # case-insensitive host or after a cross-platform project move.
            if security_sensitive and fnmatch.fnmatchcase(
                normalized_path.casefold(), candidate.casefold()
            ):
                return True
    return False


_DANGEROUS_MODE_BITS = stat.S_ISUID | stat.S_ISGID


def _gained_dangerous_mode_bits(
    prior: SnapshotEntry | None, current: SnapshotEntry | None
) -> bool:
    if current is None or current.mode is None:
        return False
    current_bits = current.mode & _DANGEROUS_MODE_BITS
    if not current_bits:
        return False
    prior_bits = 0 if prior is None or prior.mode is None else prior.mode & _DANGEROUS_MODE_BITS
    return current_bits != prior_bits


def _change(reference: SnapshotEntry | None, observed: SnapshotEntry | None) -> str:
    if reference is None:
        return "added"
    if observed is None:
        return "missing"
    if (
        reference.sha256 == observed.sha256
        and reference.mode == observed.mode
        and reference.kind == observed.kind
        and reference.observation == observed.observation
        and reference.size == observed.size
    ):
        return "unchanged"
    if reference.sha256 != observed.sha256 or reference.size != observed.size:
        return "content_changed"
    if reference.mode != observed.mode:
        return "permissions_changed"
    return "observation_changed"


def _evidence_for(path: str, evidence: Mapping[str, str]) -> str | None:
    normalized_path = unicodedata.normalize("NFC", path)
    matches = [
        value
        for key, value in evidence.items()
        if isinstance(key, str) and unicodedata.normalize("NFC", key) == normalized_path
    ]
    if len(matches) != 1:
        return None
    value = str(matches[0])
    return value if value else None


def _resolve_evidence(
    *,
    relative_path: str,
    evidence_id: str,
    expected_category: str,
    resolver: EvidenceResolver | None,
) -> tuple[bool, str | None, str | None, str | None]:
    if resolver is None:
        return False, None, None, "no authority resolver was supplied"
    try:
        verification = EvidenceVerification.from_value(resolver(evidence_id))
    except Exception as exc:
        return False, None, None, f"evidence resolver failed: {type(exc).__name__}: {exc}"[:500]
    if verification.evidence_id != evidence_id:
        return False, verification.authority or None, verification.evidence_kind or None, "resolver returned a different evidence id"
    if not verification.verified:
        return False, verification.authority or None, verification.evidence_kind or None, verification.detail or "authority did not verify the evidence"
    if verification.authority != "iteration_wallet":
        return False, verification.authority or None, verification.evidence_kind or None, "evidence authority is not Iteration Wallet"
    allowed = _ALLOWED_EVIDENCE_KINDS[expected_category]
    if verification.evidence_kind not in allowed:
        return False, verification.authority, verification.evidence_kind, "evidence kind does not authorize this classification"
    if verification.subject_path is not None and unicodedata.normalize("NFC", verification.subject_path) != unicodedata.normalize("NFC", relative_path):
        return False, verification.authority, verification.evidence_kind, "evidence subject does not match the changed path"
    return True, verification.authority, verification.evidence_kind, None


def compare_snapshots(
    reference: RuntimeSnapshot,
    observed: RuntimeSnapshot,
    *,
    policy: ContinuityPolicy | None = None,
    authorized_configuration: Mapping[str, str] | None = None,
    verified_updates: Mapping[str, str] | None = None,
    approved_exceptions: Mapping[str, str] | None = None,
    evidence_resolver: EvidenceResolver | None = None,
) -> DivergenceAssessment:
    """Classify divergence in deterministic precedence order.

    Evidence IDs alone never authorize a classification. The authority resolver
    must verify the record, its authority owner, evidence kind, and optional path
    scope. Failed or absent verification is retained as a limitation and the
    change remains unexplained.
    """
    selected_policy = policy or ContinuityPolicy()
    if reference.root_label != observed.root_label:
        raise RuntimeContinuityError("snapshots describe different roots and cannot be compared")
    if observed.previous_snapshot_id != reference.snapshot_id:
        raise RuntimeContinuityError("observed snapshot is not explicitly linked to the reference snapshot")
    if reference.policy_version != selected_policy.version or observed.policy_version != selected_policy.version:
        raise RuntimeContinuityError("snapshot policy version does not match the selected comparison policy")
    # Revalidate even in-memory objects in case a caller bypassed normal constructors.
    RuntimeSnapshot.from_dict(reference.to_dict())
    RuntimeSnapshot.from_dict(observed.to_dict())

    authorized_configuration = dict(authorized_configuration or {})
    verified_updates = dict(verified_updates or {})
    approved_exceptions = dict(approved_exceptions or {})

    reference_map = {entry.relative_path: entry for entry in reference.entries}
    observed_map = {entry.relative_path: entry for entry in observed.entries}
    findings: list[DivergenceFinding] = []
    assessment_limitations: set[str] = set(reference.warnings) | set(observed.warnings)

    for relative_path in sorted(set(reference_map) | set(observed_map)):
        prior = reference_map.get(relative_path)
        current = observed_map.get(relative_path)
        change = _change(prior, current)
        entry = current or prior
        if entry is None:
            raise RuntimeContinuityError(
                f"comparison path {relative_path!r} has no snapshot entry"
            )
        evidence_id: str | None = None
        evidence_verified = False
        evidence_authority: str | None = None
        evidence_kind: str | None = None
        evidence_limitation: str | None = None

        limitation = entry.observation
        if limitation.startswith("unstable_observation"):
            category = DivergenceCategory.UNSTABLE_OBSERVATION
            severity = Severity.HIGH
            basis = limitation
        elif not entry.readable or limitation.startswith("unverifiable") or limitation.startswith("unreadable"):
            category = DivergenceCategory.UNVERIFIABLE
            trust_regression = prior is not None and prior.readable and not entry.readable
            severity = (
                Severity.HIGH
                if trust_regression
                or _matches(relative_path, selected_policy.protected_patterns, security_sensitive=True)
                else Severity.REVIEW
            )
            basis = (
                f"previously verified entry became unverifiable ({limitation}); treated as a trust regression"
                if trust_regression
                else limitation
            )
        elif change == "unchanged":
            category = DivergenceCategory.UNCHANGED
            severity = Severity.INFO
            basis = "static identity, size, kind, observation, and permissions match"
        elif _matches(relative_path, selected_policy.prohibited_patterns, security_sensitive=True):
            category = DivergenceCategory.PROHIBITED
            severity = Severity.CRITICAL
            basis = "path/change matches explicit prohibited policy"
        else:
            evidence_requests = (
                (DivergenceCategory.AUTHORIZED_CONFIGURATION, "authorized_configuration", _evidence_for(relative_path, authorized_configuration)),
                (DivergenceCategory.VERIFIED_UPDATE, "verified_update", _evidence_for(relative_path, verified_updates)),
                (DivergenceCategory.APPROVED_EXCEPTION, "approved_exception", _evidence_for(relative_path, approved_exceptions)),
            )
            accepted_category: DivergenceCategory | None = None
            for proposed_category, expected_kind, requested_id in evidence_requests:
                if requested_id is None:
                    continue
                evidence_id = requested_id
                verified, authority, kind, evidence_limitation = _resolve_evidence(
                    relative_path=relative_path,
                    evidence_id=requested_id,
                    expected_category=expected_kind,
                    resolver=evidence_resolver,
                )
                evidence_verified = verified
                evidence_authority = authority
                evidence_kind = kind
                if verified:
                    accepted_category = proposed_category
                    break
                assessment_limitations.add(f"{relative_path}:unverified_evidence:{requested_id}:{evidence_limitation}")
            if accepted_category is not None:
                category = accepted_category
                severity = Severity.REVIEW
                basis = "linked evidence was verified by the owning Wallet authority"
            elif evidence_id is not None:
                category = DivergenceCategory.UNEXPLAINED
                dangerous_bits = _gained_dangerous_mode_bits(prior, current)
                severity = (
                    Severity.HIGH
                    if dangerous_bits
                    or _matches(relative_path, selected_policy.protected_patterns, security_sensitive=True)
                    else Severity.REVIEW
                )
                basis = (
                    "an evidence reference was supplied but did not verify as authority, and the change newly set setuid/setgid"
                    if dangerous_bits
                    else "an evidence reference was supplied but did not verify as authority"
                )
            elif _matches(relative_path, selected_policy.disposable_patterns):
                category = DivergenceCategory.DISPOSABLE
                severity = Severity.INFO
                basis = "path matches explicit disposable-state policy"
            elif _matches(relative_path, selected_policy.expected_mutable_patterns):
                category = DivergenceCategory.EXPECTED_MUTABLE
                severity = Severity.REVIEW
                basis = "path matches explicit expected-mutable policy"
            else:
                category = DivergenceCategory.UNEXPLAINED
                dangerous_bits = _gained_dangerous_mode_bits(prior, current)
                severity = (
                    Severity.HIGH
                    if dangerous_bits
                    or _matches(relative_path, selected_policy.protected_patterns, security_sensitive=True)
                    else Severity.REVIEW
                )
                basis = (
                    "observed difference has no accepted explanatory evidence, and newly set setuid/setgid"
                    if dangerous_bits
                    else "observed difference has no accepted explanatory evidence"
                )

        findings.append(
            DivergenceFinding(
                relative_path=relative_path,
                change=change,
                category=category,
                severity=severity,
                evidence_id=evidence_id,
                evidence_verified=evidence_verified,
                evidence_authority=evidence_authority,
                evidence_kind=evidence_kind,
                evidence_limitation=evidence_limitation,
                basis=basis,
                reference_sha256=prior.sha256 if prior else None,
                observed_sha256=current.sha256 if current else None,
            )
        )

    coverage = min(reference.coverage, observed.coverage)
    inconclusive = any(
        item.category in {DivergenceCategory.UNVERIFIABLE, DivergenceCategory.UNSTABLE_OBSERVATION}
        for item in findings
    )
    if coverage >= 0.999 and not inconclusive:
        confidence = "high_static_coverage"
    elif coverage >= 0.8:
        confidence = "partial_static_coverage"
    else:
        confidence = "low_static_coverage"

    identity_payload = {
        "reference_snapshot_id": reference.snapshot_id,
        "observed_snapshot_id": observed.snapshot_id,
        "root_label": reference.root_label,
        "policy_version": selected_policy.version,
        "findings": [item.to_dict() for item in findings],
    }
    return DivergenceAssessment(
        assessment_id=_snapshot_identity(identity_payload),
        reference_snapshot_id=reference.snapshot_id,
        observed_snapshot_id=observed.snapshot_id,
        root_label=reference.root_label,
        policy_version=selected_policy.version,
        created_at=_utc_now(),
        findings=tuple(findings),
        coverage=coverage,
        confidence=confidence,
        limitations=tuple(sorted(assessment_limitations)),
    )


__all__ = [
    "ContinuityPolicy",
    "DivergenceAssessment",
    "DivergenceCategory",
    "DivergenceFinding",
    "EvidenceResolver",
    "EvidenceVerification",
    "ObservationMode",
    "RuntimeContinuityError",
    "RuntimeSnapshot",
    "Severity",
    "SnapshotEntry",
    "capture_snapshot",
    "compare_snapshots",
    "load_snapshot",
    "save_snapshot",
]
