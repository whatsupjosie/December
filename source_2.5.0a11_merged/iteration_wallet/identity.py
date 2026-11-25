"""
Iteration Wallet v2.1.8 — Local Identity / Session Interface
=============================================================

This module gives the Human Intent Gatekeeper an internal identity shape without
pretending to be OAuth, SSO, passkeys, biometrics, or a full auth provider.

Product law:
- Protected custody decisions must be tied to a session identity, not only an
  arbitrary user_id string passed into a function.
- Real authentication providers can attach later by issuing the same session
  shape.
- A session can identify a human, bot, AI assistant, tool, script, system, or
  unknown actor.
- Human custody actions still require a verified human ceremony method.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

from iteration_wallet.durable_io import (
    DurableIOError,
    atomic_json,
    exclusive_json,
    ensure_within,
    file_lock,
    strict_json_read,
    validate_storage_id,
)

class IdentityError(Exception):
    """Raised for expected identity/session failures."""


HUMAN_KIND = "human"
BOT_KINDS = {"ai_assistant", "bot", "tool", "script", "unknown"}
HUMAN_INTENT_METHODS = {
    "human_ceremony",
    "ceremony_token",
    "live_ceremony",
    "manual_ceremony",
    "camera_verification",
    "typing_challenge",
    "read_aloud_challenge",
    "head_user_approval",
}


@dataclass
class ActorIdentity:
    """One local session identity record.

    This is intentionally provider-neutral. A future real auth layer should
    produce this shape instead of letting routes trust raw actor_id strings.
    """

    actor_id: str
    actor_kind: str = "unknown"
    session_id: str = field(default_factory=lambda: uuid.uuid4().hex[:24])
    device_id: Optional[str] = None
    verified_methods: List[str] = field(default_factory=list)
    role_claims: Dict[str, Any] = field(default_factory=dict)
    issued_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: Optional[datetime] = None
    revoked_at: Optional[datetime] = None

    def __post_init__(self) -> None:
        if not isinstance(self.actor_id, str) or not self.actor_id.strip():
            raise IdentityError("actor_id must be a non-empty string")
        self.actor_id = self.actor_id.strip()
        if not isinstance(self.session_id, str) or not self.session_id:
            raise IdentityError("session_id must be a non-empty string")
        self.actor_kind = str(self.actor_kind or "unknown")
        if not isinstance(self.verified_methods, list):
            raise IdentityError("verified_methods must be a list")
        self.verified_methods = list(dict.fromkeys(str(m) for m in self.verified_methods))
        if not isinstance(self.role_claims, dict):
            raise IdentityError("role_claims must be an object")
        for attribute in ("issued_at", "expires_at", "revoked_at"):
            value = getattr(self, attribute)
            if value is not None and value.tzinfo is None:
                setattr(self, attribute, value.replace(tzinfo=timezone.utc))
        if self.expires_at is None:
            self.expires_at = self.issued_at + timedelta(hours=8)

    def is_expired(self, now: Optional[datetime] = None) -> bool:
        return bool(self.expires_at and (now or datetime.now(timezone.utc)) > self.expires_at)

    def is_revoked(self) -> bool:
        return self.revoked_at is not None

    def is_valid(self, now: Optional[datetime] = None) -> bool:
        return bool(self.actor_id and not self.is_revoked() and not self.is_expired(now))

    def is_human(self) -> bool:
        return self.actor_kind == HUMAN_KIND

    def is_bot_like(self) -> bool:
        return self.actor_kind in BOT_KINDS

    def has_verified_method(self, method: str) -> bool:
        return method in set(self.verified_methods)

    def has_any_verified_method(self, methods: Iterable[str]) -> bool:
        mine = set(self.verified_methods)
        return any(m in mine for m in methods)

    def has_human_intent_proof(self) -> bool:
        return self.is_human() and self.has_any_verified_method(HUMAN_INTENT_METHODS)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "actor_id": self.actor_id,
            "actor_kind": self.actor_kind,
            "session_id": self.session_id,
            "device_id": self.device_id,
            "verified_methods": list(self.verified_methods),
            "role_claims": dict(self.role_claims),
            "issued_at": self.issued_at.isoformat(),
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "revoked_at": self.revoked_at.isoformat() if self.revoked_at else None,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ActorIdentity":
        if not isinstance(data, dict):
            raise IdentityError("identity session record must be an object")
        required_strings = ("actor_id", "session_id", "issued_at")
        for field_name in required_strings:
            value = data.get(field_name)
            if not isinstance(value, str) or not value:
                raise IdentityError(f"identity session {field_name} must be a non-empty string")
        actor_kind = data.get("actor_kind", "unknown")
        if not isinstance(actor_kind, str) or not actor_kind:
            raise IdentityError("identity session actor_kind must be a non-empty string")
        device_id = data.get("device_id")
        if device_id is not None and not isinstance(device_id, str):
            raise IdentityError("identity session device_id must be a string or null")
        verified_methods = data.get("verified_methods", [])
        if not isinstance(verified_methods, list) or any(
            not isinstance(item, str) or not item for item in verified_methods
        ):
            raise IdentityError("identity session verified_methods must be a list of non-empty strings")
        role_claims = data.get("role_claims", {})
        if not isinstance(role_claims, dict):
            raise IdentityError("identity session role_claims must be an object")
        for timestamp_name in ("expires_at", "revoked_at"):
            value = data.get(timestamp_name)
            if value is not None and not isinstance(value, str):
                raise IdentityError(f"identity session {timestamp_name} must be a string or null")
        try:
            issued_at = datetime.fromisoformat(data["issued_at"])
            expires_at = datetime.fromisoformat(data["expires_at"]) if data.get("expires_at") else None
            revoked_at = datetime.fromisoformat(data["revoked_at"]) if data.get("revoked_at") else None
        except ValueError as exc:
            raise IdentityError("identity session contains an invalid timestamp") from exc
        return cls(
            actor_id=data["actor_id"],
            actor_kind=actor_kind,
            session_id=data["session_id"],
            device_id=device_id,
            verified_methods=list(verified_methods),
            role_claims=dict(role_claims),
            issued_at=issued_at,
            expires_at=expires_at,
            revoked_at=revoked_at,
        )


class LocalIdentityProvider:
    """Minimal local identity/session provider for private alpha.

    It stores session records under the vault root. It does not authenticate by
    itself. It is the interface real auth can bind to later.
    """

    def __init__(self, vault_root: Path):
        self.vault_root = Path(vault_root)
        self.identity_dir = self.vault_root / "identity"
        self.session_dir = self.identity_dir / "sessions"
        self.lock_dir = self.identity_dir / ".locks"
        for directory in (self.identity_dir, self.session_dir, self.lock_dir):
            try:
                ensure_within(
                    self.vault_root, directory, label="identity storage",
                    error_type=IdentityError,
                )
            except DurableIOError as exc:
                raise IdentityError(str(exc)) from exc
            if directory.is_symlink():
                raise IdentityError(
                    f"identity storage directory cannot be a symlink: {directory.name}"
                )
            directory.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _session_id(session_id: str) -> str:
        try:
            return validate_storage_id(
                "session_id", str(session_id), error_type=IdentityError
            )
        except DurableIOError as exc:
            raise IdentityError(str(exc)) from exc

    def _path(self, session_id: str) -> Path:
        return self.session_dir / f"{self._session_id(session_id)}.json"

    def _lock_path(self, session_id: str) -> Path:
        return self.lock_dir / f"{self._session_id(session_id)}.lock"

    @staticmethod
    def _write_json_atomic(path: Path, data: Dict[str, Any]) -> None:
        try:
            atomic_json(path, data)
        except DurableIOError as exc:
            raise IdentityError(f"could not persist identity session: {exc}") from exc

    def issue_session(
        self,
        actor_id: str,
        actor_kind: str,
        *,
        device_id: Optional[str] = None,
        verified_methods: Optional[Sequence[str]] = None,
        role_claims: Optional[Dict[str, Any]] = None,
        ttl_minutes: int = 480,
        session_id: Optional[str] = None,
    ) -> ActorIdentity:
        if not actor_id:
            raise IdentityError("actor_id is required")
        issued_at = datetime.now(timezone.utc)
        identity = ActorIdentity(
            actor_id=actor_id,
            actor_kind=actor_kind,
            session_id=session_id or uuid.uuid4().hex[:24],
            device_id=device_id,
            verified_methods=list(verified_methods or []),
            role_claims=dict(role_claims or {}),
            issued_at=issued_at,
            expires_at=issued_at + timedelta(minutes=max(1, int(ttl_minutes))),
        )
        path = self._path(identity.session_id)
        try:
            exclusive_json(path, identity.to_dict())
        except FileExistsError as exc:
            raise IdentityError("identity session id already exists") from exc
        except DurableIOError as exc:
            raise IdentityError(f"could not create identity session: {exc}") from exc
        return identity

    def get_session(self, session_id: str) -> Optional[ActorIdentity]:
        if not session_id:
            return None
        path = self._path(session_id)
        if not path.exists():
            return None
        try:
            data = strict_json_read(path)
        except DurableIOError as exc:
            raise IdentityError(f"Unreadable identity session: {exc}") from exc
        if not isinstance(data, dict):
            raise IdentityError("Identity session record must be a JSON object")
        if data.get("session_id") != self._session_id(session_id):
            raise IdentityError("Identity session id does not match its storage name")
        try:
            return ActorIdentity.from_dict(data)
        except Exception as exc:
            raise IdentityError(f"Invalid identity session record: {exc}") from exc

    def require_session(self, session_id: str) -> ActorIdentity:
        identity = self.get_session(session_id)
        if not identity:
            raise IdentityError("Unknown identity session")
        if identity.is_revoked():
            raise IdentityError("Identity session has been revoked")
        if identity.is_expired():
            raise IdentityError("Identity session has expired")
        return identity

    def revoke_session(self, session_id: str, reason: Optional[str] = None) -> Optional[ActorIdentity]:
        try:
            with file_lock(self._lock_path(session_id)):
                identity = self.get_session(session_id)
                if not identity:
                    return None
                if identity.revoked_at is not None:
                    return identity
                identity.revoked_at = datetime.now(timezone.utc)
                claims = dict(identity.role_claims)
                if reason:
                    claims["revoke_reason"] = reason
                identity.role_claims = claims
                self._write_json_atomic(self._path(identity.session_id), identity.to_dict())
                return identity
        except DurableIOError as exc:
            raise IdentityError(f"identity session lock failed: {exc}") from exc

    def list_sessions(self, actor_id: Optional[str] = None) -> List[Dict[str, Any]]:
        sessions: List[ActorIdentity] = []
        for p in sorted(self.session_dir.glob("*.json")):
            s = self.get_session(p.stem)
            if s is not None and (actor_id is None or s.actor_id == actor_id):
                sessions.append(s)
        sessions.sort(key=lambda s: s.issued_at)
        return [s.to_dict() for s in sessions]
