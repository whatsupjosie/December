"""Strict allowlist cleaner for Iteration Wallet operating residue.

This is the only production module authorized to physically clean files, and
only inside its dedicated runtime-residue roots.  Protected content, evidence,
recovery artifacts, backups, exports, and unclassified paths are outside this
module's authority.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import stat
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping
from uuid import uuid4

from iteration_wallet.durable_io import atomic_json, ensure_within, fsync_directory, strict_json_read
from iteration_wallet.custody_io import ensure_private_directory


class RuntimeResidueError(RuntimeError):
    """Raised when residue ownership or identity cannot be proven."""


RESIDUE_CLASSES = frozenset(
    {
        "atomic_write_temp",
        "render_cache",
        "thumbnail_cache",
        "expired_ui_session",
        "stale_lock",
        "installer_scratch",
        "update_download",
        "diagnostic_scratch",
    }
)

AUTOMATIC_CLASSES = frozenset(
    {
        "atomic_write_temp",
        "render_cache",
        "thumbnail_cache",
        "expired_ui_session",
        "stale_lock",
        "installer_scratch",
    }
)

MARKER_SCHEMA = "iteration-wallet-runtime-residue/1"
RECEIPT_SCHEMA = "iteration-wallet-runtime-cleanup-receipt/1"


def _now() -> int:
    return int(datetime.now(timezone.utc).timestamp())


def _iso(timestamp: int | None = None) -> str:
    value = _now() if timestamp is None else int(timestamp)
    return datetime.fromtimestamp(value, timezone.utc).replace(microsecond=0).isoformat()


def _canonical(value: Mapping[str, Any]) -> bytes:
    return json.dumps(dict(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode):
            raise RuntimeResidueError("runtime residue must be one regular file")
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    finally:
        os.close(descriptor)
    return digest.hexdigest()


@dataclass(frozen=True)
class ResidueCandidate:
    marker_path: str
    artifact_path: str
    residue_class: str
    size: int
    sha256: str
    safe_after: int
    marker_signature: str
    marker_size: int
    marker_sha256: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "marker_path": self.marker_path,
            "artifact_path": self.artifact_path,
            "residue_class": self.residue_class,
            "size": self.size,
            "sha256": self.sha256,
            "safe_after": self.safe_after,
            "marker_signature": self.marker_signature,
            "marker_size": self.marker_size,
            "marker_sha256": self.marker_sha256,
        }


class RuntimeResidueRegistry:
    """Register, plan, and clean only explicitly owned operating artifacts."""

    def __init__(self, wallet_root: Path | str) -> None:
        self.wallet_root = Path(wallet_root).expanduser().resolve()
        self.root = self.wallet_root / "runtime_residue"
        self.receipt_root = self.wallet_root / "receipts" / "runtime_cleanup"
        self.security_root = self.wallet_root / "security"
        self.secret_path = self.security_root / "runtime_residue_secret.json"
        for directory, label in (
            (self.root, "runtime residue root"),
            (self.receipt_root, "runtime cleanup receipt root"),
            (self.security_root, "runtime residue security root"),
        ):
            ensure_private_directory(directory, error_type=RuntimeResidueError, label=label)
        for residue_class in RESIDUE_CLASSES:
            ensure_private_directory(
                self.root / residue_class,
                error_type=RuntimeResidueError,
                label=f"runtime residue class {residue_class}",
            )
        self._secret = self._load_or_create_secret()

    def _load_or_create_secret(self) -> bytes:
        if self.secret_path.exists():
            value = strict_json_read(self.secret_path)
            if not isinstance(value, dict) or value.get("schema") != "iteration-wallet-runtime-residue-secret/1":
                raise RuntimeResidueError("runtime residue secret record is malformed")
            try:
                secret = bytes.fromhex(str(value.get("secret_hex") or ""))
            except ValueError as exc:
                raise RuntimeResidueError("runtime residue secret is malformed") from exc
            if len(secret) != 32:
                raise RuntimeResidueError("runtime residue secret has an invalid length")
            return secret
        secret = secrets.token_bytes(32)
        atomic_json(
            self.secret_path,
            {
                "schema": "iteration-wallet-runtime-residue-secret/1",
                "secret_hex": secret.hex(),
                "created_at": _iso(),
            },
        )
        return secret

    def class_root(self, residue_class: str) -> Path:
        if residue_class not in RESIDUE_CLASSES:
            raise RuntimeResidueError(f"unregistered runtime residue class: {residue_class!r}")
        return self.root / residue_class

    def _relative(self, path: Path, *, root: Path) -> str:
        try:
            resolved = ensure_within(root, path, label="runtime residue path", error_type=RuntimeResidueError)
        except Exception as exc:
            if isinstance(exc, RuntimeResidueError):
                raise
            raise RuntimeResidueError(str(exc)) from exc
        if path.is_symlink() or resolved.is_symlink():
            raise RuntimeResidueError("runtime residue path cannot be a symlink")
        return resolved.relative_to(root).as_posix()

    def _sign(self, body: Mapping[str, Any]) -> str:
        return hmac.new(self._secret, _canonical(body), hashlib.sha256).hexdigest()

    @staticmethod
    def _marker_path(artifact: Path) -> Path:
        return artifact.with_name(f".{artifact.name}.iwresidue.json")

    def register(
        self,
        artifact: Path | str,
        *,
        residue_class: str,
        safe_after: int | None = None,
        transaction_id: str | None = None,
        authoritative_references: Iterable[str] = (),
    ) -> dict[str, Any]:
        class_root = self.class_root(residue_class)
        supplied_path = Path(artifact).expanduser()
        if supplied_path.is_symlink():
            raise RuntimeResidueError("runtime residue path cannot be a symlink")
        path = supplied_path.resolve(strict=True)
        relative = self._relative(path, root=class_root)
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode):
            raise RuntimeResidueError("runtime residue must be one regular file")
        if info.st_nlink != 1:
            raise RuntimeResidueError("hard-linked artifacts cannot be registered as runtime residue")
        references = [str(value) for value in authoritative_references if str(value)]
        if references:
            raise RuntimeResidueError("an artifact with authoritative references is not runtime residue")
        body = {
            "schema": MARKER_SCHEMA,
            "residue_class": residue_class,
            "artifact_relative_path": relative,
            "size": int(info.st_size),
            "sha256": _sha256(path),
            "device": int(info.st_dev),
            "inode": int(info.st_ino),
            "created_at": _iso(),
            "safe_after": int(_now() if safe_after is None else safe_after),
            "transaction_id": str(transaction_id or ""),
            "authoritative_references": [],
        }
        marker = {**body, "signature": self._sign(body)}
        marker_path = self._marker_path(path)
        if marker_path.exists() or marker_path.is_symlink():
            raise RuntimeResidueError("runtime residue marker already exists")
        atomic_json(marker_path, marker)
        return {"registered": True, "artifact": str(path), "marker": str(marker_path), **body}

    def _candidate_from_marker(self, marker_path: Path, *, now: int) -> ResidueCandidate:
        if marker_path.is_symlink() or not marker_path.is_file():
            raise RuntimeResidueError("runtime residue marker must be one regular file")
        marker_info = marker_path.lstat()
        if not stat.S_ISREG(marker_info.st_mode) or marker_info.st_nlink != 1:
            raise RuntimeResidueError("runtime residue marker identity is unsafe")
        marker = strict_json_read(marker_path)
        if not isinstance(marker, dict) or marker.get("schema") != MARKER_SCHEMA:
            raise RuntimeResidueError("runtime residue marker schema is invalid")
        signature = str(marker.get("signature") or "")
        body = {key: value for key, value in marker.items() if key != "signature"}
        if not hmac.compare_digest(signature, self._sign(body)):
            raise RuntimeResidueError("runtime residue marker signature is invalid")
        residue_class = str(marker.get("residue_class") or "")
        class_root = self.class_root(residue_class)
        expected_marker_root = class_root.resolve()
        self._relative(marker_path.resolve(), root=expected_marker_root)
        relative = str(marker.get("artifact_relative_path") or "")
        if not relative or Path(relative).is_absolute() or ".." in Path(relative).parts:
            raise RuntimeResidueError("runtime residue marker path is invalid")
        artifact = class_root / relative
        self._relative(artifact, root=class_root)
        if artifact.is_symlink() or not artifact.is_file():
            raise RuntimeResidueError("registered runtime residue artifact is unavailable or indirect")
        info = artifact.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise RuntimeResidueError("registered runtime residue identity is unsafe")
        if int(marker.get("device", -1)) != int(info.st_dev) or int(marker.get("inode", -1)) != int(info.st_ino):
            raise RuntimeResidueError("registered runtime residue identity changed")
        if int(marker.get("size", -1)) != int(info.st_size):
            raise RuntimeResidueError("registered runtime residue size changed")
        digest = _sha256(artifact)
        if digest != str(marker.get("sha256") or ""):
            raise RuntimeResidueError("registered runtime residue content changed")
        if list(marker.get("authoritative_references") or []):
            raise RuntimeResidueError("referenced material is not runtime residue")
        safe_after = int(marker.get("safe_after") or 0)
        if safe_after > now:
            raise RuntimeResidueError("runtime residue retention period has not elapsed")
        marker_digest = _sha256(marker_path)
        return ResidueCandidate(
            marker_path=str(marker_path.resolve()),
            artifact_path=str(artifact.resolve()),
            residue_class=residue_class,
            size=int(info.st_size),
            sha256=digest,
            safe_after=safe_after,
            marker_signature=signature,
            marker_size=int(marker_info.st_size),
            marker_sha256=marker_digest,
        )

    def plan(self, *, automatic_only: bool = False, now: int | None = None) -> dict[str, Any]:
        current = _now() if now is None else int(now)
        eligible: list[dict[str, Any]] = []
        retained: list[dict[str, Any]] = []
        classes = AUTOMATIC_CLASSES if automatic_only else RESIDUE_CLASSES
        for residue_class in sorted(classes):
            class_root = self.class_root(residue_class)
            for marker_path in sorted(class_root.glob(".*.iwresidue.json")):
                try:
                    eligible.append(self._candidate_from_marker(marker_path, now=current).to_dict())
                except Exception as exc:
                    retained.append({"marker_path": str(marker_path), "reason": str(exc)[:500]})
        body = {
            "schema": "iteration-wallet-runtime-cleanup-plan/1",
            "plan_id": uuid4().hex,
            "planned_at": _iso(current),
            "automatic_only": bool(automatic_only),
            "eligible": eligible,
            "retained": retained,
            "eligible_count": len(eligible),
            "retained_count": len(retained),
            "eligible_bytes": sum(int(item["size"]) for item in eligible),
        }
        body["plan_hash"] = hashlib.sha256(_canonical(body)).hexdigest()
        return body

    def _revalidate_candidate(self, candidate: Mapping[str, Any]) -> ResidueCandidate:
        marker_path = Path(str(candidate.get("marker_path") or ""))
        current = self._candidate_from_marker(marker_path, now=_now())
        supplied = ResidueCandidate(
            marker_path=str(candidate.get("marker_path") or ""),
            artifact_path=str(candidate.get("artifact_path") or ""),
            residue_class=str(candidate.get("residue_class") or ""),
            size=int(candidate.get("size") or 0),
            sha256=str(candidate.get("sha256") or ""),
            safe_after=int(candidate.get("safe_after") or 0),
            marker_signature=str(candidate.get("marker_signature") or ""),
            marker_size=int(candidate.get("marker_size") or 0),
            marker_sha256=str(candidate.get("marker_sha256") or ""),
        )
        if current != supplied:
            raise RuntimeResidueError("runtime residue changed after planning")
        return current

    @staticmethod
    def _unlink_exact(path: Path, *, expected_size: int, expected_sha256: str) -> None:
        if path.is_symlink():
            raise RuntimeResidueError("runtime residue cannot be an indirect path")
        parent = path.parent
        parent_fd = os.open(parent, os.O_RDONLY)
        descriptor: int | None = None
        try:
            flags = os.O_RDONLY
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            descriptor = os.open(path.name, flags, dir_fd=parent_fd)
            info = os.fstat(descriptor)
            listed = os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
            if (info.st_dev, info.st_ino) != (listed.st_dev, listed.st_ino):
                raise RuntimeResidueError("runtime residue identity changed during cleanup")
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise RuntimeResidueError("runtime residue identity is unsafe during cleanup")
            if int(info.st_size) != int(expected_size):
                raise RuntimeResidueError("runtime residue size changed during cleanup")
            digest = hashlib.sha256()
            while True:
                chunk = os.read(descriptor, 1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
            if digest.hexdigest() != expected_sha256:
                raise RuntimeResidueError("runtime residue content changed during cleanup")
            os.unlink(path.name, dir_fd=parent_fd)
            os.fsync(parent_fd)
        finally:
            if descriptor is not None:
                os.close(descriptor)
            os.close(parent_fd)

    def execute(self, plan: Mapping[str, Any]) -> dict[str, Any]:
        supplied = dict(plan)
        plan_hash = str(supplied.pop("plan_hash", ""))
        if not plan_hash or hashlib.sha256(_canonical(supplied)).hexdigest() != plan_hash:
            raise RuntimeResidueError("runtime cleanup plan hash is invalid")
        candidates = [self._revalidate_candidate(item) for item in list(plan.get("eligible") or [])]
        receipt_id = uuid4().hex
        receipt_path = self.receipt_root / f"{receipt_id}.json"
        pre_receipt = {
            "schema": RECEIPT_SCHEMA,
            "receipt_id": receipt_id,
            "plan_id": plan.get("plan_id"),
            "plan_hash": plan_hash,
            "status": "execution_started",
            "started_at": _iso(),
            "artifacts": [item.to_dict() for item in candidates],
            "handled": [],
        }
        atomic_json(receipt_path, pre_receipt)
        handled: list[dict[str, Any]] = []
        try:
            for candidate in candidates:
                artifact = Path(candidate.artifact_path)
                marker = Path(candidate.marker_path)
                self._unlink_exact(
                    artifact,
                    expected_size=candidate.size,
                    expected_sha256=candidate.sha256,
                )
                self._unlink_exact(
                    marker,
                    expected_size=candidate.marker_size,
                    expected_sha256=candidate.marker_sha256,
                )
                handled.append(
                    {
                        "residue_class": candidate.residue_class,
                        "artifact_path": candidate.artifact_path,
                        "size": candidate.size,
                        "sha256": candidate.sha256,
                        "handled_at": _iso(),
                    }
                )
        except Exception as exc:
            atomic_json(
                receipt_path,
                {
                    **pre_receipt,
                    "status": "attention_required",
                    "finished_at": _iso(),
                    "handled": handled,
                    "error": f"{type(exc).__name__}: {exc}"[:1000],
                },
            )
            raise
        result = {
            **pre_receipt,
            "status": "complete",
            "finished_at": _iso(),
            "handled": handled,
            "handled_count": len(handled),
            "handled_bytes": sum(int(item["size"]) for item in handled),
        }
        atomic_json(receipt_path, result)
        fsync_directory(self.receipt_root)
        return {**result, "receipt_path": str(receipt_path)}
