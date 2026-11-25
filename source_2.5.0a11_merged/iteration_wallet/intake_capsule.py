"""Immutable Wallet Intake Capsules.

A capsule is the first Wallet-owned identity assigned to bytes arriving from
outside custody.  It is inert, content-addressed, explicitly untrusted, and
separate from Candidate/Prime state.  Oubliette may inspect a capsule, but only
Wallet may capture it, authorize a transition, or admit it as a Candidate.

The module never executes or imports captured material.  Failed and duplicate
capture artifacts are preserved for audit.
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import stat
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Optional
from uuid import uuid4

from blackbox_plugin.schema import canonical_json, validate_json_value

from iteration_wallet.custody_io import write_all

from iteration_wallet.durable_io import (
    DurableIOError,
    ensure_within,
    exclusive_json,
    file_lock,
    fsync_directory,
    strict_json_read,
    validate_storage_id,
)

_PORTABLE_FORBIDDEN = set('<>:"/\\|?*')


def portable_basename(value: str, *, fallback: str = "intake.bin", max_utf8_bytes: int = 160) -> str:
    """Return a bounded cross-platform display/storage basename.

    This does not claim that every filesystem accepts every Unicode scalar. It
    replaces Windows-forbidden punctuation, control characters, path separators,
    trailing dots/spaces, and reserved device names, then bounds the UTF-8 bytes.
    """
    normalized = unicodedata.normalize("NFKC", str(value or ""))
    cleaned = "".join(
        "_" if (ch in _PORTABLE_FORBIDDEN or ord(ch) < 32 or 127 <= ord(ch) <= 159) else ch
        for ch in normalized
    ).strip().rstrip(". ")
    if not cleaned or cleaned in {".", ".."}:
        cleaned = fallback
    stem = cleaned.split(".", 1)[0].upper()
    if stem in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}:
        cleaned = f"_{cleaned}"
    encoded = cleaned.encode("utf-8")
    if len(encoded) > max_utf8_bytes:
        suffix = Path(cleaned).suffix
        suffix_bytes = suffix.encode("utf-8") if len(suffix.encode("utf-8")) < max_utf8_bytes // 2 else b""
        budget = max_utf8_bytes - len(suffix_bytes)
        prefix = cleaned[: -len(suffix)] if suffix else cleaned
        while prefix and len(prefix.encode("utf-8")) > budget:
            prefix = prefix[:-1]
        cleaned = (prefix.rstrip(". ") or "intake") + suffix_bytes.decode("utf-8")
    return cleaned


class IntakeCapsuleError(Exception):
    """Raised when exact immutable intake cannot be proven."""


def _sha256_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise IntakeCapsuleError(f"cannot open intake source safely: {exc}") from exc
    try:
        stat_result = os.fstat(descriptor)
        if not stat.S_ISREG(stat_result.st_mode):
            raise IntakeCapsuleError("intake source must be a regular file")
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
            size += len(chunk)
        if size != int(stat_result.st_size):
            raise IntakeCapsuleError("intake source size changed while hashing")
    finally:
        os.close(descriptor)
    return digest.hexdigest(), size


def _copy_exact(source: Path, destination: Path, *, expected_hash: str, expected_size: int) -> None:
    source_flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        source_flags |= os.O_NOFOLLOW
    try:
        source_fd = os.open(source, source_flags)
    except OSError as exc:
        raise IntakeCapsuleError(f"cannot reopen intake source safely: {exc}") from exc
    try:
        source_stat = os.fstat(source_fd)
        if int(source_stat.st_size) != int(expected_size):
            raise IntakeCapsuleError("intake source changed before capture")
        destination_fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        digest = hashlib.sha256()
        copied = 0
        try:
            while True:
                chunk = os.read(source_fd, 1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
                copied += len(chunk)
                write_all(destination_fd, chunk, error_type=IntakeCapsuleError)
            os.fsync(destination_fd)
        finally:
            os.close(destination_fd)
    finally:
        os.close(source_fd)
    if copied != int(expected_size) or digest.hexdigest() != expected_hash:
        raise IntakeCapsuleError(
            "intake source changed during capture; captured bytes preserved as failed evidence"
        )


class WalletIntakeCapsuleStore:
    """Write-once, content-addressed intake storage under Wallet custody."""

    SCHEMA = "rvf.wallet-intake-capsule.v1"
    ADMISSION_SCHEMA = "rvf.wallet-intake-admission.v1"
    MAX_EXTERNAL_ASSERTIONS = 32
    MAX_ASSERTION_BYTES = 128 * 1024

    def __init__(self, vault_root: Path | str) -> None:
        self.vault_root = Path(vault_root)
        self.root = self.vault_root / "intake_capsules"
        self.blob_dir = self.root / "blobs"
        self.manifest_dir = self.root / "manifests"
        self.failed_dir = self.root / "failed_captures"
        self.duplicate_dir = self.root / "duplicate_capture_evidence"
        self.admission_dir = self.root / "admissions"
        self.lock_dir = self.root / ".locks"
        try:
            ensure_within(
                self.vault_root,
                self.root,
                label="Wallet intake capsule storage",
                error_type=IntakeCapsuleError,
            )
        except DurableIOError as exc:
            raise IntakeCapsuleError(str(exc)) from exc
        for directory in (
            self.root,
            self.blob_dir,
            self.manifest_dir,
            self.failed_dir,
            self.duplicate_dir,
            self.admission_dir,
            self.lock_dir,
        ):
            if directory.is_symlink():
                raise IntakeCapsuleError(
                    f"Wallet intake directory cannot be a symlink: {directory.name}"
                )
            directory.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def semantic_manifest(record: Mapping[str, Any]) -> dict[str, Any]:
        return {
            key: value
            for key, value in dict(record).items()
            if key
            not in {
                "capsule_id",
                "manifest_hash",
                "captured_at",
                "blob_path",
                "capture_operation_id",
                "absolute_blob_path",
                "record_hash",
            }
        }

    @classmethod
    def manifest_hash(cls, record: Mapping[str, Any]) -> str:
        return hashlib.sha256(canonical_json(cls.semantic_manifest(record))).hexdigest()

    @staticmethod
    def record_hash(record: Mapping[str, Any]) -> str:
        sealed = {
            key: value
            for key, value in dict(record).items()
            if key not in {"record_hash", "absolute_blob_path"}
        }
        return hashlib.sha256(canonical_json(sealed)).hexdigest()

    @classmethod
    def seal_record(cls, record: Mapping[str, Any]) -> dict[str, Any]:
        sealed = dict(record)
        sealed["record_hash"] = cls.record_hash(sealed)
        return sealed

    @staticmethod
    def capsule_id_for(manifest_hash: str, blob_hash: str) -> str:
        digest = hashlib.sha256(
            canonical_json({"manifest_hash": manifest_hash, "blob_hash": blob_hash})
        ).hexdigest()
        return f"cap-{digest}"

    def _manifest_path(self, capsule_id: str) -> Path:
        capsule_id = validate_storage_id(
            "capsule_id", capsule_id, error_type=IntakeCapsuleError
        )
        return self.manifest_dir / f"{capsule_id}.json"

    def _blob_path(self, blob_hash: str) -> Path:
        blob_hash = validate_storage_id(
            "blob_hash", blob_hash, error_type=IntakeCapsuleError
        )
        return self.blob_dir / f"{blob_hash}.blob"

    def _lock_path(self, material: str) -> Path:
        digest = hashlib.sha256(material.encode("utf-8")).hexdigest()
        return self.lock_dir / f"{digest}.lock"

    @classmethod
    def _normalized_assertions(cls, assertions: Optional[list[Mapping[str, Any]]]) -> list[dict[str, Any]]:
        supplied = assertions or []
        if len(supplied) > cls.MAX_EXTERNAL_ASSERTIONS:
            raise IntakeCapsuleError(
                f"too many external assertions: maximum {cls.MAX_EXTERNAL_ASSERTIONS}"
            )
        normalized: list[dict[str, Any]] = []
        for assertion in supplied:
            item = dict(assertion)
            item["authority"] = "external_assertion_only"
            validate_json_value(item)
            normalized.append(item)
        if len(canonical_json({"external_assertions": normalized})) > cls.MAX_ASSERTION_BYTES:
            raise IntakeCapsuleError("external assertion envelope exceeds bounded intake size")
        return normalized

    def capture(
        self,
        *,
        project_id: str,
        section_id: str,
        parent_object_id: str,
        parent_sha256: str,
        source_path: Path | str,
        allowed_root: Path | str,
        source_label: Optional[str] = None,
        capture_operation_id: Optional[str] = None,
        external_assertions: Optional[list[Mapping[str, Any]]] = None,
        minimum_free_reserve_bytes: int = 16 * 1024 * 1024,
    ) -> dict[str, Any]:
        """Capture exact bytes into inert Wallet-owned intake storage.

        The source is hashed once to identify it and read again while copying.
        Any change between those reads fails closed.  The authority transaction
        that follows depends only on the preserved blob, never on this path.
        """
        project_id = validate_storage_id("project_id", project_id, error_type=IntakeCapsuleError)
        section_id = validate_storage_id("section_id", section_id, error_type=IntakeCapsuleError)
        parent_object_id = validate_storage_id(
            "parent_object_id", parent_object_id, error_type=IntakeCapsuleError
        )
        if not re.fullmatch(r"[0-9a-f]{64}", str(parent_sha256)):
            raise IntakeCapsuleError("parent_sha256 must be a lowercase SHA-256 digest")
        label = str(source_label or "").strip()
        if len(label) > 512 or any(ord(ch) < 32 or 127 <= ord(ch) <= 159 for ch in label):
            raise IntakeCapsuleError("source label exceeds the bounded intake metadata contract")
        source = Path(source_path).expanduser()
        root = Path(allowed_root).expanduser()
        if source.is_symlink():
            raise IntakeCapsuleError("intake source cannot be a symlink")
        try:
            resolved_root = root.resolve(strict=True)
            resolved_source = source.resolve(strict=True)
            resolved_source.relative_to(resolved_root)
        except (OSError, ValueError) as exc:
            raise IntakeCapsuleError("intake source escapes or is unavailable in the declared root") from exc
        if not resolved_source.is_file():
            raise IntakeCapsuleError("intake source must be one regular file")

        first_hash, first_size = _sha256_file(resolved_source)
        free = shutil.disk_usage(self.root).free
        required = int(first_size) + max(0, int(minimum_free_reserve_bytes))
        if free < required:
            raise IntakeCapsuleError(
                f"insufficient storage headroom for intake capture: need {required} bytes, have {free}"
            )

        semantic = {
            "schema": self.SCHEMA,
            "project_id": project_id,
            "section_id": section_id,
            "parent_object_id": parent_object_id,
            "parent_sha256": parent_sha256,
            "blob_sha256": first_hash,
            "size_bytes": int(first_size),
            "source_label": label or resolved_source.name,
            "state": "intake",
            "execution_allowed": False,
            "trust_status": "untrusted_intake_no_automatic_trust",
            "external_assertions": self._normalized_assertions(external_assertions),
        }
        manifest_hash = self.manifest_hash(semantic)
        capsule_id = self.capsule_id_for(manifest_hash, first_hash)
        blob_path = self._blob_path(first_hash)
        manifest_path = self._manifest_path(capsule_id)
        operation_id = capture_operation_id or f"capture-{uuid4().hex}"
        operation_id = validate_storage_id(
            "capture_operation_id", operation_id, error_type=IntakeCapsuleError
        )

        try:
            with file_lock(self._lock_path(f"blob:{first_hash}")):
                if blob_path.exists():
                    if blob_path.is_symlink():
                        raise IntakeCapsuleError("intake blob path cannot be a symlink")
                    existing_hash, existing_size = _sha256_file(blob_path)
                    if existing_hash != first_hash or existing_size != first_size:
                        raise IntakeCapsuleError("content-addressed intake blob conflicts with its identity")
                    confirm_hash, confirm_size = _sha256_file(resolved_source)
                    if confirm_hash != first_hash or confirm_size != first_size:
                        raise IntakeCapsuleError("intake source changed after initial observation")
                else:
                    incoming = self.blob_dir / f".{first_hash}.{os.getpid()}.{uuid4().hex}.incoming"
                    try:
                        _copy_exact(
                            resolved_source,
                            incoming,
                            expected_hash=first_hash,
                            expected_size=first_size,
                        )
                        os.replace(incoming, blob_path)
                        fsync_directory(self.blob_dir)
                    except BaseException as exc:
                        if incoming.exists():
                            preserved = self.failed_dir / (
                                f"{operation_id}.{first_hash}.{uuid4().hex}.failed"
                            )
                            try:
                                os.replace(incoming, preserved)
                                fsync_directory(self.failed_dir)
                            except Exception as preserve_exc:
                                if hasattr(exc, "add_note"):
                                    exc.add_note(
                                        f"failed capture remains at {incoming}; preservation failed: "
                                        f"{type(preserve_exc).__name__}: {preserve_exc}"
                                    )
                        raise

            record = self.seal_record({
                **semantic,
                "capsule_id": capsule_id,
                "manifest_hash": manifest_hash,
                "captured_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
                "blob_path": str(blob_path.relative_to(self.vault_root)),
                "capture_operation_id": operation_id,
            })
            with file_lock(self._lock_path(f"manifest:{capsule_id}")):
                if manifest_path.exists():
                    existing = self.get(capsule_id)
                    if self.semantic_manifest(existing) != self.semantic_manifest(record):
                        raise IntakeCapsuleError("intake capsule identity conflicts with existing manifest")
                    return existing
                try:
                    exclusive_json(manifest_path, record)
                except FileExistsError:
                    existing = self.get(capsule_id)
                    if self.semantic_manifest(existing) != self.semantic_manifest(record):
                        raise IntakeCapsuleError("concurrent intake capsule identity conflict")
                    return existing
            return self.get(capsule_id)
        except DurableIOError as exc:
            raise IntakeCapsuleError(f"intake capture lock or storage failed: {exc}") from exc

    def get(self, capsule_id: str) -> dict[str, Any]:
        path = self._manifest_path(capsule_id)
        if path.is_symlink() or not path.is_file():
            raise IntakeCapsuleError(f"intake capsule not found: {capsule_id}")
        try:
            record = strict_json_read(path)
        except DurableIOError as exc:
            raise IntakeCapsuleError(f"unreadable intake capsule manifest: {exc}") from exc
        if not isinstance(record, dict) or record.get("capsule_id") != capsule_id:
            raise IntakeCapsuleError("intake capsule identity does not match storage")
        if record.get("schema") != self.SCHEMA:
            raise IntakeCapsuleError("unsupported intake capsule schema")
        if record.get("record_hash") != self.record_hash(record):
            raise IntakeCapsuleError("intake capsule stored-record hash mismatch")
        expected_manifest_hash = self.manifest_hash(record)
        if record.get("manifest_hash") != expected_manifest_hash:
            raise IntakeCapsuleError("intake capsule manifest hash mismatch")
        expected_capsule_id = self.capsule_id_for(
            expected_manifest_hash, str(record.get("blob_sha256") or "")
        )
        if expected_capsule_id != capsule_id:
            raise IntakeCapsuleError("intake capsule id does not match its manifest")
        blob_path = self._blob_path(str(record.get("blob_sha256") or ""))
        expected_relative = str(blob_path.relative_to(self.vault_root))
        if record.get("blob_path") != expected_relative:
            raise IntakeCapsuleError("intake capsule blob path metadata mismatch")
        if blob_path.is_symlink() or not blob_path.is_file():
            raise IntakeCapsuleError("intake capsule blob is unavailable")
        blob_hash, blob_size = _sha256_file(blob_path)
        if blob_hash != record.get("blob_sha256") or blob_size != int(record.get("size_bytes") or -1):
            raise IntakeCapsuleError("intake capsule blob does not match its manifest")
        safe = dict(record)
        safe["absolute_blob_path"] = str(blob_path)
        return safe

    def admission(self, capsule_id: str) -> Optional[dict[str, Any]]:
        capsule_id = validate_storage_id(
            "capsule_id", capsule_id, error_type=IntakeCapsuleError
        )
        path = self.admission_dir / f"{capsule_id}.json"
        if not path.exists():
            return None
        if path.is_symlink() or not path.is_file():
            raise IntakeCapsuleError("intake admission record is not a regular file")
        try:
            record = strict_json_read(path)
        except DurableIOError as exc:
            raise IntakeCapsuleError(f"unreadable intake admission record: {exc}") from exc
        if not isinstance(record, dict) or record.get("capsule_id") != capsule_id:
            raise IntakeCapsuleError("intake admission record identity mismatch")
        if record.get("schema") != self.ADMISSION_SCHEMA:
            raise IntakeCapsuleError("unsupported intake admission schema")
        if record.get("record_hash") != self.record_hash(record):
            raise IntakeCapsuleError("intake admission record hash mismatch")
        return record

    def bind_admission(
        self,
        capsule_id: str,
        *,
        candidate_id: str,
        operation_id: str,
        receipt_id: str,
        candidate_sha256: str,
    ) -> dict[str, Any]:
        capsule = self.get(capsule_id)
        candidate_id = validate_storage_id(
            "candidate_id", candidate_id, error_type=IntakeCapsuleError
        )
        operation_id = validate_storage_id(
            "operation_id", operation_id, error_type=IntakeCapsuleError
        )
        receipt_id = validate_storage_id(
            "receipt_id", receipt_id, error_type=IntakeCapsuleError
        )
        if not re.fullmatch(r"[0-9a-f]{64}", str(candidate_sha256)):
            raise IntakeCapsuleError("candidate_sha256 must be a lowercase SHA-256 digest")
        if candidate_sha256 != capsule.get("blob_sha256"):
            raise IntakeCapsuleError("candidate_sha256 does not match the Intake Capsule blob")
        record = self.seal_record({
            "schema": self.ADMISSION_SCHEMA,
            "capsule_id": capsule_id,
            "manifest_hash": capsule["manifest_hash"],
            "candidate_id": candidate_id,
            "candidate_sha256": candidate_sha256,
            "operation_id": operation_id,
            "receipt_id": receipt_id,
        })
        path = self.admission_dir / f"{capsule_id}.json"
        try:
            with file_lock(self._lock_path(f"admission:{capsule_id}")):
                if path.exists():
                    existing = self.admission(capsule_id)
                    if existing != record:
                        raise IntakeCapsuleError("capsule already bound to a different admission")
                    return existing
                exclusive_json(path, record)
                return record
        except DurableIOError as exc:
            raise IntakeCapsuleError(f"could not bind intake admission: {exc}") from exc

    def capability(self) -> dict[str, Any]:
        return {
            "component": "wallet_intake_capsules",
            "available": True,
            "level": "transaction_ready",
            "schema": self.SCHEMA,
            "execution_supported": False,
            "custody_authority": "iteration_wallet_only",
        }
