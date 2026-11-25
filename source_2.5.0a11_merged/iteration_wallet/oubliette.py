"""Static-only Oubliette inspection boundary.

Oubliette observes exact bytes and bounded archive metadata without importing,
launching, extracting, repairing, moving, deleting, or deciding custody.
Findings are risk indicators, never malware verdicts. Physical quarantine
remains Wallet-owned and requires a separate Human Intent transaction.
"""
from __future__ import annotations

import hashlib
import os
import re
import stat
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path, PurePosixPath
from typing import Any, BinaryIO

from blackbox_plugin.schema import canonical_json

_SCANNER_VERSION = "rvf.oubliette-static.v2"
_MAX_SAMPLE_BYTES = 256 * 1024
_MAX_ARCHIVE_MEMBERS = 10_000
_MAX_MEMBER_UNCOMPRESSED = 2 * 1024 * 1024 * 1024
_MAX_TOTAL_UNCOMPRESSED = 8 * 1024 * 1024 * 1024
_MAX_COMPRESSION_RATIO = 250.0
_MAX_FINDINGS = 2_000
_MAX_WARNINGS = 256
_MAX_SUBJECT_CHARS = 512
_MAX_TARGET_LABEL_CHARS = 512

_EXECUTABLE_SUFFIXES = {
    ".bat", ".cmd", ".com", ".dll", ".exe", ".hta", ".js", ".jse",
    ".msi", ".ps1", ".py", ".scr", ".sh", ".vbe", ".vbs", ".wsf",
}
_STATIC_PATTERNS: tuple[tuple[str, re.Pattern[bytes], str], ...] = (
    ("dynamic_python_execution", re.compile(rb"\b(?:eval|exec)\s*\("), "dynamic execution primitive"),
    ("process_launch", re.compile(rb"\b(?:subprocess\.|os\.system\s*\(|shell\s*=\s*True)"), "process-launch primitive"),
    ("powershell_encoded", re.compile(rb"powershell(?:\.exe)?[^\r\n]{0,100}(?:-enc|-encodedcommand)\b", re.I), "encoded PowerShell invocation"),
    ("download_pipe_shell", re.compile(rb"(?:curl|wget)[^\r\n|]{0,200}\|\s*(?:sh|bash)\b", re.I), "download piped to shell"),
    ("destructive_file_api", re.compile(rb"(?:\.unlink\s*\(|shutil\.rmtree\s*\(|os\.remove\s*\()"), "destructive file API reference"),
)


class OublietteError(RuntimeError):
    """Raised when static inspection cannot proceed without violating bounds."""


class ActorKind(str, Enum):
    HUMAN = "human"
    LOCAL_SYSTEM = "local_system"
    AI = "ai"
    BOT = "bot"


class Coverage(str, Enum):
    FULL = "full"
    PARTIAL = "partial"
    NONE = "none"


class RiskLevel(str, Enum):
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass(frozen=True, slots=True)
class StaticFinding:
    code: str
    risk: RiskLevel
    subject: str
    evidence: str
    limitation: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "risk": self.risk.value,
            "subject": self.subject,
            "evidence": self.evidence,
            "limitation": self.limitation,
        }


@dataclass(frozen=True, slots=True)
class OublietteInspectionReport:
    report_id: str
    generated_at: str
    target_label: str
    target_sha256: str | None
    size_bytes: int | None
    coverage: Coverage
    bytes_sampled: int
    archive_members_observed: int
    findings: tuple[StaticFinding, ...]
    warnings: tuple[str, ...]
    actor_kind: ActorKind
    scanner_version: str = _SCANNER_VERSION
    observation_mode: str = "static_only"
    target_executed: bool = False
    target_extracted: bool = False
    target_modified: bool = False
    custody_changed: bool = False
    malware_determined: bool = False

    @property
    def quarantine_review_recommended(self) -> bool:
        return any(item.risk in {RiskLevel.HIGH, RiskLevel.MEDIUM} for item in self.findings)

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_id": self.report_id,
            "generated_at": self.generated_at,
            "target_label": self.target_label,
            "target_sha256": self.target_sha256,
            "size_bytes": self.size_bytes,
            "coverage": self.coverage.value,
            "bytes_sampled": self.bytes_sampled,
            "archive_members_observed": self.archive_members_observed,
            "findings": [item.to_dict() for item in self.findings],
            "warnings": list(self.warnings),
            "actor_kind": self.actor_kind.value,
            "scanner_version": self.scanner_version,
            "observation_mode": self.observation_mode,
            "target_executed": self.target_executed,
            "target_extracted": self.target_extracted,
            "target_modified": self.target_modified,
            "custody_changed": self.custody_changed,
            "malware_determined": self.malware_determined,
            "quarantine_review_recommended": self.quarantine_review_recommended,
        }

    def canonical_evidence_event(self, *, subject_id: str, operation_id: str) -> dict[str, Any]:
        if not subject_id or not operation_id:
            raise OublietteError("subject_id and operation_id are required")
        return {
            "event_type": "oubliette.static_inspection_completed",
            "source": "iteration_wallet.oubliette",
            "actor": f"{self.actor_kind.value}:operator",
            "subject_id": subject_id,
            "operation_id": operation_id,
            "observation_mode": "static_only",
            "coverage": self.coverage.value,
            "payload": {
                "report_id": self.report_id,
                "scanner_version": self.scanner_version,
                "target_sha256": self.target_sha256,
                "finding_codes": [item.code for item in self.findings],
                "warnings": list(self.warnings),
                "quarantine_review_recommended": self.quarantine_review_recommended,
                "target_executed": False,
                "target_extracted": False,
                "target_modified": False,
                "custody_changed": False,
                "malware_determined": False,
            },
        }


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _bounded_text(value: str, *, maximum: int) -> str:
    text = "".join(" " if ord(ch) < 32 or 127 <= ord(ch) <= 159 else ch for ch in str(value))
    return text[:maximum]


def _ensure_target(target: Path, allowed_root: Path | None) -> Path:
    expanded = target.expanduser()
    if expanded.is_symlink():
        raise OublietteError("Oubliette will not follow a symlink target")
    try:
        resolved = expanded.resolve(strict=True)
    except OSError as exc:
        raise OublietteError(f"target is unavailable: {exc}") from exc
    if allowed_root is not None:
        try:
            root = allowed_root.expanduser().resolve(strict=True)
        except OSError as exc:
            raise OublietteError(f"inspection root is unavailable: {exc}") from exc
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise OublietteError("target escapes the declared inspection root") from exc
    if not resolved.is_file():
        raise OublietteError("this foundation inspects one regular file at a time")
    return resolved


def _open_snapshot(path: Path) -> tuple[int, os.stat_result]:
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise OublietteError(f"cannot open inspection target safely: {exc}") from exc
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode):
            raise OublietteError("inspection target must remain a regular file")
        path_state = os.stat(path, follow_symlinks=False)
        if not stat.S_ISREG(path_state.st_mode):
            raise OublietteError("inspection path no longer names a regular file")
        if (getattr(opened, "st_dev", None), getattr(opened, "st_ino", None)) != (
            getattr(path_state, "st_dev", None), getattr(path_state, "st_ino", None)
        ):
            raise OublietteError("inspection path changed before observation began")
        return descriptor, opened
    except BaseException:
        os.close(descriptor)
        raise


def _read_snapshot(descriptor: int) -> tuple[str, int, bytes]:
    digest = hashlib.sha256()
    size = 0
    sample = bytearray()
    os.lseek(descriptor, 0, os.SEEK_SET)
    while True:
        chunk = os.read(descriptor, 1024 * 1024)
        if not chunk:
            break
        digest.update(chunk)
        size += len(chunk)
        if len(sample) < _MAX_SAMPLE_BYTES:
            sample.extend(chunk[: _MAX_SAMPLE_BYTES - len(sample)])
    return digest.hexdigest(), size, bytes(sample)


def _append_finding(findings: list[StaticFinding], finding: StaticFinding, warnings: list[str]) -> bool:
    if len(findings) >= _MAX_FINDINGS:
        if not any("finding limit" in item for item in warnings):
            warnings.append(f"finding limit {_MAX_FINDINGS} reached; additional indicators omitted")
        return False
    findings.append(finding)
    return True


def _archive_findings(file_object: BinaryIO) -> tuple[list[StaticFinding], list[str], int, bool]:
    findings: list[StaticFinding] = []
    warnings: list[str] = []
    member_count = 0
    partial = False
    total_uncompressed = 0
    total_compressed = 0
    try:
        file_object.seek(0)
        with zipfile.ZipFile(file_object, "r") as archive:
            infos = archive.infolist()
            original_count = len(infos)
            if original_count > _MAX_ARCHIVE_MEMBERS:
                warnings.append(
                    f"archive contains {original_count} members; inspection bounded at {_MAX_ARCHIVE_MEMBERS}"
                )
                infos = infos[:_MAX_ARCHIVE_MEMBERS]
                partial = True
            seen: set[str] = set()
            for info in infos:
                member_count += 1
                total_uncompressed += max(0, int(info.file_size))
                total_compressed += max(0, int(info.compress_size))
                name = _bounded_text(info.filename.replace("\\", "/"), maximum=_MAX_SUBJECT_CHARS)
                pure = PurePosixPath(name)
                if name in seen:
                    _append_finding(findings, StaticFinding("duplicate_archive_member", RiskLevel.MEDIUM, name, "duplicate member name"), warnings)
                seen.add(name)
                if pure.is_absolute() or ".." in pure.parts or re.match(r"^[A-Za-z]:", name):
                    _append_finding(findings, StaticFinding("archive_path_escape", RiskLevel.HIGH, name, "absolute or parent-traversal member path"), warnings)
                unix_mode = (info.external_attr >> 16) & 0xFFFF
                if unix_mode and stat.S_ISLNK(unix_mode):
                    _append_finding(findings, StaticFinding("archive_symlink", RiskLevel.HIGH, name, "archive member is a symbolic link"), warnings)
                suffix = pure.suffix.lower()
                if suffix in _EXECUTABLE_SUFFIXES:
                    _append_finding(findings, StaticFinding("archive_executable_member", RiskLevel.MEDIUM, name, f"member suffix {suffix}"), warnings)
                if info.flag_bits & 0x1:
                    _append_finding(findings, StaticFinding("archive_encrypted_member", RiskLevel.MEDIUM, name, "member is encrypted and content was not inspected", "content coverage unavailable"), warnings)
                if info.file_size > _MAX_MEMBER_UNCOMPRESSED:
                    _append_finding(findings, StaticFinding("archive_oversized_member", RiskLevel.HIGH, name, f"declared uncompressed size {info.file_size}"), warnings)
                ratio = (float("inf") if info.file_size else 1.0) if info.compress_size == 0 else info.file_size / info.compress_size
                if ratio > _MAX_COMPRESSION_RATIO:
                    _append_finding(findings, StaticFinding("archive_extreme_compression", RiskLevel.HIGH, name, f"declared compression ratio {ratio:.1f}:1"), warnings)
            if total_uncompressed > _MAX_TOTAL_UNCOMPRESSED:
                _append_finding(
                    findings,
                    StaticFinding(
                        "archive_extreme_total_size",
                        RiskLevel.HIGH,
                        "archive",
                        f"declared total uncompressed size {total_uncompressed}",
                    ),
                    warnings,
                )
            if member_count:
                warnings.append(
                    "archive member content was not extracted or executed; coverage is limited to container bytes and member metadata"
                )
                partial = True
    except (zipfile.BadZipFile, OSError, RuntimeError, ValueError) as exc:
        warnings.append(f"archive structure could not be fully inspected: {type(exc).__name__}: {exc}")
        partial = True
    return findings, warnings[:_MAX_WARNINGS], member_count, partial


def inspect_static(
    target: Path | str,
    *,
    actor_kind: ActorKind | str,
    allowed_root: Path | str | None = None,
    target_label: str | None = None,
) -> OublietteInspectionReport:
    """Inspect one stable file-descriptor snapshot without activating it."""
    try:
        actor = actor_kind if isinstance(actor_kind, ActorKind) else ActorKind(str(actor_kind))
    except ValueError as exc:
        raise OublietteError("unsupported actor kind") from exc
    if actor in {ActorKind.AI, ActorKind.BOT}:
        raise OublietteError("autonomous AI or bot operation of Oubliette is prohibited by this boundary")

    path = _ensure_target(Path(target), Path(allowed_root) if allowed_root is not None else None)
    label = _bounded_text(target_label or path.name, maximum=_MAX_TARGET_LABEL_CHARS)
    descriptor, opened = _open_snapshot(path)
    try:
        digest, size, sample = _read_snapshot(descriptor)
        findings: list[StaticFinding] = []
        warnings: list[str] = []
        archive_members = 0
        partial = size > len(sample)
        if partial:
            warnings.append(f"content-pattern inspection sampled first {len(sample)} of {size} bytes")

        if sample.startswith(b"MZ"):
            _append_finding(findings, StaticFinding("pe_executable_signature", RiskLevel.MEDIUM, path.name, "MZ/PE-compatible executable signature"), warnings)
        elif sample.startswith(b"\x7fELF"):
            _append_finding(findings, StaticFinding("elf_executable_signature", RiskLevel.MEDIUM, path.name, "ELF executable signature"), warnings)
        elif sample.startswith(b"#!"):
            _append_finding(findings, StaticFinding("script_shebang", RiskLevel.LOW, path.name, "script interpreter declaration"), warnings)

        for code, pattern, evidence in _STATIC_PATTERNS:
            if pattern.search(sample):
                _append_finding(findings, StaticFinding(code, RiskLevel.MEDIUM, path.name, evidence, "static indicator; intent and reachability not proven"), warnings)

        with os.fdopen(os.dup(descriptor), "rb", closefd=True) as snapshot:
            snapshot.seek(0)
            is_zip = zipfile.is_zipfile(snapshot)
            if is_zip:
                archive_findings, archive_warnings, archive_members, archive_partial = _archive_findings(snapshot)
                for finding in archive_findings:
                    _append_finding(findings, finding, warnings)
                warnings.extend(archive_warnings)
                warnings = warnings[:_MAX_WARNINGS]
                partial = partial or archive_partial

        after_open = os.fstat(descriptor)
        try:
            after_path = os.stat(path, follow_symlinks=False)
        except OSError:
            warnings.append("inspection path disappeared during observation; descriptor snapshot remains exact")
            partial = True
        else:
            identity_before = (getattr(opened, "st_dev", None), getattr(opened, "st_ino", None))
            identity_after = (getattr(after_path, "st_dev", None), getattr(after_path, "st_ino", None))
            if identity_before != identity_after:
                warnings.append("inspection path was replaced during observation; report covers the opened descriptor only")
                partial = True
        if (opened.st_size, opened.st_mtime_ns, opened.st_ctime_ns) != (
            after_open.st_size,
            after_open.st_mtime_ns,
            after_open.st_ctime_ns,
        ):
            warnings.append("opened target metadata changed during observation; results may be unstable")
            partial = True
    finally:
        os.close(descriptor)

    coverage = Coverage.PARTIAL if partial else Coverage.FULL
    semantic = {
        "scanner_version": _SCANNER_VERSION,
        "target_label": label,
        "target_sha256": digest,
        "size_bytes": size,
        "coverage": coverage.value,
        "bytes_sampled": len(sample),
        "archive_members_observed": archive_members,
        "findings": [item.to_dict() for item in findings],
        "warnings": warnings,
        "actor_kind": actor.value,
        "observation_mode": "static_only",
        "target_executed": False,
        "target_extracted": False,
        "target_modified": False,
        "custody_changed": False,
        "malware_determined": False,
    }
    report_id = "oub-inspect:" + hashlib.sha256(canonical_json(semantic)).hexdigest()
    return OublietteInspectionReport(
        report_id=report_id,
        generated_at=_utc_now(),
        target_label=label,
        target_sha256=digest,
        size_bytes=size,
        coverage=coverage,
        bytes_sampled=len(sample),
        archive_members_observed=archive_members,
        findings=tuple(findings),
        warnings=tuple(warnings),
        actor_kind=actor,
        scanner_version=_SCANNER_VERSION,
    )
