"""
Iteration Wallet v2.1.9 — Human Access, Notification, Approval, and BlackBox Request Control
================================================================================================

This module implements the human-intent notification/request layer for Iteration Wallet. Active evidence storage is provided by the canonical standalone BBX1 adapter.

Product laws implemented here:
- AI/bots/tools may REQUEST protected custody access, but may not directly fetch/open/alter custody.
- Humans / Head Users approve or deny through a logged request flow.
- User-facing alerts are capped: max 5 unread messages per recipient, max 150 characters each.
- System-wide alert burst/storage is capped at 200 notifications.
- BlackBox keeps the full detailed evidence trail even when notifications are capped.
- Repeated bot/agent request pressure is classified at 20/50/100/1000 as unusual/suspicious/intrusion/flood.
- Excessive requests are treated as possible intrusion evidence, not mere noise.

This is intentionally storage-light and local-first: JSON event records on disk,
append-ish BlackBox files, and no network/email provider dependency inside core logic.
"""

from __future__ import annotations

import json
import uuid
import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol, Sequence

from iteration_wallet.identity import ActorIdentity, IdentityError, LocalIdentityProvider
from iteration_wallet.canonical_evidence import CanonicalEvidenceAdapter
from iteration_wallet.durable_io import (
    DurableIOError,
    atomic_json,
    exclusive_json,
    file_lock,
    strict_json_read,
    validate_storage_id,
    ensure_within,
)


class EvidenceWriter(Protocol):
    blackbox_dir: Path
    request_dir: Path
    event_dir: Path
    incident_dir: Path
    chain_file: Path

    def _current_chain_state(self) -> tuple[str, int]: ...
    def current_chain_head(self) -> str: ...
    def write_event(self, event_type: str, summary: str, **extra: Any) -> Dict[str, Any]: ...
    def verify_chain(self) -> Dict[str, Any]: ...
    def update_request_incident_bundle(self, request: Dict[str, Any]) -> Dict[str, Any]: ...


class NotificationLevel(Enum):
    """Alert severity levels."""

    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"
    INTRUSION = "intrusion"


class RequestClassification(Enum):
    """BlackBox interpretation of request pressure."""

    NORMAL = "normal"
    UNUSUAL_PRESSURE = "unusual_access_pressure"          # >= 20
    SUSPICIOUS_PATTERN = "suspicious_access_pattern"      # >= 50
    PROBABLE_INTRUSION = "probable_intrusion_attempt"     # >= 100
    ACTIVE_FLOOD = "active_flood_hostile_access_event"    # >= 1000


class RequestStatus(Enum):
    """Lifecycle state for protected access requests."""

    LOGGED = "logged"
    NOTIFIED = "notified"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    DENIED = "denied"
    EXPIRED = "expired"
    FROZEN = "frozen_pending_head_user_review"
    EMERGENCY_LOCKOUT = "emergency_lockout_abuse_incident"


class ActorKind(Enum):
    """Actor type. Protected custody actions require a human ceremony."""

    HUMAN = "human"
    AI_ASSISTANT = "ai_assistant"
    BOT = "bot"
    TOOL = "tool"
    SCRIPT = "script"
    UNKNOWN = "unknown"


class NotificationError(Exception):
    """Raised for expected NotificationManager failures."""


def _persisted_string(
    data: Dict[str, Any],
    field_name: str,
    *,
    required: bool = False,
    maximum: int = 4096,
) -> Optional[str]:
    value = data.get(field_name)
    if value is None:
        if required:
            raise NotificationError(f"persisted field {field_name!r} is required")
        return None
    if not isinstance(value, str):
        raise NotificationError(f"persisted field {field_name!r} must be a string or null")
    if required and not value:
        raise NotificationError(f"persisted field {field_name!r} must not be empty")
    if len(value) > maximum or any(ord(ch) < 32 and ch not in "\t" for ch in value):
        raise NotificationError(f"persisted field {field_name!r} is unbounded or contains controls")
    return value


def _persisted_string_list(
    data: Dict[str, Any], field_name: str, *, maximum_items: int = 200
) -> List[str]:
    value = data.get(field_name, [])
    if not isinstance(value, list) or len(value) > maximum_items:
        raise NotificationError(f"persisted field {field_name!r} must be a bounded list")
    result: List[str] = []
    for item in value:
        if not isinstance(item, str) or not item or len(item) > 256:
            raise NotificationError(
                f"persisted field {field_name!r} must contain bounded non-empty strings"
            )
        result.append(item)
    return result


def _persisted_datetime(
    data: Dict[str, Any], field_name: str, *, required: bool = False
) -> Optional[datetime]:
    value = _persisted_string(data, field_name, required=required, maximum=128)
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise NotificationError(f"persisted field {field_name!r} is not an ISO timestamp") from exc
    # Releases before 2.5.0a11 persisted local timestamps without an offset.
    # Keep those records comparable while writing explicit UTC offsets from now on.
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class Notification:
    """A single short alert message to a recipient."""

    recipient_id: str
    message: str
    level: NotificationLevel
    action_url: Optional[str] = None
    notification_id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])
    created_at: datetime = field(default_factory=_utc_now)
    read_at: Optional[datetime] = None
    action_taken: Optional[str] = None
    blackbox_event_id: Optional[str] = None

    def __post_init__(self) -> None:
        if len(self.message) > NotificationManager.DEFAULT_LIMITS["per_recipient_char_limit"]:
            raise NotificationError("Message must be 150 characters or less.")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "notification_id": self.notification_id,
            "recipient_id": self.recipient_id,
            "message": self.message,
            "level": self.level.value,
            "action_url": self.action_url,
            "created_at": self.created_at.isoformat(),
            "read_at": self.read_at.isoformat() if self.read_at else None,
            "action_taken": self.action_taken,
            "blackbox_event_id": self.blackbox_event_id,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Notification":
        if not isinstance(data, dict):
            raise NotificationError("notification record must be an object")
        try:
            level_value = _persisted_string(data, "level", required=True, maximum=64)
            return cls(
                recipient_id=_persisted_string(data, "recipient_id", required=True, maximum=256),
                message=_persisted_string(data, "message", required=True, maximum=150),
                level=NotificationLevel(level_value),
                action_url=_persisted_string(data, "action_url", maximum=4096),
                notification_id=_persisted_string(data, "notification_id", required=True, maximum=128),
                created_at=_persisted_datetime(data, "created_at", required=True),
                read_at=_persisted_datetime(data, "read_at"),
                action_taken=_persisted_string(data, "action_taken", maximum=256),
                blackbox_event_id=_persisted_string(data, "blackbox_event_id", maximum=256),
            )
        except ValueError as exc:
            raise NotificationError(f"notification record contains an invalid enum: {exc}") from exc


@dataclass
class ApprovalRequest:
    """Request for Head User / authorized person approval."""

    vault_id: str
    object_id: str
    action: str
    requester_id: str
    claimed_purpose: str
    head_user_id: str
    approval_id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])
    created_at: datetime = field(default_factory=_utc_now)
    expires_at: Optional[datetime] = None
    status: RequestStatus = RequestStatus.PENDING_APPROVAL
    decision_at: Optional[datetime] = None
    decision_by: Optional[str] = None
    decision_reason: Optional[str] = None
    decision_session_id: Optional[str] = None
    request_id: Optional[str] = None

    def __post_init__(self) -> None:
        if self.expires_at is None:
            self.expires_at = self.created_at + timedelta(hours=24)

    def is_expired(self, now: Optional[datetime] = None) -> bool:
        current = now or datetime.now(self.expires_at.tzinfo)
        return current > self.expires_at

    def to_dict(self) -> Dict[str, Any]:
        return {
            "approval_id": self.approval_id,
            "vault_id": self.vault_id,
            "object_id": self.object_id,
            "action": self.action,
            "requester_id": self.requester_id,
            "claimed_purpose": self.claimed_purpose,
            "head_user_id": self.head_user_id,
            "created_at": self.created_at.isoformat(),
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "status": self.status.value,
            "decision_at": self.decision_at.isoformat() if self.decision_at else None,
            "decision_by": self.decision_by,
            "decision_reason": self.decision_reason,
            "decision_session_id": self.decision_session_id,
            "request_id": self.request_id,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ApprovalRequest":
        if not isinstance(data, dict):
            raise NotificationError("approval record must be an object")
        try:
            status_value = _persisted_string(
                data, "status", required=True, maximum=64
            )
            return cls(
                vault_id=_persisted_string(data, "vault_id", required=True, maximum=256),
                object_id=_persisted_string(data, "object_id", required=True, maximum=256),
                action=_persisted_string(data, "action", required=True, maximum=256),
                requester_id=_persisted_string(data, "requester_id", required=True, maximum=256),
                claimed_purpose=_persisted_string(data, "claimed_purpose", required=True, maximum=4096),
                head_user_id=_persisted_string(data, "head_user_id", required=True, maximum=256),
                approval_id=_persisted_string(data, "approval_id", required=True, maximum=128),
                created_at=_persisted_datetime(data, "created_at", required=True),
                expires_at=_persisted_datetime(data, "expires_at"),
                status=RequestStatus(status_value),
                decision_at=_persisted_datetime(data, "decision_at"),
                decision_by=_persisted_string(data, "decision_by", maximum=256),
                decision_reason=_persisted_string(data, "decision_reason", maximum=4096),
                decision_session_id=_persisted_string(data, "decision_session_id", maximum=256),
                request_id=_persisted_string(data, "request_id", maximum=128),
            )
        except ValueError as exc:
            raise NotificationError(f"approval record contains an invalid status: {exc}") from exc


@dataclass
class AccessRequest:
    """A protected custody access request filed by a human/bot/tool/agent."""

    vault_id: str
    object_id: str
    action: str
    requester_id: str
    claimed_purpose: str
    requester_kind: ActorKind = ActorKind.UNKNOWN
    section_id: Optional[str] = None
    tool_family: Optional[str] = None
    recipients: List[str] = field(default_factory=list)
    head_user_id: Optional[str] = None
    request_id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])
    created_at: datetime = field(default_factory=_utc_now)
    status: RequestStatus = RequestStatus.LOGGED
    classification: RequestClassification = RequestClassification.NORMAL
    matching_request_count: int = 1
    notification_ids: List[str] = field(default_factory=list)
    approval_id: Optional[str] = None
    system_action: str = "logged_only"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "request_id": self.request_id,
            "vault_id": self.vault_id,
            "section_id": self.section_id,
            "object_id": self.object_id,
            "action": self.action,
            "requester_id": self.requester_id,
            "requester_kind": self.requester_kind.value,
            "tool_family": self.tool_family,
            "claimed_purpose": self.claimed_purpose,
            "recipients": self.recipients,
            "head_user_id": self.head_user_id,
            "created_at": self.created_at.isoformat(),
            "status": self.status.value,
            "classification": self.classification.value,
            "matching_request_count": self.matching_request_count,
            "notification_ids": self.notification_ids,
            "approval_id": self.approval_id,
            "system_action": self.system_action,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AccessRequest":
        if not isinstance(data, dict):
            raise NotificationError("access request record must be an object")
        count = data.get("matching_request_count", 1)
        if isinstance(count, bool) or not isinstance(count, int) or count < 1:
            raise NotificationError("matching_request_count must be a positive integer")
        try:
            kind_value = _persisted_string(data, "requester_kind", required=True, maximum=64)
            status_value = _persisted_string(data, "status", required=True, maximum=64)
            classification_value = _persisted_string(
                data, "classification", required=True, maximum=128
            )
            return cls(
                vault_id=_persisted_string(data, "vault_id", required=True, maximum=256),
                section_id=_persisted_string(data, "section_id", maximum=256),
                object_id=_persisted_string(data, "object_id", required=True, maximum=256),
                action=_persisted_string(data, "action", required=True, maximum=256),
                requester_id=_persisted_string(data, "requester_id", required=True, maximum=256),
                requester_kind=ActorKind(kind_value),
                tool_family=_persisted_string(data, "tool_family", maximum=256),
                claimed_purpose=_persisted_string(data, "claimed_purpose", required=True, maximum=4096),
                recipients=_persisted_string_list(data, "recipients"),
                head_user_id=_persisted_string(data, "head_user_id", maximum=256),
                request_id=_persisted_string(data, "request_id", required=True, maximum=128),
                created_at=_persisted_datetime(data, "created_at", required=True),
                status=RequestStatus(status_value),
                classification=RequestClassification(classification_value),
                matching_request_count=count,
                notification_ids=_persisted_string_list(data, "notification_ids"),
                approval_id=_persisted_string(data, "approval_id", maximum=128),
                system_action=_persisted_string(data, "system_action", required=True, maximum=128),
            )
        except ValueError as exc:
            raise NotificationError(f"access request record contains an invalid enum: {exc}") from exc


class NotificationManager:
    """Manages alerts, Head User approval, BlackBox request evidence, and anti-overload limits."""

    DEFAULT_LIMITS: Dict[str, int] = {
        "per_recipient_max": 5,
        "per_recipient_char_limit": 150,
        "total_system_max": 200,
        "warning_threshold": 20,
        "suspicious_threshold": 50,
        "intrusion_threshold": 100,
        "flood_threshold": 1000,
        "request_window_minutes": 60,
    }

    BOT_KINDS = {ActorKind.AI_ASSISTANT, ActorKind.BOT, ActorKind.TOOL, ActorKind.SCRIPT, ActorKind.UNKNOWN}

    def __init__(self, vault_root: Path, blackbox: Optional[EvidenceWriter] = None):
        self.vault_root = Path(vault_root)
        self.vault_root.mkdir(parents=True, exist_ok=True)
        self.notification_dir = self.vault_root / "notifications"
        self.notification_archive_dir = self.vault_root / "notification_archive"
        self.approval_dir = self.vault_root / "approvals"
        self.identity_denial_dir = self.vault_root / "identity_denials"
        self.authority_denial_dir = self.vault_root / "authority_denials"
        self.lock_dir = self.vault_root / ".authority_locks"
        # Canonical evidence is the safe default.  The retired Wallet-native
        # recorder remains available only when a historical test or reader
        # injects it explicitly.
        self.blackbox: EvidenceWriter = blackbox or CanonicalEvidenceAdapter(self.vault_root)
        self.blackbox_dir = self.blackbox.blackbox_dir
        self.request_dir = self.blackbox.request_dir
        self.event_dir = self.blackbox.event_dir
        self.incident_dir = self.blackbox.incident_dir
        self.role_file = self.vault_root / "roles.json"
        self.chain_file = self.blackbox.chain_file
        self.identity = LocalIdentityProvider(self.vault_root)
        for directory in (
            self.notification_dir,
            self.notification_archive_dir,
            self.approval_dir,
            self.identity_denial_dir,
            self.authority_denial_dir,
            self.request_dir,
            self.event_dir,
            self.incident_dir,
            self.lock_dir,
        ):
            try:
                ensure_within(
                    self.vault_root,
                    directory,
                    label="notification authority storage",
                    error_type=NotificationError,
                )
            except DurableIOError as exc:
                raise NotificationError(str(exc)) from exc
            if directory.is_symlink():
                raise NotificationError(
                    f"notification authority directory cannot be a symlink: {directory.name}"
                )
            directory.mkdir(parents=True, exist_ok=True)
        self._limits = self._load_limits()

    # ─── basic helpers ──────────────────────────────────────────────────

    def _load_limits(self) -> Dict[str, int]:
        config_file = self.vault_root / "notification_limits.json"
        limits = dict(self.DEFAULT_LIMITS)
        if not config_file.exists():
            return limits
        try:
            configured = strict_json_read(config_file)
        except DurableIOError as exc:
            raise NotificationError(f"invalid notification limit configuration: {exc}") from exc
        if not isinstance(configured, dict):
            raise NotificationError("notification limit configuration must be an object")
        for key, value in configured.items():
            if key not in limits:
                continue
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise NotificationError(f"notification limit {key} must be a positive integer")
            # Configuration may tighten a constitutional cap, never loosen it.
            limits[key] = min(limits[key], value)
        return limits

    @staticmethod
    def _now() -> datetime:
        return _utc_now()

    @staticmethod
    def _shorten(text: str, limit: int = 150) -> str:
        text = " ".join(str(text).split())
        if len(text) <= limit:
            return text
        return text[: max(0, limit - 1)].rstrip() + "…"

    @staticmethod
    def _write_json_atomic(path: Path, data: Dict[str, Any]) -> None:
        try:
            atomic_json(path, data)
        except (DurableIOError, OSError, ValueError, TypeError) as exc:
            raise NotificationError(f"cannot durably write {path.name}: {exc}") from exc

    @staticmethod
    def _write_json_exclusive(path: Path, data: Dict[str, Any]) -> None:
        try:
            exclusive_json(path, data)
        except FileExistsError:
            raise
        except (DurableIOError, OSError, ValueError, TypeError) as exc:
            raise NotificationError(f"cannot durably create {path.name}: {exc}") from exc

    @staticmethod
    def _read_json_object(path: Path, *, label: str) -> Dict[str, Any]:
        try:
            data = strict_json_read(path)
        except DurableIOError as exc:
            raise NotificationError(f"unreadable {label}: {exc}") from exc
        if not isinstance(data, dict):
            raise NotificationError(f"{label} must be a JSON object")
        return data

    @staticmethod
    def _storage_id(name: str, value: str) -> str:
        try:
            return validate_storage_id(name, value, error_type=NotificationError)
        except DurableIOError as exc:
            raise NotificationError(str(exc)) from exc

    def _record_path(self, directory: Path, *, name: str, value: str) -> Path:
        record_id = self._storage_id(name, str(value))
        path = directory / f"{record_id}.json"
        try:
            ensure_within(
                directory,
                path,
                label=f"{name} storage",
                error_type=NotificationError,
            )
        except DurableIOError as exc:
            raise NotificationError(str(exc)) from exc
        if path.is_symlink():
            raise NotificationError(f"{name} storage path cannot be a symlink")
        return path

    def _record_lock(self, category: str, record_id: str) -> Path:
        category_id = self._storage_id("lock category", category)
        record_id = self._storage_id("lock record id", record_id)
        return self.lock_dir / f"{category_id}-{record_id}.lock"

    def _canonical_json(self, data: Dict[str, Any]) -> str:
        return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

    def _current_chain_state(self) -> tuple[str, int]:
        return self.blackbox._current_chain_state()

    def _current_chain_head(self) -> str:
        return self.blackbox.current_chain_head()

    def _blackbox_event(self, event_type: str, summary: str, **extra: Any) -> Dict[str, Any]:
        """Compatibility wrapper around the standalone BlackBox module."""
        return self.blackbox.write_event(event_type, summary, **extra)

    def verify_blackbox_chain(self) -> Dict[str, Any]:
        """Verify the shared local BlackBox hash chain."""
        return self.blackbox.verify_chain()

    @staticmethod
    def _observation_event_id(stage_key: str) -> str:
        return hashlib.sha256(stage_key.encode("utf-8")).hexdigest()[:32]

    def _write_observation(
        self,
        *,
        stage_key: str,
        event_type: str,
        summary: str,
        payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        return self.blackbox.write_event(
            event_type,
            summary,
            event_id=self._observation_event_id(stage_key),
            stage_key=stage_key,
            **payload,
        )

    def _record_identity_denial(self, session_id: str, reason: str) -> Dict[str, Any]:
        denial_id = uuid.uuid4().hex
        record = {
            "denial_id": denial_id,
            "session_id": str(session_id),
            "reason": str(reason),
            "denied_at": self._now().isoformat(),
        }
        self._write_json_exclusive(self.identity_denial_dir / f"{denial_id}.json", record)
        return record

    def list_identity_denials(self, session_id: Optional[str] = None) -> List[Dict[str, Any]]:
        records: List[Dict[str, Any]] = []
        for path in sorted(self.identity_denial_dir.glob("*.json")):
            denial_id = self._storage_id("identity denial id", path.stem)
            data = self._read_json_object(path, label="identity denial")
            if data.get("denial_id") != denial_id:
                raise NotificationError("identity denial id does not match its storage name")
            if session_id is None or data.get("session_id") == session_id:
                records.append(data)
        records.sort(key=lambda item: (str(item.get("denied_at") or ""), str(item.get("denial_id") or "")))
        return records

    def _record_authority_denial(
        self,
        denial_type: str,
        summary: str,
        **details: Any,
    ) -> Dict[str, Any]:
        denial_id = uuid.uuid4().hex
        record = {
            "denial_id": denial_id,
            "denial_type": denial_type,
            "summary": summary,
            "created_at": self._now().isoformat(),
            **details,
        }
        self._write_json_exclusive(self.authority_denial_dir / f"{denial_id}.json", record)
        return record

    def list_authority_denials(self) -> List[Dict[str, Any]]:
        records: List[Dict[str, Any]] = []
        for path in sorted(self.authority_denial_dir.glob("*.json")):
            denial_id = self._storage_id("authority denial id", path.stem)
            data = self._read_json_object(path, label="authority denial")
            if data.get("denial_id") != denial_id:
                raise NotificationError("authority denial id does not match its storage name")
            records.append(data)
        records.sort(key=lambda item: (str(item.get("created_at") or ""), str(item.get("denial_id") or "")))
        return records

    @staticmethod
    def _authority_denial_payload(denial: Dict[str, Any]) -> Dict[str, Any]:
        """Return denial fields safe for ``write_event(..., summary=...)``.

        ``summary`` is a recorder argument, not evidence payload. Keeping one
        authoritative copy prevents duplicate-key call failures and keeps
        immediate delivery identical to restart reconciliation.
        """
        return {key: value for key, value in denial.items() if key != "summary"}

    @staticmethod
    def _access_request_observation_payload(request: AccessRequest) -> Dict[str, Any]:
        return {
            "request_id": request.request_id,
            "vault_id": request.vault_id,
            "section_id": request.section_id,
            "object_id": request.object_id,
            "action": request.action,
            "requester_id": request.requester_id,
            "requester_kind": request.requester_kind.value,
            "tool_family": request.tool_family,
            "claimed_purpose": request.claimed_purpose,
            "recipients": list(request.recipients),
            "head_user_id": request.head_user_id,
            "created_at": request.created_at.isoformat(),
            "classification": request.classification.value,
            "matching_request_count": request.matching_request_count,
        }

    @staticmethod
    def _approval_created_payload(approval: ApprovalRequest) -> Dict[str, Any]:
        return {
            "approval_id": approval.approval_id,
            "vault_id": approval.vault_id,
            "object_id": approval.object_id,
            "action": approval.action,
            "requester_id": approval.requester_id,
            "claimed_purpose": approval.claimed_purpose,
            "head_user_id": approval.head_user_id,
            "request_id": approval.request_id,
            "created_at": approval.created_at.isoformat(),
            "expires_at": approval.expires_at.isoformat() if approval.expires_at else None,
        }

    @staticmethod
    def _approval_decision_payload(approval: ApprovalRequest) -> Dict[str, Any]:
        return {
            "approval_id": approval.approval_id,
            "vault_id": approval.vault_id,
            "object_id": approval.object_id,
            "action": approval.action,
            "status": approval.status.value,
            "decision_at": approval.decision_at.isoformat() if approval.decision_at else None,
            "decision_by": approval.decision_by,
            "decision_reason": approval.decision_reason,
            "request_id": approval.request_id,
            "decision_session_id": approval.decision_session_id,
        }

    def _observe_best_effort(
        self,
        *,
        stage_key: str,
        event_type: str,
        summary: str,
        payload: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        try:
            return self._write_observation(
                stage_key=stage_key,
                event_type=event_type,
                summary=summary,
                payload=payload,
            )
        except Exception:
            return None

    def list_role_history(self, vault_id: Optional[str] = None) -> List[Dict[str, Any]]:
        history = list(self._load_roles().get("history") or [])
        if vault_id is not None:
            history = [item for item in history if item.get("vault_id") == vault_id]
        history.sort(key=lambda item: (str(item.get("configured_at") or ""), str(item.get("change_id") or "")))
        return history

    def reconcile_request_projections(self) -> Dict[str, Any]:
        """Repair access-request projections from durable approval records.

        Approval records are the terminal decision authority.  The linked
        access-request ``approval_id`` and terminal ``status`` are projections
        that may lag after a crash or storage interruption.  Conflicting
        approval links are never guessed through; they are reported and left
        untouched for human review.
        """
        report: Dict[str, Any] = {"checked": 0, "repaired": 0, "errors": []}
        approvals_by_request: Dict[str, ApprovalRequest] = {}
        conflicts: set[str] = set()

        for path in sorted(self.approval_dir.glob("*.json")):
            try:
                approval = self.get_approval_request(path.stem)
            except Exception as exc:
                report["errors"].append(
                    {"approval_id": path.stem, "error": f"{type(exc).__name__}: {exc}"[:500]}
                )
                continue
            if approval is None or not approval.request_id:
                continue
            request_id = self._storage_id("request_id", str(approval.request_id))
            report["checked"] += 1
            previous = approvals_by_request.get(request_id)
            if previous is not None and previous.approval_id != approval.approval_id:
                conflicts.add(request_id)
                report["errors"].append(
                    {
                        "request_id": request_id,
                        "error": "multiple approval records reference the same access request",
                        "approval_ids": sorted([previous.approval_id, approval.approval_id]),
                    }
                )
                continue
            approvals_by_request[request_id] = approval

        terminal = {RequestStatus.APPROVED, RequestStatus.DENIED, RequestStatus.EXPIRED}
        for request_id, approval in approvals_by_request.items():
            if request_id in conflicts:
                continue
            try:
                with file_lock(self._record_lock("request", request_id)):
                    request = self.get_access_request(request_id)
                    if request is None:
                        raise NotificationError(
                            f"approval {approval.approval_id} references missing access request {request_id}"
                        )
                    if request.approval_id not in (None, approval.approval_id):
                        raise NotificationError(
                            f"access request {request_id} references approval {request.approval_id}, "
                            f"not {approval.approval_id}"
                        )
                    changed = False
                    if request.approval_id is None:
                        request.approval_id = approval.approval_id
                        changed = True
                    if approval.status in terminal and request.status is not approval.status:
                        request.status = approval.status
                        changed = True
                    if changed:
                        self._save_access_request(request)
                        report["repaired"] += 1
            except Exception as exc:
                report["errors"].append(
                    {
                        "request_id": request_id,
                        "approval_id": approval.approval_id,
                        "error": f"{type(exc).__name__}: {exc}"[:500],
                    }
                )
        return report

    @staticmethod
    def _empty_observation_reconciliation_report() -> Dict[str, Any]:
        return {"checked": 0, "delivered": 0, "errors": []}

    def _deliver_reconciliation_observation(
        self,
        report: Dict[str, Any],
        *,
        stage_key: str,
        event_type: str,
        summary: str,
        payload: Dict[str, Any],
    ) -> None:
        report["checked"] += 1
        try:
            self._write_observation(
                stage_key=stage_key,
                event_type=event_type,
                summary=summary,
                payload=payload,
            )
            report["delivered"] += 1
        except Exception as exc:
            report["errors"].append(
                {"stage_key": stage_key, "error": f"{type(exc).__name__}: {exc}"[:500]}
            )

    def reconcile_identity_observations(self) -> Dict[str, Any]:
        """Idempotently observe durable local identity-session records."""
        report = self._empty_observation_reconciliation_report()
        for identity_data in self.identity.list_sessions():
            session_id = str(identity_data["session_id"])
            public_identity = dict(identity_data)
            self._deliver_reconciliation_observation(
                report,
                stage_key=f"identity:{session_id}:ISSUED",
                event_type="IDENTITY_SESSION_ISSUED",
                summary=(
                    f"Identity session issued for {identity_data.get('actor_id')} "
                    f"as {identity_data.get('actor_kind')}"
                ),
                payload={
                    "session_id": session_id,
                    "identity": public_identity,
                    "issued_at": identity_data.get("issued_at"),
                },
            )
            if identity_data.get("revoked_at"):
                self._deliver_reconciliation_observation(
                    report,
                    stage_key=f"identity:{session_id}:REVOKED",
                    event_type="IDENTITY_SESSION_REVOKED",
                    summary=f"Identity session revoked for {identity_data.get('actor_id')}",
                    payload={
                        "session_id": session_id,
                        "actor_id": identity_data.get("actor_id"),
                        "revoked_at": identity_data.get("revoked_at"),
                        "reason": (identity_data.get("role_claims") or {}).get("revoke_reason"),
                    },
                )
        return report

    def reconcile_role_observations(self) -> Dict[str, Any]:
        """Idempotently observe durable vault-role history."""
        report = self._empty_observation_reconciliation_report()
        for change in self.list_role_history():
            change_id = str(change["change_id"])
            self._deliver_reconciliation_observation(
                report,
                stage_key=f"roles:{change_id}",
                event_type="VAULT_ROLES_CONFIGURED",
                summary=f"Roles configured for vault {change.get('vault_id')}",
                payload={
                    "change_id": change_id,
                    "vault_id": change.get("vault_id"),
                    "configured_at": change.get("configured_at"),
                    "vault_roles": dict(change.get("vault_roles") or {}),
                },
            )
        return report

    def reconcile_request_observations(self) -> Dict[str, Any]:
        """Idempotently observe protected-access request records."""
        report = self._empty_observation_reconciliation_report()
        for path in sorted(self.request_dir.glob("*.json")):
            request = self.get_access_request(path.stem)
            if request is None:
                continue
            self._deliver_reconciliation_observation(
                report,
                stage_key=f"request:{request.request_id}:LOGGED",
                event_type="PROTECTED_ACCESS_REQUEST_LOGGED",
                summary=(
                    f"{request.requester_kind.value} requested {request.action} on "
                    f"{request.object_id}; {request.classification.value}"
                ),
                payload=self._access_request_observation_payload(request),
            )
        return report

    def reconcile_approval_observations(self) -> Dict[str, Any]:
        """Idempotently observe Head User approval records and decisions."""
        report = self._empty_observation_reconciliation_report()
        for path in sorted(self.approval_dir.glob("*.json")):
            approval = self.get_approval_request(path.stem)
            if approval is None:
                continue
            self._deliver_reconciliation_observation(
                report,
                stage_key=f"approval:{approval.approval_id}:CREATED",
                event_type="HEAD_USER_APPROVAL_CREATED",
                summary=f"Head User approval requested for {approval.action} on {approval.object_id}",
                payload=self._approval_created_payload(approval),
            )
            if approval.status is not RequestStatus.PENDING_APPROVAL:
                self._deliver_reconciliation_observation(
                    report,
                    stage_key=f"approval:{approval.approval_id}:DECISION:{approval.status.value}",
                    event_type="HEAD_USER_APPROVAL_DECISION",
                    summary=f"Approval {approval.status.value}: {approval.action} on {approval.object_id}",
                    payload=self._approval_decision_payload(approval),
                )
        return report

    def reconcile_denial_observations(self) -> Dict[str, Any]:
        """Idempotently observe identity and protected-authority denials."""
        report = self._empty_observation_reconciliation_report()
        for denial in self.list_identity_denials():
            denial_id = str(denial["denial_id"])
            self._deliver_reconciliation_observation(
                report,
                stage_key=f"identity-denial:{denial_id}",
                event_type="IDENTITY_SESSION_INVALID",
                summary="Invalid identity session rejected",
                payload=dict(denial),
            )
        for denial in self.list_authority_denials():
            denial_id = str(denial["denial_id"])
            self._deliver_reconciliation_observation(
                report,
                stage_key=f"authority-denial:{denial_id}",
                event_type=str(denial["denial_type"]),
                summary=str(denial.get("summary") or denial["denial_type"]),
                payload=self._authority_denial_payload(denial),
            )
        return report

    def reconcile_incident_observations(self) -> Dict[str, Any]:
        """Idempotently observe durable request-pressure incident bundles."""
        report = self._empty_observation_reconciliation_report()
        for path in sorted(self.incident_dir.glob("*.json")):
            incident_id = self._storage_id("incident id", path.stem)
            incident = self._read_json_object(path, label=f"incident bundle {incident_id}")
            if incident.get("incident_id") != incident_id:
                raise NotificationError("incident bundle id does not match its storage name")
            updates = incident.get("updates") or []
            if not isinstance(updates, list):
                raise NotificationError("incident bundle updates must be a list")
            if not updates:
                updates = [{
                    "update_id": f"legacy-{incident_id}",
                    "updated_at": incident.get("updated_at"),
                    "classification": incident.get("classification"),
                    "matching_request_count": incident.get("matching_request_count"),
                    "object_id": incident.get("object_id"),
                    "request_id": None,
                }]
            for update in updates:
                update_id = str(update.get("update_id") or "")
                self._storage_id("incident update id", update_id)
                self._deliver_reconciliation_observation(
                    report,
                    stage_key=f"incident:{incident_id}:{update_id}",
                    event_type="REQUEST_INCIDENT_BUNDLE_UPDATED",
                    summary="Repeated protected access pressure recorded",
                    payload={
                        "incident_id": incident_id,
                        "update_id": update_id,
                        "request_id": update.get("request_id"),
                        "updated_at": update.get("updated_at"),
                        "classification": update.get("classification"),
                        "count": update.get("matching_request_count"),
                        "object_id": update.get("object_id"),
                    },
                )
        return report

    def reconcile_authority_observations(self) -> Dict[str, Any]:
        """Reconcile every durable authority-adjacent projection and observation.

        The category reports are exposed independently so startup can prove
        which recovery stages ran instead of collapsing them into one vague
        success flag.  The aggregate fields remain for existing callers.
        """
        projection_report = self.reconcile_request_projections()
        categories = {
            "identity": self.reconcile_identity_observations(),
            "roles": self.reconcile_role_observations(),
            "requests": self.reconcile_request_observations(),
            "approvals": self.reconcile_approval_observations(),
            "denials": self.reconcile_denial_observations(),
            "incidents": self.reconcile_incident_observations(),
        }
        report: Dict[str, Any] = {
            "checked": sum(int(item.get("checked", 0)) for item in categories.values()),
            "delivered": sum(int(item.get("delivered", 0)) for item in categories.values()),
            "request_projections_checked": projection_report["checked"],
            "request_projections_repaired": projection_report["repaired"],
            "errors": list(projection_report["errors"]),
            "categories": categories,
        }
        for category_report in categories.values():
            report["errors"].extend(category_report.get("errors") or [])
        return report

    def _reconcile_authority_best_effort(self) -> None:
        self.reconcile_authority_observations()

    # ─── local identity / session interface ───────────────────────────────

    def issue_identity_session(
        self,
        actor_id: str,
        actor_kind: ActorKind | str,
        *,
        device_id: Optional[str] = None,
        verified_methods: Optional[Sequence[str]] = None,
        role_claims: Optional[Dict[str, Any]] = None,
        ttl_minutes: int = 480,
        session_id: Optional[str] = None,
    ) -> ActorIdentity:
        kind = actor_kind.value if isinstance(actor_kind, ActorKind) else str(actor_kind)
        identity = self.identity.issue_session(
            actor_id=actor_id,
            actor_kind=kind,
            device_id=device_id,
            verified_methods=verified_methods,
            role_claims=role_claims,
            ttl_minutes=ttl_minutes,
            session_id=session_id,
        )
        self._reconcile_authority_best_effort()
        return identity

    def get_identity_session(self, session_id: str) -> Optional[ActorIdentity]:
        return self.identity.get_session(session_id)

    def require_identity_session(self, session_id: str) -> ActorIdentity:
        try:
            return self.identity.require_session(session_id)
        except IdentityError as e:
            self._record_identity_denial(session_id, str(e))
            self._reconcile_authority_best_effort()
            raise

    def revoke_identity_session(self, session_id: str, reason: Optional[str] = None) -> Optional[ActorIdentity]:
        identity = self.identity.revoke_session(session_id, reason)
        if identity:
            self._reconcile_authority_best_effort()
        return identity

    # ─── role / authority management ───────────────────────────────────────

    def _load_roles(self) -> Dict[str, Any]:
        if not self.role_file.exists():
            return {"vaults": {}, "history": []}
        data = self._read_json_object(self.role_file, label="role configuration")
        vaults = data.get("vaults")
        if not isinstance(vaults, dict):
            raise NotificationError("role configuration field 'vaults' must be an object")
        for vault_id, record in vaults.items():
            if not isinstance(vault_id, str) or not isinstance(record, dict):
                raise NotificationError("role configuration contains an invalid vault record")
            head = record.get("head_user_id")
            if head is not None and not isinstance(head, str):
                raise NotificationError("role configuration head_user_id must be a string")
            for field_name in ("admins", "authorized_users", "authorized_agents", "allowed_fallbacks"):
                values = record.get(field_name, [])
                if not isinstance(values, list) or any(not isinstance(item, str) for item in values):
                    raise NotificationError(f"role configuration {field_name} must be a list of strings")
        history = data.setdefault("history", [])
        if not isinstance(history, list):
            raise NotificationError("role configuration history must be a list")
        for item in history:
            if not isinstance(item, dict):
                raise NotificationError("role configuration history contains a non-object")
            self._storage_id("role change id", str(item.get("change_id") or ""))
            if not isinstance(item.get("vault_roles"), dict):
                raise NotificationError("role history vault_roles must be an object")
        return data

    def configure_vault_roles(
        self,
        vault_id: str,
        head_user_id: str,
        admins: Optional[Sequence[str]] = None,
        authorized_users: Optional[Sequence[str]] = None,
        authorized_agents: Optional[Sequence[str]] = None,
        allowed_fallbacks: Optional[Sequence[str]] = None,
    ) -> Dict[str, Any]:
        if not isinstance(vault_id, str) or not vault_id:
            raise NotificationError("vault_id is required for role configuration")
        if not isinstance(head_user_id, str) or not head_user_id:
            raise NotificationError("head_user_id is required for role configuration")
        vault = {
            "vault_id": vault_id,
            "head_user_id": head_user_id,
            "admins": list(dict.fromkeys(admins or [])),
            "authorized_users": list(dict.fromkeys(authorized_users or [])),
            "authorized_agents": list(dict.fromkeys(authorized_agents or [])),
            "allowed_fallbacks": list(dict.fromkeys(allowed_fallbacks or [])),
            "updated_at": self._now().isoformat(),
        }
        change = {
            "change_id": uuid.uuid4().hex,
            "vault_id": vault_id,
            "configured_at": vault["updated_at"],
            "vault_roles": dict(vault),
        }
        with file_lock(self._record_lock("roles", "global")):
            roles = self._load_roles()
            roles.setdefault("vaults", {})[vault_id] = vault
            roles.setdefault("history", []).append(change)
            self._write_json_atomic(self.role_file, roles)
        self._reconcile_authority_best_effort()
        return vault

    def get_vault_roles(self, vault_id: str) -> Dict[str, Any]:
        return self._load_roles().get("vaults", {}).get(vault_id, {})

    def is_head_user_or_admin(self, vault_id: str, user_id: str, fallback_head_user_id: Optional[str] = None) -> bool:
        roles = self.get_vault_roles(vault_id)
        head = roles.get("head_user_id") or fallback_head_user_id
        admins = set(roles.get("admins") or [])
        return bool(user_id and (user_id == head or user_id in admins))

    # ─── notification management ────────────────────────────────────────

    def _notification_path(self, notification_id: str) -> Path:
        return self._record_path(
            self.notification_dir, name="notification_id", value=notification_id
        )

    def _save_notification(self, notification: Notification, *, create: bool = False) -> None:
        path = self._notification_path(notification.notification_id)
        if create:
            try:
                self._write_json_exclusive(path, notification.to_dict())
            except FileExistsError as exc:
                raise NotificationError(
                    f"notification_id already exists: {notification.notification_id}"
                ) from exc
            return
        self._write_json_atomic(path, notification.to_dict())

    def _load_notification_file(self, path: Path) -> Notification:
        notification_id = self._storage_id("notification_id", path.stem)
        expected = self._notification_path(notification_id)
        if path.resolve() != expected.resolve():
            raise NotificationError("notification path does not match its storage id")
        if path.is_symlink():
            raise NotificationError(
                f"notification storage path cannot be a symlink: {path.name}"
            )
        data = self._read_json_object(path, label=f"notification {notification_id}")
        if data.get("notification_id") != notification_id:
            raise NotificationError(
                f"notification {notification_id} does not match its storage name"
            )
        try:
            return Notification.from_dict(data)
        except Exception as exc:
            raise NotificationError(
                f"invalid notification {notification_id}: {exc}"
            ) from exc

    def _archive_notification(self, notification: Notification, reason: str) -> bool:
        """Move a user-facing alert out of the active inbox without destroying it."""
        path = self._notification_path(notification.notification_id)
        if not path.exists():
            return False
        notification.read_at = notification.read_at or self._now()
        notification.action_taken = reason
        self._save_notification(notification)
        destination = self.notification_archive_dir / path.name
        if destination.exists():
            destination = self.notification_archive_dir / (
                f"{notification.notification_id}-{uuid.uuid4().hex[:8]}.json"
            )
        try:
            ensure_within(
                self.notification_archive_dir,
                destination,
                label="notification archive storage",
                error_type=NotificationError,
            )
        except DurableIOError as exc:
            raise NotificationError(str(exc)) from exc
        if destination.is_symlink():
            raise NotificationError("notification archive destination cannot be a symlink")
        path.rename(destination)
        return True

    def _get_all_notifications(self) -> List[Notification]:
        notifications = [
            self._load_notification_file(path)
            for path in sorted(self.notification_dir.glob("*.json"))
        ]
        return sorted(notifications, key=lambda item: item.created_at)

    def _get_recipient_notifications(self, recipient_id: str, unread_only: bool = True) -> List[Notification]:
        notes = [n for n in self._get_all_notifications() if n.recipient_id == recipient_id]
        if unread_only:
            notes = [n for n in notes if n.read_at is None]
        return notes

    def _priority_value(self, level: NotificationLevel) -> int:
        return {
            NotificationLevel.INFO: 1,
            NotificationLevel.WARNING: 2,
            NotificationLevel.CRITICAL: 3,
            NotificationLevel.INTRUSION: 4,
        }[level]

    def _make_room_for_priority_notification(
        self,
        recipient_id: str,
        level: NotificationLevel,
        *,
        notifications: Optional[List[Notification]] = None,
    ) -> bool:
        """Suppress lower-priority alerts using one validated store snapshot.

        ``create_notification`` passes the strict snapshot it loaded while
        holding the global creation lock.  Callers outside that transaction may
        omit it and receive a fresh strict read.  This preserves fail-closed
        record validation without repeatedly rescanning the directory.
        """
        if self._priority_value(level) < self._priority_value(NotificationLevel.CRITICAL):
            return False
        all_notes = notifications if notifications is not None else self._get_all_notifications()
        changed = False
        unread = [
            note
            for note in all_notes
            if note.recipient_id == recipient_id and note.read_at is None
        ]
        if len(unread) >= self._limits["per_recipient_max"]:
            lower = [n for n in unread if self._priority_value(n.level) < self._priority_value(level)]
            if lower:
                victim = min(lower, key=lambda n: (self._priority_value(n.level), n.created_at))
                victim.read_at = self._now()
                victim.action_taken = f"auto-suppressed for {level.value} alert"
                self._save_notification(victim)
                changed = True
        if len(all_notes) >= self._limits["total_system_max"]:
            lower = [n for n in all_notes if self._priority_value(n.level) < self._priority_value(level)]
            if lower:
                victim = min(lower, key=lambda n: (self._priority_value(n.level), n.created_at))
                archived = self._archive_notification(
                    victim,
                    f"auto-suppressed for {level.value} alert; archived and preserved",
                )
                if archived and notifications is not None:
                    notifications[:] = [
                        note
                        for note in notifications
                        if note.notification_id != victim.notification_id
                    ]
                changed = archived or changed
        return changed

    def create_notification(
        self,
        recipient_id: str,
        message: str,
        level: NotificationLevel,
        action_url: Optional[str] = None,
        blackbox_event_id: Optional[str] = None,
    ) -> Optional[Notification]:
        """Create a short user-facing alert if durable limits allow it.

        Limit evaluation and record creation share one cross-process lock, so
        cooperating runtimes cannot overfill the same inbox or global store by
        racing through check-then-write.
        """
        message = " ".join(str(message).split())
        if len(message) > self._limits["per_recipient_char_limit"]:
            return None
        with file_lock(self._record_lock("notification", "global")):
            # One strict coherent snapshot per locked creation transaction.
            # Every record is still freshly read and validated; the snapshot is
            # never retained after this transaction or shared across processes.
            all_notes = self._get_all_notifications()

            def recipient_unread_count() -> int:
                return sum(
                    1
                    for note in all_notes
                    if note.recipient_id == recipient_id and note.read_at is None
                )

            if recipient_unread_count() >= self._limits["per_recipient_max"]:
                self._make_room_for_priority_notification(
                    recipient_id,
                    level,
                    notifications=all_notes,
                )
            if recipient_unread_count() >= self._limits["per_recipient_max"]:
                return None
            if len(all_notes) >= self._limits["total_system_max"]:
                self._make_room_for_priority_notification(
                    recipient_id,
                    level,
                    notifications=all_notes,
                )
            if len(all_notes) >= self._limits["total_system_max"]:
                return None
            notification = Notification(
                recipient_id=recipient_id,
                message=message,
                level=level,
                action_url=action_url,
                blackbox_event_id=blackbox_event_id,
            )
            self._save_notification(notification, create=True)
            return notification

    def create_notification_burst(
        self,
        recipient_ids: Sequence[str],
        messages: Sequence[str],
        level: NotificationLevel,
        action_url: Optional[str] = None,
        blackbox_event_id: Optional[str] = None,
    ) -> List[Notification]:
        """Send up to five short messages per recipient, respecting global 200 cap."""
        created: List[Notification] = []
        clipped = [self._shorten(m, self._limits["per_recipient_char_limit"]) for m in list(messages)[: self._limits["per_recipient_max"]]]
        for recipient_id in dict.fromkeys(recipient_ids):  # stable de-dup
            for msg in clipped:
                n = self.create_notification(recipient_id, msg, level, action_url, blackbox_event_id)
                if n:
                    created.append(n)
        return created

    def get_inbox(self, recipient_id: str) -> List[Dict[str, Any]]:
        return [n.to_dict() for n in self._get_recipient_notifications(recipient_id, unread_only=True)]

    def mark_notification_read(self, notification_id: str) -> bool:
        notification_id = self._storage_id("notification_id", str(notification_id))
        with file_lock(self._record_lock("notification-record", notification_id)):
            path = self._notification_path(notification_id)
            if not path.exists():
                return False
            notification = self._load_notification_file(path)
            notification.read_at = self._now()
            self._save_notification(notification)
            return True

    def record_notification_action(self, notification_id: str, action: str) -> bool:
        notification_id = self._storage_id("notification_id", str(notification_id))
        with file_lock(self._record_lock("notification-record", notification_id)):
            path = self._notification_path(notification_id)
            if not path.exists():
                return False
            notification = self._load_notification_file(path)
            notification.action_taken = action
            self._save_notification(notification)
            return True

    # ─── approval requests ──────────────────────────────────────────────

    def _approval_path(self, approval_id: str) -> Path:
        return self._record_path(self.approval_dir, name="approval_id", value=approval_id)

    def _save_approval_request(self, approval: ApprovalRequest, *, create: bool = False) -> None:
        path = self._approval_path(approval.approval_id)
        if create:
            try:
                self._write_json_exclusive(path, approval.to_dict())
            except FileExistsError as exc:
                raise NotificationError(
                    f"approval_id already exists: {approval.approval_id}"
                ) from exc
            return
        self._write_json_atomic(path, approval.to_dict())

    def get_approval_request(self, approval_id: str) -> Optional[ApprovalRequest]:
        approval_id = self._storage_id("approval_id", str(approval_id))
        path = self._approval_path(approval_id)
        if not path.exists():
            return None
        data = self._read_json_object(path, label=f"approval record {approval_id}")
        if data.get("approval_id") != approval_id:
            raise NotificationError(
                f"approval record {approval_id} does not match its storage name"
            )
        try:
            return ApprovalRequest.from_dict(data)
        except Exception as exc:
            raise NotificationError(f"invalid approval record {approval_id}: {exc}") from exc

    def create_approval_request(
        self,
        vault_id: str,
        object_id: str,
        action: str,
        requester_id: str,
        claimed_purpose: str,
        head_user_id: str,
        request_id: Optional[str] = None,
    ) -> ApprovalRequest:
        approval = ApprovalRequest(
            vault_id=vault_id,
            object_id=object_id,
            action=action,
            requester_id=requester_id,
            claimed_purpose=claimed_purpose,
            head_user_id=head_user_id,
            request_id=request_id,
        )
        self._save_approval_request(approval, create=True)
        event = self._observe_best_effort(
            stage_key=f"approval:{approval.approval_id}:CREATED",
            event_type="HEAD_USER_APPROVAL_CREATED",
            summary=f"Head User approval requested for {action} on {object_id}",
            payload=self._approval_created_payload(approval),
        )
        message = self._shorten(f"Approval needed: {action} on {object_id[:8]}… Reply APPROVE, DENY, or REVIEW.")
        self.create_notification(
            head_user_id,
            message,
            NotificationLevel.WARNING,
            action_url=f"/approvals/{approval.approval_id}",
            blackbox_event_id=event.get("event_id") if event else None,
        )
        return approval

    def get_pending_approvals(self, head_user_id: str) -> List[Dict[str, Any]]:
        approvals = []
        for path in sorted(self.approval_dir.glob("*.json")):
            approval = self.get_approval_request(path.stem)
            if (
                approval is not None
                and approval.head_user_id == head_user_id
                and approval.status == RequestStatus.PENDING_APPROVAL
                and not approval.is_expired()
            ):
                approvals.append(approval.to_dict())
        return sorted(approvals, key=lambda item: item["created_at"])

    def submit_approval_decision(
        self,
        approval_id: str,
        approved: bool,
        decision_by: Optional[str] = None,
        reason: Optional[str] = None,
        decision_session_id: Optional[str] = None,
    ) -> Optional[ApprovalRequest]:
        approval_id = self._storage_id("approval_id", str(approval_id))
        with file_lock(self._record_lock("approval", approval_id)):
            approval = self.get_approval_request(approval_id)
            if not approval:
                return None
            if approval.status is not RequestStatus.PENDING_APPROVAL:
                raise NotificationError(
                    f"approval {approval_id} is already terminal: {approval.status.value}"
                )

            # decision_session_id is mandatory (fixed: previously an omitted session
            # silently fell back to trusting a bare client-supplied decision_by
            # string, checked only against the role list -- same bug shape as the
            # vault/open gap: an optional auth parameter that degrades instead of
            # failing closed when omitted). No caller may bypass identity
            # verification by leaving this out.
            if not decision_session_id:
                denial = self._record_authority_denial(
                    "UNAUTHORIZED_APPROVAL_DECISION_BLOCKED",
                    f"Approval decision blocked: no identity session supplied for {approval.action} on {approval.object_id}",
                    approval_id=approval.approval_id,
                    attempted_decision_by=decision_by,
                    decision_session_id=decision_session_id,
                    reason="decision_session_id is required; unauthenticated decision_by is no longer accepted",
                )
                self._observe_best_effort(
                    stage_key=f"authority-denial:{denial['denial_id']}",
                    event_type=denial["denial_type"],
                    summary=denial["summary"],
                    payload=self._authority_denial_payload(denial),
                )
                raise NotificationError(
                    "Valid Head User/admin identity session required for approval decision."
                )

            try:
                decision_identity: ActorIdentity = self.require_identity_session(decision_session_id)
            except IdentityError as exc:
                denial = self._record_authority_denial(
                    "UNAUTHORIZED_APPROVAL_DECISION_BLOCKED",
                    f"Approval decision blocked: invalid session for {approval.action} on {approval.object_id}",
                    approval_id=approval.approval_id,
                    attempted_decision_by=decision_by,
                    decision_session_id=decision_session_id,
                    reason=str(exc),
                )
                self._observe_best_effort(
                    stage_key=f"authority-denial:{denial['denial_id']}",
                    event_type=denial["denial_type"],
                    summary=denial["summary"],
                    payload=self._authority_denial_payload(denial),
                )
                raise NotificationError(
                    "Valid Head User/admin identity session required for approval decision."
                ) from exc
            if decision_by and decision_by != decision_identity.actor_id:
                denial = self._record_authority_denial(
                    "UNAUTHORIZED_APPROVAL_DECISION_BLOCKED",
                    f"Approval decision blocked: decision_by did not match session identity for {approval.action}",
                    approval_id=approval.approval_id,
                    attempted_decision_by=decision_by,
                    session_actor_id=decision_identity.actor_id,
                    decision_session_id=decision_session_id,
                )
                self._observe_best_effort(
                    stage_key=f"authority-denial:{denial['denial_id']}",
                    event_type=denial["denial_type"],
                    summary=denial["summary"],
                    payload=self._authority_denial_payload(denial),
                )
                raise NotificationError(
                    "decision_by does not match the supplied identity session."
                )
            if not decision_identity.has_human_intent_proof():
                denial = self._record_authority_denial(
                    "UNAUTHORIZED_APPROVAL_DECISION_BLOCKED",
                    f"Approval decision blocked: session lacks human intent proof for {approval.action}",
                    approval_id=approval.approval_id,
                    session_actor_id=decision_identity.actor_id,
                    decision_session_id=decision_session_id,
                    reason="identity session lacks human intent proof",
                )
                self._observe_best_effort(
                    stage_key=f"authority-denial:{denial['denial_id']}",
                    event_type=denial["denial_type"],
                    summary=denial["summary"],
                    payload=self._authority_denial_payload(denial),
                )
                raise NotificationError(
                    "Approval decisions require a human identity session with human-intent proof."
                )
            decision_by = decision_identity.actor_id

            # Second, independent gate: confirm the now-*authenticated* actor is
            # actually the Head User or a configured admin. This is authorization,
            # not authentication -- it is never a substitute for the session check
            # above. The persisted role configuration remains authoritative and is
            # loaded fail-closed; corrupt role data can never collapse into no roles.
            if not self.is_head_user_or_admin(
                approval.vault_id, decision_by, approval.head_user_id
            ):
                denial = self._record_authority_denial(
                    "UNAUTHORIZED_APPROVAL_DECISION_BLOCKED",
                    f"Unauthorized approval decision blocked for {approval.action} on {approval.object_id}",
                    approval_id=approval.approval_id,
                    attempted_decision_by=decision_by,
                    decision_session_id=decision_session_id,
                    reason="not Head User or configured admin",
                )
                self._observe_best_effort(
                    stage_key=f"authority-denial:{denial['denial_id']}",
                    event_type=denial["denial_type"],
                    summary=denial["summary"],
                    payload=self._authority_denial_payload(denial),
                )
                raise NotificationError(
                    "Only the Head User or configured admin with valid identity may approve this request."
                )

            approval.status = (
                RequestStatus.EXPIRED
                if approval.is_expired()
                else RequestStatus.APPROVED if approved else RequestStatus.DENIED
            )
            approval.decision_at = self._now()
            approval.decision_by = decision_by
            approval.decision_reason = reason
            approval.decision_session_id = decision_session_id
            self._save_approval_request(approval)

        # Durable decision is complete. Secondary evidence and notifications
        # occur after releasing the approval lock; they cannot change the
        # write-once decision state.
        self._observe_best_effort(
            stage_key=f"approval:{approval.approval_id}:DECISION:{approval.status.value}",
            event_type="HEAD_USER_APPROVAL_DECISION",
            summary=f"Approval {approval.status.value}: {approval.action} on {approval.object_id}",
            payload=self._approval_decision_payload(approval),
        )
        decision_word = (
            "approved" if approval.status == RequestStatus.APPROVED else approval.status.value
        )
        self.create_notification(
            approval.requester_id,
            self._shorten(f"Your {approval.action} request was {decision_word}."),
            NotificationLevel.INFO,
        )

        if approval.request_id:
            try:
                self._update_access_request_status(approval.request_id, approval.status)
            except NotificationError:
                # The approval file is the terminal authority.  The linked
                # request status is a repairable projection and is reconciled
                # deterministically from approval.request_id on restart.
                pass
        return approval

    # ─── access request + BlackBox control ──────────────────────────────

    def _request_path(self, request_id: str) -> Path:
        return self._record_path(self.request_dir, name="request_id", value=request_id)

    def _save_access_request(self, request: AccessRequest, *, create: bool = False) -> None:
        path = self._request_path(request.request_id)
        if create:
            try:
                self._write_json_exclusive(path, request.to_dict())
            except FileExistsError as exc:
                raise NotificationError(
                    f"request_id already exists: {request.request_id}"
                ) from exc
            return
        self._write_json_atomic(path, request.to_dict())

    def get_access_request(self, request_id: str) -> Optional[AccessRequest]:
        request_id = self._storage_id("request_id", str(request_id))
        path = self._request_path(request_id)
        if not path.exists():
            return None
        data = self._read_json_object(path, label=f"access request {request_id}")
        if data.get("request_id") != request_id:
            raise NotificationError(
                f"access request {request_id} does not match its storage name"
            )
        try:
            return AccessRequest.from_dict(data)
        except Exception as exc:
            raise NotificationError(f"invalid access request {request_id}: {exc}") from exc

    def _update_access_request_status(self, request_id: str, status: RequestStatus) -> None:
        request_id = self._storage_id("request_id", str(request_id))
        with file_lock(self._record_lock("request", request_id)):
            request = self.get_access_request(request_id)
            if request is None:
                raise NotificationError(
                    f"approval references missing access request: {request_id}"
                )
            request.status = status
            self._save_access_request(request)

    def get_all_access_requests(self) -> List[Dict[str, Any]]:
        requests: List[AccessRequest] = []
        for path in sorted(self.request_dir.glob("*.json")):
            request = self.get_access_request(path.stem)
            if request is not None:
                requests.append(request)
        return [request.to_dict() for request in sorted(requests, key=lambda item: item.created_at)]

    def _matching_request_count(self, requester_id: str, tool_family: Optional[str] = None) -> int:
        """Count similar requests inside a rolling time window."""
        count = 0
        window_start = self._now() - timedelta(minutes=int(self._limits.get("request_window_minutes", 60)))
        for r in self.get_all_access_requests():
            try:
                created = _persisted_datetime(r, "created_at", required=True)
            except Exception:
                created = self._now()
            if created < window_start:
                continue
            if r.get("requester_id") == requester_id:
                count += 1
            elif tool_family and r.get("tool_family") == tool_family:
                count += 1
        return count + 1  # include request currently being created

    def _update_incident_bundle(self, request: AccessRequest) -> Dict[str, Any]:
        """Collapse repeated pressure into one BlackBox incident bundle."""
        return self.blackbox.update_request_incident_bundle(request.to_dict())

    def classify_request_pressure(self, count: int) -> RequestClassification:
        if count >= self._limits["flood_threshold"]:
            return RequestClassification.ACTIVE_FLOOD
        if count >= self._limits["intrusion_threshold"]:
            return RequestClassification.PROBABLE_INTRUSION
        if count >= self._limits["suspicious_threshold"]:
            return RequestClassification.SUSPICIOUS_PATTERN
        if count >= self._limits["warning_threshold"]:
            return RequestClassification.UNUSUAL_PRESSURE
        return RequestClassification.NORMAL

    def _classification_level(self, classification: RequestClassification) -> NotificationLevel:
        if classification in (RequestClassification.PROBABLE_INTRUSION, RequestClassification.ACTIVE_FLOOD):
            return NotificationLevel.INTRUSION
        if classification == RequestClassification.SUSPICIOUS_PATTERN:
            return NotificationLevel.CRITICAL
        if classification == RequestClassification.UNUSUAL_PRESSURE:
            return NotificationLevel.WARNING
        return NotificationLevel.INFO

    def _system_action_for_classification(self, classification: RequestClassification) -> tuple[RequestStatus, str]:
        if classification == RequestClassification.ACTIVE_FLOOD:
            return RequestStatus.EMERGENCY_LOCKOUT, "emergency lockout; request flood preserved as possible hostile access evidence"
        if classification == RequestClassification.PROBABLE_INTRUSION:
            return RequestStatus.FROZEN, "bot request stream frozen pending Head User review"
        if classification == RequestClassification.SUSPICIOUS_PATTERN:
            return RequestStatus.FROZEN, "request stream collapsed into suspicious incident; Head User review required"
        if classification == RequestClassification.UNUSUAL_PRESSURE:
            return RequestStatus.FROZEN, "request stream collapsed into unusual-pressure incident; normal approval creation paused"
        return RequestStatus.PENDING_APPROVAL, "request logged; human approval required"

    def build_request_alert_messages(self, request: AccessRequest) -> List[str]:
        """Return max five user-facing alert messages, each capped to 150 chars."""
        if request.classification in (RequestClassification.PROBABLE_INTRUSION, RequestClassification.ACTIVE_FLOOD):
            first = "Possible hacking attempt: repeated protected access requests detected."
        elif request.classification == RequestClassification.SUSPICIOUS_PATTERN:
            first = "Suspicious access pattern: repeated protected requests detected."
        elif request.classification == RequestClassification.UNUSUAL_PRESSURE:
            first = "Unusual access pressure: protected requests are increasing."
        else:
            first = f"{request.requester_kind.value} requests protected access."
        messages = [
            first,
            f"Object: {request.object_id[:24]} Action: {request.action}",
            f"Purpose: {request.claimed_purpose or 'not supplied'}",
            f"Count: {request.matching_request_count} Classification: {request.classification.value}",
            "Reply APPROVE, DENY, or REVIEW. Full record is in BlackBox.",
        ]
        return [self._shorten(m, self._limits["per_recipient_char_limit"]) for m in messages[:5]]

    def create_access_request(
        self,
        vault_id: str,
        object_id: str,
        action: str,
        requester_id: str,
        claimed_purpose: str,
        requester_kind: ActorKind | str = ActorKind.UNKNOWN,
        recipients: Optional[Sequence[str]] = None,
        head_user_id: Optional[str] = None,
        section_id: Optional[str] = None,
        tool_family: Optional[str] = None,
    ) -> AccessRequest:
        """Log a protected access request and notify humans without allowing bot access.

        This method never opens/fetches protected custody material. It only logs,
        classifies, alerts, and optionally creates Head User approval.
        """
        kind = requester_kind if isinstance(requester_kind, ActorKind) else ActorKind(str(requester_kind))
        recipients_list = list(dict.fromkeys([*(recipients or []), *([head_user_id] if head_user_id else [])]))
        count = self._matching_request_count(requester_id, tool_family)
        classification = self.classify_request_pressure(count)
        status, system_action = self._system_action_for_classification(classification)
        request = AccessRequest(
            vault_id=vault_id,
            section_id=section_id,
            object_id=object_id,
            action=action,
            requester_id=requester_id,
            requester_kind=kind,
            tool_family=tool_family,
            claimed_purpose=claimed_purpose,
            recipients=recipients_list,
            head_user_id=head_user_id,
            status=status,
            classification=classification,
            matching_request_count=count,
            system_action=system_action,
        )
        self._save_access_request(request, create=True)
        event = self._observe_best_effort(
            stage_key=f"request:{request.request_id}:LOGGED",
            event_type="PROTECTED_ACCESS_REQUEST_LOGGED",
            summary=f"{kind.value} requested {action} on {object_id}; {classification.value}",
            payload=self._access_request_observation_payload(request),
        )
        # Normal requests create approval. Repeated-pressure requests collapse into an incident
        # bundle so a bot cannot create unlimited approval files or approval chores.
        if classification == RequestClassification.NORMAL and head_user_id:
            approval = self.create_approval_request(vault_id, object_id, action, requester_id, claimed_purpose, head_user_id, request.request_id)
            request.approval_id = approval.approval_id
        elif classification != RequestClassification.NORMAL:
            incident = self._update_incident_bundle(request)
            request.system_action = f"{request.system_action}; incident_bundle={incident['incident_id']}"
        notes = self.create_notification_burst(
            recipients_list,
            self.build_request_alert_messages(request),
            self._classification_level(classification),
            action_url=f"/blackbox/requests/{request.request_id}",
            blackbox_event_id=event.get("event_id") if event else None,
        )
        request.notification_ids = [n.notification_id for n in notes]
        if notes:
            request.status = RequestStatus.NOTIFIED if request.status == RequestStatus.PENDING_APPROVAL else request.status
        self._save_access_request(request)
        return request

    def evaluate_direct_access(
        self,
        actor_kind: ActorKind | str | None,
        action: str,
        protected: bool = True,
        human_ceremony_passed: bool = False,
        actor_identity: Optional[ActorIdentity] = None,
    ) -> Dict[str, Any]:
        """Decision helper: bots cannot directly perform protected custody actions.

        v2.1.8 accepts an ActorIdentity session. When supplied, that session is
        the source of actor kind and human-ceremony proof. Raw actor_kind remains
        only for compatibility and unprotected diagnostics.
        """
        if actor_identity is not None:
            if not actor_identity.is_valid():
                denial = self._record_authority_denial(
                    "PROTECTED_DIRECT_ACCESS_DENIED",
                    f"Protected access denied: invalid identity session for {action}",
                    action=action,
                    reason="invalid_identity_session",
                    session_id=actor_identity.session_id,
                )
                event = self._observe_best_effort(
                    stage_key=f"authority-denial:{denial['denial_id']}",
                    event_type=denial["denial_type"],
                    summary=denial["summary"],
                    payload=self._authority_denial_payload(denial),
                )
                return {
                    "allowed": False,
                    "reason": "Valid identity session required for protected custody.",
                    "action": action,
                    "blackbox_event_id": event.get("event_id") if event else None,
                }
            actor_kind = actor_identity.actor_kind
            human_ceremony_passed = bool(human_ceremony_passed or actor_identity.has_human_intent_proof())

        try:
            kind = actor_kind if isinstance(actor_kind, ActorKind) else ActorKind(str(actor_kind or ActorKind.UNKNOWN.value))
        except ValueError:
            kind = ActorKind.UNKNOWN
        if not protected:
            return {"allowed": True, "reason": "unprotected action"}
        if kind in self.BOT_KINDS:
            denial = self._record_authority_denial(
                "PROTECTED_DIRECT_ACCESS_DENIED",
                f"Bot/tool direct access denied for {action}",
                action=action,
                actor_kind=kind.value,
                session_id=actor_identity.session_id if actor_identity else None,
                reason="no_bot_direct_access",
            )
            event = self._observe_best_effort(
                stage_key=f"authority-denial:{denial['denial_id']}",
                event_type=denial["denial_type"],
                summary=denial["summary"],
                payload=self._authority_denial_payload(denial),
            )
            return {
                "allowed": False,
                "reason": "No autonomous bot/AI/tool access to protected custody. Request human approval instead.",
                "action": action,
                "blackbox_event_id": event.get("event_id") if event else None,
            }
        if kind == ActorKind.HUMAN and human_ceremony_passed:
            return {
                "allowed": True,
                "reason": "human identity session ceremony passed" if actor_identity else "human ceremony passed",
                "action": action,
                "actor_id": actor_identity.actor_id if actor_identity else None,
                "session_id": actor_identity.session_id if actor_identity else None,
            }
        denial = self._record_authority_denial(
            "PROTECTED_DIRECT_ACCESS_DENIED",
            f"Protected access denied: missing human ceremony for {action}",
            action=action,
            actor_kind=kind.value,
            session_id=actor_identity.session_id if actor_identity else None,
            reason="missing_human_ceremony",
        )
        event = self._observe_best_effort(
            stage_key=f"authority-denial:{denial['denial_id']}",
            event_type=denial["denial_type"],
            summary=denial["summary"],
            payload=self._authority_denial_payload(denial),
        )
        return {
            "allowed": False,
            "reason": "Protected custody requires live authorized human ceremony.",
            "action": action,
            "blackbox_event_id": event.get("event_id") if event else None,
        }

    # ─── summaries / reports ────────────────────────────────────────────

    def get_notification_status(self) -> Dict[str, Any]:
        all_notifs = self._get_all_notifications()
        pending = []
        for path in sorted(self.approval_dir.glob("*.json")):
            approval = self.get_approval_request(path.stem)
            if (
                approval is not None
                and approval.status == RequestStatus.PENDING_APPROVAL
                and not approval.is_expired()
            ):
                pending.append(approval)
        archived_count = len(list(self.notification_archive_dir.glob("*.json")))
        return {
            "total_notifications": len(all_notifs),
            "active_notifications": len(all_notifs),
            "archived_notifications": archived_count,
            "preserved_notification_records": len(all_notifs) + archived_count,
            "unread_notifications": len([n for n in all_notifs if n.read_at is None]),
            "total_capacity": self._limits["total_system_max"],
            "capacity_used": len(all_notifs),
            "capacity_remaining": max(0, self._limits["total_system_max"] - len(all_notifs)),
            "pending_approvals": len(pending),
            "request_count": len(self.get_all_access_requests()),
            "system_status": "normal" if len(all_notifs) < self._limits["total_system_max"] else "at_capacity",
        }

    def build_blackbox_request_report(self, limit: int = 100) -> Dict[str, Any]:
        requests = self.get_all_access_requests()[-limit:]
        counts: Dict[str, int] = {}
        intrusions: List[Dict[str, Any]] = []
        for r in requests:
            key = r.get("requester_id") or "unknown"
            counts[key] = counts.get(key, 0) + 1
            if r.get("classification") in {
                RequestClassification.PROBABLE_INTRUSION.value,
                RequestClassification.ACTIVE_FLOOD.value,
                RequestClassification.SUSPICIOUS_PATTERN.value,
            }:
                intrusions.append(r)
        incidents: List[Dict[str, Any]] = []
        incident_read_errors: List[Dict[str, str]] = []
        for incident_path in sorted(self.incident_dir.glob("*.json")):
            try:
                incident_id = self._storage_id("incident id", incident_path.stem)
                incident = self._read_json_object(
                    incident_path,
                    label=f"incident bundle {incident_id}",
                )
                if incident.get("incident_id") != incident_id:
                    raise NotificationError(
                        "incident bundle id does not match its storage name"
                    )
                incidents.append(incident)
            except NotificationError as exc:
                incident_read_errors.append(
                    {
                        "file": incident_path.name,
                        "error": str(exc),
                    }
                )
        return {
            "summary": "BlackBox protected access request report",
            "generated_at": self._now().isoformat(),
            "request_count_included": len(requests),
            "counts_by_requester": counts,
            "possible_intrusion_records": intrusions,
            "incident_bundles": sorted(incidents, key=lambda i: i.get("updated_at", "")),
            "incident_coverage": "full" if not incident_read_errors else "partial",
            "incident_read_errors": incident_read_errors,
            "blackbox_chain": self.verify_blackbox_chain(),
            "notification_limits": dict(self._limits),
            "requests": requests,
        }

    def is_approaching_limits(self, recipient_id: str) -> bool:
        return len(self._get_recipient_notifications(recipient_id)) >= (self._limits["per_recipient_max"] - 1)

    def suppress_duplicate_alerts(self, recipient_id: str, message_prefix: str) -> bool:
        one_hour_ago = self._now() - timedelta(hours=1)
        for msg in self._get_recipient_notifications(recipient_id):
            if msg.message.startswith(message_prefix) and msg.created_at > one_hour_ago:
                return True
        return False
