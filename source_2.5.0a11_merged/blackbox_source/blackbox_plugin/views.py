"""Typed, default-deny read-only views over canonical BlackBox records.

Closed views never receive an arbitrary payload dictionary. Each known event
owns a small projector that validates both field name *and* value shape.
Unknown event types expose envelope metadata only.
"""
from __future__ import annotations

from collections import Counter
from typing import Any, Callable, Iterable, Mapping

PayloadProjector = Callable[[Mapping[str, Any]], dict[str, Any]]

_SAFE_STATES = {
    "raw",
    "candidate",
    "prime",
    "archived",
    "retired",
    "quarantined",
    "banned",
    "legacy_externalized",
}
_SAFE_RESULT_STATUSES = {"completed", "failed", "reconciliation_required"}
_SAFE_ACTIONS = {
    "promote_candidate_to_prime",
    "retire_object",
    "restore_retired_object",
    "quarantine",
    "export_working_copy",
    "open_vault",
    "open_cradle",
}


def _safe_bool(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def _safe_enum(value: Any, allowed: set[str]) -> str | None:
    return value if isinstance(value, str) and value in allowed else None


def _project_fields(
    payload: Mapping[str, Any],
    validators: Mapping[str, Callable[[Any], Any | None]],
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, validator in validators.items():
        if key not in payload:
            continue
        projected = validator(payload[key])
        if projected is not None:
            result[key] = projected
    result["omitted_field_count"] = max(0, len(payload) - len(result))
    result["projection"] = "typed_default_deny"
    return result


def _candidate_observed(payload: Mapping[str, Any]) -> dict[str, Any]:
    return _project_fields(payload, {"state": lambda value: _safe_enum(value, _SAFE_STATES)})


def _prime_promoted(payload: Mapping[str, Any]) -> dict[str, Any]:
    return _project_fields(
        payload,
        {
            "state": lambda value: _safe_enum(value, {"prime"}),
            "recovered_after_restart": _safe_bool,
        },
    )


def _human_intent(payload: Mapping[str, Any]) -> dict[str, Any]:
    return _project_fields(
        payload,
        {
            "action_key": lambda value: _safe_enum(value, _SAFE_ACTIONS),
            "result_status": lambda value: _safe_enum(value, _SAFE_RESULT_STATUSES),
            "recovered_after_restart": _safe_bool,
            "coverage_gap": _safe_bool,
        },
    )


def _ceremony(payload: Mapping[str, Any]) -> dict[str, Any]:
    return _project_fields(
        payload,
        {"action_key": lambda value: _safe_enum(value, _SAFE_ACTIONS)},
    )


PROJECTORS: dict[str, PayloadProjector] = {
    "candidate.observed": _candidate_observed,
    "PRIME_PROMOTED": _prime_promoted,
    "HUMAN_INTENT_RESERVED": _human_intent,
    "HUMAN_INTENT_AUTHORIZED": _human_intent,
    "HUMAN_INTENT_COMPLETED": _human_intent,
    "HUMAN_INTENT_FAILED": _human_intent,
    "HUMAN_INTENT_RECEIPT_ANCHORED": _human_intent,
    "PROMOTION_RECONCILIATION_REQUIRED": _human_intent,
    "CEREMONY_TOKEN_ISSUED": _ceremony,
    "CEREMONY_TOKEN_CONSUMED": _ceremony,
    "CEREMONY_TOKEN_DENIED": _ceremony,
    "CEREMONY_TOKEN_REVOKED": _ceremony,
}


def project_payload(event_type: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    projector = PROJECTORS.get(str(event_type))
    if projector is None:
        return {
            "projection": "envelope_only_unknown_event",
            "omitted_field_count": len(payload),
        }
    return projector(payload)


def safe_payload(payload: Mapping[str, Any], *, event_type: str = "") -> dict[str, Any]:
    """Compatibility name for typed projection; no generic allowlist remains."""
    return project_payload(event_type, payload)


def closed_summary(records: Iterable[Mapping[str, Any]], verification: Mapping[str, Any]) -> dict[str, Any]:
    items = list(records)
    return {
        "view_mode": "closed_summary",
        "record_count": len(items),
        "event_types": dict(Counter(str(item.get("event_type") or "unknown") for item in items)),
        "channels": dict(Counter(str(item.get("channel") or "unknown") for item in items)),
        "sources": dict(Counter(str(item.get("source") or "unknown") for item in items)),
        "chain_verified": bool(verification.get("ok")),
        "sealed": bool(verification.get("sealed")),
        "coverage_warnings": len(verification.get("warnings") or []),
        "protected_values_exposed": False,
        "payload_policy": "typed_event_specific_default_deny",
        "omitted_categories": [
            "paths",
            "hashes",
            "token identifiers and secrets",
            "notes",
            "contents",
            "previews",
            "private memory",
            "unknown event payloads",
        ],
    }


def object_history(records: Iterable[Mapping[str, Any]], subject_id: str) -> dict[str, Any]:
    history = []
    for item in records:
        if str(item.get("subject_id")) != subject_id:
            continue
        actor = str(item.get("actor") or "unknown")
        actor_kind = actor.split(":", 1)[0] if ":" in actor else actor
        event_type = str(item.get("event_type") or "unknown")
        history.append(
            {
                "sequence": item.get("seq"),
                "observed_at": item.get("observed_at"),
                "event_type": event_type,
                "source": item.get("source"),
                "actor_kind": actor_kind,
                "coverage": item.get("coverage"),
                "observation_mode": item.get("observation_mode"),
                "payload": project_payload(event_type, item.get("payload") or {}),
            }
        )
    return {
        "view_mode": "contextual_object_history",
        "subject_id": subject_id,
        "record_count": len(history),
        "history": history,
        "authoritative": False,
        "derived_from_canonical_blackbox": True,
        "protected_values_exposed": False,
        "payload_policy": "typed_event_specific_default_deny",
    }


def known_record_report(records: Iterable[Mapping[str, Any]], verification: Mapping[str, Any]) -> str:
    items = list(records)
    lines = [
        "# BlackBox Known Record Report",
        "",
        "> This is a derivative human-readable report. The canonical evidence remains the BBX1 record.",
        "",
        "## Verification",
        "",
        f"- Chain verified: {'yes' if verification.get('ok') else 'no'}",
        f"- Records checked: {verification.get('checked', 0)}",
        f"- Sealed: {'yes' if verification.get('sealed') else 'no'}",
        "",
        "## Known Record",
        "",
    ]
    for item in items:
        lines.append(
            f"- {item.get('observed_at')} — `{item.get('event_type')}` from `{item.get('source')}` "
            f"with {item.get('coverage')} coverage ({item.get('observation_mode')})."
        )
    if not items:
        lines.append("- No records.")
    lines.extend(["", "## Derived Analysis", "", "None included.", "", "## Open Questions", "", "- Review any partial, sampled, unknown, or gap-marked coverage before drawing conclusions."])
    return "\n".join(lines) + "\n"
