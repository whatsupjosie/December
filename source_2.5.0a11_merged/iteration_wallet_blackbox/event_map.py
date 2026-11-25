"""Wallet vocabulary belongs here, not inside the portable BlackBox core."""
from __future__ import annotations

from blackbox_plugin.models import EvidenceEvent
from .models import WalletFact


def _codes(event_type: str) -> tuple[str, str]:
    upper = event_type.upper()
    if "HUMAN_INTENT" in upper or "RECEIPT" in upper:
        return "HIN", "RCP"
    if "CEREMONY" in upper or "TOKEN" in upper:
        return "HIN", "CER"
    if "PRIME" in upper or "CANDIDATE" in upper or "RAW_SOURCE" in upper:
        return "CUS", "VER"
    if "QUARANT" in upper:
        return "CUS", "QAR"
    if "RELEASE" in upper:
        return "CUS", "REL"
    if "INTEGRITY" in upper or "VERIFY" in upper or "SNAPSHOT" in upper or "REFERENCE" in upper:
        return "INT", "VRF"
    if "DENIED" in upper or "BLOCKED" in upper:
        return "PAC", "DNY"
    if "OPEN" in upper or "LOCK" in upper or "ACCESS" in upper:
        return "ACC", "ACS"
    return "CUS", "OBS"


def wallet_fact_to_event(fact: WalletFact) -> EvidenceEvent:
    default_channel, default_event_code = _codes(fact.event_type)
    channel = fact.channel or default_channel
    event_code = fact.event_code or default_event_code
    payload = {
        "project_id": fact.project_id,
        "section_id": fact.section_id,
        **dict(fact.payload),
    }
    return EvidenceEvent(
        event_type=fact.event_type,
        source=fact.source,
        actor=fact.actor,
        subject_id=fact.object_id,
        operation_id=fact.operation_id,
        session_id=fact.session_id,
        observed_at=fact.observed_at,
        observation_mode=fact.observation_mode,
        coverage=fact.coverage,
        source_sequence=fact.source_sequence,
        payload=payload,
        event_id=fact.event_id or fact.operation_id,
        channel=channel,
        event_code=event_code,
    )
