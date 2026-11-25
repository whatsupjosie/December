"""Recoverable Human Intent protocol for Retire and Restore transitions.

Retire and Restore are exact, reversible custody-state changes. They never
reduce protected content. The prior active directory entry is preserved as
private transition evidence, the destination is published no-clobber, and all
authority/evidence identifiers are durably reserved before mutation.
"""
from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Optional
from uuid import uuid4

from blackbox_plugin.schema import canonical_json

from iteration_wallet.canonical_evidence import (
    CanonicalEvidenceAdapter,
    HumanIntentReceiptStore,
)
from iteration_wallet.custody_io import ensure_private_directory, verified_regular_file
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
from iteration_wallet.notification_manager import ActorKind, NotificationManager
from iteration_wallet.vault_v21 import VaultEngine, VaultError


class StateTransitionTransactionError(Exception):
    """Raised when Retire or Restore cannot safely complete."""


class SimulatedStateTransitionCrash(BaseException):
    """Fault-injection sentinel used only by deterministic regression tests."""

    def __init__(self, stage: str) -> None:
        super().__init__(f"simulated process crash after {stage}")
        self.stage = stage


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def sha256_json(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json(payload)).hexdigest()


class StateTransitionJournal:
    """Sealed Wallet-owned recovery state, never canonical evidence."""

    JOURNAL_VERSION = 1

    def __init__(self, vault_root: Path | str) -> None:
        self.vault_root = Path(vault_root)
        self.root = self.vault_root / "recovery_journal" / "state_transitions"
        self.active_dir = self.root / "active"
        self.completed_dir = self.root / "completed"
        self.reconciliation_dir = self.root / "reconciliation_required"
        self.lock_dir = self.root / ".locks"
        try:
            ensure_within(
                self.vault_root,
                self.root,
                label="state-transition journal",
                error_type=StateTransitionTransactionError,
            )
        except DurableIOError as exc:
            raise StateTransitionTransactionError(str(exc)) from exc
        for path, label in (
            (self.root, "state-transition journal"),
            (self.active_dir, "active state-transition journal"),
            (self.completed_dir, "completed state-transition journal"),
            (self.reconciliation_dir, "state-transition reconciliation journal"),
            (self.lock_dir, "state-transition journal locks"),
        ):
            ensure_private_directory(path, error_type=StateTransitionTransactionError, label=label)

    @staticmethod
    def _operation_id(operation_id: str) -> str:
        try:
            return validate_storage_id(
                "operation_id", operation_id, error_type=StateTransitionTransactionError
            )
        except DurableIOError as exc:
            raise StateTransitionTransactionError(str(exc)) from exc

    @staticmethod
    def record_hash(material: Mapping[str, Any]) -> str:
        body = {key: value for key, value in dict(material).items() if key != "record_hash"}
        return hashlib.sha256(canonical_json(body)).hexdigest()

    @classmethod
    def _seal(cls, material: Mapping[str, Any]) -> dict[str, Any]:
        sealed = dict(material)
        sealed["record_hash"] = cls.record_hash(sealed)
        return sealed

    def _path(self, directory: Path, operation_id: str) -> Path:
        return directory / f"{self._operation_id(operation_id)}.json"

    def _lock_path(self, operation_id: str) -> Path:
        return self.lock_dir / f"{self._operation_id(operation_id)}.lock"

    def _read_path(self, path: Path, operation_id: str) -> dict[str, Any]:
        if path.is_symlink() or not path.is_file():
            raise StateTransitionTransactionError(
                f"state-transition journal is not a regular file: {operation_id}"
            )
        try:
            data = strict_json_read(path)
        except DurableIOError as exc:
            raise StateTransitionTransactionError(
                f"unreadable state-transition journal {operation_id}: {exc}"
            ) from exc
        if not isinstance(data, dict):
            raise StateTransitionTransactionError("state-transition journal is not an object")
        if data.get("operation_id") != operation_id:
            raise StateTransitionTransactionError(
                "state-transition journal id does not match its storage name"
            )
        if data.get("journal_version") != self.JOURNAL_VERSION:
            raise StateTransitionTransactionError("unsupported state-transition journal version")
        if data.get("record_hash") != self.record_hash(data):
            raise StateTransitionTransactionError("state-transition journal hash mismatch")
        return data

    def reserve(self, record: Mapping[str, Any]) -> dict[str, Any]:
        requested = dict(record)
        operation_id = self._operation_id(str(requested.get("operation_id") or ""))
        path = self._path(self.active_dir, operation_id)
        try:
            with file_lock(self._lock_path(operation_id)):
                if path.exists() or path.is_symlink():
                    existing = self._read_path(path, operation_id)
                    for key, value in requested.items():
                        if key in {"record_hash", "created_at", "updated_at"}:
                            continue
                        if existing.get(key) != value:
                            raise StateTransitionTransactionError(
                                f"state-transition reservation conflicts: {operation_id}:{key}"
                            )
                    return existing
                material = dict(requested)
                material.update(
                    {
                        "operation_id": operation_id,
                        "journal_version": self.JOURNAL_VERSION,
                        "stage": material.get("stage") or "RESERVED",
                        "created_at": material.get("created_at") or utc_now(),
                        "updated_at": utc_now(),
                    }
                )
                sealed = self._seal(material)
                exclusive_json(path, sealed)
        except DurableIOError as exc:
            raise StateTransitionTransactionError(
                f"state-transition reservation failed: {exc}"
            ) from exc
        return sealed

    def update(self, operation_id: str, **changes: Any) -> dict[str, Any]:
        operation_id = self._operation_id(operation_id)
        immutable_fields = {
            "operation_id",
            "action_key",
            "project_id",
            "section_id",
            "object_id",
            "source_state",
            "target_state",
            "source_path",
            "destination_path",
            "expected_hash",
            "expected_size",
        }
        try:
            with file_lock(self._lock_path(operation_id)):
                path = self._path(self.active_dir, operation_id)
                data = self._read_path(path, operation_id)
                for key in immutable_fields:
                    if key in changes and changes[key] != data.get(key):
                        raise StateTransitionTransactionError(
                            f"state-transition identity field cannot change: {key}"
                        )
                data.update(changes)
                data["updated_at"] = utc_now()
                data = self._seal(data)
                atomic_json(path, data)
                return data
        except DurableIOError as exc:
            raise StateTransitionTransactionError(
                f"state-transition journal update failed: {exc}"
            ) from exc

    def get(self, operation_id: str) -> dict[str, Any]:
        operation_id = self._operation_id(operation_id)
        for directory in (self.active_dir, self.completed_dir, self.reconciliation_dir):
            path = self._path(directory, operation_id)
            if path.exists() or path.is_symlink():
                return self._read_path(path, operation_id)
        raise StateTransitionTransactionError(f"state-transition journal not found: {operation_id}")

    def pending(self) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for path in sorted(self.active_dir.glob("*.json")):
            records.append(self._read_path(path, self._operation_id(path.stem)))
        return records

    def _finish(self, operation_id: str, destination: Path, **changes: Any) -> dict[str, Any]:
        operation_id = self._operation_id(operation_id)
        try:
            with file_lock(self._lock_path(operation_id)):
                source = self._path(self.active_dir, operation_id)
                data = self._read_path(source, operation_id)
                data.update(changes)
                data["updated_at"] = utc_now()
                data = self._seal(data)
                atomic_json(source, data)
                target = self._path(destination, operation_id)
                if target.exists() or target.is_symlink():
                    raise StateTransitionTransactionError(
                        f"terminal state-transition journal already exists: {operation_id}"
                    )
                os.replace(source, target)
                fsync_directory(source.parent)
                fsync_directory(target.parent)
                return self._read_path(target, operation_id)
        except DurableIOError as exc:
            raise StateTransitionTransactionError(
                f"state-transition journal completion failed: {exc}"
            ) from exc

    def complete(self, operation_id: str, **changes: Any) -> dict[str, Any]:
        terminal_stage = str(changes.pop("stage", "COMPLETE"))
        return self._finish(operation_id, self.completed_dir, stage=terminal_stage, **changes)

    def require_reconciliation(self, operation_id: str, **changes: Any) -> dict[str, Any]:
        return self._finish(
            operation_id,
            self.reconciliation_dir,
            stage="RECONCILIATION_REQUIRED",
            **changes,
        )


class StateTransitionTransactionCoordinator:
    """Wallet authority for exact Retire and Restore transactions."""

    ACTIONS: dict[str, dict[str, str]] = {
        "retire_object": {
            "label": "retire protected object",
            "custody_event": "OBJECT_RETIRED",
            "custody_summary": "Protected object retired with content preserved",
        },
        "restore_retired_object": {
            "label": "restore retired object",
            "custody_event": "RETIRED_OBJECT_RESTORED",
            "custody_summary": "Retired object restored with content preserved",
        },
    }

    def __init__(
        self,
        vault: VaultEngine,
        evidence: CanonicalEvidenceAdapter,
        human_access: NotificationManager,
        vault_id: str = "vault",
    ) -> None:
        if not isinstance(vault_id, str) or not vault_id:
            raise StateTransitionTransactionError("state-transition vault_id is required")
        self.vault = vault
        self.evidence = evidence
        self.human_access = human_access
        self.vault_id = vault_id
        self.journal = StateTransitionJournal(vault.root)
        self.receipts = HumanIntentReceiptStore(vault.root)
        self.lock_dir = Path(vault.root) / "authority_locks" / "state_transitions"
        ensure_private_directory(
            self.lock_dir,
            error_type=StateTransitionTransactionError,
            label="state-transition authority locks",
        )
        self.evidence.attach_receipt_store(self.receipts)
        for action_key in self.ACTIONS:
            self.evidence.register_receipt_verifier(action_key, self.verify_receipt)

    @staticmethod
    def _ids() -> dict[str, str]:
        return {
            "operation_id": uuid4().hex,
            "receipt_id": uuid4().hex,
            "reserved_event_id": uuid4().hex,
            "authorization_event_id": uuid4().hex,
            "custody_event_id": uuid4().hex,
            "terminal_event_id": uuid4().hex,
            "anchor_event_id": uuid4().hex,
            "reconciliation_event_id": uuid4().hex,
        }

    def _spec(self, action_key: str) -> dict[str, str]:
        try:
            return self.ACTIONS[action_key]
        except KeyError as exc:
            raise StateTransitionTransactionError(
                f"unsupported state-transition action: {action_key!r}"
            ) from exc

    def _lock_path(self, project_id: str, section_id: str, object_id: str) -> Path:
        digest = hashlib.sha256(
            canonical_json(
                {"project_id": project_id, "section_id": section_id, "object_id": object_id}
            )
        ).hexdigest()
        return self.lock_dir / f"{digest}.lock"

    def _policy_decision(self, action_key: str, session_id: str) -> tuple[Any, dict[str, Any]]:
        identity = self.human_access.require_identity_session(session_id)
        decision = evaluate_protected_action(
            action_key,
            ActorKind.HUMAN,
            actor_identity=identity,
            human_ceremony_passed=True,
            vault_id=self.vault_id,
            gate=self.human_access,
        )
        if not decision.get("allowed"):
            raise StateTransitionTransactionError(
                decision.get("reason", "Human Intent policy denied state transition")
            )
        return identity, decision

    def _pre_state(
        self,
        action_key: str,
        project_id: str,
        section_id: str,
        object_id: str,
    ) -> dict[str, Any]:
        record = self.vault._find_file(project_id, section_id, object_id)
        source_state = str(record.get("state") or "")
        if action_key == "retire_object":
            if source_state == "prime":
                raise StateTransitionTransactionError(
                    "Current Prime cannot be retired; promote a replacement first"
                )
            if source_state not in {"raw", "candidate", "archived"}:
                raise StateTransitionTransactionError(
                    "Retire supports Raw Source, Candidate, or Archive objects"
                )
            target_state = "retired"
        else:
            if source_state != "retired":
                raise StateTransitionTransactionError("Restore requires a retired object")
            target_state = str(record.get("retired_from_state") or "")
            if target_state not in {"raw", "candidate", "archived"}:
                raise StateTransitionTransactionError(
                    "Retired object does not contain a safe restorable prior state"
                )
        source_path = Path(str(record.get("vault_path") or ""))
        source_root = self.vault._compartment_dir(
            project_id,
            section_id,
            self.vault._compartment_for_state(source_state),
        )
        try:
            source_path = ensure_within(
                source_root,
                source_path,
                label="state-transition source",
                error_type=StateTransitionTransactionError,
            )
        except DurableIOError as exc:
            raise StateTransitionTransactionError(str(exc)) from exc
        expected_hash = str(record.get("hash") or "")
        expected_size = int(record.get("size_bytes") or -1)
        if len(expected_hash) != 64 or expected_size < 0:
            raise StateTransitionTransactionError(
                "Protected object lacks a complete hash/size identity"
            )
        verified_regular_file(
            source_path,
            expected_hash=expected_hash,
            expected_size=expected_size,
            error_type=StateTransitionTransactionError,
            label="state-transition source",
        )
        destination_root = self.vault._compartment_dir(
            project_id,
            section_id,
            self.vault._compartment_for_state(target_state),
        )
        destination_path = destination_root / self.vault._custody_destination_name(
            object_id, source_path.name
        )
        if destination_path.exists() or destination_path.is_symlink():
            raise StateTransitionTransactionError(
                "Authorized state-transition destination is already occupied"
            )
        return {
            "source_state": source_state,
            "target_state": target_state,
            "source_path": str(source_path),
            "destination_path": str(destination_path),
            "expected_hash": expected_hash,
            "expected_size": expected_size,
            "object_name": str(record.get("name") or object_id),
            "pre_record": {
                "id": record.get("id"),
                "name": record.get("name"),
                "state": source_state,
                "vault_path": str(source_path),
                "hash": expected_hash,
                "size_bytes": expected_size,
                "retired_from_state": record.get("retired_from_state"),
            },
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

    def retire(
        self,
        *,
        project_id: str,
        section_id: str,
        object_id: str,
        ceremony_token: str,
        session_id: str,
        reason: str = "",
        fault_after: Optional[str] = None,
    ) -> dict[str, Any]:
        return self.transition(
            action_key="retire_object",
            project_id=project_id,
            section_id=section_id,
            object_id=object_id,
            ceremony_token=ceremony_token,
            session_id=session_id,
            reason=reason,
            fault_after=fault_after,
        )

    def restore(
        self,
        *,
        project_id: str,
        section_id: str,
        object_id: str,
        ceremony_token: str,
        session_id: str,
        reason: str = "",
        fault_after: Optional[str] = None,
    ) -> dict[str, Any]:
        return self.transition(
            action_key="restore_retired_object",
            project_id=project_id,
            section_id=section_id,
            object_id=object_id,
            ceremony_token=ceremony_token,
            session_id=session_id,
            reason=reason,
            fault_after=fault_after,
        )

    def transition(
        self,
        *,
        action_key: str,
        project_id: str,
        section_id: str,
        object_id: str,
        ceremony_token: str,
        session_id: str,
        reason: str = "",
        fault_after: Optional[str] = None,
    ) -> dict[str, Any]:
        self._spec(action_key)
        try:
            with self.vault.catalog_transaction():
                with file_lock(self._lock_path(project_id, section_id, object_id)):
                    return self._transition_locked(
                        action_key=action_key,
                        project_id=project_id,
                        section_id=section_id,
                        object_id=object_id,
                        ceremony_token=ceremony_token,
                        session_id=session_id,
                        reason=reason,
                        fault_after=fault_after,
                    )
        except (DurableIOError, VaultError) as exc:
            raise StateTransitionTransactionError(
                f"state-transition authority lock failed: {exc}"
            ) from exc

    def _transition_locked(
        self,
        *,
        action_key: str,
        project_id: str,
        section_id: str,
        object_id: str,
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
        pre = self._pre_state(action_key, project_id, section_id, object_id)
        identity, decision = self._policy_decision(action_key, session_id)
        ids = self._ids()
        journal = self.journal.reserve(
            {
                **ids,
                "action_key": action_key,
                "project_id": project_id,
                "section_id": section_id,
                "object_id": object_id,
                "session_id": session_id,
                "actor_id": identity.actor_id,
                "reason": str(reason or "")[:2000],
                "policy": decision["policy"],
                "policy_hash": sha256_json(decision["policy"]),
                "receipt_issued_at": utc_now(),
                **pre,
            }
        )
        actor = f"human:{identity.actor_id}"
        reserved = self._append_stage(
            journal,
            stage="RESERVED",
            event_type="HUMAN_INTENT_RESERVED",
            event_id_key="reserved_event_id",
            actor=actor,
            summary="Human Intent identifiers durably reserved",
            payload={
                "transaction_id": ids["operation_id"],
                "receipt_id": ids["receipt_id"],
                "project_id": project_id,
                "section_id": section_id,
                "object_id": object_id,
                "action_key": action_key,
                "source_state": pre["source_state"],
                "target_state": pre["target_state"],
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
                action_key=action_key,
                session_id=session_id,
                project_id=project_id,
                section_id=section_id,
                object_id=object_id,
            )
            if token_record.get("legacy_unscoped"):
                raise StateTransitionTransactionError(
                    "state transition requires an exact scoped ceremony token"
                )
        except (VaultError, StateTransitionTransactionError) as exc:
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
            summary=f"Wallet authorized one scoped {self._spec(action_key)['label']} transaction",
            payload={
                "transaction_id": ids["operation_id"],
                "receipt_id": ids["receipt_id"],
                "project_id": project_id,
                "section_id": section_id,
                "object_id": object_id,
                "action_key": action_key,
                "actor_id": identity.actor_id,
                "session_id": session_id,
                "ceremony_token_id": token_id,
                "ceremony_consumption_hash": consumption_hash,
                "policy": decision["policy"],
                "policy_hash": journal["policy_hash"],
                "source_state": pre["source_state"],
                "target_state": pre["target_state"],
            },
        )
        journal = self.journal.update(
            ids["operation_id"],
            authorization_event_hash=authorized["event_hash"],
            stage="AUTHORIZED",
        )
        if fault_after == "authorized":
            raise SimulatedStateTransitionCrash("authorized")

        def fault_hook(stage: str) -> None:
            if fault_after == stage:
                raise SimulatedStateTransitionCrash(stage)

        try:
            result = self.vault._transition_object_state_unchecked(
                project_id,
                section_id,
                object_id,
                action_key=action_key,
                source_state=pre["source_state"],
                target_state=pre["target_state"],
                source_path=pre["source_path"],
                destination_path=pre["destination_path"],
                expected_hash=pre["expected_hash"],
                expected_size=pre["expected_size"],
                transaction_id=ids["operation_id"],
                reason=reason,
                fault_hook=fault_hook,
            )
            return self._finalize_completed(
                journal,
                result,
                actor=actor,
                recovered=False,
                fault_after=fault_after,
            )
        except SimulatedStateTransitionCrash:
            raise
        except Exception as exc:
            outcome, observed = self._observed_outcome(journal)
            if outcome == "ambiguous":
                self._freeze_ambiguous(
                    journal,
                    observed,
                    reason=f"{type(exc).__name__}: {exc}",
                )
            raise

    def _verified_path(self, path_text: Any, expected_hash: str, expected_size: int) -> bool:
        if not path_text:
            return False
        try:
            verified_regular_file(
                Path(str(path_text)),
                expected_hash=expected_hash,
                expected_size=expected_size,
                error_type=StateTransitionTransactionError,
                label="observed state-transition file",
            )
            return True
        except Exception:
            return False

    def _observed_outcome(self, journal: Mapping[str, Any]) -> tuple[str, dict[str, Any]]:
        record = self.vault._find_file(
            str(journal["project_id"]),
            str(journal["section_id"]),
            str(journal["object_id"]),
        )
        expected_hash = str(journal["expected_hash"])
        expected_size = int(journal["expected_size"])
        source_path = Path(str(journal["source_path"]))
        destination_path = Path(str(journal["destination_path"]))
        evidence_path = (
            self.vault._transition_evidence_root(
                str(journal["project_id"]), str(journal["section_id"])
            )
            / str(journal["operation_id"])
            / source_path.name
        )
        observed = {
            "record_state": record.get("state"),
            "record_path": record.get("vault_path"),
            "last_state_transition_id": record.get("last_state_transition_id"),
            "source_present": source_path.exists() or source_path.is_symlink(),
            "destination_present": destination_path.exists() or destination_path.is_symlink(),
            "evidence_present": evidence_path.exists() or evidence_path.is_symlink(),
        }
        if (
            record.get("state") == journal.get("target_state")
            and record.get("vault_path") == str(destination_path)
            and record.get("last_state_transition_id") == journal.get("operation_id")
            and self._verified_path(destination_path, expected_hash, expected_size)
        ):
            return "completed", observed
        if (
            record.get("state") == journal.get("source_state")
            and record.get("vault_path") == str(source_path)
            and record.get("hash") == expected_hash
        ):
            source_ok = self._verified_path(source_path, expected_hash, expected_size)
            destination_ok = (
                not observed["destination_present"]
                or self._verified_path(destination_path, expected_hash, expected_size)
            )
            evidence_ok = (
                not observed["evidence_present"]
                or self._verified_path(evidence_path, expected_hash, expected_size)
            )
            if source_ok and destination_ok and evidence_ok:
                return "recoverable", observed
        return "ambiguous", observed

    def _receipt_material(
        self,
        journal: Mapping[str, Any],
        *,
        actor: str,
        custody_event: Mapping[str, Any],
        terminal_event: Mapping[str, Any],
        recovered: bool,
    ) -> dict[str, Any]:
        return {
            "receipt_id": journal["receipt_id"],
            "receipt_type": "human_intent_receipt_v2",
            "issued_at": journal["receipt_issued_at"],
            "operation_id": journal["operation_id"],
            "action_key": journal["action_key"],
            "action_label": self._spec(str(journal["action_key"]))["label"],
            "project_id": journal["project_id"],
            "section_id": journal["section_id"],
            "object_id": journal["object_id"],
            "object_name": journal.get("object_name"),
            "source_state": journal["source_state"],
            "target_state": journal["target_state"],
            "protected_content_preserved": True,
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
            "recovered_after_restart": bool(recovered),
            "intent_statement": (
                "A Wallet-authorized local human identity session completed this exact "
                "Retire or Restore custody-state transition."
            ),
            "evidence_limits": (
                "Local continuity evidence; not real-world identity authentication, "
                "nonrepudiation, or an independent external witness."
            ),
        }

    def _finalize_completed(
        self,
        journal: Mapping[str, Any],
        result: Mapping[str, Any],
        *,
        actor: str,
        recovered: bool,
        fault_after: Optional[str] = None,
    ) -> dict[str, Any]:
        operation_id = str(journal["operation_id"])
        if "completion_recovered_after_restart" not in journal:
            journal = self.journal.update(
                operation_id,
                completion_recovered_after_restart=bool(recovered),
            )
        completion_recovered = bool(journal["completion_recovered_after_restart"])
        spec = self._spec(str(journal["action_key"]))
        custody = self._append_stage(
            journal,
            stage="CUSTODY",
            event_type=spec["custody_event"],
            event_id_key="custody_event_id",
            actor=actor,
            summary=spec["custody_summary"],
            payload={
                "transaction_id": operation_id,
                "authorization_event_hash": journal["authorization_event_hash"],
                "project_id": journal["project_id"],
                "section_id": journal["section_id"],
                "object_id": journal["object_id"],
                "action_key": journal["action_key"],
                "source_state": journal["source_state"],
                "target_state": journal["target_state"],
                "protected_content_preserved": True,
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
            summary="Protected state-transition transaction completed",
            payload={
                "transaction_id": operation_id,
                "authorization_event_hash": journal["authorization_event_hash"],
                "custody_event_hash": custody["event_hash"],
                "result_status": "completed",
                "project_id": journal["project_id"],
                "section_id": journal["section_id"],
                "object_id": journal["object_id"],
                "action_key": journal["action_key"],
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
                "action_key": journal["action_key"],
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
            raise SimulatedStateTransitionCrash("anchor_recorded")
        stored = self.receipts.create(receipt)
        journal = self.journal.update(
            operation_id,
            receipt_written=True,
            stage="RECEIPT_WRITTEN",
        )
        if fault_after == "receipt_written":
            raise SimulatedStateTransitionCrash("receipt_written")
        verification = self.verify_receipt(stored["receipt_id"])
        if not verification.get("ok"):
            raise StateTransitionTransactionError(
                f"new state-transition receipt failed verification: {verification.get('reason')}"
            )
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
            summary="Protected state-transition transaction failed before mutation",
            payload={
                "transaction_id": journal["operation_id"],
                "authorization_event_hash": journal.get("authorization_event_hash"),
                "result_status": "failed",
                "reason_class": reason[:200],
                "project_id": journal["project_id"],
                "section_id": journal["section_id"],
                "object_id": journal["object_id"],
                "action_key": journal["action_key"],
            },
        )
        self.journal.complete(
            str(journal["operation_id"]),
            stage="FAILED",
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
        operation_id = str(journal["operation_id"])
        self.vault._mark_state_transition_reconciliation_unchecked(
            str(journal["project_id"]),
            str(journal["section_id"]),
            str(journal["object_id"]),
            transaction_id=operation_id,
            reason=reason,
        )
        actor = f"human:{journal.get('actor_id') or 'unknown'}"
        event = self._append_stage(
            journal,
            stage="RECONCILIATION_REQUIRED",
            event_type="STATE_TRANSITION_RECONCILIATION_REQUIRED",
            event_id_key="reconciliation_event_id",
            actor=actor,
            summary="State transition requires human-guided reconciliation",
            payload={
                "transaction_id": operation_id,
                "project_id": journal["project_id"],
                "section_id": journal["section_id"],
                "object_id": journal["object_id"],
                "action_key": journal["action_key"],
                "reason_class": reason[:200],
                "observed": dict(observed),
            },
        )
        self.journal.require_reconciliation(
            operation_id,
            reconciliation_event_hash=event["event_hash"],
            reason=reason[:500],
            observed=dict(observed),
        )

    def reconcile_pending(self) -> dict[str, Any]:
        report: dict[str, Any] = {
            "checked": 0,
            "reconciled": 0,
            "failed": 0,
            "ambiguous": 0,
            "receipts": [],
            "errors": [],
        }
        for pending in self.journal.pending():
            report["checked"] += 1
            operation_id = str(pending["operation_id"])
            actor = f"human:{pending.get('actor_id') or 'unknown'}"
            try:
                with self.vault.catalog_transaction():
                    with file_lock(
                        self._lock_path(
                            str(pending["project_id"]),
                            str(pending["section_id"]),
                            str(pending["object_id"]),
                        )
                    ):
                        journal = self.journal.get(operation_id)
                        if not journal.get("ceremony_token_id"):
                            self._finalize_failed(
                                journal,
                                actor=actor,
                                reason="restart before authorization",
                            )
                            report["reconciled"] += 1
                            continue
                        if not journal.get("authorization_event_hash"):
                            authorized = self._append_stage(
                                journal,
                                stage="AUTHORIZED",
                                event_type="HUMAN_INTENT_AUTHORIZED",
                                event_id_key="authorization_event_id",
                                actor=actor,
                                summary=f"Wallet authorized one scoped {self._spec(str(journal['action_key']))['label']} transaction",
                                payload={
                                    "transaction_id": operation_id,
                                    "receipt_id": journal["receipt_id"],
                                    "project_id": journal["project_id"],
                                    "section_id": journal["section_id"],
                                    "object_id": journal["object_id"],
                                    "action_key": journal["action_key"],
                                    "actor_id": journal["actor_id"],
                                    "session_id": journal["session_id"],
                                    "ceremony_token_id": journal["ceremony_token_id"],
                                    "ceremony_consumption_hash": journal["ceremony_consumption_hash"],
                                    "policy": journal["policy"],
                                    "policy_hash": journal["policy_hash"],
                                    "source_state": journal["source_state"],
                                    "target_state": journal["target_state"],
                                },
                            )
                            journal = self.journal.update(
                                operation_id,
                                authorization_event_hash=authorized["event_hash"],
                                stage="AUTHORIZED",
                            )
                        result = self.vault._transition_object_state_unchecked(
                            str(journal["project_id"]),
                            str(journal["section_id"]),
                            str(journal["object_id"]),
                            action_key=str(journal["action_key"]),
                            source_state=str(journal["source_state"]),
                            target_state=str(journal["target_state"]),
                            source_path=str(journal["source_path"]),
                            destination_path=str(journal["destination_path"]),
                            expected_hash=str(journal["expected_hash"]),
                            expected_size=int(journal["expected_size"]),
                            transaction_id=operation_id,
                            reason=str(journal.get("reason") or ""),
                        )
                        completed = self._finalize_completed(
                            journal,
                            result,
                            actor=actor,
                            recovered=True,
                        )
                        report["reconciled"] += 1
                        report["receipts"].append(completed["receipt"]["receipt_id"])
            except Exception as exc:
                try:
                    journal = self.journal.get(operation_id)
                    outcome, observed = self._observed_outcome(journal)
                    if outcome == "completed":
                        completed = self._finalize_completed(
                            journal,
                            self.vault._find_file(
                                str(journal["project_id"]),
                                str(journal["section_id"]),
                                str(journal["object_id"]),
                            ),
                            actor=actor,
                            recovered=True,
                        )
                        report["reconciled"] += 1
                        report["receipts"].append(completed["receipt"]["receipt_id"])
                    elif outcome == "ambiguous":
                        self._freeze_ambiguous(
                            journal,
                            observed,
                            reason=f"{type(exc).__name__}: {exc}",
                        )
                        report["ambiguous"] += 1
                    else:
                        report["failed"] += 1
                        report["errors"].append(
                            {"operation_id": operation_id, "error": f"{type(exc).__name__}: {exc}"[:500]}
                        )
                except Exception as secondary:
                    report["failed"] += 1
                    report["errors"].append(
                        {
                            "operation_id": operation_id,
                            "error": f"{type(exc).__name__}: {exc}"[:300],
                            "recovery_error": f"{type(secondary).__name__}: {secondary}"[:300],
                        }
                    )
        return report

    def verify_receipt(self, receipt_id: str) -> dict[str, Any]:
        try:
            receipt = self.receipts.get(receipt_id)
        except Exception as exc:
            return {"ok": False, "status": "invalid", "reason": f"receipt unavailable: {exc}"}
        action_key = str(receipt.get("action_key") or "")
        try:
            spec = self._spec(action_key)
        except StateTransitionTransactionError as exc:
            return {"ok": False, "status": "invalid", "reason": str(exc)}
        if receipt.get("receipt_hash") != HumanIntentReceiptStore.core_hash(receipt):
            return {"ok": False, "status": "invalid", "reason": "receipt hash mismatch"}
        if receipt.get("protected_content_preserved") is not True:
            return {"ok": False, "status": "invalid", "reason": "preservation assertion missing"}
        chain = self.evidence.verify_chain()
        if not chain.get("ok"):
            return {
                "ok": False,
                "status": "invalid",
                "reason": "canonical BlackBox chain invalid",
                "chain": chain,
            }
        expected = [
            ("reserved_event_id", "reserved_event_hash", "HUMAN_INTENT_RESERVED"),
            ("authorization_event_id", "authorization_event_hash", "HUMAN_INTENT_AUTHORIZED"),
            ("custody_event_id", "custody_event_hash", spec["custody_event"]),
            ("terminal_event_id", "terminal_event_hash", "HUMAN_INTENT_COMPLETED"),
            ("anchor_event_id", "anchor_event_hash", "HUMAN_INTENT_RECEIPT_ANCHORED"),
        ]
        records: list[dict[str, Any]] = []
        for id_key, hash_key, event_type in expected:
            record = self.evidence.record_by_id(str(receipt.get(id_key) or ""))
            if not record:
                return {"ok": False, "status": "invalid", "reason": f"missing {event_type} record"}
            if record.get("hash") != receipt.get(hash_key):
                return {"ok": False, "status": "invalid", "reason": f"{event_type} hash mismatch"}
            if record.get("event_type") != event_type:
                return {"ok": False, "status": "invalid", "reason": f"wrong event type for {id_key}"}
            payload = record.get("payload") or {}
            if payload.get("transaction_id") != receipt.get("operation_id"):
                return {"ok": False, "status": "invalid", "reason": f"{event_type} transaction mismatch"}
            records.append(record)
        if [int(record["seq"]) for record in records] != sorted(int(record["seq"]) for record in records):
            return {"ok": False, "status": "invalid", "reason": "receipt graph out of order"}
        reserved, authorized, custody, terminal, anchor = [record.get("payload") or {} for record in records]
        for name, payload in (
            ("reserved", reserved),
            ("authorization", authorized),
            ("custody", custody),
            ("terminal", terminal),
        ):
            for key in ("project_id", "section_id", "object_id"):
                if payload.get(key) != receipt.get(key):
                    return {"ok": False, "status": "invalid", "reason": f"{name} {key} mismatch"}
        if authorized.get("action_key") != action_key or custody.get("action_key") != action_key or terminal.get("action_key") != action_key:
            return {"ok": False, "status": "invalid", "reason": "action key mismatch"}
        if custody.get("source_state") != receipt.get("source_state") or custody.get("target_state") != receipt.get("target_state"):
            return {"ok": False, "status": "invalid", "reason": "custody state binding mismatch"}
        if custody.get("protected_content_preserved") is not True:
            return {"ok": False, "status": "invalid", "reason": "custody preservation fact missing"}
        if authorized.get("actor_id") != receipt.get("actor_id") or authorized.get("session_id") != receipt.get("session_id"):
            return {"ok": False, "status": "invalid", "reason": "authorization identity mismatch"}
        if authorized.get("ceremony_token_id") != receipt.get("ceremony_token_id") or authorized.get("ceremony_consumption_hash") != receipt.get("ceremony_consumption_hash"):
            return {"ok": False, "status": "invalid", "reason": "authorization ceremony binding mismatch"}
        policy = authorized.get("policy")
        if not isinstance(policy, Mapping) or sha256_json(policy) != receipt.get("policy_hash"):
            return {"ok": False, "status": "invalid", "reason": "policy snapshot hash mismatch"}
        if custody.get("authorization_event_hash") != receipt.get("authorization_event_hash"):
            return {"ok": False, "status": "invalid", "reason": "custody authorization link mismatch"}
        if terminal.get("authorization_event_hash") != receipt.get("authorization_event_hash") or terminal.get("custody_event_hash") != receipt.get("custody_event_hash"):
            return {"ok": False, "status": "invalid", "reason": "terminal evidence link mismatch"}
        if anchor.get("receipt_id") != receipt.get("receipt_id") or anchor.get("receipt_hash") != receipt.get("receipt_hash"):
            return {"ok": False, "status": "invalid", "reason": "anchor receipt binding mismatch"}
        if anchor.get("authorization_event_hash") != receipt.get("authorization_event_hash") or anchor.get("terminal_event_hash") != receipt.get("terminal_event_hash"):
            return {"ok": False, "status": "invalid", "reason": "anchor evidence link mismatch"}
        operation_records = self.evidence.records_for_operation(str(receipt.get("operation_id") or ""))
        expected_ids = {str(receipt.get(id_key) or "") for id_key, _, _ in expected}
        if "" in expected_ids or len(expected_ids) != len(expected):
            return {"ok": False, "status": "invalid", "reason": "receipt graph has missing or duplicate ids"}
        graph_types = {event_type for _, _, event_type in expected}
        contradictory = {"HUMAN_INTENT_FAILED", "STATE_TRANSITION_RECONCILIATION_REQUIRED"}
        graph_records = [
            record for record in operation_records if record.get("event_type") in graph_types | contradictory
        ]
        if any(record.get("event_type") in contradictory for record in graph_records):
            return {"ok": False, "status": "invalid", "reason": "receipt graph contains a contradictory stage"}
        for event_type in graph_types:
            if len([record for record in graph_records if record.get("event_type") == event_type]) != 1:
                return {"ok": False, "status": "invalid", "reason": f"duplicate or missing {event_type} stage"}
        if {str(record.get("record_id")) for record in graph_records} != expected_ids:
            return {"ok": False, "status": "invalid", "reason": "receipt graph contains an uncommitted stage"}
        try:
            token_id = str(receipt.get("ceremony_token_id") or "")
            token_record = self.vault.ceremony_ledger.get_record(token_id, include_hash=True)
            token_hash = self.vault.ceremony_ledger.record_hash(token_id)
        except Exception as exc:
            return {"ok": False, "status": "invalid", "reason": f"ceremony record unavailable: {exc}"}
        if token_hash != receipt.get("ceremony_consumption_hash"):
            return {"ok": False, "status": "invalid", "reason": "ceremony consumption hash mismatch"}
        for key in ("action_key", "session_id", "project_id", "section_id", "object_id"):
            if token_record.get(key) != receipt.get(key):
                return {"ok": False, "status": "invalid", "reason": f"ceremony {key} mismatch"}
        if not token_record.get("consumed_at") or token_record.get("consumed_by_action") != action_key:
            return {"ok": False, "status": "invalid", "reason": "ceremony token was not consumed for this action"}
        return {
            "ok": True,
            "status": "complete",
            "receipt_id": receipt_id,
            "operation_id": receipt.get("operation_id"),
            "chain": chain,
            "evidence_limit": receipt.get("evidence_limits"),
        }
