"""Wallet-owned LabCopy export and Candidate-only result return.

A LabCopy is a traceable working package exported outside Wallet custody.  This
module never executes the package, never runs a laboratory tool, and never
upgrades returned claims into trust.  Returned bytes first become immutable
Wallet Intake Capsules and may enter the generation graph only through a
proposal-scoped Human Intent transaction as a new Candidate.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import stat
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Optional
from uuid import uuid4

from blackbox_plugin.schema import canonical_json, validate_json_value

from iteration_wallet.canonical_evidence import (
    CanonicalEvidenceAdapter,
    CanonicalEvidenceError,
    HumanIntentReceiptStore,
)
from iteration_wallet.custody_io import publish_no_clobber, verified_regular_file, write_all
from iteration_wallet.durable_io import (
    DurableIOError,
    atomic_json,
    ensure_within,
    exclusive_json,
    file_lock,
    fsync_directory,
    strict_json_read,
    validate_storage_id,
)
from iteration_wallet.gatekeeper import evaluate_protected_action
from iteration_wallet.intake_capsule import WalletIntakeCapsuleStore, IntakeCapsuleError, portable_basename
from iteration_wallet.notification_manager import ActorKind, NotificationManager
from iteration_wallet.vault_v21 import VaultEngine, VaultError


class LabCopyTransactionError(Exception):
    """A LabCopy operation could not be completed or proven safely."""


class SimulatedLabCopyCrash(BaseException):
    """Fault-injection sentinel that intentionally bypasses ordinary recovery."""

    def __init__(self, stage: str) -> None:
        super().__init__(f"simulated process crash after {stage}")
        self.stage = stage


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def sha256_json(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json(payload)).hexdigest()


def sha256_file(path: Path) -> tuple[str, int]:
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise LabCopyTransactionError(f"cannot open file safely: {exc}") from exc
    digest = hashlib.sha256()
    size = 0
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode):
            raise LabCopyTransactionError("LabCopy material must be one regular file")
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
            size += len(chunk)
    finally:
        os.close(descriptor)
    return digest.hexdigest(), size


class _SealedStore:
    """Small write-once/sealed JSON store rooted under Wallet custody."""

    def __init__(self, vault_root: Path, relative: str) -> None:
        self.vault_root = Path(vault_root)
        self.root = self.vault_root / relative
        self.lock_dir = self.root / ".locks"
        try:
            ensure_within(
                self.vault_root,
                self.root,
                label=relative,
                error_type=LabCopyTransactionError,
            )
        except DurableIOError as exc:
            raise LabCopyTransactionError(str(exc)) from exc
        for directory in (self.root, self.lock_dir):
            if directory.is_symlink():
                raise LabCopyTransactionError(f"LabCopy storage cannot be a symlink: {directory}")
            directory.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def record_hash(record: Mapping[str, Any]) -> str:
        body = {key: value for key, value in dict(record).items() if key != "record_hash"}
        return hashlib.sha256(canonical_json(body)).hexdigest()

    @classmethod
    def seal(cls, record: Mapping[str, Any]) -> dict[str, Any]:
        sealed = dict(record)
        sealed["record_hash"] = cls.record_hash(sealed)
        return sealed

    @staticmethod
    def _id(label: str, value: str) -> str:
        try:
            return validate_storage_id(label, value, error_type=LabCopyTransactionError)
        except DurableIOError as exc:
            raise LabCopyTransactionError(str(exc)) from exc

    def path(self, record_id: str) -> Path:
        safe = self._id("record_id", record_id)
        return self.root / f"{safe}.json"

    def lock_path(self, record_id: str) -> Path:
        safe = self._id("record_id", record_id)
        return self.lock_dir / f"{safe}.lock"

    def create(self, record_id: str, record: Mapping[str, Any]) -> dict[str, Any]:
        safe = self._id("record_id", record_id)
        material = self.seal({**dict(record), "record_id": safe})
        validate_json_value(material)
        try:
            with file_lock(self.lock_path(safe)):
                path = self.path(safe)
                if path.exists() or path.is_symlink():
                    existing = self.get(safe)
                    if existing != material:
                        raise LabCopyTransactionError(
                            f"LabCopy record conflicts with existing identity: {safe}"
                        )
                    return existing
                exclusive_json(path, material)
        except DurableIOError as exc:
            raise LabCopyTransactionError(f"cannot create LabCopy record: {exc}") from exc
        return material

    def get(self, record_id: str) -> dict[str, Any]:
        path = self.path(record_id)
        if path.is_symlink() or not path.is_file():
            raise LabCopyTransactionError(f"LabCopy record is missing or unsafe: {record_id}")
        try:
            value = strict_json_read(path)
        except DurableIOError as exc:
            raise LabCopyTransactionError(f"cannot read LabCopy record: {exc}") from exc
        if not isinstance(value, dict):
            raise LabCopyTransactionError("LabCopy record must be a JSON object")
        if value.get("record_id") != self._id("record_id", record_id):
            raise LabCopyTransactionError("LabCopy record identity mismatch")
        if value.get("record_hash") != self.record_hash(value):
            raise LabCopyTransactionError("LabCopy record seal mismatch")
        return value


class LabCopyJournal:
    JOURNAL_VERSION = 1

    def __init__(self, vault_root: Path | str) -> None:
        self.vault_root = Path(vault_root)
        self.root = self.vault_root / "recovery_journal" / "labcopy"
        self.active = self.root / "active"
        self.completed = self.root / "completed"
        self.reconciliation = self.root / "reconciliation_required"
        self.locks = self.root / ".locks"
        try:
            ensure_within(
                self.vault_root,
                self.root,
                label="LabCopy journal",
                error_type=LabCopyTransactionError,
            )
        except DurableIOError as exc:
            raise LabCopyTransactionError(str(exc)) from exc
        for directory in (self.root, self.active, self.completed, self.reconciliation, self.locks):
            if directory.is_symlink():
                raise LabCopyTransactionError(f"LabCopy journal path cannot be a symlink: {directory}")
            directory.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _id(value: str) -> str:
        try:
            return validate_storage_id("operation_id", value, error_type=LabCopyTransactionError)
        except DurableIOError as exc:
            raise LabCopyTransactionError(str(exc)) from exc

    @staticmethod
    def record_hash(record: Mapping[str, Any]) -> str:
        return hashlib.sha256(
            canonical_json({k: v for k, v in dict(record).items() if k != "record_hash"})
        ).hexdigest()

    @classmethod
    def seal(cls, record: Mapping[str, Any]) -> dict[str, Any]:
        material = dict(record)
        material["record_hash"] = cls.record_hash(material)
        return material

    def _path(self, directory: Path, operation_id: str) -> Path:
        return directory / f"{self._id(operation_id)}.json"

    def _lock(self, operation_id: str) -> Path:
        return self.locks / f"{self._id(operation_id)}.lock"

    def _read(self, path: Path, operation_id: str) -> dict[str, Any]:
        if path.is_symlink() or not path.is_file():
            raise LabCopyTransactionError(f"LabCopy journal is missing or unsafe: {operation_id}")
        try:
            value = strict_json_read(path)
        except DurableIOError as exc:
            raise LabCopyTransactionError(f"unreadable LabCopy journal: {exc}") from exc
        if not isinstance(value, dict):
            raise LabCopyTransactionError("LabCopy journal must be an object")
        if value.get("operation_id") != operation_id:
            raise LabCopyTransactionError("LabCopy journal identity mismatch")
        if value.get("journal_version") != self.JOURNAL_VERSION:
            raise LabCopyTransactionError("unsupported LabCopy journal version")
        if value.get("record_hash") != self.record_hash(value):
            raise LabCopyTransactionError("LabCopy journal seal mismatch")
        return value

    def reserve(self, record: Mapping[str, Any]) -> dict[str, Any]:
        material = dict(record)
        operation_id = self._id(str(material.get("operation_id") or ""))
        material.update(
            operation_id=operation_id,
            journal_version=self.JOURNAL_VERSION,
            stage="RESERVED",
            created_at=material.get("created_at") or utc_now(),
            updated_at=utc_now(),
        )
        material = self.seal(material)
        try:
            with file_lock(self._lock(operation_id)):
                path = self._path(self.active, operation_id)
                if path.exists() or path.is_symlink():
                    existing = self._read(path, operation_id)
                    if existing != material:
                        raise LabCopyTransactionError("LabCopy operation identity conflict")
                    return existing
                exclusive_json(path, material)
        except DurableIOError as exc:
            raise LabCopyTransactionError(f"LabCopy journal reservation failed: {exc}") from exc
        return material

    def get(self, operation_id: str) -> dict[str, Any]:
        operation_id = self._id(operation_id)
        for directory in (self.active, self.completed, self.reconciliation):
            path = self._path(directory, operation_id)
            if path.exists() or path.is_symlink():
                return self._read(path, operation_id)
        raise LabCopyTransactionError(f"LabCopy journal not found: {operation_id}")

    def update(self, operation_id: str, **changes: Any) -> dict[str, Any]:
        operation_id = self._id(operation_id)
        try:
            with file_lock(self._lock(operation_id)):
                path = self._path(self.active, operation_id)
                value = self._read(path, operation_id)
                for key in (
                    "operation_id", "action_key", "project_id", "section_id", "object_id",
                    "proposal_id", "proposal_hash",
                ):
                    if key in changes and changes[key] != value.get(key):
                        raise LabCopyTransactionError(f"LabCopy journal identity cannot change: {key}")
                value.update(changes)
                value["updated_at"] = utc_now()
                value = self.seal(value)
                atomic_json(path, value)
                return value
        except DurableIOError as exc:
            raise LabCopyTransactionError(f"LabCopy journal update failed: {exc}") from exc

    def pending(self) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for path in sorted(self.active.glob("*.json")):
            result.append(self._read(path, self._id(path.stem)))
        return result

    def _finish(self, operation_id: str, destination: Path, **changes: Any) -> dict[str, Any]:
        operation_id = self._id(operation_id)
        try:
            with file_lock(self._lock(operation_id)):
                source = self._path(self.active, operation_id)
                value = self._read(source, operation_id)
                value.update(changes)
                value["updated_at"] = utc_now()
                value = self.seal(value)
                atomic_json(source, value)
                target = self._path(destination, operation_id)
                if target.exists() or target.is_symlink():
                    raise LabCopyTransactionError("LabCopy terminal journal already exists")
                os.rename(source, target)
                fsync_directory(source.parent)
                fsync_directory(target.parent)
                return self._read(target, operation_id)
        except DurableIOError as exc:
            raise LabCopyTransactionError(f"LabCopy journal completion failed: {exc}") from exc

    def complete(self, operation_id: str, **changes: Any) -> dict[str, Any]:
        return self._finish(operation_id, self.completed, stage=changes.pop("stage", "COMPLETE"), **changes)

    def require_reconciliation(self, operation_id: str, **changes: Any) -> dict[str, Any]:
        return self._finish(
            operation_id,
            self.reconciliation,
            stage="RECONCILIATION_REQUIRED",
            **changes,
        )


class LabCopyRegistry:
    PROPOSAL_SCHEMA = "rvf.labcopy-proposal.v1"
    EXPORT_SCHEMA = "rvf.labcopy-export.v1"
    RESULT_SCHEMA = "rvf.labcopy-result-link.v1"
    PACKAGE_SCHEMA = "rvf.labcopy-package.v1"
    ZIP_TIME = (2026, 7, 21, 0, 0, 0)

    def __init__(self, vault_root: Path | str) -> None:
        self.vault_root = Path(vault_root)
        self.root = self.vault_root / "labcopy"
        self.proposals = _SealedStore(self.vault_root, "labcopy/proposals")
        self.exports = _SealedStore(self.vault_root, "labcopy/exports")
        self.results = _SealedStore(self.vault_root, "labcopy/result_links")
        self.package_dir = self.root / "packages"
        self.failed_dir = self.root / "failed_packages"
        self.lock_dir = self.root / ".locks"
        self.hmac_key_path = self.root / "manifest_hmac.key"
        for directory in (self.root, self.package_dir, self.failed_dir, self.lock_dir):
            if directory.is_symlink():
                raise LabCopyTransactionError(f"LabCopy registry path cannot be a symlink: {directory}")
            directory.mkdir(parents=True, exist_ok=True)

    def _manifest_key(self) -> bytes:
        """Load or create the Wallet-local LabCopy manifest authentication key."""
        path = self.hmac_key_path
        lock_path = self.root / ".manifest_hmac.key.lock"
        with file_lock(lock_path):
            if path.is_symlink():
                raise LabCopyTransactionError("LabCopy HMAC key path cannot be a symlink")
            if path.exists():
                if os.name != "nt" and stat.S_IMODE(path.stat().st_mode) & 0o077:
                    raise LabCopyTransactionError(
                        "LabCopy HMAC key permissions are too broad; expected owner-only access"
                    )
                key = path.read_bytes()
                if len(key) == 32:
                    return key
                # Preserve an interrupted/invalid first key only when no signed exports exist.
                if any(self.exports.root.glob("*.json")):
                    raise LabCopyTransactionError(
                        "LabCopy HMAC key is invalid and signed exports already exist; refusing replacement"
                    )
                self.failed_dir.mkdir(parents=True, exist_ok=True)
                failed = self.failed_dir / f"manifest_hmac.invalid.{uuid4().hex}.key"
                os.replace(path, failed)
                fsync_directory(self.failed_dir)
            key = secrets.token_bytes(32)
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            try:
                fd = os.open(path, flags, 0o600)
            except FileExistsError:
                # Defensive convergence if another compliant process published the
                # key between observation and O_EXCL despite a non-cooperating lock.
                if path.is_symlink():
                    raise LabCopyTransactionError("LabCopy HMAC key path cannot be a symlink")
                if os.name != "nt" and stat.S_IMODE(path.stat().st_mode) & 0o077:
                    raise LabCopyTransactionError(
                        "Concurrent LabCopy HMAC key permissions are too broad"
                    )
                winner = path.read_bytes()
                if len(winner) == 32:
                    return winner
                raise LabCopyTransactionError(
                    "Concurrent LabCopy HMAC key creation produced an invalid key"
                )
            try:
                write_all(fd, key, error_type=LabCopyTransactionError)
                os.fsync(fd)
            finally:
                os.close(fd)
            fsync_directory(path.parent)
            return key

    @staticmethod
    def _manifest_auth_material(manifest: Mapping[str, Any]) -> dict[str, str]:
        return {
            "parent_sha256": str(manifest.get("parent_sha256") or ""),
            "parent_object_id": str(manifest.get("parent_object_id") or ""),
            "export_timestamp": str(manifest.get("export_timestamp") or ""),
        }

    def sign_manifest(self, manifest: Mapping[str, Any]) -> str:
        material = self._manifest_auth_material(manifest)
        if not all(material.values()):
            raise LabCopyTransactionError("LabCopy manifest authentication fields are incomplete")
        return hmac.new(self._manifest_key(), canonical_json(material), hashlib.sha256).hexdigest()

    def verify_manifest(self, manifest: Mapping[str, Any]) -> dict[str, Any]:
        material = self._manifest_auth_material(manifest)
        signature = str(manifest.get("hmac_sha256") or "")
        valid = (
            str(manifest.get("hmac_algorithm") or "") == "HMAC-SHA256"
            and len(signature) == 64
            and all(material.values())
            and hmac.compare_digest(signature, self.sign_manifest(material))
        )
        return {"valid": bool(valid), **material, "hmac_algorithm": "HMAC-SHA256"}

    def _lock(self, lab_id: str) -> Path:
        safe = validate_storage_id("lab_id", lab_id, error_type=LabCopyTransactionError)
        return self.lock_dir / f"{safe}.lock"

    def package_path(self, lab_id: str) -> Path:
        safe = validate_storage_id("lab_id", lab_id, error_type=LabCopyTransactionError)
        return self.package_dir / f"{safe}.iwlab"

    @staticmethod
    def _external_root(vault_root: Path, output_root: Path | str) -> Path:
        root = Path(output_root).expanduser()
        if root.is_symlink():
            raise LabCopyTransactionError("LabCopy output root cannot be a symlink")
        try:
            root = root.resolve(strict=True)
        except OSError as exc:
            raise LabCopyTransactionError("LabCopy output root must already exist") from exc
        if not root.is_dir():
            raise LabCopyTransactionError("LabCopy output root must be a directory")
        try:
            root.relative_to(vault_root.resolve())
        except ValueError:
            pass
        else:
            raise LabCopyTransactionError("LabCopy output must be outside Wallet custody")
        return root

    def create_proposal(
        self,
        *,
        project_id: str,
        section_id: str,
        object_record: Mapping[str, Any],
        output_root: Path | str,
        lab_policy: str,
        requested_label: Optional[str] = None,
        lab_id: Optional[str] = None,
    ) -> dict[str, Any]:
        project_id = validate_storage_id("project_id", project_id, error_type=LabCopyTransactionError)
        section_id = validate_storage_id("section_id", section_id, error_type=LabCopyTransactionError)
        object_id = validate_storage_id(
            "object_id", str(object_record.get("id") or ""), error_type=LabCopyTransactionError
        )
        root = self._external_root(self.vault_root, output_root)
        policy = str(lab_policy or "").strip()
        if not policy or len(policy) > 256 or any(ord(ch) < 32 for ch in policy):
            raise LabCopyTransactionError("lab_policy must be bounded printable text")
        lab_id = validate_storage_id(
            "lab_id", lab_id or f"lab-{uuid4().hex}", error_type=LabCopyTransactionError
        )
        label = portable_basename(
            str(requested_label or object_record.get("name") or "artifact.bin"),
            fallback="artifact.bin",
            max_utf8_bytes=140,
        )
        material = {
            "schema": self.PROPOSAL_SCHEMA,
            "lab_id": lab_id,
            "project_id": project_id,
            "section_id": section_id,
            "object_id": object_id,
            "source_state": str(object_record.get("state") or ""),
            "source_sha256": str(object_record.get("hash") or ""),
            "source_size": int(object_record.get("size_bytes") or 0),
            "source_label": label,
            "output_root": str(root),
            "external_package_path": str(root / f"{lab_id}.iwlab"),
            "lab_policy": policy,
            "execution_inside_wallet": False,
            "return_policy": "wallet_intake_capsule_then_new_candidate_only",
            "created_at": utc_now(),
        }
        core = {k: v for k, v in material.items() if k not in {"created_at"}}
        proposal_hash = sha256_json(core)
        proposal_id = f"labprop-{proposal_hash}"
        material.update(proposal_id=proposal_id, proposal_hash=proposal_hash)
        return self.proposals.create(proposal_id, material)

    def get_proposal(self, proposal_id: str) -> dict[str, Any]:
        return self.proposals.get(proposal_id)

    def _build_package(
        self,
        proposal: Mapping[str, Any],
        source: Path,
    ) -> dict[str, Any]:
        lab_id = str(proposal["lab_id"])
        package = self.package_path(lab_id)
        expected_hash = str(proposal["source_sha256"])
        expected_size = int(proposal["source_size"])
        verified_regular_file(
            source,
            expected_hash=expected_hash,
            expected_size=expected_size,
            error_type=LabCopyTransactionError,
            label="LabCopy source",
        )
        if package.exists() or package.is_symlink():
            digest, size = sha256_file(package)
            export = self.exports.get(lab_id)
            if digest != export.get("package_sha256") or size != int(export.get("package_size") or -1):
                raise LabCopyTransactionError("existing LabCopy package conflicts with registry")
            return export

        manifest = {
            "schema": self.PACKAGE_SCHEMA,
            "lab_id": lab_id,
            "source": {
                "project_id": proposal["project_id"],
                "section_id": proposal["section_id"],
                "object_id": proposal["object_id"],
                "state": proposal["source_state"],
                "sha256": expected_hash,
                "size_bytes": expected_size,
                "label": proposal["source_label"],
            },
            "parent_sha256": expected_hash,
            "parent_object_id": proposal["object_id"],
            "export_timestamp": proposal["created_at"],
            "hmac_algorithm": "HMAC-SHA256",
            "lab_policy": proposal["lab_policy"],
            "created_at": proposal["created_at"],
            "execution_inside_wallet": False,
            "external_execution_authority": "outside_wallet_only",
            "return_policy": proposal["return_policy"],
            "payload_entry": f"payload/{proposal['source_label']}",
            "evidence_limits": (
                "Wallet proves exported bytes and lineage. It does not prove what an external tool "
                "does with the copy or that returned claims are correct."
            ),
        }
        manifest["hmac_sha256"] = self.sign_manifest(manifest)
        manifest_hash = sha256_json(manifest)
        package.parent.mkdir(parents=True, exist_ok=True)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        try:
            fd = os.open(package, flags, 0o600)
        except FileExistsError as exc:
            raise LabCopyTransactionError("LabCopy package appeared during creation") from exc
        source_fd: int | None = None
        try:
            with os.fdopen(fd, "w+b", closefd=True) as file_obj:
                with zipfile.ZipFile(file_obj, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as archive:
                    def add_bytes(name: str, data: bytes) -> None:
                        info = zipfile.ZipInfo(name, self.ZIP_TIME)
                        info.compress_type = zipfile.ZIP_STORED
                        info.create_system = 3
                        info.external_attr = 0o100600 << 16
                        archive.writestr(info, data)

                    add_bytes("manifest.json", canonical_json(manifest) + b"\n")
                    add_bytes(
                        "README.txt",
                        (
                            "Rearview Foresight LabCopy\n"
                            "This package is outside Wallet custody. Wallet does not execute it.\n"
                            "Returned bytes must re-enter as an Intake Capsule and new Candidate.\n"
                        ).encode("utf-8"),
                    )
                    source_flags = os.O_RDONLY
                    if hasattr(os, "O_NOFOLLOW"):
                        source_flags |= os.O_NOFOLLOW
                    source_fd = os.open(source, source_flags)
                    info = os.fstat(source_fd)
                    if not stat.S_ISREG(info.st_mode) or int(info.st_size) != expected_size:
                        raise LabCopyTransactionError("LabCopy source changed before package write")
                    entry = zipfile.ZipInfo(str(manifest["payload_entry"]), self.ZIP_TIME)
                    entry.compress_type = zipfile.ZIP_STORED
                    entry.create_system = 3
                    entry.external_attr = 0o100600 << 16
                    digest = hashlib.sha256()
                    copied = 0
                    with archive.open(entry, "w", force_zip64=True) as output:
                        while True:
                            chunk = os.read(source_fd, 1024 * 1024)
                            if not chunk:
                                break
                            output.write(chunk)
                            digest.update(chunk)
                            copied += len(chunk)
                    if digest.hexdigest() != expected_hash or copied != expected_size:
                        raise LabCopyTransactionError("LabCopy source changed during package write")
                file_obj.flush()
                os.fsync(file_obj.fileno())
        except BaseException:
            # A partial package is evidence of interruption and remains in place.
            raise
        finally:
            if source_fd is not None:
                os.close(source_fd)
        fsync_directory(package.parent)
        package_hash, package_size = sha256_file(package)
        record = {
            "schema": self.EXPORT_SCHEMA,
            "lab_id": lab_id,
            "proposal_id": proposal["proposal_id"],
            "proposal_hash": proposal["proposal_hash"],
            "manifest": manifest,
            "manifest_hash": manifest_hash,
            "package_path": str(package),
            "package_sha256": package_hash,
            "package_size": package_size,
            "external_package_path": proposal["external_package_path"],
            "publication_mode": None,
            "published_at": None,
            "created_at": utc_now(),
        }
        return self.exports.create(lab_id, record)

    def package_and_publish(self, proposal: Mapping[str, Any], source: Path) -> dict[str, Any]:
        lab_id = str(proposal["lab_id"])
        with file_lock(self._lock(lab_id)):
            export = self._build_package(proposal, source)
            package = Path(str(export["package_path"]))
            destination = Path(str(export["external_package_path"]))
            if destination.parent.is_symlink():
                raise LabCopyTransactionError("LabCopy output root became a symlink")
            root = self._external_root(self.vault_root, destination.parent)
            if destination.parent != root:
                raise LabCopyTransactionError("LabCopy output root identity changed")
            if destination.exists() or destination.is_symlink():
                digest, size = sha256_file(destination)
                if digest != export["package_sha256"] or size != int(export["package_size"]):
                    raise LabCopyTransactionError("external LabCopy destination conflicts with this export")
                mode = str(export.get("publication_mode") or "preexisting_verified")
            else:
                mode = publish_no_clobber(
                    package,
                    destination,
                    expected_hash=str(export["package_sha256"]),
                    expected_size=int(export["package_size"]),
                    error_type=LabCopyTransactionError,
                    label="LabCopy package",
                )
            updated = {**export, "publication_mode": mode, "published_at": export.get("published_at") or utc_now()}
            # Export records are write-once; publication is a second sealed record.
            publication = self.exports.create(f"{lab_id}.published", updated)
            return publication

    def get_export(self, lab_id: str) -> dict[str, Any]:
        try:
            return self.exports.get(f"{lab_id}.published")
        except LabCopyTransactionError:
            return self.exports.get(lab_id)

    def link_result(self, *, lab_id: str, capsule: Mapping[str, Any]) -> dict[str, Any]:
        export = self.get_export(lab_id)
        record = {
            "schema": self.RESULT_SCHEMA,
            "lab_id": lab_id,
            "source_object_id": export["manifest"]["source"]["object_id"],
            "source_sha256": export["manifest"]["source"]["sha256"],
            "capsule_id": capsule["capsule_id"],
            "capsule_manifest_hash": capsule["manifest_hash"],
            "blob_sha256": capsule["blob_sha256"],
            "blob_size": capsule["size_bytes"],
            # The capsule capture time is immutable and therefore makes retrying
            # the same semantic result produce the same sealed link record.
            "linked_at": str(capsule["captured_at"]),
            "trust_status": "external_result_untrusted_candidate_only",
        }
        return self.results.create(str(capsule["capsule_id"]), record)

    def get_result_link(self, capsule_id: str) -> dict[str, Any]:
        return self.results.get(capsule_id)


class LabCopyTransactionCoordinator:
    MAX_EXTERNAL_MANIFEST_BYTES = 64 * 1024
    EXPORT_ACTION = "export_working_copy"
    ADMIT_ACTION = "admit_labcopy_result_as_candidate"
    ACTION_LABELS = {
        EXPORT_ACTION: "export a traceable LabCopy outside custody",
        ADMIT_ACTION: "admit a returned LabCopy result as a new Candidate",
    }
    RESULT_EVENTS = {
        EXPORT_ACTION: "LABCOPY_EXPORTED",
        ADMIT_ACTION: "LABCOPY_RESULT_ADMITTED_AS_CANDIDATE",
    }

    def __init__(
        self,
        vault: VaultEngine,
        evidence: CanonicalEvidenceAdapter,
        human_access: NotificationManager,
    ) -> None:
        self.vault = vault
        self.evidence = evidence
        self.human_access = human_access
        self.registry = LabCopyRegistry(vault.root)
        self.capsules = WalletIntakeCapsuleStore(vault.root)
        self.journal = LabCopyJournal(vault.root)
        self.receipts = HumanIntentReceiptStore(vault.root)
        self.lock_dir = Path(vault.root) / "authority_locks" / "labcopy"
        for directory in (self.lock_dir,):
            if directory.is_symlink():
                raise LabCopyTransactionError("LabCopy authority lock cannot be a symlink")
            directory.mkdir(parents=True, exist_ok=True)
        self.evidence.attach_receipt_store(self.receipts)
        self.evidence.register_receipt_verifier(self.EXPORT_ACTION, self.verify_receipt)
        self.evidence.register_receipt_verifier(self.ADMIT_ACTION, self.verify_receipt)

    def capability(self) -> dict[str, Any]:
        return {
            "component": "labcopy",
            "available": True,
            "export": True,
            "result_capture": True,
            "candidate_only_return": True,
            "external_execution": False,
            "automatic_trust": False,
            "manifest_authentication": "HMAC-SHA256",
            "missing_or_invalid_manifest_disposition": "unlinked_raw_source",
            "identical_hash_disposition": "no_op",
        }

    def _scope_lock(self, project_id: str, section_id: str, object_id: str) -> Path:
        return self.lock_dir / f"{sha256_json({'p': project_id, 's': section_id, 'o': object_id})}.lock"

    @staticmethod
    def _ids() -> dict[str, str]:
        return {
            "operation_id": uuid4().hex,
            "receipt_id": uuid4().hex,
            "reserved_event_id": uuid4().hex,
            "authorization_event_id": uuid4().hex,
            "result_event_id": uuid4().hex,
            "terminal_event_id": uuid4().hex,
            "anchor_event_id": uuid4().hex,
        }

    def _append(
        self,
        journal: Mapping[str, Any],
        *,
        stage: str,
        event_type: str,
        id_key: str,
        actor: str,
        summary: str,
        payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        return self.evidence.append_fact(
            event_type=event_type,
            summary=summary,
            event_id=str(journal[id_key]),
            transaction_id=str(journal["operation_id"]),
            stage_key=f"{journal['operation_id']}:{stage}",
            actor=actor,
            subject_id=f"object:{journal['object_id']}",
            payload=payload,
            event_code=stage,
        )

    def _policy(self, action: str, session_id: str) -> tuple[Any, dict[str, Any]]:
        identity = self.human_access.require_identity_session(session_id)
        decision = evaluate_protected_action(
            action,
            ActorKind.HUMAN,
            actor_identity=identity,
            human_ceremony_passed=True,
            gate=self.human_access,
        )
        if not decision.get("allowed"):
            raise LabCopyTransactionError(decision.get("reason", "Human Intent policy denied LabCopy action"))
        return identity, decision

    def export_proposal(
        self,
        *,
        project_id: str,
        section_id: str,
        object_id: str,
        output_root: Path | str,
        lab_policy: str,
        requested_label: Optional[str] = None,
        lab_id: Optional[str] = None,
    ) -> dict[str, Any]:
        with self.vault.catalog_transaction():
            record = self.vault._find_file(project_id, section_id, object_id)
            if record.get("state") not in {"prime", "candidate"}:
                raise LabCopyTransactionError("LabCopy export supports a Prime or Candidate")
            self.vault.assert_canonical_evidence_current(
                project_id=project_id, section_id=section_id, file_id=object_id
            )
            compartment = self.vault._compartment_dir(
                project_id, section_id, self.vault._compartment_for_state(str(record["state"]))
            )
            source = self.vault._require_owned_custody_file(
                record["vault_path"], expected_compartment=compartment, label="LabCopy source"
            )
            digest, size = sha256_file(source)
            if digest != record.get("hash") or size != int(record.get("size_bytes") or -1):
                raise LabCopyTransactionError("LabCopy source no longer matches its custody identity")
            snapshot = dict(record)
        return self.registry.create_proposal(
            project_id=project_id,
            section_id=section_id,
            object_record=snapshot,
            output_root=output_root,
            lab_policy=lab_policy,
            requested_label=requested_label,
            lab_id=lab_id,
        )

    def export(
        self,
        *,
        project_id: str,
        section_id: str,
        object_id: str,
        proposal_id: str,
        proposal_hash: str,
        ceremony_token: str,
        session_id: str,
        reason: str = "",
        fault_after: Optional[str] = None,
    ) -> dict[str, Any]:
        try:
            with self.vault.catalog_transaction():
                with file_lock(self._scope_lock(project_id, section_id, object_id)):
                    return self._export_locked(
                        project_id=project_id,
                        section_id=section_id,
                        object_id=object_id,
                        proposal_id=proposal_id,
                        proposal_hash=proposal_hash,
                        ceremony_token=ceremony_token,
                        session_id=session_id,
                        reason=reason,
                        fault_after=fault_after,
                    )
        except (DurableIOError, VaultError) as exc:
            raise LabCopyTransactionError(f"LabCopy authority lock failed: {exc}") from exc

    def _export_locked(self, **args: Any) -> dict[str, Any]:
        project_id = str(args["project_id"])
        section_id = str(args["section_id"])
        object_id = str(args["object_id"])
        proposal = self.registry.get_proposal(str(args["proposal_id"]))
        if proposal.get("proposal_hash") != args["proposal_hash"]:
            raise LabCopyTransactionError("LabCopy proposal hash mismatch")
        for key, expected in (
            ("project_id", project_id), ("section_id", section_id), ("object_id", object_id)
        ):
            if proposal.get(key) != expected:
                raise LabCopyTransactionError(f"LabCopy proposal {key} mismatch")
        self.vault.assert_canonical_evidence_current(
            project_id=project_id, section_id=section_id, file_id=object_id
        )
        record = self.vault._find_file(project_id, section_id, object_id)
        if record.get("state") != proposal.get("source_state") or record.get("hash") != proposal.get("source_sha256"):
            raise LabCopyTransactionError("LabCopy source changed after proposal creation")
        identity, decision = self._policy(self.EXPORT_ACTION, str(args["session_id"]))
        ids = self._ids()
        journal = self.journal.reserve({
            **ids,
            "action_key": self.EXPORT_ACTION,
            "project_id": project_id,
            "section_id": section_id,
            "object_id": object_id,
            "proposal_id": proposal["proposal_id"],
            "proposal_hash": proposal["proposal_hash"],
            "lab_id": proposal["lab_id"],
            "session_id": args["session_id"],
            "actor_id": identity.actor_id,
            "reason": str(args.get("reason") or ""),
            "policy": decision["policy"],
            "policy_hash": sha256_json(decision["policy"]),
            "receipt_issued_at": utc_now(),
            "source_snapshot": {
                "state": record.get("state"), "hash": record.get("hash"),
                "size_bytes": record.get("size_bytes"), "vault_path": record.get("vault_path"),
            },
            "export_snapshot": dict(proposal),
        })
        actor = f"human:{identity.actor_id}"
        reserved = self._append(
            journal, stage="RESERVED", event_type="HUMAN_INTENT_RESERVED",
            id_key="reserved_event_id", actor=actor,
            summary="Human Intent identifiers reserved for LabCopy export",
            payload={
                "transaction_id": ids["operation_id"], "receipt_id": ids["receipt_id"],
                "action_key": self.EXPORT_ACTION, "project_id": project_id,
                "section_id": section_id, "object_id": object_id,
                "proposal_id": proposal["proposal_id"], "proposal_hash": proposal["proposal_hash"],
                "lab_id": proposal["lab_id"],
            },
        )
        journal = self.journal.update(ids["operation_id"], reserved_event_hash=reserved["event_hash"], stage="RESERVED_RECORDED")
        try:
            token = self.vault._require_open_token(
                str(args["ceremony_token"]), action_key=self.EXPORT_ACTION,
                session_id=str(args["session_id"]), project_id=project_id,
                section_id=section_id, object_id=object_id,
                proposal_id=str(proposal["proposal_id"]), proposal_hash=str(proposal["proposal_hash"]),
            )
            if token.get("legacy_unscoped"):
                raise LabCopyTransactionError("LabCopy export requires an exact proposal-scoped token")
        except Exception as exc:
            self._finalize_failed(journal, actor, f"authorization rejected: {type(exc).__name__}: {exc}")
            raise
        token_id = str(token["token_id"])
        consumption_hash = self.vault.ceremony_ledger.record_hash(token_id)
        journal = self.journal.update(
            ids["operation_id"], ceremony_token_id=token_id,
            ceremony_consumption_hash=consumption_hash, stage="TOKEN_CONSUMED",
        )
        authorized = self._append(
            journal, stage="AUTHORIZED", event_type="HUMAN_INTENT_AUTHORIZED",
            id_key="authorization_event_id", actor=actor,
            summary="Wallet authorized one exact LabCopy export",
            payload={
                "transaction_id": ids["operation_id"], "receipt_id": ids["receipt_id"],
                "reserved_event_hash": reserved["event_hash"], "actor_id": identity.actor_id,
                "session_id": identity.session_id, "action_key": self.EXPORT_ACTION,
                "project_id": project_id, "section_id": section_id, "object_id": object_id,
                "proposal_id": proposal["proposal_id"], "proposal_hash": proposal["proposal_hash"],
                "lab_id": proposal["lab_id"], "ceremony_token_id": token_id,
                "ceremony_consumption_hash": consumption_hash,
                "policy": decision["policy"], "policy_hash": journal["policy_hash"],
            },
        )
        journal = self.journal.update(ids["operation_id"], authorization_event_hash=authorized["event_hash"], stage="AUTHORIZED")
        if args.get("fault_after") == "authorized":
            raise SimulatedLabCopyCrash("authorized")
        compartment = self.vault._compartment_dir(
            project_id, section_id, self.vault._compartment_for_state(str(record["state"]))
        )
        source = self.vault._require_owned_custody_file(
            record["vault_path"], expected_compartment=compartment, label="LabCopy source"
        )
        try:
            exported = self.registry.package_and_publish(proposal, source)
            if args.get("fault_after") == "external_published":
                raise SimulatedLabCopyCrash("external_published")
            return self._finalize_completed(journal, exported, actor=actor, recovered=False)
        except SimulatedLabCopyCrash:
            raise
        except Exception as exc:
            state = self._observe_export(journal)
            if state == "unchanged":
                self._finalize_failed(journal, actor, f"{type(exc).__name__}: {exc}")
            elif state == "ambiguous":
                self._freeze_ambiguous(journal, f"{type(exc).__name__}: {exc}")
            raise

    def _read_external_manifest(self, manifest_path: Path | str | None) -> tuple[dict[str, Any] | None, str]:
        if manifest_path is None:
            return None, "manifest_missing"
        path = Path(manifest_path)
        if path.is_symlink() or not path.is_file():
            return None, "manifest_missing"
        try:
            if path.suffix.lower() == ".iwlab":
                with zipfile.ZipFile(path) as archive:
                    entries = [item for item in archive.infolist() if item.filename == "manifest.json"]
                    if len(entries) != 1 or entries[0].file_size > self.MAX_EXTERNAL_MANIFEST_BYTES:
                        return None, "manifest_invalid"
                    encoded = archive.read(entries[0])
            else:
                if path.stat().st_size > self.MAX_EXTERNAL_MANIFEST_BYTES:
                    return None, "manifest_invalid"
                encoded = path.read_bytes()
            if len(encoded) > self.MAX_EXTERNAL_MANIFEST_BYTES:
                return None, "manifest_invalid"
            manifest = json.loads(encoded.decode("utf-8", errors="strict"))
            if not isinstance(manifest, dict):
                return None, "manifest_invalid"
        except (OSError, UnicodeError, ValueError, KeyError, zipfile.BadZipFile, json.JSONDecodeError):
            return None, "manifest_invalid"
        try:
            verification = self.registry.verify_manifest(manifest)
        except Exception:
            return None, "manifest_invalid"
        if not verification["valid"]:
            return None, "manifest_invalid"
        return manifest, "manifest_valid"

    def classify_reentry(
        self,
        *,
        project_id: str,
        section_id: str,
        result_path: Path | str,
        allowed_root: Path | str,
        manifest_path: Path | str | None,
        source_label: Optional[str] = None,
    ) -> dict[str, Any]:
        """Classify one returned file under the narrowly approved LabCopy rules.

        Invalid or absent linkage never destroys or rejects bytes: it stores them as
        an unlinked Raw Source. Valid changed material is captured as immutable Intake
        and returns an exact Candidate-admission proposal; identical bytes are a no-op.
        """
        result = Path(result_path)
        root_input = Path(allowed_root)
        if root_input.is_symlink():
            raise LabCopyTransactionError("LabCopy allowed_root cannot be a symlink")
        try:
            root = root_input.resolve(strict=True)
        except OSError as exc:
            raise LabCopyTransactionError("LabCopy allowed_root must exist") from exc
        if not root.is_dir():
            raise LabCopyTransactionError("LabCopy allowed_root must be a directory")
        try:
            resolved = result.resolve(strict=True)
            resolved.relative_to(root)
        except (OSError, ValueError) as exc:
            raise LabCopyTransactionError("LabCopy result must be a regular file under allowed_root") from exc
        if result.is_symlink() or not resolved.is_file():
            raise LabCopyTransactionError("LabCopy result must be a non-symlink regular file")
        returned_sha256, returned_size = sha256_file(resolved)
        manifest, manifest_status = self._read_external_manifest(manifest_path)

        def record_event(disposition: str, *, object_id: str | None = None, derived_from: str | None = None):
            return self.evidence.append_fact(
                event_type="LABCOPY_REENTRY",
                summary=f"LabCopy re-entry classified as {disposition}",
                actor="human:labcopy_reentry",
                subject_id=f"object:{object_id}" if object_id else f"sha256:{returned_sha256}",
                payload={
                    "disposition": disposition,
                    "manifest_status": manifest_status,
                    "returned_sha256": returned_sha256,
                    "returned_size": returned_size,
                    "object_id": object_id,
                    "derived_from_hash": derived_from,
                    "automatic_trust": False,
                },
                event_code="REENTRY",
            )

        if manifest is None:
            raw = self.vault.add_raw_source(
                project_id, section_id, str(resolved),
                notes=f"LabCopy re-entry preserved as unlinked Raw Source: {manifest_status}",
            )
            with self.vault.catalog_transaction():
                stored = self.vault._find_file(project_id, section_id, str(raw["id"]))
                stored["origin"] = "labcopy_unlinked_reentry"
                stored["link_status"] = "unlinked"
                stored["link_failure_reason"] = manifest_status
                self.vault._save()
                raw = stored
            event = record_event("unlinked_raw_source", object_id=str(raw["id"]))
            return {"disposition": "unlinked_raw_source", "result": raw, "canonical_event": event}

        parent_id = str(manifest["parent_object_id"])
        parent_sha = str(manifest["parent_sha256"])
        try:
            parent = self.vault._find_file(project_id, section_id, parent_id)
        except Exception:
            parent = None
        if parent is None or str(parent.get("hash") or "") != parent_sha:
            manifest_status = "manifest_parent_mismatch"
            raw = self.vault.add_raw_source(
                project_id, section_id, str(resolved),
                notes="LabCopy re-entry preserved as unlinked Raw Source: manifest parent mismatch",
            )
            with self.vault.catalog_transaction():
                stored = self.vault._find_file(project_id, section_id, str(raw["id"]))
                stored["origin"] = "labcopy_unlinked_reentry"
                stored["link_status"] = "unlinked"
                stored["link_failure_reason"] = manifest_status
                self.vault._save()
                raw = stored
            event = record_event("unlinked_raw_source", object_id=str(raw["id"]))
            return {"disposition": "unlinked_raw_source", "result": raw, "canonical_event": event}

        if returned_sha256 == parent_sha:
            event = record_event("no_op_identical_hash", object_id=parent_id, derived_from=parent_sha)
            return {
                "disposition": "no_op_identical_hash",
                "result": parent,
                "derived_from_hash": parent_sha,
                "canonical_event": event,
            }

        lab_id = str(manifest.get("lab_id") or "")
        try:
            export = self.registry.get_export(lab_id)
        except (LabCopyTransactionError, OSError, KeyError, ValueError):
            export = None
        if export is None or export.get("manifest_hash") != sha256_json(manifest):
            # A valid HMAC proves only the three approved linkage fields. Missing,
            # malformed, foreign, or otherwise unresolvable local-export metadata
            # must demote to Raw Source rather than turning re-entry into rejection.
            manifest_status = "manifest_export_mismatch"
            raw = self.vault.add_raw_source(
                project_id, section_id, str(resolved),
                notes="LabCopy re-entry preserved as unlinked Raw Source: export mismatch",
            )
            with self.vault.catalog_transaction():
                stored = self.vault._find_file(project_id, section_id, str(raw["id"]))
                stored["origin"] = "labcopy_unlinked_reentry"
                stored["link_status"] = "unlinked"
                stored["link_failure_reason"] = manifest_status
                self.vault._save()
                raw = stored
            event = record_event("unlinked_raw_source", object_id=str(raw["id"]))
            return {"disposition": "unlinked_raw_source", "result": raw, "canonical_event": event}

        captured = self.capture_result(
            lab_id=lab_id,
            result_path=resolved,
            allowed_root=root,
            source_label=source_label or resolved.name,
            external_assertions=[],
        )
        proposal = self.result_admission_proposal(
            lab_id=lab_id, capsule_id=str(captured["capsule"]["capsule_id"])
        )
        event = record_event("candidate_pending_authorization", derived_from=parent_sha)
        return {
            "disposition": "candidate_pending_authorization",
            "capsule": captured["capsule"],
            "proposal": proposal,
            "derived_from_hash": parent_sha,
            "canonical_event": event,
        }

    def capture_result(
        self,
        *,
        lab_id: str,
        result_path: Path | str,
        allowed_root: Path | str,
        source_label: Optional[str] = None,
        external_assertions: Optional[list[Mapping[str, Any]]] = None,
    ) -> dict[str, Any]:
        export = self.registry.get_export(lab_id)
        source = export["manifest"]["source"]
        assertions = [
            {
                "type": "labcopy_result",
                "lab_id": lab_id,
                "labcopy_manifest_hash": export["manifest_hash"],
                "labcopy_package_sha256": export["package_sha256"],
                "claim": "returned bytes were supplied from the declared external LabCopy workflow",
            },
            *(external_assertions or []),
        ]
        try:
            capsule = self.capsules.capture(
                project_id=str(source["project_id"]),
                section_id=str(source["section_id"]),
                parent_object_id=str(source["object_id"]),
                parent_sha256=str(source["sha256"]),
                source_path=result_path,
                allowed_root=allowed_root,
                source_label=source_label,
                external_assertions=assertions,
            )
        except IntakeCapsuleError as exc:
            raise LabCopyTransactionError(str(exc)) from exc
        link = self.registry.link_result(lab_id=lab_id, capsule=capsule)
        event = self.evidence.append_fact(
            event_type="LABCOPY_RESULT_CAPTURED_AS_INTAKE",
            summary="External LabCopy result preserved as an untrusted Wallet Intake Capsule",
            actor="wallet:labcopy",
            subject_id=f"capsule:{capsule['capsule_id']}",
            payload={
                "lab_id": lab_id,
                "source_object_id": source["object_id"],
                "capsule_id": capsule["capsule_id"],
                "manifest_hash": capsule["manifest_hash"],
                "blob_sha256": capsule["blob_sha256"],
                "trust_status": "untrusted_intake_no_automatic_trust",
                "external_assertions_are_not_direct_evidence": True,
            },
            event_code="CAP",
        )
        return {"capsule": capsule, "link": link, "canonical_event": event}

    def result_admission_proposal(self, *, lab_id: str, capsule_id: str) -> dict[str, Any]:
        export = self.registry.get_export(lab_id)
        capsule = self.capsules.get(capsule_id)
        link = self.registry.get_result_link(capsule_id)
        source = export["manifest"]["source"]
        if link.get("lab_id") != lab_id or capsule.get("parent_object_id") != source["object_id"]:
            raise LabCopyTransactionError("LabCopy result capsule lineage mismatch")
        material = {
            "schema": "rvf.labcopy-result-admission-proposal.v1",
            "action_key": self.ADMIT_ACTION,
            "lab_id": lab_id,
            "project_id": source["project_id"],
            "section_id": source["section_id"],
            "object_id": source["object_id"],
            "source_sha256": source["sha256"],
            "capsule_id": capsule["capsule_id"],
            "capsule_manifest_hash": capsule["manifest_hash"],
            "blob_sha256": capsule["blob_sha256"],
            "blob_size": capsule["size_bytes"],
            "candidate_id": f"labcand-{hashlib.sha256(canonical_json({'lab_id': lab_id, 'capsule_id': capsule_id})).hexdigest()}",
            "trust_status": "candidate_only_no_automatic_trust",
        }
        proposal_hash = sha256_json(material)
        proposal_id = f"labadmit-{proposal_hash}"
        return self.registry.proposals.create(
            proposal_id,
            {
                **material,
                "proposal_id": proposal_id,
                "proposal_hash": proposal_hash,
                # The immutable capsule capture timestamp keeps semantic retries
                # byte-identical instead of poisoning a write-once proposal.
                "created_at": str(capsule["captured_at"]),
            },
        )

    def admit_result(
        self,
        *,
        lab_id: str,
        capsule_id: str,
        proposal_id: str,
        proposal_hash: str,
        ceremony_token: str,
        session_id: str,
        reason: str = "",
        fault_after: Optional[str] = None,
    ) -> dict[str, Any]:
        proposal = self.registry.proposals.get(proposal_id)
        if proposal.get("action_key") != self.ADMIT_ACTION or proposal.get("lab_id") != lab_id:
            raise LabCopyTransactionError("LabCopy result admission proposal scope mismatch")
        if proposal.get("capsule_id") != capsule_id or proposal.get("proposal_hash") != proposal_hash:
            raise LabCopyTransactionError("LabCopy result admission proposal identity mismatch")
        project_id, section_id, object_id = (
            str(proposal["project_id"]), str(proposal["section_id"]), str(proposal["object_id"])
        )
        try:
            with self.vault.catalog_transaction():
                with file_lock(self._scope_lock(project_id, section_id, object_id)):
                    return self._admit_locked(
                        proposal=proposal,
                        ceremony_token=ceremony_token,
                        session_id=session_id,
                        reason=reason,
                        fault_after=fault_after,
                    )
        except (DurableIOError, VaultError) as exc:
            raise LabCopyTransactionError(f"LabCopy admission authority lock failed: {exc}") from exc

    def _admit_locked(
        self,
        *,
        proposal: Mapping[str, Any],
        ceremony_token: str,
        session_id: str,
        reason: str,
        fault_after: Optional[str],
    ) -> dict[str, Any]:
        project_id, section_id, object_id = (
            str(proposal["project_id"]), str(proposal["section_id"]), str(proposal["object_id"])
        )
        source_record = self.vault._find_file(project_id, section_id, object_id)
        if source_record.get("hash") != proposal.get("source_sha256"):
            raise LabCopyTransactionError("LabCopy parent changed after result proposal creation")
        capsule = self.capsules.get(str(proposal["capsule_id"]))
        if (
            capsule.get("manifest_hash") != proposal.get("capsule_manifest_hash")
            or capsule.get("blob_sha256") != proposal.get("blob_sha256")
            or int(capsule.get("size_bytes") or -1) != int(proposal.get("blob_size") or -2)
        ):
            raise LabCopyTransactionError("LabCopy result capsule changed after proposal creation")
        identity, decision = self._policy(self.ADMIT_ACTION, session_id)
        ids = self._ids()
        journal = self.journal.reserve({
            **ids,
            "action_key": self.ADMIT_ACTION,
            "project_id": project_id,
            "section_id": section_id,
            "object_id": object_id,
            "proposal_id": proposal["proposal_id"],
            "proposal_hash": proposal["proposal_hash"],
            "lab_id": proposal["lab_id"],
            "capsule_id": proposal["capsule_id"],
            "candidate_id": proposal["candidate_id"],
            "session_id": session_id,
            "actor_id": identity.actor_id,
            "reason": reason,
            "policy": decision["policy"],
            "policy_hash": sha256_json(decision["policy"]),
            "receipt_issued_at": utc_now(),
        })
        actor = f"human:{identity.actor_id}"
        reserved = self._append(
            journal, stage="RESERVED", event_type="HUMAN_INTENT_RESERVED",
            id_key="reserved_event_id", actor=actor,
            summary="Human Intent identifiers reserved for LabCopy result admission",
            payload={
                "transaction_id": ids["operation_id"], "receipt_id": ids["receipt_id"],
                "action_key": self.ADMIT_ACTION, "project_id": project_id,
                "section_id": section_id, "object_id": object_id,
                "proposal_id": proposal["proposal_id"], "proposal_hash": proposal["proposal_hash"],
                "lab_id": proposal["lab_id"], "capsule_id": proposal["capsule_id"],
                "candidate_id": proposal["candidate_id"],
            },
        )
        journal = self.journal.update(ids["operation_id"], reserved_event_hash=reserved["event_hash"], stage="RESERVED_RECORDED")
        try:
            token = self.vault._require_open_token(
                ceremony_token, action_key=self.ADMIT_ACTION, session_id=session_id,
                project_id=project_id, section_id=section_id, object_id=object_id,
                proposal_id=str(proposal["proposal_id"]), proposal_hash=str(proposal["proposal_hash"]),
            )
            if token.get("legacy_unscoped"):
                raise LabCopyTransactionError("LabCopy admission requires an exact proposal-scoped token")
        except Exception as exc:
            self._finalize_failed(journal, actor, f"authorization rejected: {type(exc).__name__}: {exc}")
            raise
        token_id = str(token["token_id"])
        consumption_hash = self.vault.ceremony_ledger.record_hash(token_id)
        journal = self.journal.update(
            ids["operation_id"], ceremony_token_id=token_id,
            ceremony_consumption_hash=consumption_hash, stage="TOKEN_CONSUMED",
        )
        authorized = self._append(
            journal, stage="AUTHORIZED", event_type="HUMAN_INTENT_AUTHORIZED",
            id_key="authorization_event_id", actor=actor,
            summary="Wallet authorized one exact LabCopy result admission",
            payload={
                "transaction_id": ids["operation_id"], "receipt_id": ids["receipt_id"],
                "reserved_event_hash": reserved["event_hash"], "actor_id": identity.actor_id,
                "session_id": identity.session_id, "action_key": self.ADMIT_ACTION,
                "project_id": project_id, "section_id": section_id, "object_id": object_id,
                "proposal_id": proposal["proposal_id"], "proposal_hash": proposal["proposal_hash"],
                "lab_id": proposal["lab_id"], "capsule_id": proposal["capsule_id"],
                "candidate_id": proposal["candidate_id"], "ceremony_token_id": token_id,
                "ceremony_consumption_hash": consumption_hash,
                "policy": decision["policy"], "policy_hash": journal["policy_hash"],
            },
        )
        journal = self.journal.update(ids["operation_id"], authorization_event_hash=authorized["event_hash"], stage="AUTHORIZED")
        if fault_after == "authorized":
            raise SimulatedLabCopyCrash("authorized")
        try:
            result = self.vault._admit_labcopy_capsule_unchecked(
                project_id, section_id, object_id,
                capsule_path=str(capsule["absolute_blob_path"]),
                capsule_id=str(capsule["capsule_id"]),
                manifest_hash=str(capsule["manifest_hash"]),
                blob_sha256=str(capsule["blob_sha256"]),
                blob_size=int(capsule["size_bytes"]),
                source_label=str(capsule["source_label"]),
                candidate_id=str(proposal["candidate_id"]),
                lab_id=str(proposal["lab_id"]),
                transaction_id=ids["operation_id"],
                reason=reason,
                fault_hook=(lambda stage: (_ for _ in ()).throw(SimulatedLabCopyCrash(stage))) if fault_after else None,
                fault_stage=fault_after,
            )
            return self._finalize_completed(journal, result, actor=actor, recovered=False)
        except SimulatedLabCopyCrash:
            raise
        except Exception as exc:
            state = self._observe_admission(journal)
            if state == "unchanged":
                self._finalize_failed(journal, actor, f"{type(exc).__name__}: {exc}")
            elif state == "ambiguous":
                self._freeze_ambiguous(journal, f"{type(exc).__name__}: {exc}")
            raise

    def _observe_export(self, journal: Mapping[str, Any]) -> str:
        try:
            export = self.registry.get_export(str(journal["lab_id"]))
            package = Path(str(export["package_path"]))
            external = Path(str(export["external_package_path"]))
            pd, ps = sha256_file(package)
            if pd != export["package_sha256"] or ps != int(export["package_size"]):
                return "ambiguous"
            if not external.exists():
                return "package_ready"
            ed, es = sha256_file(external)
            return "complete" if (ed, es) == (pd, ps) else "ambiguous"
        except LabCopyTransactionError:
            return "unchanged"

    def _observe_admission(self, journal: Mapping[str, Any]) -> str:
        try:
            candidate = self.vault._find_file(
                str(journal["project_id"]), str(journal["section_id"]), str(journal["candidate_id"])
            )
        except VaultError:
            return "unchanged"
        if (
            candidate.get("state") == "candidate"
            and candidate.get("labcopy_id") == journal.get("lab_id")
            and candidate.get("wallet_intake_capsule_id") == journal.get("capsule_id")
            and (
                candidate.get("admission_operation_id") == journal.get("operation_id")
                or journal.get("operation_id") in (candidate.get("admission_operation_ids") or [])
            )
        ):
            return "complete"
        return "ambiguous"

    def _finalize_completed(
        self,
        journal: Mapping[str, Any],
        result: Mapping[str, Any],
        *,
        actor: str,
        recovered: bool,
    ) -> dict[str, Any]:
        operation_id = str(journal["operation_id"])
        if "completion_recovered_after_restart" not in journal:
            journal = self.journal.update(
                operation_id, completion_recovered_after_restart=bool(recovered)
            )
        recovered = bool(journal["completion_recovered_after_restart"])
        event_type = self.RESULT_EVENTS[str(journal["action_key"])]
        result_event = self._append(
            journal, stage="RESULT", event_type=event_type,
            id_key="result_event_id", actor=actor,
            summary=(
                "Traceable LabCopy published outside custody"
                if journal["action_key"] == self.EXPORT_ACTION
                else "Returned LabCopy result admitted as a new Candidate"
            ),
            payload={
                "transaction_id": operation_id,
                "authorization_event_hash": journal["authorization_event_hash"],
                "project_id": journal["project_id"], "section_id": journal["section_id"],
                "object_id": journal["object_id"], "lab_id": journal["lab_id"],
                "proposal_id": journal["proposal_id"], "proposal_hash": journal["proposal_hash"],
                "result": dict(result), "recovered_after_restart": recovered,
                "external_execution_performed_by_wallet": False,
                "automatic_trust_granted": False,
            },
        )
        journal = self.journal.update(operation_id, result_event_hash=result_event["event_hash"], stage="RESULT_RECORDED")
        terminal = self._append(
            journal, stage="COMPLETED", event_type="HUMAN_INTENT_COMPLETED",
            id_key="terminal_event_id", actor=actor,
            summary="Protected LabCopy transaction completed",
            payload={
                "transaction_id": operation_id,
                "authorization_event_hash": journal["authorization_event_hash"],
                "result_event_hash": result_event["event_hash"],
                "result_status": "completed", "project_id": journal["project_id"],
                "section_id": journal["section_id"], "object_id": journal["object_id"],
                "recovered_after_restart": recovered,
            },
        )
        journal = self.journal.update(operation_id, terminal_event_hash=terminal["event_hash"], stage="COMPLETED_RECORDED")
        receipt = {
            "receipt_id": journal["receipt_id"],
            "receipt_type": "human_intent_receipt_v2",
            "issued_at": journal["receipt_issued_at"],
            "operation_id": operation_id,
            "action_key": journal["action_key"],
            "action_label": self.ACTION_LABELS[str(journal["action_key"])],
            "project_id": journal["project_id"], "section_id": journal["section_id"],
            "object_id": journal["object_id"], "lab_id": journal["lab_id"],
            "proposal_id": journal["proposal_id"], "proposal_hash": journal["proposal_hash"],
            "actor_id": journal["actor_id"], "actor": actor, "session_id": journal["session_id"],
            "ceremony_token_id": journal["ceremony_token_id"],
            "ceremony_consumption_hash": journal["ceremony_consumption_hash"],
            "policy_hash": journal["policy_hash"],
            "reserved_event_id": journal["reserved_event_id"], "reserved_event_hash": journal["reserved_event_hash"],
            "authorization_event_id": journal["authorization_event_id"], "authorization_event_hash": journal["authorization_event_hash"],
            "result_event_id": result_event["event_id"], "result_event_hash": result_event["event_hash"],
            "terminal_event_id": terminal["event_id"], "terminal_event_hash": terminal["event_hash"],
            "anchor_event_id": journal["anchor_event_id"],
            "result_status": "completed", "recovered_after_restart": recovered,
            "intent_statement": "A Wallet-authorized local human identity session completed this exact LabCopy transition.",
            "evidence_limits": "Local continuity evidence; external laboratory behavior and claims are not independently witnessed.",
        }
        receipt_hash = HumanIntentReceiptStore.core_hash(receipt)
        anchor = self._append(
            journal, stage="RECEIPT_ANCHORED", event_type="HUMAN_INTENT_RECEIPT_ANCHORED",
            id_key="anchor_event_id", actor=actor,
            summary="Portable LabCopy Human Intent receipt anchored",
            payload={
                "transaction_id": operation_id, "receipt_id": journal["receipt_id"],
                "receipt_hash": receipt_hash,
                "authorization_event_hash": journal["authorization_event_hash"],
                "terminal_event_hash": terminal["event_hash"],
                "ceremony_consumption_hash": journal["ceremony_consumption_hash"],
            },
        )
        receipt["anchor_event_hash"] = anchor["event_hash"]
        stored = self.receipts.create(receipt)
        verification = self.verify_receipt(str(stored["receipt_id"]))
        if not verification.get("ok"):
            raise LabCopyTransactionError(f"LabCopy receipt failed verification: {verification.get('reason')}")
        self.journal.complete(
            operation_id, receipt_id=stored["receipt_id"], receipt_hash=stored["receipt_hash"],
            anchor_event_hash=anchor["event_hash"], recovered_after_restart=recovered,
        )
        return {"result": dict(result), "receipt": stored, "verification": verification}

    def _finalize_failed(self, journal: Mapping[str, Any], actor: str, reason: str) -> None:
        terminal = self._append(
            journal, stage="FAILED", event_type="HUMAN_INTENT_FAILED",
            id_key="terminal_event_id", actor=actor,
            summary="Protected LabCopy transaction failed before a proven result",
            payload={
                "transaction_id": journal["operation_id"],
                "authorization_event_hash": journal.get("authorization_event_hash"),
                "result_status": "failed", "reason_class": reason[:200],
            },
        )
        self.journal.complete(
            str(journal["operation_id"]), stage="FAILED",
            terminal_event_hash=terminal["event_hash"], failure_reason=reason[:500],
        )

    def _freeze_ambiguous(self, journal: Mapping[str, Any], reason: str) -> None:
        with self.vault.catalog_transaction():
            section = self.vault._get_section_loaded(
                str(journal["project_id"]), str(journal["section_id"])
            )
            section["reconciliation_required"] = True
            section["reconciliation_operation_id"] = journal["operation_id"]
        event = self.evidence.append_fact(
            event_type="LABCOPY_RECONCILIATION_REQUIRED",
            summary="LabCopy state is ambiguous; automatic completion is frozen",
            actor="wallet:reconciler", transaction_id=str(journal["operation_id"]),
            stage_key=f"{journal['operation_id']}:RECONCILIATION_REQUIRED",
            subject_id=f"object:{journal['object_id']}",
            payload={
                "transaction_id": journal["operation_id"], "action_key": journal["action_key"],
                "project_id": journal["project_id"], "section_id": journal["section_id"],
                "object_id": journal["object_id"], "reason_class": reason[:200],
                "coverage_gap": True,
            },
        )
        self.journal.require_reconciliation(
            str(journal["operation_id"]), reconciliation_event_hash=event["event_hash"],
            reason=reason[:500],
        )

    def reconcile_pending(self) -> dict[str, Any]:
        report = {"checked": 0, "reconciled": 0, "failed": 0, "ambiguous": 0, "receipts": []}
        for item in self.journal.pending():
            report["checked"] += 1
            try:
                with self.vault.catalog_transaction():
                    with file_lock(self._scope_lock(str(item["project_id"]), str(item["section_id"]), str(item["object_id"]))):
                        journal = self.journal.get(str(item["operation_id"]))
                        actor = f"human:{journal.get('actor_id') or 'unknown'}"
                        if journal["action_key"] == self.EXPORT_ACTION:
                            state = self._observe_export(journal)
                            if state == "package_ready":
                                proposal = self.registry.get_proposal(str(journal["proposal_id"]))
                                source_record = self.vault._find_file(
                                    str(journal["project_id"]), str(journal["section_id"]), str(journal["object_id"])
                                )
                                compartment = self.vault._compartment_dir(
                                    str(journal["project_id"]), str(journal["section_id"]),
                                    self.vault._compartment_for_state(str(source_record["state"])),
                                )
                                source = self.vault._require_owned_custody_file(
                                    source_record["vault_path"], expected_compartment=compartment, label="LabCopy source"
                                )
                                self.registry.package_and_publish(proposal, source)
                                state = "complete"
                            if state == "complete":
                                completed = self._finalize_completed(
                                    journal, self.registry.get_export(str(journal["lab_id"])), actor=actor, recovered=True
                                )
                                report["reconciled"] += 1
                                report["receipts"].append(completed["receipt"]["receipt_id"])
                            elif state == "unchanged":
                                self._finalize_failed(journal, actor, "restart observed no LabCopy result")
                                report["failed"] += 1
                            else:
                                self._freeze_ambiguous(journal, "restart could not prove LabCopy export")
                                report["ambiguous"] += 1
                        else:
                            state = self._observe_admission(journal)
                            if state == "complete":
                                candidate = self.vault._find_file(
                                    str(journal["project_id"]), str(journal["section_id"]), str(journal["candidate_id"])
                                )
                                completed = self._finalize_completed(journal, candidate, actor=actor, recovered=True)
                                report["reconciled"] += 1
                                report["receipts"].append(completed["receipt"]["receipt_id"])
                            elif state == "unchanged":
                                self._finalize_failed(journal, actor, "restart observed no Candidate admission")
                                report["failed"] += 1
                            else:
                                self._freeze_ambiguous(journal, "restart could not prove LabCopy Candidate admission")
                                report["ambiguous"] += 1
            except Exception as exc:
                raise LabCopyTransactionError(f"LabCopy reconciliation failed: {exc}") from exc
        return report

    def verify_receipt(self, receipt_id: str) -> dict[str, Any]:
        try:
            receipt = self.receipts.get(receipt_id)
        except CanonicalEvidenceError as exc:
            return {"ok": False, "status": "invalid", "reason": str(exc)}
        if receipt.get("receipt_hash") != HumanIntentReceiptStore.core_hash(receipt):
            return {"ok": False, "status": "invalid", "reason": "receipt hash mismatch"}
        chain = self.evidence.verify_chain()
        if not chain.get("ok"):
            return {"ok": False, "status": "invalid", "reason": "canonical BlackBox chain invalid"}
        result_type = self.RESULT_EVENTS.get(str(receipt.get("action_key")))
        if not result_type:
            return {"ok": False, "status": "invalid", "reason": "unknown LabCopy receipt action"}
        expected = [
            ("reserved_event_id", "reserved_event_hash", "HUMAN_INTENT_RESERVED"),
            ("authorization_event_id", "authorization_event_hash", "HUMAN_INTENT_AUTHORIZED"),
            ("result_event_id", "result_event_hash", result_type),
            ("terminal_event_id", "terminal_event_hash", "HUMAN_INTENT_COMPLETED"),
            ("anchor_event_id", "anchor_event_hash", "HUMAN_INTENT_RECEIPT_ANCHORED"),
        ]
        records = []
        for id_key, hash_key, event_type in expected:
            record = self.evidence.record_by_id(str(receipt.get(id_key) or ""))
            if not record or record.get("hash") != receipt.get(hash_key) or record.get("event_type") != event_type:
                return {"ok": False, "status": "invalid", "reason": f"invalid {event_type} stage"}
            if (record.get("payload") or {}).get("transaction_id") != receipt.get("operation_id"):
                return {"ok": False, "status": "invalid", "reason": f"{event_type} transaction mismatch"}
            records.append(record)
        if [int(record["seq"]) for record in records] != sorted(int(record["seq"]) for record in records):
            return {"ok": False, "status": "invalid", "reason": "receipt graph out of order"}
        auth, result, terminal, anchor = (records[1]["payload"], records[2]["payload"], records[3]["payload"], records[4]["payload"])
        for key in ("project_id", "section_id", "object_id", "proposal_id", "proposal_hash", "lab_id"):
            if auth.get(key) != receipt.get(key):
                return {"ok": False, "status": "invalid", "reason": f"authorization {key} mismatch"}
        if result.get("authorization_event_hash") != receipt.get("authorization_event_hash"):
            return {"ok": False, "status": "invalid", "reason": "result authorization link mismatch"}
        if terminal.get("result_event_hash") != receipt.get("result_event_hash"):
            return {"ok": False, "status": "invalid", "reason": "terminal result link mismatch"}
        if anchor.get("receipt_hash") != receipt.get("receipt_hash") or anchor.get("receipt_id") != receipt.get("receipt_id"):
            return {"ok": False, "status": "invalid", "reason": "anchor receipt binding mismatch"}
        try:
            token = self.vault.ceremony_ledger.get_record(str(receipt["ceremony_token_id"]), include_hash=True)
            token_hash = self.vault.ceremony_ledger.record_hash(str(receipt["ceremony_token_id"]))
        except Exception as exc:
            return {"ok": False, "status": "invalid", "reason": f"ceremony record unavailable: {exc}"}
        if token_hash != receipt.get("ceremony_consumption_hash"):
            return {"ok": False, "status": "invalid", "reason": "ceremony consumption hash mismatch"}
        for key in ("action_key", "session_id", "project_id", "section_id", "object_id", "proposal_id", "proposal_hash"):
            if token.get(key) != receipt.get(key):
                return {"ok": False, "status": "invalid", "reason": f"ceremony {key} mismatch"}
        if not token.get("consumed_at") or token.get("consumed_by_action") != receipt.get("action_key"):
            return {"ok": False, "status": "invalid", "reason": "ceremony token not consumed for receipt action"}
        operation_records = self.evidence.records_for_operation(str(receipt["operation_id"]))
        required_ids = {str(receipt[k]) for k, _, _ in expected}
        graph_types = {event_type for _, _, event_type in expected}
        graph = [r for r in operation_records if r.get("event_type") in graph_types | {"HUMAN_INTENT_FAILED", "LABCOPY_RECONCILIATION_REQUIRED"}]
        if any(r.get("event_type") in {"HUMAN_INTENT_FAILED", "LABCOPY_RECONCILIATION_REQUIRED"} for r in graph):
            return {"ok": False, "status": "invalid", "reason": "receipt graph contains contradictory stage"}
        if {str(r.get("record_id")) for r in graph} != required_ids:
            return {"ok": False, "status": "invalid", "reason": "receipt graph is incomplete, duplicated, or contains extra stages"}
        return {
            "ok": True, "status": "complete", "receipt_id": receipt_id,
            "operation_id": receipt["operation_id"], "chain": chain,
            "evidence_limit": receipt.get("evidence_limits"),
        }
