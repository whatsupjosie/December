"""Wallet-owned Oubliette inspection and custody transactions.

Oubliette may observe and recommend review.  Iteration Wallet alone consumes
Human Intent ceremony tokens, mutates custody, writes recovery journals, and
mints portable receipts.  Canonical BlackBox records facts but grants no
custody authority.
"""
from __future__ import annotations

import hashlib
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Optional
from uuid import uuid4

from blackbox_plugin.models import Coverage as BlackBoxCoverage
from blackbox_plugin.models import ObservationMode
from blackbox_plugin.schema import canonical_json

from iteration_wallet.oubliette_blackbox_adapter import OublietteBlackBoxAdapter

from iteration_wallet.canonical_evidence import (
    CanonicalEvidenceAdapter,
    CanonicalEvidenceError,
    HumanIntentReceiptStore,
)
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
from iteration_wallet.intake_capsule import (
    IntakeCapsuleError,
    WalletIntakeCapsuleStore,
    portable_basename,
)
from iteration_wallet.notification_manager import ActorKind as AccessActorKind
from iteration_wallet.notification_manager import NotificationManager
from iteration_wallet.oubliette import (
    ActorKind as OublietteActorKind,
    Coverage as InspectionCoverage,
    OublietteError,
    OublietteInspectionReport,
    inspect_static,
)
from iteration_wallet.vault_v21 import VaultEngine, VaultError


class OublietteTransactionError(Exception):
    """Raised when an Oubliette/Wallet protocol cannot safely continue."""


class SimulatedOublietteCrash(BaseException):
    """Fault-injection sentinel that bypasses normal exception recovery."""

    def __init__(self, stage: str) -> None:
        super().__init__(f"simulated process crash after {stage}")
        self.stage = stage


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def sha256_json(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json(payload)).hexdigest()


def _safe_digest_id(prefix: str, material: str) -> str:
    return f"{prefix}-{hashlib.sha256(material.encode('utf-8')).hexdigest()}"


class OublietteReportStore:
    """Write-once, fully sealed inspection reports with canonical binding."""

    def __init__(self, vault_root: Path | str) -> None:
        self.vault_root = Path(vault_root)
        self.root = self.vault_root / "oubliette" / "reports"
        self.lock_dir = self.vault_root / "oubliette" / ".report_locks"
        try:
            ensure_within(
                self.vault_root,
                self.root,
                label="Oubliette report storage",
                error_type=OublietteTransactionError,
            )
            ensure_within(
                self.vault_root,
                self.lock_dir,
                label="Oubliette report locks",
                error_type=OublietteTransactionError,
            )
        except DurableIOError as exc:
            raise OublietteTransactionError(str(exc)) from exc
        for directory in (self.root, self.lock_dir):
            if directory.is_symlink():
                raise OublietteTransactionError(
                    f"Oubliette report directory cannot be a symlink: {directory.name}"
                )
            directory.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _storage_id(report_id: str) -> str:
        return validate_storage_id(
            "report_storage_id",
            _safe_digest_id("oub-report", report_id),
            error_type=OublietteTransactionError,
        )

    def _path(self, report_id: str) -> Path:
        return self.root / f"{self._storage_id(report_id)}.json"

    def _lock_path(self, report_id: str) -> Path:
        return self.lock_dir / f"{self._storage_id(report_id)}.lock"

    @staticmethod
    def semantic_core(material: Mapping[str, Any]) -> dict[str, Any]:
        return {
            key: value
            for key, value in dict(material).items()
            if key
            not in {
                "stored_at",
                "generated_at",
                "report_hash",
                "record_hash",
                "canonical_event_id",
                "canonical_event_hash",
            }
        }

    @classmethod
    def report_hash(cls, material: Mapping[str, Any]) -> str:
        return hashlib.sha256(canonical_json(cls.semantic_core(material))).hexdigest()

    @staticmethod
    def record_hash(material: Mapping[str, Any]) -> str:
        sealed = {key: value for key, value in dict(material).items() if key != "record_hash"}
        return hashlib.sha256(canonical_json(sealed)).hexdigest()

    @classmethod
    def seal_record(cls, material: Mapping[str, Any]) -> dict[str, Any]:
        sealed = dict(material)
        sealed["record_hash"] = cls.record_hash(sealed)
        return sealed

    def create(
        self,
        report: OublietteInspectionReport,
        *,
        project_id: str,
        section_id: str,
        object_id: str,
        report_role: str = "custodied_intake",
        extra_scope: Optional[Mapping[str, Any]] = None,
    ) -> dict[str, Any]:
        project_id = validate_storage_id(
            "project_id", project_id, error_type=OublietteTransactionError
        )
        section_id = validate_storage_id(
            "section_id", section_id, error_type=OublietteTransactionError
        )
        object_id = validate_storage_id(
            "object_id", object_id, error_type=OublietteTransactionError
        )
        if not isinstance(report_role, str) or not report_role or len(report_role) > 128:
            raise OublietteTransactionError("invalid Oubliette report role")
        scope = dict(extra_scope or {})
        reserved = set(report.to_dict()) | {
            "project_id",
            "section_id",
            "object_id",
            "report_role",
            "stored_at",
            "report_hash",
            "record_hash",
            "canonical_event_id",
            "canonical_event_hash",
        }
        collision = sorted(reserved.intersection(scope))
        if collision:
            raise OublietteTransactionError(
                "extra report scope cannot override reserved fields: " + ", ".join(collision)
            )
        material = {
            **report.to_dict(),
            "project_id": project_id,
            "section_id": section_id,
            "object_id": object_id,
            "report_role": report_role,
            **scope,
            "stored_at": utc_now(),
        }
        material["report_hash"] = self.report_hash(material)
        material = self.seal_record(material)
        path = self._path(report.report_id)
        try:
            with file_lock(self._lock_path(report.report_id)):
                if path.exists():
                    existing = self.get(report.report_id)
                    if self.semantic_core(existing) != self.semantic_core(material):
                        raise OublietteTransactionError(
                            f"inspection report retry conflicts with write-once artifact: {report.report_id}"
                        )
                    return existing
                try:
                    exclusive_json(path, material)
                except FileExistsError:
                    existing = self.get(report.report_id)
                    if self.semantic_core(existing) != self.semantic_core(material):
                        raise OublietteTransactionError(
                            f"concurrent inspection report conflicts with write-once artifact: {report.report_id}"
                        )
                    return existing
        except DurableIOError as exc:
            raise OublietteTransactionError(f"inspection report storage failed: {exc}") from exc
        return material

    def bind_canonical_event(
        self,
        report_id: str,
        *,
        event_id: str,
        event_hash: str,
    ) -> dict[str, Any]:
        event_id = validate_storage_id(
            "canonical_event_id", event_id, error_type=OublietteTransactionError
        )
        if not re.fullmatch(r"[0-9a-f]{64}", str(event_hash)):
            raise OublietteTransactionError("canonical_event_hash must be a lowercase SHA-256 digest")
        path = self._path(report_id)
        try:
            with file_lock(self._lock_path(report_id)):
                existing = self.get(report_id)
                prior_id = existing.get("canonical_event_id")
                prior_hash = existing.get("canonical_event_hash")
                if prior_id or prior_hash:
                    if prior_id != event_id or prior_hash != event_hash:
                        raise OublietteTransactionError(
                            f"inspection report already bound to different canonical evidence: {report_id}"
                        )
                    return existing
                bound = dict(existing)
                bound["canonical_event_id"] = event_id
                bound["canonical_event_hash"] = event_hash
                bound = self.seal_record(bound)
                atomic_json(path, bound)
                return self.get(report_id)
        except DurableIOError as exc:
            raise OublietteTransactionError(f"inspection report binding failed: {exc}") from exc

    def get(self, report_id: str) -> dict[str, Any]:
        path = self._path(report_id)
        if path.is_symlink() or not path.is_file():
            raise OublietteTransactionError(f"inspection report not found: {report_id}")
        try:
            material = strict_json_read(path)
        except DurableIOError as exc:
            raise OublietteTransactionError(f"unreadable inspection report: {exc}") from exc
        if not isinstance(material, dict) or material.get("report_id") != report_id:
            raise OublietteTransactionError("inspection report identity does not match storage")
        expected = self.report_hash(material)
        if material.get("report_hash") != expected:
            raise OublietteTransactionError("inspection report hash mismatch")
        if material.get("record_hash") != self.record_hash(material):
            raise OublietteTransactionError("inspection report stored-record hash mismatch")
        return material


class OublietteJournal:
    """Sealed Wallet recovery state for quarantine and capsule admission."""

    TERMINAL_STAGES = {"COMPLETE", "FAILED", "RECONCILIATION_REQUIRED"}
    JOURNAL_VERSION = 2

    def __init__(self, vault_root: Path | str) -> None:
        self.vault_root = Path(vault_root)
        self.root = self.vault_root / "recovery_journal" / "oubliette"
        self.active_dir = self.root / "active"
        self.completed_dir = self.root / "completed"
        self.reconciliation_dir = self.root / "reconciliation_required"
        self.lock_dir = self.root / ".locks"
        try:
            ensure_within(
                self.vault_root,
                self.root,
                label="Oubliette journal",
                error_type=OublietteTransactionError,
            )
        except DurableIOError as exc:
            raise OublietteTransactionError(str(exc)) from exc
        for directory in (
            self.root,
            self.active_dir,
            self.completed_dir,
            self.reconciliation_dir,
            self.lock_dir,
        ):
            if directory.is_symlink():
                raise OublietteTransactionError(
                    f"Oubliette journal directory cannot be a symlink: {directory.name}"
                )
            directory.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _operation_id(operation_id: str) -> str:
        return validate_storage_id(
            "operation_id", operation_id, error_type=OublietteTransactionError
        )

    @staticmethod
    def record_hash(material: Mapping[str, Any]) -> str:
        sealed = {key: value for key, value in dict(material).items() if key != "record_hash"}
        return hashlib.sha256(canonical_json(sealed)).hexdigest()

    @classmethod
    def _seal(cls, material: Mapping[str, Any]) -> dict[str, Any]:
        sealed = dict(material)
        sealed["record_hash"] = cls.record_hash(sealed)
        return sealed

    def _active_path(self, operation_id: str) -> Path:
        return self.active_dir / f"{self._operation_id(operation_id)}.json"

    def _lock_path(self, operation_id: str) -> Path:
        return self.lock_dir / f"{self._operation_id(operation_id)}.lock"

    def _read_path(self, path: Path, operation_id: str) -> dict[str, Any]:
        if path.is_symlink() or not path.is_file():
            raise OublietteTransactionError(f"journal record is not a regular file: {operation_id}")
        try:
            data = strict_json_read(path)
        except DurableIOError as exc:
            raise OublietteTransactionError(f"unreadable journal {operation_id}: {exc}") from exc
        if not isinstance(data, dict) or data.get("operation_id") != operation_id:
            raise OublietteTransactionError(f"journal identity does not match storage: {operation_id}")
        if data.get("journal_version") != self.JOURNAL_VERSION:
            raise OublietteTransactionError(
                f"unsupported or unsealed Oubliette journal version: {data.get('journal_version')!r}"
            )
        if data.get("record_hash") != self.record_hash(data):
            raise OublietteTransactionError("Oubliette journal record hash mismatch")
        return data

    def reserve(self, record: Mapping[str, Any]) -> dict[str, Any]:
        material = dict(record)
        operation_id = self._operation_id(str(material.get("operation_id") or ""))
        material["operation_id"] = operation_id
        material["journal_version"] = self.JOURNAL_VERSION
        material.setdefault("stage", "RESERVED")
        material.setdefault("created_at", utc_now())
        material["updated_at"] = utc_now()
        material = self._seal(material)
        try:
            with file_lock(self._lock_path(operation_id)):
                exclusive_json(self._active_path(operation_id), material)
        except DurableIOError as exc:
            raise OublietteTransactionError(f"journal reservation failed: {exc}") from exc
        return material

    def get(self, operation_id: str) -> dict[str, Any]:
        operation_id = self._operation_id(operation_id)
        for directory in (self.active_dir, self.completed_dir, self.reconciliation_dir):
            path = directory / f"{operation_id}.json"
            if path.exists() or path.is_symlink():
                return self._read_path(path, operation_id)
        raise OublietteTransactionError(f"journal not found: {operation_id}")

    def update(self, operation_id: str, **changes: Any) -> dict[str, Any]:
        operation_id = self._operation_id(operation_id)
        if "operation_id" in changes or "journal_version" in changes or "created_at" in changes:
            raise OublietteTransactionError("immutable journal identity fields cannot be changed")
        try:
            with file_lock(self._lock_path(operation_id)):
                path = self._active_path(operation_id)
                data = self._read_path(path, operation_id)
                data.update(changes)
                data["updated_at"] = utc_now()
                data = self._seal(data)
                atomic_json(path, data)
                return data
        except DurableIOError as exc:
            raise OublietteTransactionError(f"journal update failed: {exc}") from exc

    def pending(self) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for path in sorted(self.active_dir.glob("*.json")):
            expected = self._operation_id(path.stem)
            records.append(self._read_path(path, expected))
        return records

    def _finish(self, operation_id: str, destination: Path, **changes: Any) -> dict[str, Any]:
        operation_id = self._operation_id(operation_id)
        try:
            with file_lock(self._lock_path(operation_id)):
                source = self._active_path(operation_id)
                data = self._read_path(source, operation_id)
                data.update(changes)
                data["updated_at"] = utc_now()
                data = self._seal(data)
                atomic_json(source, data)
                target = destination / source.name
                if target.exists() or target.is_symlink():
                    raise OublietteTransactionError(
                        f"terminal journal already exists: {target.name}"
                    )
                os.replace(source, target)
                fsync_directory(source.parent)
                fsync_directory(target.parent)
                return data
        except DurableIOError as exc:
            raise OublietteTransactionError(f"journal completion failed: {exc}") from exc

    def complete(self, operation_id: str, **changes: Any) -> dict[str, Any]:
        return self._finish(operation_id, self.completed_dir, stage="COMPLETE", **changes)

    def fail(self, operation_id: str, **changes: Any) -> dict[str, Any]:
        return self._finish(operation_id, self.completed_dir, stage="FAILED", **changes)

    def require_reconciliation(self, operation_id: str, **changes: Any) -> dict[str, Any]:
        return self._finish(
            operation_id,
            self.reconciliation_dir,
            stage="RECONCILIATION_REQUIRED",
            **changes,
        )


class OublietteTransactionCoordinator:
    """Static intake observation plus Wallet-owned Oubliette crossings."""

    QUARANTINE_ACTION = "quarantine"
    DERIVATIVE_ACTION = "admit_oubliette_derivative_as_candidate"

    def __init__(
        self,
        vault: VaultEngine,
        evidence: CanonicalEvidenceAdapter,
        human_access: NotificationManager,
        participation_mode: str = "inspect",
    ) -> None:
        mode = str(participation_mode or "inspect").strip().lower()
        if mode not in {"inspect", "transaction"}:
            raise OublietteTransactionError(
                "Oubliette participation_mode must be 'inspect' or 'transaction'"
            )
        self.participation_mode = mode
        self.vault = vault
        self.evidence = evidence
        self.oubliette_evidence = OublietteBlackBoxAdapter(evidence)
        self.human_access = human_access
        self.reports = OublietteReportStore(vault.root)
        self.capsules = WalletIntakeCapsuleStore(vault.root)
        self.journal = OublietteJournal(vault.root)
        self.receipts = HumanIntentReceiptStore(vault.root)
        self.lock_dir = Path(vault.root) / "authority_locks" / "oubliette"
        try:
            ensure_within(
                Path(vault.root),
                self.lock_dir,
                label="Oubliette authority locks",
                error_type=OublietteTransactionError,
            )
        except DurableIOError as exc:
            raise OublietteTransactionError(str(exc)) from exc
        if self.lock_dir.is_symlink():
            raise OublietteTransactionError("Oubliette authority lock directory cannot be a symlink")
        self.lock_dir.mkdir(parents=True, exist_ok=True)
        self.evidence.attach_receipt_store(self.receipts)
        self.evidence.register_receipt_verifier(self.QUARANTINE_ACTION, self.verify_receipt)
        self.evidence.register_receipt_verifier(self.DERIVATIVE_ACTION, self.verify_receipt)

    def capability(self) -> dict[str, Any]:
        transaction_ready = self.participation_mode == "transaction"
        return {
            "component": "oubliette",
            "available": True,
            "participation_mode": self.participation_mode,
            "level": "transaction_ready" if transaction_ready else "inspect_and_request",
            "static_inspection": True,
            "protective_requests": True,
            "wallet_owned_crossings": transaction_ready,
            "execution_supported": False,
            "core_wallet_dependency": False,
            "failure_policy": "degrade_without_blocking_wallet_blackbox_core",
            "blackbox_adapter": self.oubliette_evidence.status(),
        }

    def _require_transaction_capability(self) -> None:
        if self.participation_mode != "transaction":
            raise OublietteTransactionError(
                "Oubliette is available in inspect-only mode; Wallet custody crossing was not attempted"
            )

    @staticmethod
    def _record_snapshot(record: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "id": record.get("id"),
            "name": record.get("name"),
            "state": record.get("state"),
            "vault_path": record.get("vault_path"),
            "hash": record.get("hash"),
            "quarantined": bool(record.get("quarantined")),
            "quarantine_operation_id": record.get("quarantine_operation_id"),
        }

    def _scope_lock_path(self, project_id: str, section_id: str, object_id: str) -> Path:
        digest = sha256_json(
            {"project_id": project_id, "section_id": section_id, "object_id": object_id}
        )
        return self.lock_dir / f"{digest}.lock"

    @staticmethod
    def _event_ids() -> dict[str, str]:
        return {
            "operation_id": uuid4().hex,
            "receipt_id": uuid4().hex,
            "reserved_event_id": uuid4().hex,
            "authorization_event_id": uuid4().hex,
            "custody_event_id": uuid4().hex,
            "terminal_event_id": uuid4().hex,
            "anchor_event_id": uuid4().hex,
        }

    def _append_stage(
        self,
        journal: Mapping[str, Any],
        *,
        stage: str,
        event_type: str,
        event_id_key: str,
        actor: str,
        summary: str,
        payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        return self.evidence.append_fact(
            event_type=event_type,
            summary=summary,
            event_id=str(journal[event_id_key]),
            transaction_id=str(journal["operation_id"]),
            stage_key=f"{journal['operation_id']}:{stage}",
            actor=actor,
            subject_id=f"object:{journal['object_id']}",
            payload=payload,
            event_code=stage,
        )

    def inspect_object(
        self,
        *,
        project_id: str,
        section_id: str,
        object_id: str,
        actor_kind: OublietteActorKind | str,
        target_label: Optional[str] = None,
    ) -> dict[str, Any]:
        """Inspect one stable custodied object without holding the catalog lock."""
        with self.vault.catalog_transaction():
            record = self.vault._find_file(project_id, section_id, object_id)
            state = str(record.get("state") or "")
            if state not in {"raw", "candidate", "quarantined"}:
                raise OublietteTransactionError(
                    "Static Oubliette intake inspection supports Raw Source, Candidate, or quarantined original"
                )
            compartment = self.vault._compartment_dir(
                project_id, section_id, self.vault._compartment_for_state(state)
            )
            path = self.vault._require_owned_custody_file(
                record.get("vault_path"),
                expected_compartment=compartment,
                label="Oubliette inspection target",
            )
            before_hash = self.vault._sha256(path)
            if before_hash != record.get("hash"):
                raise OublietteTransactionError(
                    "custody hash mismatch before inspection; report would describe unregistered bytes"
                )
            snapshot = self._record_snapshot(record)

        try:
            report = inspect_static(
                path,
                actor_kind=actor_kind,
                allowed_root=compartment,
                target_label=target_label or str(snapshot.get("name") or path.name),
            )
        except OublietteError as exc:
            raise OublietteTransactionError(str(exc)) from exc
        if report.target_sha256 != before_hash:
            raise OublietteTransactionError(
                "static report hash differs from the registered custody object"
            )

        with self.vault.catalog_transaction():
            current = self.vault._find_file(project_id, section_id, object_id)
            if self._record_snapshot(current) != snapshot:
                raise OublietteTransactionError(
                    "custody record changed during static observation; report remains unregistered"
                )
            current_path = self.vault._require_owned_custody_file(
                current.get("vault_path"),
                expected_compartment=compartment,
                label="Oubliette inspection target",
            )
            if current_path != path or self.vault._sha256(current_path) != before_hash:
                raise OublietteTransactionError(
                    "custodied bytes changed during static observation; refusing to register report"
                )

        stored = self.reports.create(
            report,
            project_id=project_id,
            section_id=section_id,
            object_id=object_id,
            report_role="custodied_intake",
        )
        operation_id = _safe_digest_id(
            "oub-inspection",
            f"{project_id}|{section_id}|{object_id}|{report.report_id}",
        )
        event_id = hashlib.sha256(f"{operation_id}|event".encode("utf-8")).hexdigest()
        coverage = (
            BlackBoxCoverage.FULL
            if report.coverage is InspectionCoverage.FULL
            else BlackBoxCoverage.PARTIAL
        )
        event = self.oubliette_evidence.append_observation(
            event_type="OUBLIETTE_STATIC_INSPECTION_COMPLETED",
            summary="Static-only Oubliette inspection completed without custody change",
            event_id=event_id,
            transaction_id=operation_id,
            stage_key=f"{operation_id}:INSPECTION",
            actor=f"{report.actor_kind.value}:operator",
            subject_id=f"object:{object_id}",
            payload={
                "project_id": project_id,
                "section_id": section_id,
                "object_id": object_id,
                "report_id": report.report_id,
                "report_hash": stored["report_hash"],
                "target_sha256": before_hash,
                "coverage": report.coverage.value,
                "finding_codes": [item.code for item in report.findings],
                "warnings": list(report.warnings),
                "quarantine_review_recommended": report.quarantine_review_recommended,
                "target_executed": False,
                "target_extracted": False,
                "target_modified": False,
                "custody_changed": False,
                "malware_determined": False,
            },
            coverage=coverage,
            channel="OUB",
            event_code="INSPECT",
        )
        bound = self.reports.bind_canonical_event(
            report.report_id,
            event_id=event["event_id"],
            event_hash=event["event_hash"],
        )
        with self.vault.catalog_transaction():
            current = self.vault._find_file(project_id, section_id, object_id)
            if self._record_snapshot(current) != snapshot:
                raise OublietteTransactionError(
                    "custody record changed before inspection attachment; canonical observation remains preserved"
                )
            attached = self.vault._attach_oubliette_inspection_unchecked(
                project_id,
                section_id,
                object_id,
                report_id=report.report_id,
                report_hash=bound["report_hash"],
                target_sha256=before_hash,
                coverage=report.coverage.value,
                finding_codes=[item.code for item in report.findings],
                warnings=list(report.warnings),
                canonical_event_id=event["event_id"],
                canonical_event_hash=event["event_hash"],
            )
        quarantine_proposal = self._quarantine_proposal_material(
            project_id=project_id,
            section_id=section_id,
            object_record=attached,
            report=bound,
        ) if attached.get("state") in {"raw", "candidate"} else None
        return {
            "report": bound,
            "canonical_event": event,
            "object": self._record_snapshot(attached),
            "quarantine_proposal": quarantine_proposal,
            "authority": {
                "custody_changed": False,
                "trust_decided": False,
                "quarantine_requires_human_intent": True,
            },
        }

    def capture_intake_capsule(
        self,
        *,
        project_id: str,
        section_id: str,
        quarantined_object_id: str,
        source_path: Path | str,
        allowed_root: Path | str,
        actor_kind: OublietteActorKind | str,
        source_label: Optional[str] = None,
        external_assertions: Optional[list[Mapping[str, Any]]] = None,
    ) -> dict[str, Any]:
        """Capture exact external bytes without blocking unrelated Wallet catalog work."""
        kind = OublietteActorKind(str(actor_kind))
        if kind in {OublietteActorKind.AI, OublietteActorKind.BOT}:
            raise OublietteTransactionError("AI and bot operation of Oubliette intake is prohibited")
        with self.vault.catalog_transaction():
            parent = self.vault._find_file(project_id, section_id, quarantined_object_id)
            if parent.get("state") != "quarantined":
                raise OublietteTransactionError(
                    "Intake Capsule capture requires a preserved quarantined parent"
                )
            parent_snapshot = self._record_snapshot(parent)
        try:
            capsule = self.capsules.capture(
                project_id=project_id,
                section_id=section_id,
                parent_object_id=quarantined_object_id,
                parent_sha256=str(parent_snapshot.get("hash") or ""),
                source_path=source_path,
                allowed_root=allowed_root,
                source_label=source_label,
                external_assertions=external_assertions,
            )
        except IntakeCapsuleError as exc:
            raise OublietteTransactionError(str(exc)) from exc

        with self.vault.catalog_transaction():
            current_parent = self.vault._find_file(project_id, section_id, quarantined_object_id)
            current_snapshot = self._record_snapshot(current_parent)
            lineage_current = (
                current_parent.get("state") == "quarantined"
                and current_parent.get("hash") == parent_snapshot.get("hash")
                and current_parent.get("id") == parent_snapshot.get("id")
            )
        operation_id = _safe_digest_id(
            "wallet-intake-capture",
            f"{project_id}|{section_id}|{quarantined_object_id}|{capsule['capsule_id']}",
        )
        event_id = hashlib.sha256(f"{operation_id}|event".encode("utf-8")).hexdigest()
        if not lineage_current:
            self.evidence.append_fact(
                event_type="WALLET_INTAKE_CAPSULE_CAPTURED_LINEAGE_STALE",
                summary="Exact external bytes were preserved but parent lineage changed before registration",
                event_id=event_id,
                transaction_id=operation_id,
                stage_key=f"{operation_id}:CAPTURE_LINEAGE_STALE",
                actor=f"{kind.value}:operator",
                subject_id=f"capsule:{capsule['capsule_id']}",
                payload={
                    "project_id": project_id,
                    "section_id": section_id,
                    "parent_object_id": quarantined_object_id,
                    "expected_parent_sha256": parent_snapshot.get("hash"),
                    "observed_parent": current_snapshot,
                    "capsule_id": capsule["capsule_id"],
                    "manifest_hash": capsule["manifest_hash"],
                    "blob_sha256": capsule["blob_sha256"],
                    "candidate_admitted": False,
                    "trust_decided": False,
                },
                observation_mode=ObservationMode.ADAPTER_OBSERVED,
                coverage=BlackBoxCoverage.PARTIAL,
                channel="CUS",
                event_code="INTAKE_STALE",
            )
            raise OublietteTransactionError(
                "parent lineage changed during Intake capture; preserved capsule was not registered for admission"
            )
        event = self.evidence.append_fact(
            event_type="WALLET_INTAKE_CAPSULE_CAPTURED",
            summary="Exact external bytes captured into inert Wallet Intake",
            event_id=event_id,
            transaction_id=operation_id,
            stage_key=f"{operation_id}:CAPTURE",
            actor=f"{kind.value}:operator",
            subject_id=f"capsule:{capsule['capsule_id']}",
            payload={
                "project_id": project_id,
                "section_id": section_id,
                "parent_object_id": quarantined_object_id,
                "parent_sha256": parent_snapshot.get("hash"),
                "capsule_id": capsule["capsule_id"],
                "manifest_hash": capsule["manifest_hash"],
                "blob_sha256": capsule["blob_sha256"],
                "size_bytes": capsule["size_bytes"],
                "state": "intake",
                "execution_allowed": False,
                "trust_decided": False,
                "external_assertion_count": len(capsule.get("external_assertions") or []),
            },
            observation_mode=ObservationMode.ADAPTER_OBSERVED,
            coverage=BlackBoxCoverage.FULL,
            channel="CUS",
            event_code="INTAKE_CAPTURE",
        )
        return {
            "capsule": capsule,
            "canonical_event": event,
            "parent": parent_snapshot,
            "authority": {
                "custody_state": "intake",
                "candidate_admitted": False,
                "trust_decided": False,
                "execution_allowed": False,
            },
        }

    @staticmethod
    def _admission_proposal(
        *,
        project_id: str,
        section_id: str,
        parent_object_id: str,
        parent_sha256: str,
        capsule: Mapping[str, Any],
        report: Mapping[str, Any],
    ) -> dict[str, Any]:
        material = {
            "schema": "rvf.wallet-protected-transition-proposal.v1",
            "action_key": OublietteTransactionCoordinator.DERIVATIVE_ACTION,
            "project_id": project_id,
            "section_id": section_id,
            "parent_object_id": parent_object_id,
            "parent_sha256": parent_sha256,
            "capsule_id": capsule["capsule_id"],
            "manifest_hash": capsule["manifest_hash"],
            "blob_sha256": capsule["blob_sha256"],
            "report_id": report["report_id"],
            "report_hash": report["report_hash"],
            "destination_state": "candidate",
            "automatic_trust": False,
        }
        proposal_hash = sha256_json(material)
        return {
            **material,
            "proposal_id": f"proposal-{proposal_hash}",
            "proposal_hash": proposal_hash,
        }

    def inspect_intake_capsule(
        self,
        *,
        project_id: str,
        section_id: str,
        parent_object_id: str,
        capsule_id: str,
        actor_kind: OublietteActorKind | str,
        target_label: Optional[str] = None,
    ) -> dict[str, Any]:
        """Statically inspect immutable Wallet-owned Intake bytes without catalog blocking."""
        kind = OublietteActorKind(str(actor_kind))
        if kind in {OublietteActorKind.AI, OublietteActorKind.BOT}:
            raise OublietteTransactionError("AI and bot operation of Oubliette inspection is prohibited")
        with self.vault.catalog_transaction():
            parent = self.vault._find_file(project_id, section_id, parent_object_id)
            if parent.get("state") != "quarantined":
                raise OublietteTransactionError(
                    "Capsule inspection requires the preserved parent to remain quarantined"
                )
            parent_snapshot = self._record_snapshot(parent)
        try:
            capsule = self.capsules.get(capsule_id)
        except IntakeCapsuleError as exc:
            raise OublietteTransactionError(str(exc)) from exc
        if (
            capsule.get("project_id") != project_id
            or capsule.get("section_id") != section_id
            or capsule.get("parent_object_id") != parent_object_id
            or capsule.get("parent_sha256") != parent_snapshot.get("hash")
        ):
            raise OublietteTransactionError("Wallet Intake Capsule lineage scope mismatch")
        blob_path = Path(str(capsule["absolute_blob_path"]))
        try:
            report = inspect_static(
                blob_path,
                actor_kind=kind,
                allowed_root=self.capsules.blob_dir,
                target_label=target_label or str(capsule.get("source_label") or blob_path.name),
            )
        except OublietteError as exc:
            raise OublietteTransactionError(str(exc)) from exc
        if (
            report.target_sha256 != capsule.get("blob_sha256")
            or report.size_bytes != int(capsule.get("size_bytes") or -1)
        ):
            raise OublietteTransactionError("static report does not match immutable Intake Capsule")
        with self.vault.catalog_transaction():
            current = self.vault._find_file(project_id, section_id, parent_object_id)
            if (
                current.get("state") != "quarantined"
                or current.get("hash") != parent_snapshot.get("hash")
            ):
                raise OublietteTransactionError(
                    "parent lineage changed during Intake Capsule inspection"
                )
        stored = self.reports.create(
            report,
            project_id=project_id,
            section_id=section_id,
            object_id=parent_object_id,
            report_role="wallet_intake_capsule",
            extra_scope={
                "parent_object_id": parent_object_id,
                "parent_sha256": parent_snapshot.get("hash"),
                "capsule_id": capsule_id,
                "manifest_hash": capsule["manifest_hash"],
                "blob_sha256": capsule["blob_sha256"],
            },
        )
        operation_id = _safe_digest_id(
            "oub-capsule-inspection",
            f"{project_id}|{section_id}|{parent_object_id}|{capsule_id}|{report.report_id}",
        )
        event_id = hashlib.sha256(f"{operation_id}|event".encode("utf-8")).hexdigest()
        coverage = (
            BlackBoxCoverage.FULL
            if report.coverage is InspectionCoverage.FULL
            else BlackBoxCoverage.PARTIAL
        )
        event = self.oubliette_evidence.append_observation(
            event_type="OUBLIETTE_INTAKE_CAPSULE_STATIC_INSPECTION_COMPLETED",
            summary="Immutable Wallet Intake Capsule inspected statically",
            event_id=event_id,
            transaction_id=operation_id,
            stage_key=f"{operation_id}:INSPECTION",
            actor=f"{report.actor_kind.value}:operator",
            subject_id=f"capsule:{capsule_id}",
            payload={
                "project_id": project_id,
                "section_id": section_id,
                "parent_object_id": parent_object_id,
                "parent_sha256": parent_snapshot.get("hash"),
                "capsule_id": capsule_id,
                "manifest_hash": capsule["manifest_hash"],
                "blob_sha256": capsule["blob_sha256"],
                "report_id": report.report_id,
                "report_hash": stored["report_hash"],
                "coverage": report.coverage.value,
                "finding_codes": [item.code for item in report.findings],
                "warnings": list(report.warnings),
                "target_executed": False,
                "target_extracted": False,
                "target_modified": False,
                "candidate_admitted": False,
                "trust_decided": False,
            },
            coverage=coverage,
            channel="OUB",
            event_code="INTAKE_INSPECT",
        )
        bound = self.reports.bind_canonical_event(
            report.report_id,
            event_id=event["event_id"],
            event_hash=event["event_hash"],
        )
        proposal = self._admission_proposal(
            project_id=project_id,
            section_id=section_id,
            parent_object_id=parent_object_id,
            parent_sha256=str(parent_snapshot.get("hash") or ""),
            capsule=capsule,
            report=bound,
        )
        return {
            "capsule": capsule,
            "report": bound,
            "canonical_event": event,
            "admission_proposal": proposal,
            "authority": {
                "custody_changed": False,
                "candidate_admitted": False,
                "trust_decided": False,
                "human_intent_must_bind_proposal": True,
            },
        }

    def inspect_derivative(
        self,
        *,
        project_id: str,
        section_id: str,
        quarantined_object_id: str,
        derivative_path: Path | str,
        allowed_root: Path | str,
        actor_kind: OublietteActorKind | str,
        target_label: Optional[str] = None,
    ) -> dict[str, Any]:
        """Compatibility wrapper: capture first, then inspect immutable Intake.

        No ceremony or Candidate admission may ever be bound directly to the
        external path passed here.
        """
        captured = self.capture_intake_capsule(
            project_id=project_id,
            section_id=section_id,
            quarantined_object_id=quarantined_object_id,
            source_path=derivative_path,
            allowed_root=allowed_root,
            actor_kind=actor_kind,
            source_label=target_label or Path(derivative_path).name,
        )
        inspected = self.inspect_intake_capsule(
            project_id=project_id,
            section_id=section_id,
            parent_object_id=quarantined_object_id,
            capsule_id=str(captured["capsule"]["capsule_id"]),
            actor_kind=actor_kind,
            target_label=target_label,
        )
        inspected["capture_event"] = captured["canonical_event"]
        inspected["compatibility_path_wrapper"] = True
        return inspected

    @staticmethod
    def _quarantine_proposal_material(
        *,
        project_id: str,
        section_id: str,
        object_record: Mapping[str, Any],
        report: Mapping[str, Any],
    ) -> dict[str, Any]:
        material = {
            "schema": "rvf.wallet-protected-transition-proposal.v1",
            "action_key": OublietteTransactionCoordinator.QUARANTINE_ACTION,
            "project_id": project_id,
            "section_id": section_id,
            "object_id": str(object_record.get("id") or ""),
            "object_sha256": str(object_record.get("hash") or ""),
            "source_state": str(object_record.get("state") or ""),
            "report_id": str(report.get("report_id") or ""),
            "report_hash": str(report.get("report_hash") or ""),
            "report_target_sha256": str(report.get("target_sha256") or ""),
            "destination_state": "quarantined",
            "automatic_trust": False,
            "target_executed": False,
        }
        proposal_hash = sha256_json(material)
        return {
            **material,
            "proposal_id": f"proposal-{proposal_hash}",
            "proposal_hash": proposal_hash,
        }

    def quarantine_proposal(
        self,
        *,
        project_id: str,
        section_id: str,
        object_id: str,
        report_id: str,
    ) -> dict[str, Any]:
        """Return the exact immutable proposal a quarantine ceremony must authorize."""
        with self.vault.catalog_transaction():
            report = self._validate_quarantine_report(
                project_id=project_id,
                section_id=section_id,
                object_id=object_id,
                report_id=report_id,
            )
            record = self.vault._find_file(project_id, section_id, object_id)
            if record.get("state") not in {"raw", "candidate"}:
                raise OublietteTransactionError(
                    "Quarantine proposal requires a Raw Source or Candidate"
                )
            return self._quarantine_proposal_material(
                project_id=project_id,
                section_id=section_id,
                object_record=record,
                report=report,
            )

    def _policy_decision(self, action_key: str, session_id: str) -> tuple[Any, dict[str, Any]]:
        identity = self.human_access.require_identity_session(session_id)
        decision = evaluate_protected_action(
            action_key,
            AccessActorKind.HUMAN,
            actor_identity=identity,
            human_ceremony_passed=True,
            gate=self.human_access,
        )
        if not decision.get("allowed"):
            raise OublietteTransactionError(
                decision.get("reason", "Human Intent policy denied Oubliette custody action")
            )
        return identity, decision

    def _validate_quarantine_report(
        self,
        *,
        project_id: str,
        section_id: str,
        object_id: str,
        report_id: str,
    ) -> dict[str, Any]:
        report = self.reports.get(report_id)
        if (
            report.get("project_id") != project_id
            or report.get("section_id") != section_id
            or report.get("object_id") != object_id
        ):
            raise OublietteTransactionError("inspection report scope does not match quarantine request")
        if not report.get("canonical_event_id") or not report.get("canonical_event_hash"):
            raise OublietteTransactionError("inspection report is not anchored to canonical BlackBox")
        record = self.vault._find_file(project_id, section_id, object_id)
        if report.get("target_sha256") != record.get("hash"):
            raise OublietteTransactionError("inspection report does not match current custodied bytes")
        return report

    def _observed_quarantine(self, journal: Mapping[str, Any]) -> tuple[str, dict[str, Any]]:
        project_id = str(journal["project_id"])
        section_id = str(journal["section_id"])
        object_id = str(journal["object_id"])
        record = self.vault._find_file(project_id, section_id, object_id)
        pre = dict(journal["pre_state"])
        quarantine_root = self.vault._compartment_dir(project_id, section_id, "quarantine")
        complete = (
            record.get("state") == "quarantined"
            and record.get("quarantine_operation_id") == journal.get("operation_id")
            and record.get("quarantine_report_id") == journal.get("report_id")
            and record.get("hash") == pre.get("hash")
        )
        if complete:
            try:
                path = self.vault._require_owned_custody_file(
                    record.get("vault_path"),
                    expected_compartment=quarantine_root,
                    label="quarantined object",
                )
                complete = self.vault._sha256(path) == pre.get("hash")
            except VaultError:
                complete = False
        if complete:
            return "complete", self._record_snapshot(record)

        unchanged = (
            record.get("state") == pre.get("state")
            and record.get("vault_path") == pre.get("vault_path")
            and record.get("hash") == pre.get("hash")
        )
        if unchanged:
            try:
                root = self.vault._compartment_dir(
                    project_id,
                    section_id,
                    self.vault._compartment_for_state(str(pre.get("state"))),
                )
                path = self.vault._require_owned_custody_file(
                    record.get("vault_path"), expected_compartment=root, label="pre-quarantine object"
                )
                unchanged = self.vault._sha256(path) == pre.get("hash")
                planned_destination = quarantine_root / self.vault._custody_destination_name(
                    object_id, Path(str(pre.get("vault_path") or "artifact.bin")).name
                )
                if planned_destination.exists() or planned_destination.is_symlink():
                    # A published quarantine copy with an unchanged catalog is
                    # an interrupted/competing custody transition, not a no-op.
                    unchanged = False
            except (VaultError, OSError):
                unchanged = False
        return ("unchanged" if unchanged else "ambiguous"), self._record_snapshot(record)

    def quarantine(
        self,
        *,
        project_id: str,
        section_id: str,
        object_id: str,
        report_id: str,
        ceremony_token: str,
        session_id: str,
        reason: str,
        fault_after: Optional[str] = None,
    ) -> dict[str, Any]:
        self._require_transaction_capability()
        try:
            with self.vault.catalog_transaction():
                with file_lock(self._scope_lock_path(project_id, section_id, object_id)):
                    return self._quarantine_locked(
                        project_id=project_id,
                        section_id=section_id,
                        object_id=object_id,
                        report_id=report_id,
                        ceremony_token=ceremony_token,
                        session_id=session_id,
                        reason=reason,
                        fault_after=fault_after,
                    )
        except (DurableIOError, VaultError) as exc:
            raise OublietteTransactionError(f"Oubliette authority lock failed: {exc}") from exc

    def _quarantine_locked(
        self,
        *,
        project_id: str,
        section_id: str,
        object_id: str,
        report_id: str,
        ceremony_token: str,
        session_id: str,
        reason: str,
        fault_after: Optional[str],
    ) -> dict[str, Any]:
        self.vault.assert_canonical_evidence_current(
            project_id=project_id,
            section_id=section_id,
            file_id=object_id,
        )
        report = self._validate_quarantine_report(
            project_id=project_id,
            section_id=section_id,
            object_id=object_id,
            report_id=report_id,
        )
        identity, decision = self._policy_decision(self.QUARANTINE_ACTION, session_id)
        record = self.vault._find_file(project_id, section_id, object_id)
        if record.get("state") not in {"raw", "candidate"}:
            raise OublietteTransactionError(
                "This bounded crossing quarantines only a Raw Source or Candidate"
            )
        proposal = self._quarantine_proposal_material(
            project_id=project_id,
            section_id=section_id,
            object_record=record,
            report=report,
        )
        ids = self._event_ids()
        journal = self.journal.reserve(
            {
                **ids,
                "action_key": self.QUARANTINE_ACTION,
                "project_id": project_id,
                "section_id": section_id,
                "object_id": object_id,
                "report_id": report_id,
                "report_hash": report["report_hash"],
                "proposal_id": proposal["proposal_id"],
                "proposal_hash": proposal["proposal_hash"],
                "session_id": session_id,
                "actor_id": identity.actor_id,
                "reason": reason,
                "policy": decision["policy"],
                "policy_hash": sha256_json(decision["policy"]),
                "receipt_issued_at": utc_now(),
                "pre_state": self._record_snapshot(record),
            }
        )
        actor = f"human:{identity.actor_id}"
        reserved = self._append_stage(
            journal,
            stage="RESERVED",
            event_type="HUMAN_INTENT_RESERVED",
            event_id_key="reserved_event_id",
            actor=actor,
            summary="Human Intent identifiers durably reserved for Oubliette quarantine",
            payload={
                "transaction_id": ids["operation_id"],
                "receipt_id": ids["receipt_id"],
                "action_key": self.QUARANTINE_ACTION,
                "project_id": project_id,
                "section_id": section_id,
                "object_id": object_id,
                "report_id": report_id,
                "report_hash": report["report_hash"],
                "proposal_id": proposal["proposal_id"],
                "proposal_hash": proposal["proposal_hash"],
            },
        )
        journal = self.journal.update(
            ids["operation_id"],
            reserved_event_hash=reserved["event_hash"],
            stage="RESERVED_RECORDED",
        )
        try:
            token_record = self.vault._require_open_token(
                ceremony_token,
                action_key=self.QUARANTINE_ACTION,
                session_id=session_id,
                project_id=project_id,
                section_id=section_id,
                object_id=object_id,
                proposal_id=proposal["proposal_id"],
                proposal_hash=proposal["proposal_hash"],
            )
            if token_record.get("legacy_unscoped"):
                raise OublietteTransactionError(
                    "quarantine requires an exact proposal-scoped ceremony token"
                )
        except Exception as exc:
            self._finalize_failed(
                journal,
                actor=actor,
                reason=f"authorization rejected: {type(exc).__name__}: {exc}",
            )
            raise
        token_id = str(token_record["token_id"])
        consumption_hash = self.vault.ceremony_ledger.record_hash(token_id)
        journal = self.journal.update(
            ids["operation_id"],
            ceremony_token_id=token_id,
            ceremony_consumption_hash=consumption_hash,
            stage="TOKEN_CONSUMED",
        )
        authorized = self._append_stage(
            journal,
            stage="AUTHORIZED",
            event_type="HUMAN_INTENT_AUTHORIZED",
            event_id_key="authorization_event_id",
            actor=actor,
            summary="Wallet authorized one scoped Oubliette quarantine transaction",
            payload={
                "transaction_id": ids["operation_id"],
                "receipt_id": ids["receipt_id"],
                "reserved_event_hash": reserved["event_hash"],
                "actor_id": identity.actor_id,
                "actor_kind": identity.actor_kind,
                "session_id": identity.session_id,
                "device_id": identity.device_id,
                "verified_methods": list(identity.verified_methods),
                "action_key": self.QUARANTINE_ACTION,
                "project_id": project_id,
                "section_id": section_id,
                "object_id": object_id,
                "report_id": report_id,
                "report_hash": report["report_hash"],
                "proposal_id": proposal["proposal_id"],
                "proposal_hash": proposal["proposal_hash"],
                "ceremony_token_id": token_id,
                "ceremony_consumption_hash": consumption_hash,
                "policy": decision["policy"],
                "policy_hash": journal["policy_hash"],
            },
        )
        journal = self.journal.update(
            ids["operation_id"],
            authorization_event_hash=authorized["event_hash"],
            stage="AUTHORIZED",
        )
        if fault_after == "authorized":
            raise SimulatedOublietteCrash("authorized")

        def fault_hook(stage: str) -> None:
            if fault_after == stage:
                raise SimulatedOublietteCrash(stage)

        try:
            result = self.vault._quarantine_file_unchecked(
                project_id,
                section_id,
                object_id,
                reason=reason,
                report_id=report_id,
                report_hash=report["report_hash"],
                transaction_id=ids["operation_id"],
                fault_hook=fault_hook,
            )
            return self._finalize_completed(
                journal,
                result,
                actor=actor,
                recovered=False,
                custody_event_type="OBJECT_QUARANTINED",
                custody_summary="Object moved into fenced Oubliette quarantine custody",
                result_state="quarantined",
                fault_after=fault_after,
            )
        except SimulatedOublietteCrash:
            raise
        except Exception as exc:
            outcome, observed = self._observed_quarantine(journal)
            if outcome == "unchanged":
                self._finalize_failed(journal, actor=actor, reason=f"{type(exc).__name__}: {exc}")
            elif outcome == "ambiguous":
                self._freeze_ambiguous(journal, observed, reason=f"{type(exc).__name__}: {exc}")
            raise

    def _validate_derivative_report(
        self,
        *,
        project_id: str,
        section_id: str,
        parent_object_id: str,
        report_id: str,
        capsule_id: Optional[str] = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        report = self.reports.get(report_id)
        report_capsule_id = str(report.get("capsule_id") or "")
        if (
            report.get("project_id") != project_id
            or report.get("section_id") != section_id
            or report.get("object_id") != parent_object_id
            or report.get("parent_object_id") != parent_object_id
            or report.get("report_role") != "wallet_intake_capsule"
            or not report_capsule_id
            or (capsule_id is not None and report_capsule_id != capsule_id)
        ):
            raise OublietteTransactionError(
                "Intake Capsule inspection report scope does not match admission request"
            )
        if not report.get("canonical_event_id") or not report.get("canonical_event_hash"):
            raise OublietteTransactionError(
                "Intake Capsule inspection report is not anchored to canonical BlackBox"
            )
        parent = self.vault._find_file(project_id, section_id, parent_object_id)
        if parent.get("state") != "quarantined":
            raise OublietteTransactionError(
                "capsule admission requires the original to remain quarantined"
            )
        if report.get("parent_sha256") != parent.get("hash"):
            raise OublietteTransactionError(
                "Intake Capsule report no longer matches the preserved parent"
            )
        try:
            capsule = self.capsules.get(report_capsule_id)
        except IntakeCapsuleError as exc:
            raise OublietteTransactionError(str(exc)) from exc
        if (
            capsule.get("project_id") != project_id
            or capsule.get("section_id") != section_id
            or capsule.get("parent_object_id") != parent_object_id
            or capsule.get("parent_sha256") != parent.get("hash")
            or capsule.get("manifest_hash") != report.get("manifest_hash")
            or capsule.get("blob_sha256") != report.get("blob_sha256")
            or capsule.get("blob_sha256") != report.get("target_sha256")
            or int(capsule.get("size_bytes") or -1) != int(report.get("size_bytes") or -2)
        ):
            raise OublietteTransactionError(
                "Intake Capsule, report, and parent lineage do not match"
            )
        return report, capsule

    def _observed_derivative(self, journal: Mapping[str, Any]) -> tuple[str, dict[str, Any]]:
        project_id = str(journal["project_id"])
        section_id = str(journal["section_id"])
        parent_id = str(journal["object_id"])
        candidate_id = str(journal["candidate_id"])
        section = self.vault.get_section(project_id, section_id)
        parent = self.vault._find_file(project_id, section_id, parent_id)
        candidate = next(
            (item for item in section.get("files", []) if item.get("id") == candidate_id),
            None,
        )
        candidates_root = self.vault._compartment_dir(project_id, section_id, "candidates")
        final = candidates_root / str(journal["candidate_filename"])
        expected_hash = str(journal.get("blob_sha256") or journal.get("derivative_sha256") or "")
        expected_size = int(journal.get("blob_size") or journal.get("derivative_size") or -1)
        parent_ok = (
            parent.get("state") == "quarantined"
            and parent.get("hash") == journal.get("parent_sha256")
        )
        if parent_ok:
            try:
                parent_path = self.vault._require_owned_custody_file(
                    parent.get("vault_path"),
                    expected_compartment=self.vault._compartment_dir(
                        project_id, section_id, "quarantine"
                    ),
                    label="quarantined capsule parent",
                )
                parent_ok = self.vault._sha256(parent_path) == journal.get("parent_sha256")
            except VaultError:
                parent_ok = False
        candidate_ok = False
        if candidate is not None:
            candidate_ok = (
                candidate.get("state") == "candidate"
                and candidate.get("hash") == expected_hash
                and candidate.get("parent_quarantined_id") == parent_id
                and candidate.get("oubliette_derivative_report_id") == journal.get("report_id")
                and candidate.get("admission_operation_id") == journal.get("operation_id")
            )
            if journal.get("capsule_id"):
                candidate_ok = candidate_ok and (
                    candidate.get("wallet_intake_capsule_id") == journal.get("capsule_id")
                    and candidate.get("wallet_intake_manifest_hash") == journal.get("manifest_hash")
                )
            if candidate_ok:
                try:
                    candidate_path = self.vault._require_owned_custody_file(
                        candidate.get("vault_path"),
                        expected_compartment=candidates_root,
                        label="admitted capsule Candidate",
                    )
                    candidate_ok = self.vault._sha256(candidate_path) == expected_hash
                except VaultError:
                    candidate_ok = False
        if parent_ok and candidate_ok:
            return "complete", {
                "parent": self._record_snapshot(parent),
                "candidate": self._record_snapshot(candidate),
            }
        if parent_ok and candidate is None and not final.is_symlink() and final.is_file():
            try:
                if self.vault._sha256(final) == expected_hash and final.stat().st_size == expected_size:
                    return "copy_only", {
                        "parent": self._record_snapshot(parent),
                        "candidate": None,
                        "candidate_path": str(final),
                    }
            except OSError:
                pass
        if parent_ok and candidate is None and not final.exists():
            return "unchanged", {
                "parent": self._record_snapshot(parent),
                "candidate": None,
            }
        return "ambiguous", {
            "parent": self._record_snapshot(parent),
            "candidate": self._record_snapshot(candidate) if candidate else None,
            "candidate_path_exists": final.exists(),
        }

    def admit_derivative_as_candidate(
        self,
        *,
        project_id: str,
        section_id: str,
        parent_object_id: str,
        report_id: str,
        ceremony_token: str,
        session_id: str,
        reason: str,
        capsule_id: Optional[str] = None,
        proposal_id: Optional[str] = None,
        proposal_hash: Optional[str] = None,
        derivative_path: Path | str | None = None,
        fault_after: Optional[str] = None,
    ) -> dict[str, Any]:
        """Compatibility entry point for capsule-scoped Candidate admission.

        ``derivative_path`` is intentionally ignored for authority.  The report
        must identify an immutable Wallet Intake Capsule created by the inspect
        compatibility wrapper or the explicit capture API.
        """
        report = self.reports.get(report_id)
        resolved_capsule_id = str(capsule_id or report.get("capsule_id") or "")
        if not resolved_capsule_id:
            raise OublietteTransactionError(
                "legacy path-bound derivative reports cannot authorize admission; capture and inspect a Wallet Intake Capsule"
            )
        return self.admit_intake_capsule_as_candidate(
            project_id=project_id,
            section_id=section_id,
            parent_object_id=parent_object_id,
            capsule_id=resolved_capsule_id,
            report_id=report_id,
            ceremony_token=ceremony_token,
            session_id=session_id,
            reason=reason,
            proposal_id=proposal_id,
            proposal_hash=proposal_hash,
            fault_after=fault_after,
        )

    def _existing_capsule_admission(self, capsule_id: str) -> Optional[dict[str, Any]]:
        try:
            admission = self.capsules.admission(capsule_id)
        except IntakeCapsuleError as exc:
            raise OublietteTransactionError(str(exc)) from exc
        if not admission:
            return None
        try:
            result = self.vault._find_file(
                str(self.capsules.get(capsule_id)["project_id"]),
                str(self.capsules.get(capsule_id)["section_id"]),
                str(admission["candidate_id"]),
            )
            receipt = self.receipts.get(str(admission["receipt_id"]))
            verification = self.verify_receipt(str(admission["receipt_id"]))
        except Exception as exc:
            raise OublietteTransactionError(
                f"existing capsule admission is incomplete or inconsistent: {type(exc).__name__}: {exc}"
            ) from exc
        if not verification.get("ok"):
            raise OublietteTransactionError(
                f"existing capsule admission receipt is invalid: {verification.get('reason')}"
            )
        return {
            "result": dict(result),
            "receipt": receipt,
            "verification": verification,
            "idempotent_existing": True,
        }

    def admit_intake_capsule_as_candidate(
        self,
        *,
        project_id: str,
        section_id: str,
        parent_object_id: str,
        capsule_id: str,
        report_id: str,
        ceremony_token: str,
        session_id: str,
        reason: str,
        proposal_id: Optional[str] = None,
        proposal_hash: Optional[str] = None,
        fault_after: Optional[str] = None,
    ) -> dict[str, Any]:
        self._require_transaction_capability()
        existing = self._existing_capsule_admission(capsule_id)
        if existing is not None:
            return existing
        try:
            with self.vault.catalog_transaction():
                with file_lock(self._scope_lock_path(project_id, section_id, capsule_id)):
                    existing = self._existing_capsule_admission(capsule_id)
                    if existing is not None:
                        return existing
                    return self._admit_capsule_locked(
                        project_id=project_id,
                        section_id=section_id,
                        parent_object_id=parent_object_id,
                        capsule_id=capsule_id,
                        report_id=report_id,
                        ceremony_token=ceremony_token,
                        session_id=session_id,
                        reason=reason,
                        proposal_id=proposal_id,
                        proposal_hash=proposal_hash,
                        fault_after=fault_after,
                    )
        except (DurableIOError, VaultError) as exc:
            raise OublietteTransactionError(
                f"Wallet Intake Capsule authority lock failed: {exc}"
            ) from exc

    def _admit_capsule_locked(
        self,
        *,
        project_id: str,
        section_id: str,
        parent_object_id: str,
        capsule_id: str,
        report_id: str,
        ceremony_token: str,
        session_id: str,
        reason: str,
        proposal_id: Optional[str],
        proposal_hash: Optional[str],
        fault_after: Optional[str],
    ) -> dict[str, Any]:
        self.vault.assert_canonical_evidence_current(
            project_id=project_id,
            section_id=section_id,
            file_id=parent_object_id,
        )
        report, capsule = self._validate_derivative_report(
            project_id=project_id,
            section_id=section_id,
            parent_object_id=parent_object_id,
            report_id=report_id,
            capsule_id=capsule_id,
        )
        parent = self.vault._find_file(project_id, section_id, parent_object_id)
        proposal = self._admission_proposal(
            project_id=project_id,
            section_id=section_id,
            parent_object_id=parent_object_id,
            parent_sha256=str(parent.get("hash") or ""),
            capsule=capsule,
            report=report,
        )
        if proposal_id is not None and proposal_id != proposal["proposal_id"]:
            raise OublietteTransactionError("admission proposal id does not match capsule/report scope")
        if proposal_hash is not None and proposal_hash != proposal["proposal_hash"]:
            raise OublietteTransactionError("admission proposal hash does not match capsule/report scope")

        identity, decision = self._policy_decision(self.DERIVATIVE_ACTION, session_id)
        ids = self._event_ids()
        candidate_id = hashlib.sha256(
            canonical_json(
                {
                    "capsule_id": capsule_id,
                    "manifest_hash": capsule["manifest_hash"],
                    "action_key": self.DERIVATIVE_ACTION,
                    "destination_state": "candidate",
                }
            )
        ).hexdigest()[:32]
        safe_label = portable_basename(str(capsule.get("source_label") or "intake.bin"), max_utf8_bytes=96)
        candidate_filename = f"{candidate_id}_{safe_label}"
        journal = self.journal.reserve(
            {
                **ids,
                "action_key": self.DERIVATIVE_ACTION,
                "project_id": project_id,
                "section_id": section_id,
                "object_id": parent_object_id,
                "candidate_id": candidate_id,
                "candidate_filename": candidate_filename,
                "capsule_id": capsule_id,
                "manifest_hash": capsule["manifest_hash"],
                "blob_sha256": capsule["blob_sha256"],
                "blob_size": int(capsule["size_bytes"]),
                "source_label": safe_label,
                "parent_sha256": parent.get("hash"),
                "report_id": report_id,
                "report_hash": report["report_hash"],
                "proposal_id": proposal["proposal_id"],
                "proposal_hash": proposal["proposal_hash"],
                "session_id": session_id,
                "actor_id": identity.actor_id,
                "reason": reason,
                "policy": decision["policy"],
                "policy_hash": sha256_json(decision["policy"]),
                "receipt_issued_at": utc_now(),
                "pre_state": self._record_snapshot(parent),
            }
        )
        actor = f"human:{identity.actor_id}"
        reserved = self._append_stage(
            journal,
            stage="RESERVED",
            event_type="HUMAN_INTENT_RESERVED",
            event_id_key="reserved_event_id",
            actor=actor,
            summary="Human Intent identifiers reserved for exact Intake Capsule admission",
            payload={
                "transaction_id": ids["operation_id"],
                "receipt_id": ids["receipt_id"],
                "action_key": self.DERIVATIVE_ACTION,
                "project_id": project_id,
                "section_id": section_id,
                "object_id": parent_object_id,
                "candidate_id": candidate_id,
                "capsule_id": capsule_id,
                "manifest_hash": capsule["manifest_hash"],
                "report_id": report_id,
                "report_hash": report["report_hash"],
                "proposal_id": proposal["proposal_id"],
                "proposal_hash": proposal["proposal_hash"],
                "blob_sha256": capsule["blob_sha256"],
            },
        )
        journal = self.journal.update(
            ids["operation_id"],
            reserved_event_hash=reserved["event_hash"],
            stage="RESERVED_RECORDED",
        )
        try:
            token_record = self.vault._require_open_token(
                ceremony_token,
                action_key=self.DERIVATIVE_ACTION,
                session_id=session_id,
                project_id=project_id,
                section_id=section_id,
                object_id=parent_object_id,
                proposal_id=proposal["proposal_id"],
                proposal_hash=proposal["proposal_hash"],
            )
            if token_record.get("legacy_unscoped"):
                raise OublietteTransactionError(
                    "capsule admission requires a proposal-scoped ceremony token"
                )
        except Exception as exc:
            self._finalize_failed(
                journal,
                actor=actor,
                reason=f"authorization rejected: {type(exc).__name__}: {exc}",
            )
            raise
        token_id = str(token_record["token_id"])
        consumption_hash = self.vault.ceremony_ledger.record_hash(token_id)
        journal = self.journal.update(
            ids["operation_id"],
            ceremony_token_id=token_id,
            ceremony_consumption_hash=consumption_hash,
            stage="TOKEN_CONSUMED",
        )
        authorized = self._append_stage(
            journal,
            stage="AUTHORIZED",
            event_type="HUMAN_INTENT_AUTHORIZED",
            event_id_key="authorization_event_id",
            actor=actor,
            summary="Wallet authorized one exact Intake Capsule to enter as Candidate",
            payload={
                "transaction_id": ids["operation_id"],
                "receipt_id": ids["receipt_id"],
                "reserved_event_hash": reserved["event_hash"],
                "actor_id": identity.actor_id,
                "actor_kind": identity.actor_kind,
                "session_id": identity.session_id,
                "device_id": identity.device_id,
                "verified_methods": list(identity.verified_methods),
                "action_key": self.DERIVATIVE_ACTION,
                "project_id": project_id,
                "section_id": section_id,
                "object_id": parent_object_id,
                "candidate_id": candidate_id,
                "capsule_id": capsule_id,
                "manifest_hash": capsule["manifest_hash"],
                "report_id": report_id,
                "report_hash": report["report_hash"],
                "proposal_id": proposal["proposal_id"],
                "proposal_hash": proposal["proposal_hash"],
                "blob_sha256": capsule["blob_sha256"],
                "ceremony_token_id": token_id,
                "ceremony_consumption_hash": consumption_hash,
                "policy": decision["policy"],
                "policy_hash": journal["policy_hash"],
            },
        )
        journal = self.journal.update(
            ids["operation_id"],
            authorization_event_hash=authorized["event_hash"],
            stage="AUTHORIZED",
        )
        if fault_after == "authorized":
            raise SimulatedOublietteCrash("authorized")

        def fault_hook(stage: str) -> None:
            if fault_after == stage:
                raise SimulatedOublietteCrash(stage)

        try:
            result = self.vault._admit_intake_capsule_unchecked(
                project_id,
                section_id,
                parent_object_id,
                capsule_path=str(capsule["absolute_blob_path"]),
                capsule_id=capsule_id,
                manifest_hash=str(capsule["manifest_hash"]),
                blob_sha256=str(capsule["blob_sha256"]),
                blob_size=int(capsule["size_bytes"]),
                source_label=safe_label,
                candidate_id=candidate_id,
                report_id=report_id,
                report_hash=report["report_hash"],
                transaction_id=ids["operation_id"],
                reason=reason,
                fault_hook=fault_hook,
            )
            return self._finalize_completed(
                journal,
                result,
                actor=actor,
                recovered=False,
                custody_event_type="WALLET_INTAKE_CAPSULE_ADMITTED_AS_CANDIDATE",
                custody_summary="Exact immutable Intake Capsule admitted as a new Candidate; parent remains quarantined",
                result_state="candidate",
                fault_after=fault_after,
            )
        except SimulatedOublietteCrash:
            raise
        except Exception as exc:
            outcome, observed = self._observed_derivative(journal)
            if outcome == "unchanged":
                self._finalize_failed(
                    journal, actor=actor, reason=f"{type(exc).__name__}: {exc}"
                )
            elif outcome == "ambiguous":
                self._freeze_ambiguous(
                    journal, observed, reason=f"{type(exc).__name__}: {exc}"
                )
            raise

    def _receipt_material(
        self,
        journal: Mapping[str, Any],
        *,
        actor: str,
        custody_event: Mapping[str, Any],
        terminal_event: Mapping[str, Any],
        recovered: bool,
        result_object_id: str,
        result_state: str,
    ) -> dict[str, Any]:
        action_key = str(journal["action_key"])
        if action_key == self.QUARANTINE_ACTION:
            action_label = "quarantine custodied object through Oubliette boundary"
            intent_statement = (
                "A Wallet-authorized local human identity session approved this "
                "scoped custody crossing after a static Oubliette report."
            )
        else:
            action_label = "admit exact Wallet Intake Capsule as a new Candidate"
            intent_statement = (
                "A Wallet-authorized local human identity session approved this exact "
                "immutable Intake Capsule and proposal to enter as a new Candidate while "
                "the original remained quarantined."
            )
        return {
            "receipt_id": journal["receipt_id"],
            "receipt_type": "human_intent_receipt_v2",
            "issued_at": journal["receipt_issued_at"],
            "operation_id": journal["operation_id"],
            "action_key": action_key,
            "action_label": action_label,
            "project_id": journal["project_id"],
            "section_id": journal["section_id"],
            "object_id": journal["object_id"],
            "result_object_id": result_object_id,
            "report_id": journal["report_id"],
            "report_hash": journal["report_hash"],
            "capsule_id": journal.get("capsule_id"),
            "manifest_hash": journal.get("manifest_hash"),
            "blob_sha256": journal.get("blob_sha256"),
            "proposal_id": journal.get("proposal_id"),
            "proposal_hash": journal.get("proposal_hash"),
            "actor_id": journal["actor_id"],
            "actor": actor,
            "session_id": journal["session_id"],
            "ceremony_token_id": journal["ceremony_token_id"],
            "ceremony_consumption_hash": journal["ceremony_consumption_hash"],
            "policy_hash": journal["policy_hash"],
            "reserved_event_id": journal["reserved_event_id"],
            "reserved_event_hash": journal["reserved_event_hash"],
            "authorization_event_id": journal["authorization_event_id"],
            "authorization_event_hash": journal["authorization_event_hash"],
            "custody_event_id": custody_event["event_id"],
            "custody_event_hash": custody_event["event_hash"],
            "terminal_event_id": terminal_event["event_id"],
            "terminal_event_hash": terminal_event["event_hash"],
            "anchor_event_id": journal["anchor_event_id"],
            "result_status": "completed",
            "result_state": result_state,
            "recovered_after_restart": bool(recovered),
            "intent_statement": intent_statement,
            "evidence_limits": (
                "Local continuity evidence. Oubliette reported static indicators only; "
                "it did not determine malware, independently authenticate identity, or decide trust."
            ),
        }

    def _finalize_completed(
        self,
        journal: Mapping[str, Any],
        result: Mapping[str, Any],
        *,
        actor: str,
        recovered: bool,
        custody_event_type: str,
        custody_summary: str,
        result_state: str,
        fault_after: Optional[str] = None,
    ) -> dict[str, Any]:
        operation_id = str(journal["operation_id"])
        if "completion_recovered_after_restart" not in journal:
            journal = self.journal.update(
                operation_id,
                completion_recovered_after_restart=bool(recovered),
            )
        completion_recovered = bool(journal["completion_recovered_after_restart"])
        result_object_id = str(result.get("id") or journal["object_id"])
        journal = self.journal.update(
            operation_id,
            result_object_id=result_object_id,
            result_state=result_state,
        )
        custody = self._append_stage(
            journal,
            stage="CUSTODY",
            event_type=custody_event_type,
            event_id_key="custody_event_id",
            actor=actor,
            summary=custody_summary,
            payload={
                "transaction_id": operation_id,
                "authorization_event_hash": journal["authorization_event_hash"],
                "project_id": journal["project_id"],
                "section_id": journal["section_id"],
                "file_id": result_object_id,
                "object_id": journal["object_id"],
                "parent_object_id": (
                    journal["object_id"]
                    if journal.get("action_key") == self.DERIVATIVE_ACTION
                    else None
                ),
                "result_object_id": result_object_id,
                "report_id": journal["report_id"],
                "report_hash": journal["report_hash"],
                "capsule_id": journal.get("capsule_id"),
                "manifest_hash": journal.get("manifest_hash"),
                "proposal_id": journal.get("proposal_id"),
                "proposal_hash": journal.get("proposal_hash"),
                "state": result_state,
                "reason": journal.get("reason") or "",
                "recovered_after_restart": completion_recovered,
            },
        )
        journal = self.journal.update(
            operation_id,
            custody_event_hash=custody["event_hash"],
            stage="CUSTODY_RECORDED",
        )
        terminal = self._append_stage(
            journal,
            stage="COMPLETED",
            event_type="HUMAN_INTENT_COMPLETED",
            event_id_key="terminal_event_id",
            actor=actor,
            summary="Protected Oubliette custody transaction completed",
            payload={
                "transaction_id": operation_id,
                "authorization_event_hash": journal["authorization_event_hash"],
                "custody_event_hash": custody["event_hash"],
                "result_status": "completed",
                "project_id": journal["project_id"],
                "section_id": journal["section_id"],
                "object_id": journal["object_id"],
                "result_object_id": result_object_id,
                "report_id": journal["report_id"],
                "capsule_id": journal.get("capsule_id"),
                "proposal_id": journal.get("proposal_id"),
                "proposal_hash": journal.get("proposal_hash"),
                "result_state": result_state,
                "recovered_after_restart": completion_recovered,
            },
        )
        journal = self.journal.update(
            operation_id,
            terminal_event_hash=terminal["event_hash"],
            stage="COMPLETED_RECORDED",
        )
        receipt = self._receipt_material(
            journal,
            actor=actor,
            custody_event=custody,
            terminal_event=terminal,
            recovered=completion_recovered,
            result_object_id=result_object_id,
            result_state=result_state,
        )
        receipt_hash = HumanIntentReceiptStore.core_hash(receipt)
        anchor = self._append_stage(
            journal,
            stage="RECEIPT_ANCHORED",
            event_type="HUMAN_INTENT_RECEIPT_ANCHORED",
            event_id_key="anchor_event_id",
            actor=actor,
            summary="Portable Human Intent receipt anchored to canonical evidence",
            payload={
                "transaction_id": operation_id,
                "receipt_id": journal["receipt_id"],
                "receipt_hash": receipt_hash,
                "authorization_event_hash": journal["authorization_event_hash"],
                "terminal_event_hash": terminal["event_hash"],
                "ceremony_consumption_hash": journal["ceremony_consumption_hash"],
                "proposal_id": journal.get("proposal_id"),
                "proposal_hash": journal.get("proposal_hash"),
            },
        )
        journal = self.journal.update(
            operation_id,
            anchor_event_hash=anchor["event_hash"],
            receipt_hash=receipt_hash,
            stage="RECEIPT_ANCHORED",
        )
        receipt["anchor_event_hash"] = anchor["event_hash"]
        if fault_after == "anchor_recorded":
            raise SimulatedOublietteCrash("anchor_recorded")
        stored = self.receipts.create(receipt)
        journal = self.journal.update(
            operation_id,
            receipt_written=True,
            stage="RECEIPT_WRITTEN",
        )
        if fault_after == "receipt_written":
            raise SimulatedOublietteCrash("receipt_written")
        verification = self.verify_receipt(stored["receipt_id"])
        if not verification.get("ok"):
            raise OublietteTransactionError(
                f"new Oubliette Human Intent receipt failed verification: {verification.get('reason')}"
            )
        if journal.get("capsule_id"):
            try:
                self.capsules.bind_admission(
                    str(journal["capsule_id"]),
                    candidate_id=result_object_id,
                    operation_id=operation_id,
                    receipt_id=str(stored["receipt_id"]),
                    candidate_sha256=str(result.get("hash") or journal.get("blob_sha256") or ""),
                )
            except IntakeCapsuleError as exc:
                raise OublietteTransactionError(f"could not bind capsule admission: {exc}") from exc
        self.journal.complete(
            operation_id,
            anchor_event_hash=anchor["event_hash"],
            receipt_hash=stored["receipt_hash"],
            receipt_id=stored["receipt_id"],
            recovered_after_restart=completion_recovered,
        )
        return {"result": dict(result), "receipt": stored, "verification": verification}

    def _finalize_failed(self, journal: Mapping[str, Any], *, actor: str, reason: str) -> None:
        terminal = self._append_stage(
            journal,
            stage="FAILED",
            event_type="HUMAN_INTENT_FAILED",
            event_id_key="terminal_event_id",
            actor=actor,
            summary="Protected Oubliette custody transaction failed before a proven mutation",
            payload={
                "transaction_id": journal["operation_id"],
                "authorization_event_hash": journal.get("authorization_event_hash"),
                "result_status": "failed",
                "reason_class": reason[:200],
            },
        )
        self.journal.fail(
            str(journal["operation_id"]),
            terminal_event_hash=terminal["event_hash"],
            failure_reason=reason[:500],
        )

    def _freeze_ambiguous(
        self,
        journal: Mapping[str, Any],
        observed: Mapping[str, Any],
        *,
        reason: str,
    ) -> None:
        record = self.vault._find_file(
            str(journal["project_id"]),
            str(journal["section_id"]),
            str(journal["object_id"]),
        )
        section = self.vault.get_section(
            str(journal["project_id"]), str(journal["section_id"])
        )
        record["custody_locked"] = True
        record["custody_lock_reason"] = "oubliette_reconciliation_required"
        section["reconciliation_required"] = True
        section["reconciliation_operation_id"] = journal["operation_id"]
        self.vault._save()
        event = self.evidence.append_fact(
            event_type="OUBLIETTE_RECONCILIATION_REQUIRED",
            summary="Oubliette custody state is ambiguous; further crossings frozen",
            transaction_id=str(journal["operation_id"]),
            stage_key=f"{journal['operation_id']}:RECONCILIATION_REQUIRED",
            actor="wallet:reconciler",
            subject_id=f"object:{journal['object_id']}",
            payload={
                "transaction_id": journal["operation_id"],
                "project_id": journal["project_id"],
                "section_id": journal["section_id"],
                "object_id": journal["object_id"],
                "reason_class": reason[:200],
                "observed_state": observed,
                "coverage_gap": True,
            },
        )
        self.journal.require_reconciliation(
            str(journal["operation_id"]),
            reconciliation_event_hash=event["event_hash"],
            observed_state=observed,
            reason=reason[:500],
        )

    def reconcile_pending(self) -> dict[str, Any]:
        report = {
            "checked": 0,
            "reconciled": 0,
            "failed": 0,
            "ambiguous": 0,
            "receipts": [],
        }
        for pending in self.journal.pending():
            report["checked"] += 1
            project_id = str(pending["project_id"])
            section_id = str(pending["section_id"])
            object_id = str(pending["object_id"])
            action_key = str(pending.get("action_key") or "")
            try:
                with self.vault.catalog_transaction():
                    with file_lock(
                        self._scope_lock_path(project_id, section_id, object_id)
                    ):
                        journal = self.journal.get(str(pending["operation_id"]))
                        if journal.get("stage") in OublietteJournal.TERMINAL_STAGES:
                            continue
                        actor = f"human:{journal.get('actor_id') or 'unknown'}"
                        if action_key == self.QUARANTINE_ACTION:
                            outcome, observed = self._observed_quarantine(journal)
                            if outcome == "complete":
                                result = self.vault._find_file(
                                    project_id, section_id, object_id
                                )
                                completed = self._finalize_completed(
                                    journal,
                                    result,
                                    actor=actor,
                                    recovered=True,
                                    custody_event_type="OBJECT_QUARANTINED",
                                    custody_summary=(
                                        "Object moved into fenced Oubliette quarantine custody"
                                    ),
                                    result_state="quarantined",
                                )
                                report["reconciled"] += 1
                                report["receipts"].append(
                                    completed["receipt"]["receipt_id"]
                                )
                            elif outcome == "unchanged":
                                self._finalize_failed(
                                    journal,
                                    actor=actor,
                                    reason=(
                                        "restart reconciliation observed no custody mutation"
                                    ),
                                )
                                report["failed"] += 1
                            else:
                                self._freeze_ambiguous(
                                    journal,
                                    observed,
                                    reason=(
                                        "restart reconciliation could not prove completion or no-op"
                                    ),
                                )
                                report["ambiguous"] += 1
                        elif action_key == self.DERIVATIVE_ACTION:
                            outcome, observed = self._observed_derivative(journal)
                            if outcome == "copy_only":
                                # The authorized bytes are already in the final
                                # Candidate compartment with the precommitted hash.
                                # Complete only the missing catalog record.
                                if journal.get("capsule_id"):
                                    capsule = self.capsules.get(str(journal["capsule_id"]))
                                    result = self.vault._admit_intake_capsule_unchecked(
                                        project_id,
                                        section_id,
                                        object_id,
                                        capsule_path=str(capsule["absolute_blob_path"]),
                                        capsule_id=str(journal["capsule_id"]),
                                        manifest_hash=str(journal["manifest_hash"]),
                                        blob_sha256=str(journal["blob_sha256"]),
                                        blob_size=int(journal["blob_size"]),
                                        source_label=str(journal.get("source_label") or "intake.bin"),
                                        candidate_id=str(journal["candidate_id"]),
                                        report_id=str(journal["report_id"]),
                                        report_hash=str(journal["report_hash"]),
                                        transaction_id=str(journal["operation_id"]),
                                        reason=str(journal.get("reason") or ""),
                                    )
                                else:
                                    result = self.vault._admit_oubliette_derivative_unchecked(
                                        project_id,
                                        section_id,
                                        object_id,
                                        derivative_path=str(journal["derivative_path"]),
                                        derivative_sha256=str(journal["derivative_sha256"]),
                                        derivative_size=int(journal["derivative_size"]),
                                        candidate_id=str(journal["candidate_id"]),
                                        report_id=str(journal["report_id"]),
                                        report_hash=str(journal["report_hash"]),
                                        transaction_id=str(journal["operation_id"]),
                                        reason=str(journal.get("reason") or ""),
                                    )
                                outcome = "complete"
                            elif outcome == "complete":
                                result = self.vault._find_file(
                                    project_id,
                                    section_id,
                                    str(journal["candidate_id"]),
                                )
                            if outcome == "complete":
                                completed = self._finalize_completed(
                                    journal,
                                    result,
                                    actor=actor,
                                    recovered=True,
                                    custody_event_type=(
                                        "WALLET_INTAKE_CAPSULE_ADMITTED_AS_CANDIDATE"
                                        if journal.get("capsule_id")
                                        else "OUBLIETTE_DERIVATIVE_ADMITTED_AS_CANDIDATE"
                                    ),
                                    custody_summary=(
                                        "Exact immutable Intake Capsule admitted as a new Candidate; parent remains quarantined"
                                        if journal.get("capsule_id")
                                        else "Inspected derivative admitted as a new Candidate; parent remains quarantined"
                                    ),
                                    result_state="candidate",
                                )
                                report["reconciled"] += 1
                                report["receipts"].append(
                                    completed["receipt"]["receipt_id"]
                                )
                            elif outcome == "unchanged":
                                self._finalize_failed(
                                    journal,
                                    actor=actor,
                                    reason=(
                                        "restart reconciliation observed no Candidate admission"
                                    ),
                                )
                                report["failed"] += 1
                            else:
                                self._freeze_ambiguous(
                                    journal,
                                    observed,
                                    reason=(
                                        "restart reconciliation could not prove derivative admission or no-op"
                                    ),
                                )
                                report["ambiguous"] += 1
                        else:
                            self._freeze_ambiguous(
                                journal,
                                {"action_key": action_key},
                                reason=(
                                    "no reconciliation proof is registered for this Oubliette action"
                                ),
                            )
                            report["ambiguous"] += 1
            except (DurableIOError, VaultError) as exc:
                raise OublietteTransactionError(
                    f"Oubliette reconciliation lock failed: {exc}"
                ) from exc
        return report

    def verify_receipt(self, receipt_id: str) -> dict[str, Any]:
        try:
            receipt = self.receipts.get(receipt_id)
        except CanonicalEvidenceError as exc:
            return {"ok": False, "status": "invalid", "reason": str(exc)}
        action_key = str(receipt.get("action_key") or "")
        if action_key not in {self.QUARANTINE_ACTION, self.DERIVATIVE_ACTION}:
            return {"ok": False, "status": "invalid", "reason": "wrong receipt verifier"}
        if receipt.get("receipt_hash") != HumanIntentReceiptStore.core_hash(receipt):
            return {"ok": False, "status": "invalid", "reason": "receipt hash mismatch"}
        chain = self.evidence.verify_chain()
        if not chain.get("ok"):
            return {
                "ok": False,
                "status": "invalid",
                "reason": "canonical BlackBox chain invalid",
                "chain": chain,
            }
        expected_custody = (
            "OBJECT_QUARANTINED"
            if action_key == self.QUARANTINE_ACTION
            else (
                "WALLET_INTAKE_CAPSULE_ADMITTED_AS_CANDIDATE"
                if receipt.get("capsule_id")
                else "OUBLIETTE_DERIVATIVE_ADMITTED_AS_CANDIDATE"
            )
        )
        expected = [
            ("reserved_event_id", "reserved_event_hash", "HUMAN_INTENT_RESERVED"),
            ("authorization_event_id", "authorization_event_hash", "HUMAN_INTENT_AUTHORIZED"),
            ("custody_event_id", "custody_event_hash", expected_custody),
            ("terminal_event_id", "terminal_event_hash", "HUMAN_INTENT_COMPLETED"),
            ("anchor_event_id", "anchor_event_hash", "HUMAN_INTENT_RECEIPT_ANCHORED"),
        ]
        required_ids = {str(receipt.get(id_key) or "") for id_key, _, _ in expected}
        if "" in required_ids or len(required_ids) != len(expected):
            return {
                "ok": False,
                "status": "invalid",
                "reason": "receipt graph uses missing or duplicate record ids",
            }
        records: list[dict[str, Any]] = []
        for id_key, hash_key, event_type in expected:
            record = self.evidence.record_by_id(str(receipt.get(id_key) or ""))
            if not record:
                return {
                    "ok": False,
                    "status": "invalid",
                    "reason": f"missing {event_type} record",
                }
            if record.get("hash") != receipt.get(hash_key):
                return {
                    "ok": False,
                    "status": "invalid",
                    "reason": f"{event_type} hash mismatch",
                }
            if record.get("event_type") != event_type:
                return {
                    "ok": False,
                    "status": "invalid",
                    "reason": f"wrong event type for {id_key}",
                }
            if (record.get("payload") or {}).get("transaction_id") != receipt.get(
                "operation_id"
            ):
                return {
                    "ok": False,
                    "status": "invalid",
                    "reason": f"{event_type} transaction mismatch",
                }
            records.append(record)
        if [int(item["seq"]) for item in records] != sorted(
            int(item["seq"]) for item in records
        ):
            return {"ok": False, "status": "invalid", "reason": "receipt graph out of order"}

        operation_records = self.evidence.records_for_operation(
            str(receipt.get("operation_id") or "")
        )
        graph_types = {event_type for _, _, event_type in expected}
        contradictory = {"HUMAN_INTENT_FAILED", "OUBLIETTE_RECONCILIATION_REQUIRED"}
        graph_records = [
            record
            for record in operation_records
            if record.get("event_type") in graph_types | contradictory
        ]
        if any(record.get("event_type") in contradictory for record in graph_records):
            return {
                "ok": False,
                "status": "invalid",
                "reason": "receipt graph contains contradictory terminal evidence",
            }
        for event_type in graph_types:
            if len([r for r in graph_records if r.get("event_type") == event_type]) != 1:
                return {
                    "ok": False,
                    "status": "invalid",
                    "reason": f"receipt graph has duplicate or missing {event_type} stage",
                }
        if {str(record.get("record_id")) for record in graph_records} != required_ids:
            return {
                "ok": False,
                "status": "invalid",
                "reason": "receipt graph contains an uncommitted extra stage",
            }

        reserved, authorized, custody, terminal, anchor = [
            item.get("payload") or {} for item in records
        ]
        for name, payload in (
            ("reserved", reserved),
            ("authorization", authorized),
            ("custody", custody),
            ("terminal", terminal),
        ):
            if payload.get("project_id") != receipt.get("project_id"):
                return {
                    "ok": False,
                    "status": "invalid",
                    "reason": f"{name} project scope mismatch",
                }
            if payload.get("section_id") != receipt.get("section_id"):
                return {
                    "ok": False,
                    "status": "invalid",
                    "reason": f"{name} section scope mismatch",
                }
        if reserved.get("receipt_id") != receipt.get("receipt_id"):
            return {"ok": False, "status": "invalid", "reason": "reserved receipt mismatch"}
        if reserved.get("action_key") != action_key:
            return {"ok": False, "status": "invalid", "reason": "reserved action mismatch"}
        if reserved.get("object_id") != receipt.get("object_id"):
            return {"ok": False, "status": "invalid", "reason": "reserved object mismatch"}
        if authorized.get("receipt_id") != receipt.get("receipt_id"):
            return {
                "ok": False,
                "status": "invalid",
                "reason": "authorization receipt mismatch",
            }
        if authorized.get("action_key") != action_key:
            return {
                "ok": False,
                "status": "invalid",
                "reason": "authorization action mismatch",
            }
        if authorized.get("object_id") != receipt.get("object_id"):
            return {
                "ok": False,
                "status": "invalid",
                "reason": "authorization object mismatch",
            }
        if (
            authorized.get("actor_id") != receipt.get("actor_id")
            or authorized.get("session_id") != receipt.get("session_id")
        ):
            return {
                "ok": False,
                "status": "invalid",
                "reason": "authorization identity mismatch",
            }
        if (
            authorized.get("ceremony_token_id") != receipt.get("ceremony_token_id")
            or authorized.get("ceremony_consumption_hash")
            != receipt.get("ceremony_consumption_hash")
        ):
            return {"ok": False, "status": "invalid", "reason": "ceremony binding mismatch"}
        if authorized.get("policy_hash") != receipt.get("policy_hash"):
            return {"ok": False, "status": "invalid", "reason": "policy hash mismatch"}
        policy = authorized.get("policy")
        if not isinstance(policy, Mapping) or sha256_json(policy) != receipt.get(
            "policy_hash"
        ):
            return {"ok": False, "status": "invalid", "reason": "policy snapshot mismatch"}
        if receipt.get("proposal_id"):
            for name, payload in (
                ("reserved", reserved),
                ("authorization", authorized),
                ("custody", custody),
                ("terminal", terminal),
                ("anchor", anchor),
            ):
                if payload.get("proposal_id") != receipt.get("proposal_id"):
                    return {"ok": False, "status": "invalid", "reason": f"{name} proposal id mismatch"}
                if payload.get("proposal_hash") != receipt.get("proposal_hash"):
                    return {"ok": False, "status": "invalid", "reason": f"{name} proposal hash mismatch"}
        if receipt.get("capsule_id"):
            if reserved.get("capsule_id") != receipt.get("capsule_id"):
                return {"ok": False, "status": "invalid", "reason": "reserved capsule mismatch"}
            if authorized.get("capsule_id") != receipt.get("capsule_id"):
                return {"ok": False, "status": "invalid", "reason": "authorization capsule mismatch"}
            if authorized.get("manifest_hash") != receipt.get("manifest_hash"):
                return {"ok": False, "status": "invalid", "reason": "authorization manifest mismatch"}
        if custody.get("authorization_event_hash") != receipt.get(
            "authorization_event_hash"
        ):
            return {
                "ok": False,
                "status": "invalid",
                "reason": "custody authorization link mismatch",
            }
        if custody.get("object_id") != receipt.get("object_id"):
            return {"ok": False, "status": "invalid", "reason": "custody authority scope mismatch"}
        if custody.get("result_object_id") != receipt.get("result_object_id"):
            return {"ok": False, "status": "invalid", "reason": "custody result scope mismatch"}
        if custody.get("state") != receipt.get("result_state"):
            return {"ok": False, "status": "invalid", "reason": "custody result state mismatch"}
        if (
            terminal.get("authorization_event_hash")
            != receipt.get("authorization_event_hash")
            or terminal.get("custody_event_hash") != receipt.get("custody_event_hash")
        ):
            return {
                "ok": False,
                "status": "invalid",
                "reason": "terminal evidence link mismatch",
            }
        if terminal.get("result_status") != receipt.get("result_status"):
            return {"ok": False, "status": "invalid", "reason": "terminal result mismatch"}
        if terminal.get("result_object_id") != receipt.get("result_object_id"):
            return {"ok": False, "status": "invalid", "reason": "terminal result scope mismatch"}
        if terminal.get("result_state") != receipt.get("result_state"):
            return {"ok": False, "status": "invalid", "reason": "terminal state mismatch"}
        if (
            anchor.get("receipt_id") != receipt.get("receipt_id")
            or anchor.get("receipt_hash") != receipt.get("receipt_hash")
        ):
            return {
                "ok": False,
                "status": "invalid",
                "reason": "anchor receipt binding mismatch",
            }
        if (
            anchor.get("authorization_event_hash")
            != receipt.get("authorization_event_hash")
            or anchor.get("terminal_event_hash") != receipt.get("terminal_event_hash")
            or anchor.get("ceremony_consumption_hash")
            != receipt.get("ceremony_consumption_hash")
        ):
            return {"ok": False, "status": "invalid", "reason": "anchor evidence link mismatch"}

        try:
            stored_report = self.reports.get(str(receipt.get("report_id") or ""))
        except OublietteTransactionError as exc:
            return {"ok": False, "status": "invalid", "reason": str(exc)}
        if stored_report.get("report_hash") != receipt.get("report_hash"):
            return {
                "ok": False,
                "status": "invalid",
                "reason": "inspection report binding mismatch",
            }
        if (
            stored_report.get("project_id") != receipt.get("project_id")
            or stored_report.get("section_id") != receipt.get("section_id")
            or stored_report.get("object_id") != receipt.get("object_id")
        ):
            return {"ok": False, "status": "invalid", "reason": "inspection report scope mismatch"}
        try:
            authority_object = self.vault._find_file(
                str(receipt.get("project_id")),
                str(receipt.get("section_id")),
                str(receipt.get("object_id")),
            )
        except VaultError as exc:
            return {"ok": False, "status": "invalid", "reason": f"authority object unavailable: {exc}"}
        if action_key == self.QUARANTINE_ACTION:
            if stored_report.get("report_role") != "custodied_intake":
                return {"ok": False, "status": "invalid", "reason": "wrong report role"}
            if stored_report.get("target_sha256") != authority_object.get("hash"):
                return {"ok": False, "status": "invalid", "reason": "quarantine report target mismatch"}
            if receipt.get("result_object_id") != receipt.get("object_id"):
                return {"ok": False, "status": "invalid", "reason": "quarantine result identity mismatch"}
        else:
            capsule_id = str(receipt.get("capsule_id") or "")
            expected_role = "wallet_intake_capsule" if capsule_id else "external_derivative"
            if stored_report.get("report_role") != expected_role:
                return {"ok": False, "status": "invalid", "reason": "wrong derivative report role"}
            if stored_report.get("parent_sha256") != authority_object.get("hash"):
                return {"ok": False, "status": "invalid", "reason": "derivative parent binding mismatch"}
            try:
                result_object = self.vault._find_file(
                    str(receipt.get("project_id")),
                    str(receipt.get("section_id")),
                    str(receipt.get("result_object_id")),
                )
            except VaultError as exc:
                return {"ok": False, "status": "invalid", "reason": f"result Candidate unavailable: {exc}"}
            if (
                result_object.get("hash") != stored_report.get("target_sha256")
                or result_object.get("parent_quarantined_id") != receipt.get("object_id")
                or result_object.get("oubliette_derivative_report_id")
                != receipt.get("report_id")
                or result_object.get("admission_operation_id")
                != receipt.get("operation_id")
            ):
                return {"ok": False, "status": "invalid", "reason": "derivative Candidate lineage mismatch"}
            if capsule_id:
                try:
                    capsule = self.capsules.get(capsule_id)
                    admission = self.capsules.admission(capsule_id)
                except IntakeCapsuleError as exc:
                    return {"ok": False, "status": "invalid", "reason": str(exc)}
                if (
                    capsule.get("manifest_hash") != receipt.get("manifest_hash")
                    or capsule.get("blob_sha256") != receipt.get("blob_sha256")
                    or stored_report.get("capsule_id") != capsule_id
                    or stored_report.get("manifest_hash") != receipt.get("manifest_hash")
                    or result_object.get("wallet_intake_capsule_id") != capsule_id
                    or result_object.get("wallet_intake_manifest_hash") != receipt.get("manifest_hash")
                ):
                    return {"ok": False, "status": "invalid", "reason": "Intake Capsule lineage mismatch"}
                if admission is not None and (
                    admission.get("candidate_id") != receipt.get("result_object_id")
                    or admission.get("operation_id") != receipt.get("operation_id")
                    or admission.get("receipt_id") != receipt.get("receipt_id")
                ):
                    return {"ok": False, "status": "invalid", "reason": "capsule admission binding mismatch"}

        token_id = str(receipt.get("ceremony_token_id") or "")
        try:
            token_record = self.vault.ceremony_ledger.get_record(
                token_id, include_hash=True
            )
            token_hash = self.vault.ceremony_ledger.record_hash(token_id)
        except Exception as exc:
            return {
                "ok": False,
                "status": "invalid",
                "reason": f"ceremony record unavailable: {exc}",
            }
        if token_hash != receipt.get("ceremony_consumption_hash"):
            return {
                "ok": False,
                "status": "invalid",
                "reason": "ceremony consumption hash mismatch",
            }
        token_scope = [
            ("action_key", action_key),
            ("session_id", receipt.get("session_id")),
            ("project_id", receipt.get("project_id")),
            ("section_id", receipt.get("section_id")),
            ("object_id", receipt.get("object_id")),
        ]
        if receipt.get("capsule_id"):
            token_scope.extend([
                ("proposal_id", receipt.get("proposal_id")),
                ("proposal_hash", receipt.get("proposal_hash")),
            ])
        for key, expected_value in token_scope:
            if token_record.get(key) != expected_value:
                return {
                    "ok": False,
                    "status": "invalid",
                    "reason": f"ceremony {key} mismatch",
                }
        if (
            not token_record.get("consumed_at")
            or token_record.get("consumed_by_action") != action_key
        ):
            return {
                "ok": False,
                "status": "invalid",
                "reason": "ceremony token not consumed for action",
            }
        return {
            "ok": True,
            "status": "complete",
            "receipt_id": receipt_id,
            "operation_id": receipt.get("operation_id"),
            "chain": chain,
            "evidence_limit": receipt.get("evidence_limits"),
        }
