"""
Iteration Wallet v2.2.2 — Ceremony Token Lifecycle
===================================================

Action-bound ceremony tokens are short-lived, session-bound, and single-use.
They are not receipts, passwords, or permissions by themselves. They are the
small intentional-action proof that links a live human session to one protected
custody action.

Product law:
- Protected custody actions must not accept a loose reusable token at the API gate.
- Tokens are scoped to action/session/object context and expire quickly.
- Raw token secrets are never persisted; only token hashes are stored.
- Consumed, expired, revoked, wrong-action, wrong-session, or wrong-object tokens fail closed.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from typing import Protocol

from blackbox_plugin.schema import canonical_json


class CeremonyEvidenceWriter(Protocol):
    def write_event(self, event_type: str, summary: str, **extra: Any) -> Dict[str, Any]: ...

from iteration_wallet.durable_io import (
    DurableIOError,
    atomic_json,
    exclusive_json,
    file_lock,
    strict_json_read,
    validate_storage_id,
    ensure_within,
)


class CeremonyTokenError(Exception):
    """Raised for expected ceremony token lifecycle failures."""


class CeremonyTokenLedger:
    """File-backed ledger for scoped ceremony tokens.

    Token records live under `<vault_root>/ceremony_tokens`. The raw token is
    returned once on issue and is never written to disk. Validation recomputes
    the hash, checks scope, and consumes the token atomically.
    """

    TOKEN_PREFIX = "iwct"

    def __init__(self, vault_root: Path, blackbox: Optional[CeremonyEvidenceWriter] = None):
        self.vault_root = Path(vault_root)
        self.blackbox = blackbox
        self.token_dir = self.vault_root / "ceremony_tokens"
        self.lock_dir = self.token_dir / ".locks"
        self.denial_dir = self.vault_root / "ceremony_denials"
        for directory in (self.token_dir, self.lock_dir, self.denial_dir):
            try:
                ensure_within(
                    self.vault_root, directory, label="ceremony token storage",
                    error_type=CeremonyTokenError,
                )
            except DurableIOError as exc:
                raise CeremonyTokenError(str(exc)) from exc
            if directory.is_symlink():
                raise CeremonyTokenError(
                    f"ceremony token directory cannot be a symlink: {directory.name}"
                )
            directory.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def now() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def _write_json_atomic(path: Path, data: Dict[str, Any]) -> None:
        try:
            atomic_json(path, data)
        except DurableIOError as exc:
            raise CeremonyTokenError(f"could not persist ceremony record: {exc}") from exc

    @staticmethod
    def token_hash(raw_token: str) -> str:
        return hashlib.sha256(str(raw_token).encode("utf-8")).hexdigest()

    @classmethod
    def parse_token_id(cls, raw_token: str) -> str:
        parts = str(raw_token or "").split("_", 2)
        if len(parts) != 3 or parts[0] != cls.TOKEN_PREFIX or not parts[1] or not parts[2]:
            raise CeremonyTokenError("Invalid ceremony token format")
        return parts[1]

    def _validated_token_id(self, token_id: str) -> str:
        try:
            return validate_storage_id("token_id", str(token_id), error_type=CeremonyTokenError)
        except DurableIOError as exc:
            raise CeremonyTokenError(str(exc)) from exc

    def _path(self, token_id: str) -> Path:
        token_id = self._validated_token_id(token_id)
        return self.token_dir / f"{token_id}.json"

    def _lock_path(self, token_id: str) -> Path:
        token_id = self._validated_token_id(token_id)
        return self.lock_dir / f"{token_id}.lock"

    def _load_record(self, token_id: str) -> Dict[str, Any]:
        path = self._path(token_id)
        if not path.exists():
            raise CeremonyTokenError("Unknown ceremony token")
        try:
            record = strict_json_read(path)
        except DurableIOError as exc:
            raise CeremonyTokenError(f"Unreadable ceremony token record: {exc}") from exc
        if not isinstance(record, dict):
            raise CeremonyTokenError("Ceremony token record must be a JSON object")
        if record.get("token_id") != token_id:
            raise CeremonyTokenError("Ceremony token id does not match its storage name")
        return record

    def _create_record(self, record: Dict[str, Any]) -> None:
        try:
            exclusive_json(self._path(record["token_id"]), record)
        except FileExistsError as exc:
            raise CeremonyTokenError("ceremony token identifier collision") from exc
        except DurableIOError as exc:
            raise CeremonyTokenError(f"could not create ceremony record: {exc}") from exc

    def _save_record(self, record: Dict[str, Any]) -> None:
        self._write_json_atomic(self._path(record["token_id"]), record)

    def get_record(self, token_id: str, *, include_hash: bool = False) -> Dict[str, Any]:
        """Return one durable token record; raw token secrets are never present."""
        record = self._load_record(token_id)
        if not include_hash:
            record = dict(record)
            record.pop("token_hash", None)
        return record

    def record_hash(self, token_id: str) -> str:
        """Hash the complete durable token record, including the stored token hash.

        The returned digest binds receipt evidence to the exact consumed ledger
        record without exposing the raw ceremony token.
        """
        return hashlib.sha256(canonical_json(self._load_record(token_id))).hexdigest()

    @staticmethod
    def _observation_event_id(stage_key: str) -> str:
        return hashlib.sha256(stage_key.encode("utf-8")).hexdigest()[:32]

    def _record_denial(
        self,
        *,
        token_id: str,
        action_key: str,
        session_id: Optional[str],
        project_id: Optional[str],
        section_id: Optional[str],
        object_id: Optional[str],
        proposal_id: Optional[str],
        proposal_hash: Optional[str],
        reason: str,
    ) -> Dict[str, Any]:
        denial_id = uuid.uuid4().hex
        record = {
            "denial_id": denial_id,
            "token_id": self._validated_token_id(token_id),
            "action_key": action_key,
            "session_id": session_id,
            "project_id": project_id,
            "section_id": section_id,
            "object_id": object_id,
            "proposal_id": proposal_id,
            "proposal_hash": proposal_hash,
            "reason": reason,
            "denied_at": self.now().isoformat(),
        }
        try:
            exclusive_json(self.denial_dir / f"{denial_id}.json", record)
        except (FileExistsError, DurableIOError) as exc:
            raise CeremonyTokenError(f"could not preserve ceremony denial: {exc}") from exc
        return record

    def list_denials(self, token_id: Optional[str] = None) -> List[Dict[str, Any]]:
        expected_token = self._validated_token_id(token_id) if token_id else None
        records: List[Dict[str, Any]] = []
        for path in sorted(self.denial_dir.glob("*.json")):
            try:
                denial_id = validate_storage_id(
                    "denial_id", path.stem, error_type=CeremonyTokenError
                )
                data = strict_json_read(path)
            except DurableIOError as exc:
                raise CeremonyTokenError(f"Unreadable ceremony denial record: {exc}") from exc
            if not isinstance(data, dict) or data.get("denial_id") != denial_id:
                raise CeremonyTokenError("Ceremony denial id does not match its storage name")
            if expected_token is None or data.get("token_id") == expected_token:
                records.append(data)
        records.sort(key=lambda item: (str(item.get("denied_at") or ""), str(item.get("denial_id") or "")))
        return records

    def _token_observations(self, record: Dict[str, Any]) -> List[Dict[str, Any]]:
        token_id = str(record["token_id"])
        shared = {
            "token_id": token_id,
            "action_key": record.get("action_key"),
            "session_id": record.get("session_id"),
            "actor_id": record.get("actor_id"),
            "project_id": record.get("project_id"),
            "section_id": record.get("section_id"),
            "file_id": record.get("object_id"),
            "proposal_id": record.get("proposal_id"),
            "proposal_hash": record.get("proposal_hash"),
        }
        observations = [
            {
                "stage": "ISSUED",
                "event_type": "CEREMONY_TOKEN_ISSUED",
                "summary": f"Ceremony token issued for {record.get('action_key')}",
                "payload": {
                    **shared,
                    "issued_at": record.get("issued_at"),
                    "expires_at": record.get("expires_at"),
                },
            }
        ]
        if record.get("consumed_at"):
            observations.append(
                {
                    "stage": "CONSUMED",
                    "event_type": "CEREMONY_TOKEN_CONSUMED",
                    "summary": f"Ceremony token consumed for {record.get('consumed_by_action')}",
                    "payload": {
                        **shared,
                        "consumed_at": record.get("consumed_at"),
                        "consumed_by_action": record.get("consumed_by_action"),
                    },
                }
            )
        if record.get("revoked_at"):
            observations.append(
                {
                    "stage": "REVOKED",
                    "event_type": "CEREMONY_TOKEN_REVOKED",
                    "summary": f"Ceremony token revoked: {record.get('revoked_reason') or 'revoked'}",
                    "payload": {
                        **shared,
                        "revoked_at": record.get("revoked_at"),
                        "revoked_reason": record.get("revoked_reason"),
                    },
                }
            )
        return observations

    def reconcile_observations(self, token_id: Optional[str] = None) -> Dict[str, Any]:
        """Idempotently reconstruct observational BBX1 events from durable records.

        Ceremony records remain the local authority state. These events are
        observations of that state and never mutate a consumed record or change
        the hash later committed into a Human Intent receipt.
        """
        report: Dict[str, Any] = {"checked": 0, "delivered": 0, "errors": []}
        if not self.blackbox:
            report["errors"].append("canonical evidence writer unavailable")
            return report
        records = (
            [self._load_record(self._validated_token_id(token_id))]
            if token_id
            else [self._load_record(path.stem) for path in sorted(self.token_dir.glob("*.json"))]
        )
        for record in records:
            current_id = str(record["token_id"])
            for observation in self._token_observations(record):
                report["checked"] += 1
                stage_key = f"ceremony:{current_id}:{observation['stage']}"
                try:
                    self.blackbox.write_event(
                        observation["event_type"],
                        observation["summary"],
                        event_id=self._observation_event_id(stage_key),
                        stage_key=stage_key,
                        **observation["payload"],
                    )
                    report["delivered"] += 1
                except Exception as exc:
                    report["errors"].append(
                        {"stage_key": stage_key, "error": f"{type(exc).__name__}: {exc}"[:500]}
                    )
            for denial in self.list_denials(current_id):
                report["checked"] += 1
                stage_key = f"ceremony-denial:{denial['denial_id']}"
                try:
                    self.blackbox.write_event(
                        "CEREMONY_TOKEN_DENIED",
                        f"Ceremony token denied for {denial.get('action_key')}: {denial.get('reason')}",
                        event_id=self._observation_event_id(stage_key),
                        stage_key=stage_key,
                        token_id=current_id,
                        action_key=denial.get("action_key"),
                        session_id=denial.get("session_id"),
                        project_id=denial.get("project_id"),
                        section_id=denial.get("section_id"),
                        file_id=denial.get("object_id"),
                        reason=denial.get("reason"),
                        denied_at=denial.get("denied_at"),
                        denial_id=denial.get("denial_id"),
                    )
                    report["delivered"] += 1
                except Exception as exc:
                    report["errors"].append(
                        {"stage_key": stage_key, "error": f"{type(exc).__name__}: {exc}"[:500]}
                    )
        return report

    def _reconcile_best_effort(self, token_id: str) -> None:
        # Observation availability must never turn a completed local authority
        # transition into a caller-visible false failure. Startup and explicit
        # reconciliation can safely retry the deterministic events.
        self.reconcile_observations(token_id)

    def issue_token(
        self,
        *,
        action_key: str,
        session_id: str,
        open_session_id: str,
        actor_id: Optional[str] = None,
        project_id: Optional[str] = None,
        section_id: Optional[str] = None,
        object_id: Optional[str] = None,
        proposal_id: Optional[str] = None,
        proposal_hash: Optional[str] = None,
        ttl_seconds: int = 300,
    ) -> Dict[str, Any]:
        if not action_key:
            raise CeremonyTokenError("action_key is required")
        if not session_id:
            raise CeremonyTokenError("session_id is required")
        if not open_session_id:
            raise CeremonyTokenError("Vault must be open before issuing a ceremony token")
        if bool(proposal_id) != bool(proposal_hash):
            raise CeremonyTokenError("proposal_id and proposal_hash must be supplied together")
        if proposal_hash is not None:
            if len(str(proposal_hash)) != 64 or any(ch not in "0123456789abcdef" for ch in str(proposal_hash).lower()):
                raise CeremonyTokenError("proposal_hash must be a SHA-256 hex digest")
        ttl_seconds = max(5, min(int(ttl_seconds or 300), 900))
        issued_at = self.now()
        expires_at = issued_at + timedelta(seconds=ttl_seconds)
        token_id = uuid.uuid4().hex[:16]
        secret = secrets.token_urlsafe(32)
        raw_token = f"{self.TOKEN_PREFIX}_{token_id}_{secret}"
        record = {
            "token_id": token_id,
            "token_hash": self.token_hash(raw_token),
            "action_key": action_key,
            "session_id": session_id,
            "actor_id": actor_id,
            "project_id": project_id,
            "section_id": section_id,
            "object_id": object_id,
            "proposal_id": proposal_id,
            "proposal_hash": proposal_hash,
            "open_session_id": open_session_id,
            "issued_at": issued_at.isoformat(),
            "expires_at": expires_at.isoformat(),
            "consumed_at": None,
            "consumed_by_action": None,
            "revoked_at": None,
            "revoked_reason": None,
        }
        self._create_record(record)
        self._reconcile_best_effort(token_id)
        public = dict(record)
        public.pop("token_hash", None)
        public["ceremony_token"] = raw_token
        return public

    def validate_and_consume(
        self,
        raw_token: str,
        *,
        action_key: str,
        session_id: Optional[str] = None,
        open_session_id: Optional[str] = None,
        project_id: Optional[str] = None,
        section_id: Optional[str] = None,
        object_id: Optional[str] = None,
        proposal_id: Optional[str] = None,
        proposal_hash: Optional[str] = None,
    ) -> Dict[str, Any]:
        token_id = self.parse_token_id(raw_token)

        def deny(reason: str) -> None:
            self._record_denial(
                token_id=token_id,
                action_key=action_key,
                session_id=session_id,
                project_id=project_id,
                section_id=section_id,
                object_id=object_id,
                proposal_id=proposal_id,
                proposal_hash=proposal_hash,
                reason=reason,
            )
            self._reconcile_best_effort(token_id)
            raise CeremonyTokenError(reason)

        try:
            with file_lock(self._lock_path(token_id)):
                record = self._load_record(token_id)
                now = self.now()
                if record.get("token_hash") != self.token_hash(raw_token):
                    deny("Ceremony token secret mismatch")
                if record.get("revoked_at"):
                    deny("Ceremony token has been revoked")
                if record.get("consumed_at"):
                    deny("Ceremony token has already been used")
                expires_at = datetime.fromisoformat(record["expires_at"])
                if expires_at.tzinfo is None:
                    expires_at = expires_at.replace(tzinfo=timezone.utc)
                if now > expires_at:
                    deny("Ceremony token has expired")
                if record.get("action_key") != action_key:
                    deny("Ceremony token is not valid for this action")
                if session_id is not None and record.get("session_id") != session_id:
                    deny("Ceremony token is not valid for this identity session")
                if open_session_id is not None and record.get("open_session_id") != open_session_id:
                    deny("Ceremony token is not valid for the current open Vault session")
                for key, expected in (
                    ("project_id", project_id),
                    ("section_id", section_id),
                    ("object_id", object_id),
                    ("proposal_id", proposal_id),
                    ("proposal_hash", proposal_hash),
                ):
                    if expected is not None and record.get(key) != expected:
                        deny(f"Ceremony token is not valid for this {key}")

                record["consumed_at"] = now.isoformat()
                record["consumed_by_action"] = action_key
                self._save_record(record)
                safe = dict(record)
                safe.pop("token_hash", None)
        except DurableIOError as exc:
            raise CeremonyTokenError(f"Ceremony token lock failed: {exc}") from exc

        self._reconcile_best_effort(token_id)
        return safe

    def revoke_token(self, raw_token: str, reason: str = "manual revocation") -> Dict[str, Any]:
        token_id = self.parse_token_id(raw_token)
        try:
            with file_lock(self._lock_path(token_id)):
                record = self._load_record(token_id)
                if record.get("token_hash") != self.token_hash(raw_token):
                    raise CeremonyTokenError("Ceremony token secret mismatch")
                if record.get("consumed_at"):
                    raise CeremonyTokenError(
                        "consumed ceremony token records are immutable and cannot be revoked"
                    )
                if record.get("revoked_at"):
                    safe = dict(record)
                    safe.pop("token_hash", None)
                    return safe
                record["revoked_at"] = self.now().isoformat()
                record["revoked_reason"] = reason
                self._save_record(record)
                safe = dict(record)
                safe.pop("token_hash", None)
        except DurableIOError as exc:
            raise CeremonyTokenError(f"Ceremony token lock failed: {exc}") from exc
        self._reconcile_best_effort(token_id)
        return safe

    def revoke_for_open_session(self, open_session_id: str, reason: str = "vault locked") -> int:
        if not open_session_id:
            return 0
        count = 0
        for path in sorted(self.token_dir.glob("*.json")):
            token_id = self._validated_token_id(path.stem)
            try:
                with file_lock(self._lock_path(token_id)):
                    record = self._load_record(token_id)
                    if record.get("open_session_id") != open_session_id:
                        continue
                    if record.get("consumed_at") or record.get("revoked_at"):
                        continue
                    record["revoked_at"] = self.now().isoformat()
                    record["revoked_reason"] = reason
                    self._save_record(record)
                    count += 1
            except DurableIOError as exc:
                raise CeremonyTokenError(
                    f"ceremony token lock failed during vault lock: {exc}"
                ) from exc
        if count:
            for path in sorted(self.token_dir.glob("*.json")):
                record = self._load_record(path.stem)
                if record.get("open_session_id") == open_session_id and record.get("revoked_reason") == reason:
                    self._reconcile_best_effort(str(record["token_id"]))
        return count

    def list_tokens(self, *, include_hashes: bool = False) -> List[Dict[str, Any]]:
        records: List[Dict[str, Any]] = []
        for path in sorted(self.token_dir.glob("*.json")):
            token_id = self._validated_token_id(path.stem)
            record = self._load_record(token_id)
            if not include_hashes:
                record = dict(record)
                record.pop("token_hash", None)
            records.append(record)
        records.sort(key=lambda r: (r.get("issued_at", ""), r.get("token_id", "")))
        return records
