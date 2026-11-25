"""Wallet-facing access to the canonical standalone BlackBox recorder.

This module deliberately separates three responsibilities:

* ``CanonicalEvidenceAdapter`` translates Wallet facts into the host-neutral
  BBX1 recorder. It observes; it does not authorize custody.
* ``HumanIntentReceiptStore`` is Wallet-owned portable receipt storage.
* Receipt graph verification is performed against canonical BBX1 records and
  the Wallet ceremony ledger, never against caller-supplied approval booleans.

The historical writable ``iteration_wallet.blackbox.BlackBox`` implementation is
preserved outside the active package path. The compatibility module fails closed.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Optional
from uuid import uuid4

from blackbox_plugin.models import Coverage, ObservationMode
from blackbox_plugin.schema import ZERO_HASH, canonical_json
from blackbox_plugin.client import BlackBoxClient, LocalBlackBoxClient
from blackbox_plugin.errors import WitnessUnavailableError
from iteration_wallet_blackbox import (
    DurableOutbox, WalletBlackBoxConnector, WalletFact, WitnessAcknowledgementPersistenceError, WitnessDelivery, WitnessRejectedError,
)

from iteration_wallet.durable_io import (
    DurableIOError,
    atomic_json as _atomic_json,
    exclusive_json as _exclusive_json,
    strict_json_read,
    validate_storage_id,
    ensure_within,
    file_lock,
)


class CanonicalEvidenceError(Exception):
    """Raised when canonical evidence or receipt storage fails closed."""



class HumanIntentReceiptStore:
    """Wallet-owned, write-once portable Human Intent receipts."""

    HASH_EXCLUDED_FIELDS = {"receipt_hash", "anchor_event_hash"}

    def __init__(self, vault_root: Path | str) -> None:
        self.root = Path(vault_root)
        self.receipt_dir = self.root / "human_intent_receipts"
        try:
            ensure_within(
                self.root, self.receipt_dir, label="receipt storage",
                error_type=CanonicalEvidenceError,
            )
        except DurableIOError as exc:
            raise CanonicalEvidenceError(str(exc)) from exc
        if self.receipt_dir.is_symlink():
            raise CanonicalEvidenceError("receipt storage directory cannot be a symlink")
        self.receipt_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _receipt_id(receipt_id: str) -> str:
        try:
            return validate_storage_id("receipt_id", receipt_id, error_type=CanonicalEvidenceError)
        except DurableIOError as exc:
            raise CanonicalEvidenceError(str(exc)) from exc

    @classmethod
    def core_hash(cls, receipt: Mapping[str, Any]) -> str:
        core = {
            key: value
            for key, value in dict(receipt).items()
            if key not in cls.HASH_EXCLUDED_FIELDS
        }
        return hashlib.sha256(canonical_json(core)).hexdigest()

    def create(self, receipt: Mapping[str, Any]) -> dict[str, Any]:
        """Create a receipt once, or verify an identical retry.

        Restart recovery may legitimately repeat the final write after the
        canonical anchor already exists.  That retry is accepted only when the
        complete receipt material is identical.  A same-ID/different-content
        attempt remains a hard failure rather than an overwrite.
        """
        material = dict(receipt)
        receipt_id = self._receipt_id(str(material.get("receipt_id") or ""))
        material["receipt_hash"] = self.core_hash(material)
        path = self.receipt_dir / f"{receipt_id}.json"
        if path.exists():
            existing = self.get(receipt_id)
            if canonical_json(existing) != canonical_json(material):
                raise CanonicalEvidenceError(
                    f"receipt retry conflicts with write-once artifact: {receipt_id}"
                )
            return existing
        try:
            _exclusive_json(path, material)
        except FileExistsError:
            existing = self.get(receipt_id)
            if canonical_json(existing) != canonical_json(material):
                raise CanonicalEvidenceError(
                    f"concurrent receipt write conflicts with write-once artifact: {receipt_id}"
                )
            return existing
        return material

    def get(self, receipt_id: str) -> dict[str, Any]:
        receipt_id = self._receipt_id(str(receipt_id))
        path = self.receipt_dir / f"{receipt_id}.json"
        if not path.is_file():
            raise CanonicalEvidenceError(f"receipt not found: {receipt_id}")
        try:
            data = strict_json_read(path)
        except DurableIOError as exc:
            raise CanonicalEvidenceError(f"unreadable receipt {receipt_id}: {exc}") from exc
        if not isinstance(data, dict):
            raise CanonicalEvidenceError(f"receipt is not an object: {receipt_id}")
        if data.get("receipt_id") != receipt_id:
            raise CanonicalEvidenceError(f"receipt id does not match its storage name: {receipt_id}")
        return data

    def list(self) -> list[dict[str, Any]]:
        receipts = [self.get(path.stem) for path in sorted(self.receipt_dir.glob("*.json"))]
        receipts.sort(key=lambda item: (str(item.get("issued_at") or ""), str(item.get("receipt_id") or "")))
        return receipts


class CanonicalEvidenceAdapter:
    """Wallet-compatible adapter over the canonical BBX1 recorder.

    Compatibility methods here translate neutral event-writing calls only. This
    class intentionally has no method that mints Human Intent authority.
    """

    def __init__(
        self,
        vault_root: Path | str,
        *,
        session_id: str = "wallet-main",
        client: BlackBoxClient | None = None,
    ) -> None:
        self.vault_root = Path(vault_root)
        self.blackbox_dir = self.vault_root / "canonical_blackbox"
        self.support_dir = self.vault_root / "canonical_blackbox_support"
        self.request_dir = self.support_dir / "requests"
        self.incident_dir = self.support_dir / "incidents"
        self.lock_dir = self.support_dir / ".locks"
        self.event_dir = self.blackbox_dir / "sessions" / session_id / "segments"
        self.chain_file = self.blackbox_dir / "sessions" / session_id / "active_state.json"
        for directory in (
            self.blackbox_dir, self.support_dir, self.request_dir, self.incident_dir,
            self.lock_dir,
        ):
            try:
                ensure_within(
                    self.vault_root, directory, label="canonical evidence storage",
                    error_type=CanonicalEvidenceError,
                )
            except DurableIOError as exc:
                raise CanonicalEvidenceError(str(exc)) from exc
            if directory.is_symlink():
                raise CanonicalEvidenceError(
                    f"canonical evidence directory cannot be a symlink: {directory.name}"
                )
            directory.mkdir(parents=True, exist_ok=True)
        self.client: BlackBoxClient = client or LocalBlackBoxClient.open(self.blackbox_dir, session_id=session_id)
        self.outbox = DurableOutbox(self.support_dir / "wallet_evidence_outbox.jsonl")
        self.connector = WalletBlackBoxConnector(self.outbox, self.client)
        self.session_id = session_id
        self.receipts: Optional[HumanIntentReceiptStore] = None
        self.receipt_verifier: Optional[Callable[[str], dict[str, Any]]] = None
        self.receipt_verifiers: dict[str, Callable[[str], dict[str, Any]]] = {}

    def attach_receipt_store(
        self,
        receipts: HumanIntentReceiptStore,
        *,
        verifier: Optional[Callable[[str], dict[str, Any]]] = None,
    ) -> None:
        """Attach Wallet-owned receipt storage and an optional legacy verifier.

        Multiple Wallet transaction coordinators may share the same write-once
        receipt store.  Action-specific semantic verifiers are registered with
        :meth:`register_receipt_verifier`; the legacy callback remains only for
        backward compatibility with the original promotion-only runtime.
        """
        if self.receipts is not None and self.receipts.receipt_dir != receipts.receipt_dir:
            raise CanonicalEvidenceError("cannot attach competing Wallet receipt stores")
        self.receipts = receipts
        if verifier is not None:
            self.receipt_verifier = verifier

    def register_receipt_verifier(
        self,
        action_key: str,
        verifier: Callable[[str], dict[str, Any]],
    ) -> None:
        if not action_key or not callable(verifier):
            raise CanonicalEvidenceError("receipt verifier requires action_key and callable")
        # A restarted Wallet coordinator legitimately supersedes the prior
        # in-memory bound method while using the same durable receipt store.
        # Registration changes no evidence and grants no minting authority.
        self.receipt_verifiers[action_key] = verifier

    def _current_chain_state(self) -> tuple[str, int]:
        health = dict(self.client.status().get("health") or {})
        head = str(health.get("last_record_hash") or ZERO_HASH)
        next_sequence = int(health.get("sequence") or 0)
        return ("GENESIS" if head == ZERO_HASH else head, next_sequence)

    def current_chain_head(self) -> str:
        return self._current_chain_state()[0]

    @staticmethod
    def _subject(extra: Mapping[str, Any]) -> str:
        for key, prefix in (
            ("file_id", "file"),
            ("object_id", "object"),
            ("section_id", "section"),
            ("project_id", "project"),
            ("vault_id", "vault"),
            ("request_id", "request"),
        ):
            value = extra.get(key)
            if value:
                return f"{prefix}:{value}"
        return "wallet:root"

    @staticmethod
    def _actor(extra: Mapping[str, Any]) -> str:
        actor_id = extra.get("actor_id")
        if not actor_id and isinstance(extra.get("identity"), Mapping):
            actor_id = extra["identity"].get("actor_id")
        return f"human:{actor_id}" if actor_id else "wallet:system"

    def append_fact(
        self,
        *,
        event_type: str,
        summary: str,
        source: str = "iteration_wallet",
        event_id: Optional[str] = None,
        transaction_id: Optional[str] = None,
        stage_key: Optional[str] = None,
        actor: Optional[str] = None,
        subject_id: Optional[str] = None,
        payload: Optional[Mapping[str, Any]] = None,
        observation_mode: ObservationMode = ObservationMode.DIRECT,
        coverage: Coverage = Coverage.FULL,
        channel: str = "IW",
        event_code: str = "OBS",
    ) -> dict[str, Any]:
        material = dict(payload or {})
        if summary:
            material.setdefault("summary", summary)
        if transaction_id:
            material.setdefault("transaction_id", transaction_id)
        event_identifier = event_id or uuid4().hex
        operation_key = stage_key or (
            f"{transaction_id}:{event_type}" if transaction_id else f"event:{event_identifier}"
        )
        fact = WalletFact(
            event_type=event_type,
            actor=actor or "wallet:system",
            object_id=subject_id or "wallet:root",
            project_id=str(material.get("project_id") or "project:wallet"),
            source=source,
            section_id=(
                None if material.get("section_id") is None else str(material.get("section_id"))
            ),
            operation_id=operation_key,
            payload=material,
            session_id=self.session_id,
            event_id=event_identifier,
            observation_mode=observation_mode,
            coverage=coverage,
            channel=channel,
            event_code=event_code,
        )
        try:
            delivery, receipt = self.connector.submit(fact, require_ack=True)
        except WitnessRejectedError as exc:
            raise CanonicalEvidenceError(f"canonical BlackBox rejected Wallet evidence: {exc}") from exc
        except WitnessAcknowledgementPersistenceError as exc:
            raise CanonicalEvidenceError(
                "canonical BlackBox accepted Wallet evidence, but local acknowledgement persistence failed; "
                "the durable outbox remains pending for idempotent recovery"
            ) from exc
        except WitnessUnavailableError as exc:
            raise CanonicalEvidenceError(f"canonical BlackBox acknowledgement unavailable: {exc}") from exc
        if delivery is not WitnessDelivery.ACKNOWLEDGED or receipt is None:
            raise CanonicalEvidenceError(f"canonical evidence delivery did not acknowledge: {delivery.value}")
        return {
            "event_id": receipt.record_id,
            "event_hash": receipt.event_hash,
            "previous_event_hash": receipt.previous_hash,
            "chain_index": receipt.sequence,
            "event_type": event_type,
            "created_at": receipt.accepted_at,
            "operation_id": transaction_id,
            "stage_key": operation_key,
            **material,
        }

    def write_event(self, event_type: str, summary: str, **extra: Any) -> dict[str, Any]:
        transaction_id = extra.pop("transaction_id", None) or extra.pop("operation_id", None)
        event_id = extra.pop("event_id", None)
        stage_key = extra.pop("stage_key", None)
        return self.append_fact(
            event_type=event_type,
            summary=summary,
            event_id=event_id,
            transaction_id=transaction_id,
            stage_key=stage_key,
            actor=self._actor(extra),
            subject_id=self._subject(extra),
            payload=extra,
        )

    def write_custody_event(
        self,
        event_type: str,
        summary: str,
        source: str = "iteration_wallet",
        *,
        project_id: Optional[str] = None,
        section_id: Optional[str] = None,
        file_id: Optional[str] = None,
        state: Optional[str] = None,
        **extra: Any,
    ) -> dict[str, Any]:
        return self.write_event(
            event_type,
            summary,
            project_id=project_id,
            section_id=section_id,
            file_id=file_id,
            state=state,
            custody_event=True,
            **extra,
        )

    def write_violation_event(self, event_type: str, summary: str, **extra: Any) -> dict[str, Any]:
        return self.write_event(
            event_type,
            summary,
            custody_violation=True,
            possible_intrusion=True,
            **extra,
        )

    def update_request_incident_bundle(self, request: Mapping[str, Any]) -> dict[str, Any]:
        """Append one request-pressure update without losing concurrent writers."""
        raw = "|".join(
            str(request.get(key) or "")
            for key in ("vault_id", "object_id", "action", "requester_id", "tool_family")
        )
        incident_id = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
        incident_id = validate_storage_id(
            "incident_id", incident_id, error_type=CanonicalEvidenceError
        )
        path = self.incident_dir / f"{incident_id}.json"
        lock_path = self.lock_dir / f"incident-{incident_id}.lock"
        try:
            ensure_within(
                self.incident_dir, path, label="incident bundle storage",
                error_type=CanonicalEvidenceError,
            )
            ensure_within(
                self.lock_dir, lock_path, label="incident bundle lock",
                error_type=CanonicalEvidenceError,
            )
        except DurableIOError as exc:
            raise CanonicalEvidenceError(str(exc)) from exc
        if path.is_symlink():
            raise CanonicalEvidenceError("incident bundle path cannot be a symlink")

        try:
            lock_context = file_lock(lock_path)
            with lock_context:
                if path.exists():
                    try:
                        incident = strict_json_read(path)
                        if not isinstance(incident, dict):
                            raise CanonicalEvidenceError("incident bundle is not an object")
                    except (DurableIOError, CanonicalEvidenceError) as exc:
                        raise CanonicalEvidenceError(
                            f"existing incident bundle is unreadable: {exc}"
                        ) from exc
                    if incident.get("incident_id") != incident_id:
                        raise CanonicalEvidenceError(
                            "incident bundle id does not match its storage name"
                        )
                else:
                    incident = {
                        "incident_id": incident_id,
                        "incident_type": "BOT_REQUEST_PRESSURE",
                        "created_at": request.get("created_at"),
                        "raw_request_ids": [],
                        "updates": [],
                    }

                request_id = str(request.get("request_id") or "")
                if request_id:
                    validate_storage_id(
                        "request_id", request_id, error_type=CanonicalEvidenceError
                    )
                raw_request_ids = incident.setdefault("raw_request_ids", [])
                if not isinstance(raw_request_ids, list):
                    raise CanonicalEvidenceError("incident raw_request_ids must be a list")
                if request_id and request_id not in raw_request_ids:
                    raw_request_ids.append(request_id)

                updates = incident.setdefault("updates", [])
                if not isinstance(updates, list):
                    raise CanonicalEvidenceError("incident updates must be a list")
                if request_id and not any(
                    isinstance(item, dict) and item.get("update_id") == request_id
                    for item in updates
                ):
                    updates.append(
                        {
                            "update_id": request_id,
                            "request_id": request_id,
                            "updated_at": request.get("created_at"),
                            "classification": request.get("classification"),
                            "matching_request_count": int(
                                request.get("matching_request_count") or 0
                            ),
                            "status": request.get("status"),
                            "object_id": request.get("object_id"),
                        }
                    )

                valid_updates = [item for item in updates if isinstance(item, dict)]
                highest = max(
                    valid_updates,
                    key=lambda item: (
                        int(item.get("matching_request_count") or 0),
                        str(item.get("updated_at") or ""),
                        str(item.get("update_id") or ""),
                    ),
                    default=None,
                )
                latest_time = max(
                    (str(item.get("updated_at") or "") for item in valid_updates),
                    default=str(request.get("created_at") or ""),
                )
                incident.update(
                    {
                        "updated_at": latest_time,
                        "classification": (highest or {}).get("classification"),
                        "matching_request_count": int(
                            (highest or {}).get("matching_request_count") or 0
                        ),
                        "status": (highest or {}).get("status"),
                        "object_id": request.get("object_id"),
                        "action": request.get("action"),
                        "requester_id": request.get("requester_id"),
                        "tool_family": request.get("tool_family"),
                    }
                )
                _atomic_json(path, incident)
                return incident
        except DurableIOError as exc:
            raise CanonicalEvidenceError(
                f"cannot lock incident bundle {incident_id}: {exc}"
            ) from exc

    def issue_human_intent_receipt(self, **_: Any) -> dict[str, Any]:
        """Fail closed: only a Wallet transaction coordinator may mint receipts."""
        raise PermissionError(
            "Canonical evidence adapters cannot mint Human Intent receipts; "
            "use a Wallet-owned protected-action transaction coordinator."
        )

    def _require_receipt_store(self) -> HumanIntentReceiptStore:
        if self.receipts is None:
            raise CanonicalEvidenceError("Wallet receipt store is not attached")
        return self.receipts

    def get_human_intent_receipt(self, receipt_id: str) -> Optional[dict[str, Any]]:
        try:
            return self._require_receipt_store().get(receipt_id)
        except CanonicalEvidenceError as exc:
            if "not found" in str(exc):
                return None
            raise

    def verify_human_intent_receipt(self, receipt_id: str) -> dict[str, Any]:
        try:
            receipt = self._require_receipt_store().get(receipt_id)
        except CanonicalEvidenceError as exc:
            return {"ok": False, "status": "invalid", "reason": str(exc), "receipt_id": receipt_id}
        action_key = str(receipt.get("action_key") or "")
        verifier = self.receipt_verifiers.get(action_key)
        if verifier is not None:
            return verifier(receipt_id)
        if self.receipt_verifier is not None:
            return self.receipt_verifier(receipt_id)
        return {
            "ok": False,
            "status": "unavailable",
            "reason": f"Wallet semantic receipt verifier is not registered for {action_key!r}",
            "receipt_id": receipt_id,
        }

    def verify_chain(self) -> dict[str, Any]:
        result = dict(self.client.verify())
        # Preserve the old local interface name without overstating authority.
        result.setdefault("chain_head", self._current_chain_state()[0])
        result.setdefault("event_count", result.get("checked", 0))
        return result

    def records(self) -> list[dict[str, Any]]:
        return [dict(item) for item in self.client.iter_records()]

    def iter_events(self) -> Iterable[dict[str, Any]]:
        return iter(self.records())

    def records_for_operation(self, transaction_id: str) -> list[dict[str, Any]]:
        return [
            record
            for record in self.records()
            if record.get("operation_id") == transaction_id
            or (record.get("payload") or {}).get("transaction_id") == transaction_id
        ]

    def record_by_id(self, record_id: str) -> Optional[dict[str, Any]]:
        for record in self.records():
            if record.get("record_id") == record_id:
                return record
        return None

    def build_closed_evidence_summary(
        self,
        *,
        project_id: Optional[str] = None,
        section_id: Optional[str] = None,
        file_id: Optional[str] = None,
        limit: int = 5,
    ) -> dict[str, Any]:
        def matches(record: Mapping[str, Any]) -> bool:
            payload = record.get("payload") or {}
            return not (
                project_id and payload.get("project_id") != project_id
                or section_id and payload.get("section_id") != section_id
                or file_id and payload.get("file_id") != file_id
            )

        matched = [record for record in self.records() if matches(record)]
        recent = matched[-max(0, int(limit)):]
        verification = self.verify_chain()
        return {
            "chain_ok": bool(verification.get("ok")),
            "event_count": len(matched),
            "last_event_type": matched[-1].get("event_type") if matched else None,
            "last_event_at": matched[-1].get("observed_at") if matched else None,
            "recent_events": [
                {
                    "event_type": record.get("event_type"),
                    "observed_at": record.get("observed_at"),
                    "coverage": record.get("coverage"),
                }
                for record in recent
            ],
            "protected_values_exposed": False,
        }

    def list_human_intent_receipts(self, **filters: Any) -> list[dict[str, Any]]:
        if self.receipts is None:
            return []
        result = self.receipts.list()
        for key in ("project_id", "section_id", "object_id"):
            if filters.get(key):
                result = [item for item in result if item.get(key) == filters[key]]
        limit = int(filters.get("limit", 1000))
        if limit < 0:
            raise CanonicalEvidenceError("receipt limit cannot be negative")
        return result[-limit:] if limit else []

    def build_human_intent_receipt_report(self, limit: int = 1000) -> dict[str, Any]:
        receipts = self.list_human_intent_receipts(limit=limit)
        verification = [
            self.verify_human_intent_receipt(str(receipt.get("receipt_id") or ""))
            for receipt in receipts
        ]
        invalid = [item for item in verification if not item.get("ok")]
        return {
            "report_type": "canonical_human_intent_receipts",
            "summary": "Canonical Human Intent receipt report",
            "receipt_count": len(receipts),
            "receipt_count_included": len(receipts),
            "valid_count": len(receipts) - len(invalid),
            "invalid_count": len(invalid),
            "all_receipts_valid": not invalid,
            "receipts": receipts,
            "verification": verification,
            "chain": self.verify_chain(),
            "authority_boundary": (
                "Receipts are minted by Wallet transaction coordinators; "
                "this adapter provides canonical evidence reads only."
            ),
        }
