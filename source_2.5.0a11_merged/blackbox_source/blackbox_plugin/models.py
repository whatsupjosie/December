"""Host-neutral evidence contracts for the standalone BlackBox plugin.

The models describe observed facts. They do not decide custody, legitimacy,
guilt, motive, authorization, or whether a host action should occur.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from hashlib import sha256
from typing import Any, Mapping
from uuid import uuid4

from .errors import RecordValidationError
from .schema import canonical_json

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@/+\-]{0,191}$")
_MAX_PAYLOAD_BYTES = 64 * 1024


class ObservationMode(str, Enum):
    DIRECT = "direct"
    ADAPTER_OBSERVED = "adapter_observed"
    ACTOR_ASSERTED = "actor_asserted"
    DERIVED = "derived"
    IMPORTED = "imported"
    UNKNOWN = "unknown"


class Coverage(str, Enum):
    FULL = "full"
    PARTIAL = "partial"
    SAMPLED = "sampled"
    SUMMARY = "summary"
    UNKNOWN = "unknown"


class RecorderState(str, Enum):
    STARTING = "starting"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    COVERAGE_GAP = "coverage_gap"
    SEALED = "sealed"
    UNAVAILABLE = "unavailable"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _validate_identifier(name: str, value: str, *, allow_blank: bool = False) -> None:
    if not isinstance(value, str):
        raise RecordValidationError(f"{name} must be a string")
    if allow_blank and not value:
        return
    if not value or not _ID_RE.fullmatch(value):
        raise RecordValidationError(f"invalid {name}: {value!r}")


def _validate_timestamp(value: str, *, label: str = "observed_at") -> str:
    if not isinstance(value, str):
        raise RecordValidationError(f"{label} must be a string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RecordValidationError(f"{label} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise RecordValidationError(f"{label} must include a timezone")
    return value


@dataclass(frozen=True, slots=True)
class EvidenceEvent:
    event_type: str
    source: str
    actor: str
    subject_id: str
    observation_mode: ObservationMode = ObservationMode.DIRECT
    coverage: Coverage = Coverage.FULL
    payload: Mapping[str, Any] = field(default_factory=dict)
    operation_id: str | None = None
    session_id: str | None = None
    source_sequence: int | None = None
    observed_at: str = field(default_factory=utc_now)
    event_id: str = field(default_factory=lambda: uuid4().hex)
    channel: str = "GEN"
    event_code: str = "OBS"

    def __post_init__(self) -> None:
        for name, value in {
            "event_type": self.event_type,
            "source": self.source,
            "actor": self.actor,
            "subject_id": self.subject_id,
            "event_id": self.event_id,
            "channel": self.channel,
            "event_code": self.event_code,
        }.items():
            _validate_identifier(name, value)
        if self.operation_id is not None:
            _validate_identifier("operation_id", self.operation_id)
        if self.session_id is not None:
            _validate_identifier("session_id", self.session_id)
        if self.source_sequence is not None and (
            not isinstance(self.source_sequence, int)
            or isinstance(self.source_sequence, bool)
            or self.source_sequence < 0
        ):
            raise RecordValidationError("source_sequence must be a non-negative integer or null")
        _validate_timestamp(self.observed_at)
        if not isinstance(self.payload, Mapping):
            raise RecordValidationError("payload must be an object")
        encoded = canonical_json(dict(self.payload))
        if len(encoded) > _MAX_PAYLOAD_BYTES:
            raise RecordValidationError(f"payload exceeds {_MAX_PAYLOAD_BYTES} bytes")

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_type": self.event_type,
            "source": self.source,
            "actor": self.actor,
            "subject_id": self.subject_id,
            "observation_mode": self.observation_mode.value,
            "coverage": self.coverage.value,
            "payload": dict(self.payload),
            "operation_id": self.operation_id,
            "session_id": self.session_id,
            "source_sequence": self.source_sequence,
            "observed_at": self.observed_at,
            "event_id": self.event_id,
            "channel": self.channel,
            "event_code": self.event_code,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "EvidenceEvent":
        if not isinstance(data, Mapping):
            raise RecordValidationError("evidence event must be an object")

        def required_string(name: str) -> str:
            if name not in data or not isinstance(data[name], str):
                raise RecordValidationError(f"{name} must be a string")
            return data[name]

        def optional_string(name: str, *, default: str | None = None) -> str | None:
            value = data.get(name, default)
            if value is None:
                return None
            if not isinstance(value, str):
                raise RecordValidationError(f"{name} must be a string or null")
            return value

        payload = data.get("payload", {})
        if not isinstance(payload, Mapping):
            raise RecordValidationError("payload must be an object")
        source_sequence = data.get("source_sequence")
        if source_sequence is not None and (
            not isinstance(source_sequence, int)
            or isinstance(source_sequence, bool)
            or source_sequence < 0
        ):
            raise RecordValidationError("source_sequence must be a non-negative integer or null")
        try:
            observation_mode = ObservationMode(
                optional_string("observation_mode", default=ObservationMode.UNKNOWN.value)
            )
            coverage = Coverage(optional_string("coverage", default=Coverage.UNKNOWN.value))
        except ValueError as exc:
            raise RecordValidationError(f"invalid evidence event enum: {exc}") from exc

        return cls(
            event_type=required_string("event_type"),
            source=required_string("source"),
            actor=required_string("actor"),
            subject_id=required_string("subject_id"),
            observation_mode=observation_mode,
            coverage=coverage,
            payload=dict(payload),
            operation_id=optional_string("operation_id"),
            session_id=optional_string("session_id"),
            source_sequence=source_sequence,
            observed_at=optional_string("observed_at", default=utc_now()),
            event_id=optional_string("event_id", default=uuid4().hex),
            channel=optional_string("channel", default="GEN"),
            event_code=optional_string("event_code", default="OBS"),
        )

    def semantic_fingerprint(self) -> str:
        """Stable retry fingerprint; intentionally excludes event id and timestamp."""
        data = self.to_dict()
        data.pop("event_id", None)
        data.pop("observed_at", None)
        return sha256(canonical_json(data)).hexdigest()


@dataclass(frozen=True, slots=True)
class AppendReceipt:
    record_id: str
    sequence: int
    event_hash: str
    previous_hash: str
    accepted_at: str
    segment: int
    duplicate: bool = False
    checkpoint_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class VerificationResult:
    ok: bool
    checked: int
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    sealed: bool = False
    session_id: str | None = None
    segment_count: int = 0
    recoverable_tail: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class RecorderHealth:
    state: RecorderState
    session_id: str
    sequence: int
    last_record_hash: str
    last_success_at: str | None
    coverage_gap_started_at: str | None = None
    details: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["state"] = self.state.value
        return result
