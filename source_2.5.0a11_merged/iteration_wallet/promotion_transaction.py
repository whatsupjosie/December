"""Recoverable Human Intent protocol for Candidate -> Prime promotion.

The Wallet owns authorization, custody mutation, recovery decisions, and the
portable receipt. The standalone BlackBox owns the canonical append-only
record. Neither side impersonates the other.
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
    CanonicalEvidenceError,
    HumanIntentReceiptStore,
)
from iteration_wallet.durable_io import (
    DurableIOError,
    atomic_json as _atomic_json,
    ensure_within,
    exclusive_json as _exclusive_json,
    file_lock,
    fsync_directory as _fsync_directory,
    strict_json_read,
    validate_storage_id,
)
from iteration_wallet.gatekeeper import evaluate_protected_action
from iteration_wallet.notification_manager import ActorKind, NotificationManager
from iteration_wallet.vault_v21 import VaultEngine, VaultError


class PromotionTransactionError(Exception):
    """Raised when a promotion protocol cannot safely complete."""


class SimulatedPromotionCrash(BaseException):
    """Fault-injection sentinel that intentionally bypasses normal recovery code."""

    def __init__(self, stage: str) -> None:
        super().__init__(f"simulated process crash after {stage}")
        self.stage = stage


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def sha256_json(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json(payload)).hexdigest()


class PromotionJournal:
    """Sealed Wallet-owned recovery state; never a second evidence authority."""

    JOURNAL_VERSION = 2

    def __init__(self, vault_root: Path | str) -> None:
        self.vault_root = Path(vault_root)
        self.root = self.vault_root / "recovery_journal" / "promotions"
        self.active_dir = self.root / "active"
        self.completed_dir = self.root / "completed"
        self.reconciliation_dir = self.root / "reconciliation_required"
        self.lock_dir = self.root / ".locks"
        try:
            ensure_within(
                self.vault_root, self.root, label="promotion journal",
                error_type=PromotionTransactionError,
            )
        except DurableIOError as exc:
            raise PromotionTransactionError(str(exc)) from exc
        for directory in (
            self.root,
            self.active_dir,
            self.completed_dir,
            self.reconciliation_dir,
            self.lock_dir,
        ):
            if directory.is_symlink():
                raise PromotionTransactionError(
                    f"journal directory cannot be a symlink: {directory.name}"
                )
            directory.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _operation_id(operation_id: str) -> str:
        try:
            return validate_storage_id(
                "operation_id", operation_id, error_type=PromotionTransactionError
            )
        except DurableIOError as exc:
            raise PromotionTransactionError(str(exc)) from exc

    @staticmethod
    def record_hash(material: Mapping[str, Any]) -> str:
        body = {key: value for key, value in dict(material).items() if key != "record_hash"}
        return hashlib.sha256(canonical_json(body)).hexdigest()

    @classmethod
    def _seal(cls, material: Mapping[str, Any]) -> dict[str, Any]:
        sealed = dict(material)
        sealed["record_hash"] = cls.record_hash(sealed)
        return sealed

    def _active_path(self, operation_id: str) -> Path:
        operation_id = self._operation_id(str(operation_id))
        return self.active_dir / f"{operation_id}.json"

    def _lock_path(self, operation_id: str) -> Path:
        operation_id = self._operation_id(str(operation_id))
        return self.lock_dir / f"{operation_id}.lock"

    def _read_path(self, path: Path, operation_id: str) -> dict[str, Any]:
        if path.is_symlink() or not path.is_file():
            raise PromotionTransactionError(f"journal is not a regular file: {operation_id}")
        try:
            data = strict_json_read(path)
        except DurableIOError as exc:
            raise PromotionTransactionError(
                f"unreadable journal {operation_id}: {exc}"
            ) from exc
        if not isinstance(data, dict):
            raise PromotionTransactionError(f"journal is not an object: {operation_id}")
        if data.get("operation_id") != operation_id:
            raise PromotionTransactionError(
                f"journal operation id does not match storage name: {operation_id}"
            )
        if data.get("journal_version") != self.JOURNAL_VERSION:
            raise PromotionTransactionError(
                f"unsupported or unsealed promotion journal version: {operation_id}"
            )
        if data.get("record_hash") != self.record_hash(data):
            raise PromotionTransactionError(f"journal record hash mismatch: {operation_id}")
        return data

    def reserve(self, record: Mapping[str, Any]) -> dict[str, Any]:
        material = dict(record)
        material["journal_version"] = self.JOURNAL_VERSION
        material.setdefault("stage", "RESERVED")
        material.setdefault("created_at", utc_now())
        material["updated_at"] = utc_now()
        operation_id = str(material.get("operation_id") or "")
        if not operation_id:
            raise PromotionTransactionError("journal reservation requires operation_id")
        operation_id = self._operation_id(operation_id)
        material["operation_id"] = operation_id
        material = self._seal(material)
        try:
            with file_lock(self._lock_path(operation_id)):
                path = self._active_path(operation_id)
                if path.exists():
                    existing = self._read_path(path, operation_id)
                    if existing != material:
                        raise PromotionTransactionError(
                            f"journal reservation conflicts with existing operation: {operation_id}"
                        )
                    return existing
                _exclusive_json(path, material)
        except DurableIOError as exc:
            raise PromotionTransactionError(f"journal reservation failed: {exc}") from exc
        return material

    def get(self, operation_id: str) -> dict[str, Any]:
        operation_id = self._operation_id(str(operation_id))
        for directory in (self.active_dir, self.completed_dir, self.reconciliation_dir):
            path = directory / f"{operation_id}.json"
            if path.exists() or path.is_symlink():
                return self._read_path(path, operation_id)
        raise PromotionTransactionError(f"journal not found: {operation_id}")

    def update(self, operation_id: str, **changes: Any) -> dict[str, Any]:
        operation_id = self._operation_id(str(operation_id))
        try:
            with file_lock(self._lock_path(operation_id)):
                path = self._active_path(operation_id)
                data = self._read_path(path, operation_id)
                immutable = {
                    key: data.get(key)
                    for key in (
                        "operation_id",
                        "action_key",
                        "project_id",
                        "section_id",
                        "candidate_id",
                    )
                    if key in data
                }
                for key, expected in immutable.items():
                    if key in changes and changes[key] != expected:
                        raise PromotionTransactionError(
                            f"journal identity field cannot change: {key}"
                        )
                data.update(changes)
                data["updated_at"] = utc_now()
                data = self._seal(data)
                _atomic_json(path, data)
                return data
        except DurableIOError as exc:
            raise PromotionTransactionError(f"journal update failed: {exc}") from exc

    def pending(self) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for path in sorted(self.active_dir.iterdir()):
            if path.name.startswith("."):
                continue
            if path.suffix != ".json":
                continue
            expected_id = self._operation_id(path.stem)
            records.append(self._read_path(path, expected_id))
        return records

    def _finish(self, operation_id: str, destination: Path, **changes: Any) -> dict[str, Any]:
        operation_id = self._operation_id(str(operation_id))
        try:
            with file_lock(self._lock_path(operation_id)):
                source = self._active_path(operation_id)
                data = self._read_path(source, operation_id)
                data.update(changes)
                data["updated_at"] = utc_now()
                data = self._seal(data)
                _atomic_json(source, data)
                target = destination / source.name
                if target.exists() or target.is_symlink():
                    raise PromotionTransactionError(
                        f"journal terminal record already exists: {target.name}"
                    )
                os.replace(source, target)
                _fsync_directory(source.parent)
                _fsync_directory(target.parent)
                return self._read_path(target, operation_id)
        except DurableIOError as exc:
            raise PromotionTransactionError(f"journal completion failed: {exc}") from exc

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


class PromotionTransactionCoordinator:
    """Wallet authority for the debut's bounded Prime-promotion transaction."""

    ACTION_KEY = "promote_candidate_to_prime"
    ACTION_LABEL = "promote Candidate to Prime"

    def __init__(
        self,
        vault: VaultEngine,
        evidence: CanonicalEvidenceAdapter,
        human_access: NotificationManager,
    ) -> None:
        self.vault = vault
        self.evidence = evidence
        self.human_access = human_access
        self.journal = PromotionJournal(vault.root)
        self.receipts = HumanIntentReceiptStore(vault.root)
        self.lock_dir = Path(vault.root) / "authority_locks" / "promotion"
        try:
            ensure_within(
                Path(vault.root), self.lock_dir, label="promotion lock directory",
                error_type=PromotionTransactionError,
            )
        except DurableIOError as exc:
            raise PromotionTransactionError(str(exc)) from exc
        if self.lock_dir.is_symlink():
            raise PromotionTransactionError("promotion lock directory cannot be a symlink")
        self.lock_dir.mkdir(parents=True, exist_ok=True)
        self.evidence.attach_receipt_store(self.receipts)
        self.evidence.register_receipt_verifier(self.ACTION_KEY, self.verify_receipt)

    @staticmethod
    def _record_snapshot(record: Optional[Mapping[str, Any]]) -> Optional[dict[str, Any]]:
        if not record:
            return None
        return {
            "id": record.get("id"),
            "name": record.get("name"),
            "state": record.get("state"),
            "vault_path": record.get("vault_path"),
            "hash": record.get("hash"),
            "promoted": bool(record.get("promoted")),
        }

    def _pre_state(self, project_id: str, section_id: str, candidate_id: str) -> dict[str, Any]:
        section = self.vault.get_section(project_id, section_id)
        candidate = self.vault._find_file(project_id, section_id, candidate_id)
        old_prime_id = section.get("prime")
        old_prime = (
            self.vault._find_file(project_id, section_id, old_prime_id)
            if old_prime_id
            else None
        )
        return {
            "section_prime": old_prime_id,
            "section_archive": list(section.get("archive") or []),
            "candidate": self._record_snapshot(candidate),
            "old_prime": self._record_snapshot(old_prime),
        }

    @staticmethod
    def _verified_custody_file(
        path_text: Any,
        *,
        expected_root: Path,
        expected_hash: Any = None,
    ) -> bool:
        if not path_text:
            return False
        path = Path(str(path_text))
        try:
            resolved = ensure_within(
                expected_root, path, label="custody record path",
                error_type=PromotionTransactionError,
            )
        except (DurableIOError, PromotionTransactionError, OSError):
            return False
        # Custody records point to owned files, not indirections. Even an
        # in-root symlink would make the catalog describe a different object.
        if path.is_symlink() or not resolved.is_file():
            return False
        if expected_hash:
            try:
                digest = hashlib.sha256(resolved.read_bytes()).hexdigest()
            except OSError:
                return False
            return digest == expected_hash
        return True

    def _path_matches(
        self,
        snapshot: Optional[Mapping[str, Any]],
        *,
        expected_root: Path,
    ) -> bool:
        if not snapshot:
            return True
        return self._verified_custody_file(
            snapshot.get("vault_path"),
            expected_root=expected_root,
            expected_hash=snapshot.get("hash"),
        )

    def _observed_outcome(self, journal: Mapping[str, Any]) -> tuple[str, dict[str, Any]]:
        project_id = str(journal["project_id"])
        section_id = str(journal["section_id"])
        candidate_id = str(journal["candidate_id"])
        pre = dict(journal["pre_state"])
        section = self.vault.get_section(project_id, section_id)
        candidate = self.vault._find_file(project_id, section_id, candidate_id)
        old_snapshot = pre.get("old_prime")
        old_prime = None
        if old_snapshot and old_snapshot.get("id"):
            old_prime = self.vault._find_file(project_id, section_id, str(old_snapshot["id"]))

        cradle_root = self.vault._compartment_dir(project_id, section_id, "cradle")
        archive_root = self.vault._compartment_dir(project_id, section_id, "archive")
        candidate_complete = (
            candidate.get("state") == "prime"
            and section.get("prime") == candidate_id
            and self._verified_custody_file(
                candidate.get("vault_path"),
                expected_root=cradle_root,
                expected_hash=candidate.get("hash"),
            )
        )
        old_complete = True
        if old_prime is not None:
            old_complete = (
                old_prime.get("state") == "archived"
                and old_prime.get("id") in (section.get("archive") or [])
                and self._verified_custody_file(
                    old_prime.get("vault_path"),
                    expected_root=archive_root,
                    expected_hash=old_prime.get("hash"),
                )
            )

        if candidate_complete and old_complete:
            return "complete", {
                "candidate": self._record_snapshot(candidate),
                "old_prime": self._record_snapshot(old_prime),
                "section_prime": section.get("prime"),
                "section_archive": list(section.get("archive") or []),
            }

        candidate_pre = pre.get("candidate") or {}
        old_pre = pre.get("old_prime")
        unchanged = (
            candidate.get("state") == candidate_pre.get("state")
            and candidate.get("vault_path") == candidate_pre.get("vault_path")
            and section.get("prime") == pre.get("section_prime")
            and self._path_matches(
                candidate_pre,
                expected_root=self.vault._compartment_dir(
                    project_id,
                    section_id,
                    "raw_sources" if candidate_pre.get("state") == "raw" else "candidates",
                ),
            )
        )
        if old_pre:
            unchanged = unchanged and old_prime is not None and (
                old_prime.get("state") == old_pre.get("state")
                and old_prime.get("vault_path") == old_pre.get("vault_path")
                and self._path_matches(
                    old_pre,
                    expected_root=self.vault._compartment_dir(project_id, section_id, "cradle"),
                )
            )
        if unchanged:
            planned_candidate = cradle_root / self.vault._custody_destination_name(
                candidate_id, Path(str(candidate_pre.get("vault_path") or "artifact.bin")).name
            )
            if planned_candidate.exists() or planned_candidate.is_symlink():
                unchanged = False
        if unchanged and old_pre:
            planned_archive = archive_root / self.vault._custody_destination_name(
                str(old_pre.get("id") or "old-prime"),
                Path(str(old_pre.get("vault_path") or "artifact.bin")).name,
            )
            if planned_archive.exists() or planned_archive.is_symlink():
                unchanged = False
        if unchanged:
            return "unchanged", {
                "candidate": self._record_snapshot(candidate),
                "old_prime": self._record_snapshot(old_prime),
                "section_prime": section.get("prime"),
                "section_archive": list(section.get("archive") or []),
            }
        return "ambiguous", {
            "candidate": self._record_snapshot(candidate),
            "old_prime": self._record_snapshot(old_prime),
            "section_prime": section.get("prime"),
            "section_archive": list(section.get("archive") or []),
        }

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
        }

    def _append_stage(
        self,
        journal: Mapping[str, Any],
        *,
        stage: str,
        event_type: str,
        event_id_key: str,
        actor: str,
        payload: Mapping[str, Any],
        summary: str,
        coverage: Any = None,
    ) -> dict[str, Any]:
        kwargs: dict[str, Any] = {}
        if coverage is not None:
            kwargs["coverage"] = coverage
        return self.evidence.append_fact(
            event_type=event_type,
            summary=summary,
            event_id=str(journal[event_id_key]),
            transaction_id=str(journal["operation_id"]),
            stage_key=f"{journal['operation_id']}:{stage}",
            actor=actor,
            subject_id=f"candidate:{journal['candidate_id']}",
            payload=payload,
            event_code=stage,
            **kwargs,
        )

    def _policy_decision(self, session_id: str) -> tuple[Any, dict[str, Any]]:
        identity = self.human_access.require_identity_session(session_id)
        decision = evaluate_protected_action(
            self.ACTION_KEY,
            ActorKind.HUMAN,
            actor_identity=identity,
            human_ceremony_passed=True,
            gate=self.human_access,
        )
        if not decision.get("allowed"):
            raise PromotionTransactionError(decision.get("reason", "Human Intent policy denied promotion"))
        return identity, decision

    def _promotion_lock_path(self, project_id: str, section_id: str) -> Path:
        scope_hash = hashlib.sha256(
            canonical_json({"project_id": project_id, "section_id": section_id})
        ).hexdigest()
        return self.lock_dir / f"{scope_hash}.lock"

    def promote_to_prime(
        self,
        *,
        project_id: str,
        section_id: str,
        candidate_id: str,
        ceremony_token: str,
        session_id: str,
        reason: str = "",
        fault_after: Optional[str] = None,
    ) -> dict[str, Any]:
        """Serialize one section's trust-expanding promotion across processes."""
        try:
            with self.vault.catalog_transaction():
                with file_lock(self._promotion_lock_path(project_id, section_id)):
                    return self._promote_to_prime_locked(
                        project_id=project_id,
                        section_id=section_id,
                        candidate_id=candidate_id,
                        ceremony_token=ceremony_token,
                        session_id=session_id,
                        reason=reason,
                        fault_after=fault_after,
                    )
        except (DurableIOError, VaultError) as exc:
            raise PromotionTransactionError(f"promotion authority lock failed: {exc}") from exc

    def _promote_to_prime_locked(
        self,
        *,
        project_id: str,
        section_id: str,
        candidate_id: str,
        ceremony_token: str,
        session_id: str,
        reason: str = "",
        fault_after: Optional[str] = None,
    ) -> dict[str, Any]:
        # Trust expansion may not outrun missing evidence from the object's
        # custody intake or its containing project/section. Delivery is retried
        # first; a persistent gap blocks before token consumption or reservation.
        self.vault.assert_canonical_evidence_current(
            project_id=project_id,
            section_id=section_id,
            file_id=candidate_id,
        )
        identity, decision = self._policy_decision(session_id)
        ids = self._ids()
        journal = self.journal.reserve(
            {
                **ids,
                "action_key": self.ACTION_KEY,
                "project_id": project_id,
                "section_id": section_id,
                "candidate_id": candidate_id,
                "session_id": session_id,
                "actor_id": identity.actor_id,
                "reason": reason,
                "policy": decision["policy"],
                "policy_hash": sha256_json(decision["policy"]),
                # Receipt time is precommitted so restart recovery reproduces
                # the exact receipt hash rather than minting a new assertion.
                "receipt_issued_at": utc_now(),
                "pre_state": self._pre_state(project_id, section_id, candidate_id),
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
                "object_id": candidate_id,
                "action_key": self.ACTION_KEY,
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
                action_key=self.ACTION_KEY,
                session_id=session_id,
                project_id=project_id,
                section_id=section_id,
                object_id=candidate_id,
            )
            if token_record.get("legacy_unscoped"):
                raise PromotionTransactionError("integrated promotion requires a scoped ceremony token")
        except (VaultError, PromotionTransactionError) as exc:
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
            summary="Wallet authorized one scoped Prime-promotion transaction",
            payload={
                "transaction_id": ids["operation_id"],
                "receipt_id": ids["receipt_id"],
                "reserved_event_hash": reserved["event_hash"],
                "actor_id": identity.actor_id,
                "actor_kind": identity.actor_kind,
                "session_id": identity.session_id,
                "device_id": identity.device_id,
                "verified_methods": list(identity.verified_methods),
                "action_key": self.ACTION_KEY,
                "project_id": project_id,
                "section_id": section_id,
                "object_id": candidate_id,
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
            raise SimulatedPromotionCrash("authorized")

        def fault_hook(stage: str) -> None:
            if fault_after == stage:
                raise SimulatedPromotionCrash(stage)

        try:
            result = self.vault._promote_candidate_to_prime_unchecked(
                project_id,
                section_id,
                candidate_id,
                reason=reason,
                transaction_id=ids["operation_id"],
                fault_hook=fault_hook,
            )
            return self._finalize_completed(
                journal,
                result,
                actor=actor,
                recovered=False,
                fault_after=fault_after,
            )
        except SimulatedPromotionCrash:
            raise
        except Exception as exc:
            outcome, observed = self._observed_outcome(journal)
            if outcome == "unchanged":
                self._finalize_failed(journal, actor=actor, reason=f"{type(exc).__name__}: {exc}")
            elif outcome == "ambiguous":
                self._freeze_ambiguous(journal, observed, reason=f"{type(exc).__name__}: {exc}")
            # If the mutation completed but evidence failed, leave the journal
            # active for startup reconciliation rather than inventing a result.
            raise

    def _receipt_material(
        self,
        journal: Mapping[str, Any],
        *,
        actor: str,
        status: str,
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
            "action_label": self.ACTION_LABEL,
            "project_id": journal["project_id"],
            "section_id": journal["section_id"],
            "object_id": journal["candidate_id"],
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
            "result_status": status,
            "recovered_after_restart": bool(
                journal.get("completion_recovered_after_restart", recovered)
            ),
            "intent_statement": (
                "A Wallet-authorized local human identity session completed "
                "this scoped protected custody action."
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
        # Freeze the recovery characterization before any canonical final-stage
        # event is written.  Retries must reproduce the exact same semantic
        # fact, not rewrite it as a newly recovered assertion.
        if "completion_recovered_after_restart" not in journal:
            journal = self.journal.update(
                operation_id,
                completion_recovered_after_restart=bool(recovered),
            )
        completion_recovered = bool(journal["completion_recovered_after_restart"])
        custody = self._append_stage(
            journal,
            stage="CUSTODY",
            event_type="PRIME_PROMOTED",
            event_id_key="custody_event_id",
            actor=actor,
            summary="Candidate promoted to Prime and former Prime archived",
            payload={
                "transaction_id": operation_id,
                "authorization_event_hash": journal["authorization_event_hash"],
                "project_id": journal["project_id"],
                "section_id": journal["section_id"],
                "file_id": journal["candidate_id"],
                "state": "prime",
                "previous_prime_id": (journal.get("pre_state") or {}).get("section_prime"),
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
            summary="Protected Prime-promotion transaction completed",
            payload={
                "transaction_id": operation_id,
                "authorization_event_hash": journal["authorization_event_hash"],
                "custody_event_hash": custody["event_hash"],
                "result_status": "completed",
                "project_id": journal["project_id"],
                "section_id": journal["section_id"],
                "object_id": journal["candidate_id"],
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
            status="completed",
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
            raise SimulatedPromotionCrash("anchor_recorded")
        stored = self.receipts.create(receipt)
        journal = self.journal.update(
            operation_id,
            receipt_written=True,
            stage="RECEIPT_WRITTEN",
        )
        if fault_after == "receipt_written":
            raise SimulatedPromotionCrash("receipt_written")
        verification = self.verify_receipt(stored["receipt_id"])
        if not verification.get("ok"):
            raise PromotionTransactionError(
                f"new Human Intent receipt failed verification: {verification.get('reason')}"
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
            summary="Protected Prime-promotion transaction failed before mutation",
            payload={
                "transaction_id": journal["operation_id"],
                "authorization_event_hash": journal.get("authorization_event_hash"),
                "result_status": "failed",
                "reason_class": reason[:200],
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
        candidate = self.vault._find_file(
            str(journal["project_id"]),
            str(journal["section_id"]),
            str(journal["candidate_id"]),
        )
        section = self.vault.get_section(str(journal["project_id"]), str(journal["section_id"]))
        candidate["trust_locked"] = True
        candidate["trust_lock_reason"] = "promotion_reconciliation_required"
        section["reconciliation_required"] = True
        section["reconciliation_operation_id"] = journal["operation_id"]
        self.vault._save()
        event = self.evidence.append_fact(
            event_type="PROMOTION_RECONCILIATION_REQUIRED",
            summary="Promotion state is ambiguous; trust expansion frozen",
            transaction_id=str(journal["operation_id"]),
            stage_key=f"{journal['operation_id']}:RECONCILIATION_REQUIRED",
            actor="wallet:reconciler",
            subject_id=f"candidate:{journal['candidate_id']}",
            payload={
                "transaction_id": journal["operation_id"],
                "project_id": journal["project_id"],
                "section_id": journal["section_id"],
                "object_id": journal["candidate_id"],
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
        report = {"checked": 0, "reconciled": 0, "failed": 0, "ambiguous": 0, "receipts": []}
        for pending in self.journal.pending():
            report["checked"] += 1
            project_id = str(pending["project_id"])
            section_id = str(pending["section_id"])
            try:
                with self.vault.catalog_transaction():
                    with file_lock(self._promotion_lock_path(project_id, section_id)):
                        # Another process may have completed this journal while we
                        # waited. Re-read durable journal and catalog under both locks.
                        try:
                            journal = self.journal.get(str(pending["operation_id"]))
                        except PromotionTransactionError:
                            continue
                        if journal.get("stage") in {"COMPLETE", "FAILED", "RECONCILIATION_REQUIRED"}:
                            continue
                        outcome, observed = self._observed_outcome(journal)
                        actor = f"human:{journal.get('actor_id') or 'unknown'}"
                        if outcome == "complete":
                            result = self.vault._find_file(
                                project_id, section_id, str(journal["candidate_id"])
                            )
                            completed = self._finalize_completed(
                                journal, result, actor=actor, recovered=True
                            )
                            report["reconciled"] += 1
                            report["receipts"].append(completed["receipt"]["receipt_id"])
                        elif outcome == "unchanged":
                            self._finalize_failed(
                                journal,
                                actor=actor,
                                reason="restart reconciliation observed no custody mutation",
                            )
                            report["failed"] += 1
                        else:
                            self._freeze_ambiguous(
                                journal,
                                observed,
                                reason="restart reconciliation could not prove completion or no-op",
                            )
                            report["ambiguous"] += 1
            except (DurableIOError, VaultError) as exc:
                raise PromotionTransactionError(
                    f"promotion reconciliation lock failed: {exc}"
                ) from exc
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
            return {"ok": False, "status": "invalid", "reason": "canonical BlackBox chain invalid", "chain": chain}

        expected = [
            ("reserved_event_id", "reserved_event_hash", "HUMAN_INTENT_RESERVED"),
            ("authorization_event_id", "authorization_event_hash", "HUMAN_INTENT_AUTHORIZED"),
            ("custody_event_id", "custody_event_hash", "PRIME_PROMOTED"),
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
            if (record.get("payload") or {}).get("transaction_id") != receipt.get("operation_id"):
                return {"ok": False, "status": "invalid", "reason": f"{event_type} transaction mismatch"}
            records.append(record)
        if [int(record["seq"]) for record in records] != sorted(int(record["seq"]) for record in records):
            return {"ok": False, "status": "invalid", "reason": "receipt graph out of order"}
        reserved_payload = records[0].get("payload") or {}
        authorization_payload = records[1].get("payload") or {}
        custody_payload = records[2].get("payload") or {}
        terminal_payload = records[3].get("payload") or {}
        anchor_payload = records[4].get("payload") or {}
        for key in ("project_id", "section_id"):
            expected_value = receipt.get(key)
            for name, payload in (("reserved", reserved_payload), ("authorization", authorization_payload), ("custody", custody_payload), ("terminal", terminal_payload)):
                if payload.get(key) != expected_value:
                    return {"ok": False, "status": "invalid", "reason": f"{name} {key} mismatch"}
        for name, payload, object_key in (
            ("reserved", reserved_payload, "object_id"),
            ("authorization", authorization_payload, "object_id"),
            ("custody", custody_payload, "file_id"),
            ("terminal", terminal_payload, "object_id"),
        ):
            if payload.get(object_key) != receipt.get("object_id"):
                return {"ok": False, "status": "invalid", "reason": f"{name} object scope mismatch"}
        if reserved_payload.get("receipt_id") != receipt.get("receipt_id"):
            return {"ok": False, "status": "invalid", "reason": "reserved receipt id mismatch"}
        if authorization_payload.get("receipt_id") != receipt.get("receipt_id"):
            return {"ok": False, "status": "invalid", "reason": "authorization receipt id mismatch"}
        if authorization_payload.get("actor_id") != receipt.get("actor_id") or authorization_payload.get("session_id") != receipt.get("session_id"):
            return {"ok": False, "status": "invalid", "reason": "authorization identity mismatch"}
        if authorization_payload.get("ceremony_token_id") != receipt.get("ceremony_token_id") or authorization_payload.get("ceremony_consumption_hash") != receipt.get("ceremony_consumption_hash"):
            return {"ok": False, "status": "invalid", "reason": "authorization ceremony binding mismatch"}
        if authorization_payload.get("policy_hash") != receipt.get("policy_hash"):
            return {"ok": False, "status": "invalid", "reason": "authorization policy hash mismatch"}
        policy = authorization_payload.get("policy")
        if not isinstance(policy, Mapping) or sha256_json(policy) != receipt.get("policy_hash"):
            return {"ok": False, "status": "invalid", "reason": "policy snapshot hash mismatch"}
        if custody_payload.get("authorization_event_hash") != receipt.get("authorization_event_hash"):
            return {"ok": False, "status": "invalid", "reason": "custody authorization link mismatch"}
        if terminal_payload.get("authorization_event_hash") != receipt.get("authorization_event_hash") or terminal_payload.get("custody_event_hash") != receipt.get("custody_event_hash"):
            return {"ok": False, "status": "invalid", "reason": "terminal evidence link mismatch"}
        if terminal_payload.get("result_status") != receipt.get("result_status"):
            return {"ok": False, "status": "invalid", "reason": "terminal result mismatch"}
        if anchor_payload.get("receipt_id") != receipt.get("receipt_id") or anchor_payload.get("receipt_hash") != receipt.get("receipt_hash"):
            return {"ok": False, "status": "invalid", "reason": "anchor receipt binding mismatch"}
        if anchor_payload.get("authorization_event_hash") != receipt.get("authorization_event_hash") or anchor_payload.get("terminal_event_hash") != receipt.get("terminal_event_hash"):
            return {"ok": False, "status": "invalid", "reason": "anchor event link mismatch"}
        if anchor_payload.get("ceremony_consumption_hash") != receipt.get("ceremony_consumption_hash"):
            return {"ok": False, "status": "invalid", "reason": "anchor ceremony binding mismatch"}
        operation_records = self.evidence.records_for_operation(str(receipt.get("operation_id") or ""))
        required_ids = {str(receipt.get(id_key) or "") for id_key, _, _ in expected}
        if "" in required_ids or len(required_ids) != len(expected):
            return {"ok": False, "status": "invalid", "reason": "receipt graph uses missing or duplicate record ids"}
        required_records = [
            record for record in operation_records
            if str(record.get("record_id")) in required_ids
        ]
        if len(required_records) != len(required_ids):
            return {"ok": False, "status": "invalid", "reason": "receipt graph is incomplete or duplicated"}

        graph_event_types = {event_type for _, _, event_type in expected}
        contradictory_types = {
            "HUMAN_INTENT_FAILED",
            "PROMOTION_RECONCILIATION_REQUIRED",
        }
        graph_records = [
            record for record in operation_records
            if record.get("event_type") in graph_event_types | contradictory_types
        ]
        if any(record.get("event_type") in contradictory_types for record in graph_records):
            return {"ok": False, "status": "invalid", "reason": "receipt graph contains a contradictory terminal or reconciliation stage"}
        for _, _, event_type in expected:
            matches = [record for record in graph_records if record.get("event_type") == event_type]
            if len(matches) != 1:
                return {"ok": False, "status": "invalid", "reason": f"receipt graph has duplicate or missing {event_type} stage"}
        if {str(record.get("record_id")) for record in graph_records} != required_ids:
            return {"ok": False, "status": "invalid", "reason": "receipt graph contains an uncommitted extra stage"}

        token_id = str(receipt.get("ceremony_token_id") or "")
        try:
            token_record = self.vault.ceremony_ledger.get_record(token_id, include_hash=True)
            token_hash = self.vault.ceremony_ledger.record_hash(token_id)
        except Exception as exc:
            return {"ok": False, "status": "invalid", "reason": f"ceremony record unavailable: {exc}"}
        if token_hash != receipt.get("ceremony_consumption_hash"):
            return {"ok": False, "status": "invalid", "reason": "ceremony consumption hash mismatch"}
        for key, expected_value in (
            ("action_key", receipt.get("action_key")),
            ("session_id", receipt.get("session_id")),
            ("project_id", receipt.get("project_id")),
            ("section_id", receipt.get("section_id")),
            ("object_id", receipt.get("object_id")),
        ):
            if token_record.get(key) != expected_value:
                return {"ok": False, "status": "invalid", "reason": f"ceremony {key} mismatch"}
        if not token_record.get("consumed_at") or token_record.get("consumed_by_action") != receipt.get("action_key"):
            return {"ok": False, "status": "invalid", "reason": "ceremony token was not consumed for this action"}
        return {
            "ok": True,
            "status": "complete",
            "receipt_id": receipt_id,
            "operation_id": receipt.get("operation_id"),
            "chain": chain,
            "evidence_limit": receipt.get("evidence_limits"),
        }
