"""Wallet-domain facts queued for BlackBox witness delivery."""
from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Mapping
from uuid import uuid4

from blackbox_plugin.models import Coverage, ObservationMode, utc_now
from blackbox_plugin.schema import canonical_json, validate_json_value

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@/+\-]{0,191}$")


class WalletFactValidationError(ValueError):
    """Raised when a queued Wallet fact is not a bounded portable fact."""


def _identifier(name: str, value: str, *, allow_blank: bool = False) -> str:
    if allow_blank and not value:
        return value
    if not isinstance(value, str) or not _ID_RE.fullmatch(value):
        raise WalletFactValidationError(f"invalid {name}: {value!r}")
    return value


def _timestamp(value: str) -> str:
    if not isinstance(value, str):
        raise WalletFactValidationError("observed_at must be a string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise WalletFactValidationError("observed_at must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise WalletFactValidationError("observed_at must include a timezone")
    return value


@dataclass(frozen=True, slots=True)
class WalletFact:
    event_type: str
    actor: str
    object_id: str
    project_id: str
    source: str = "iteration_wallet"
    operation_id: str = field(default_factory=lambda: uuid4().hex)
    payload: Mapping[str, Any] = field(default_factory=dict)
    section_id: str | None = None
    session_id: str | None = None
    observed_at: str = field(default_factory=utc_now)
    observation_mode: ObservationMode = ObservationMode.DIRECT
    coverage: Coverage = Coverage.FULL
    source_sequence: int | None = None
    event_id: str | None = None
    channel: str | None = None
    event_code: str | None = None

    def __post_init__(self) -> None:
        for name, value in (
            ("event_type", self.event_type),
            ("actor", self.actor),
            ("object_id", self.object_id),
            ("project_id", self.project_id),
            ("operation_id", self.operation_id),
            ("source", self.source),
        ):
            _identifier(name, value)
        if self.section_id is not None:
            _identifier("section_id", self.section_id)
        if self.session_id is not None:
            _identifier("session_id", self.session_id)
        _timestamp(self.observed_at)
        if self.source_sequence is not None and (
            not isinstance(self.source_sequence, int) or self.source_sequence < 0
        ):
            raise WalletFactValidationError("source_sequence must be a non-negative integer")
        if self.event_id is not None:
            _identifier("event_id", self.event_id)
        if self.channel is not None:
            _identifier("channel", self.channel)
        if self.event_code is not None:
            _identifier("event_code", self.event_code)
        material = dict(self.payload)
        validate_json_value(material)
        if len(canonical_json(material)) > 64 * 1024:
            raise WalletFactValidationError("Wallet fact payload exceeds 65536 encoded bytes")
        object.__setattr__(self, "payload", material)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["observation_mode"] = self.observation_mode.value
        data["coverage"] = self.coverage.value
        data["payload"] = dict(self.payload)
        return data

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "WalletFact":
        if not isinstance(data, Mapping):
            raise WalletFactValidationError("Wallet fact must be an object")

        def required_string(name: str) -> str:
            if name not in data or not isinstance(data[name], str):
                raise WalletFactValidationError(f"{name} must be a string")
            return data[name]

        def optional_string(name: str) -> str | None:
            value = data.get(name)
            if value is None:
                return None
            if not isinstance(value, str):
                raise WalletFactValidationError(f"{name} must be a string or null")
            return value

        payload = data.get("payload", {})
        if not isinstance(payload, Mapping):
            raise WalletFactValidationError("payload must be an object")
        source = data.get("source", "iteration_wallet")
        if not isinstance(source, str):
            raise WalletFactValidationError("source must be a string")
        source_sequence = data.get("source_sequence")
        if source_sequence is not None and (
            not isinstance(source_sequence, int)
            or isinstance(source_sequence, bool)
            or source_sequence < 0
        ):
            raise WalletFactValidationError("source_sequence must be a non-negative integer or null")
        try:
            observation_mode = ObservationMode(required_string("observation_mode"))
            coverage = Coverage(required_string("coverage"))
        except ValueError as exc:
            raise WalletFactValidationError(f"invalid Wallet fact enum: {exc}") from exc

        return cls(
            event_type=required_string("event_type"),
            actor=required_string("actor"),
            object_id=required_string("object_id"),
            project_id=required_string("project_id"),
            operation_id=required_string("operation_id"),
            source=source,
            payload=dict(payload),
            section_id=optional_string("section_id"),
            session_id=optional_string("session_id"),
            observed_at=required_string("observed_at"),
            observation_mode=observation_mode,
            coverage=coverage,
            source_sequence=source_sequence,
            event_id=optional_string("event_id"),
            channel=optional_string("channel"),
            event_code=optional_string("event_code"),
        )

    def semantic_fingerprint(self) -> str:
        material = self.to_dict()
        material.pop("observed_at", None)
        material.pop("event_id", None)
        return hashlib.sha256(canonical_json(material)).hexdigest()
