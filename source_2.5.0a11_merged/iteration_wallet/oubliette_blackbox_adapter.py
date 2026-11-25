"""Oubliette-owned translation into the neutral BlackBox client boundary.

Oubliette may report static observations and coverage.  It cannot record a
Wallet custody result through this adapter and it cannot mint Human Intent.
"""
from __future__ import annotations

from typing import Any, Mapping

from blackbox_plugin.models import Coverage, ObservationMode

from iteration_wallet.canonical_evidence import CanonicalEvidenceAdapter


class OublietteEvidenceError(RuntimeError):
    """Raised when an Oubliette observation cannot be recorded canonically."""


class OublietteBlackBoxAdapter:
    SOURCE = "oubliette"

    def __init__(self, evidence: CanonicalEvidenceAdapter) -> None:
        if not isinstance(evidence, CanonicalEvidenceAdapter):
            raise TypeError("OublietteBlackBoxAdapter requires CanonicalEvidenceAdapter")
        self.evidence = evidence

    def append_observation(
        self,
        *,
        event_type: str,
        summary: str,
        event_id: str,
        transaction_id: str,
        stage_key: str,
        actor: str,
        subject_id: str,
        payload: Mapping[str, Any],
        coverage: Coverage,
        channel: str = "OUB",
        event_code: str = "OBS",
    ) -> dict[str, Any]:
        if channel != "OUB":
            raise OublietteEvidenceError("Oubliette observations must use the OUB channel")
        material = dict(payload)
        if material.get("custody_changed") is True:
            raise OublietteEvidenceError(
                "Oubliette cannot claim a Wallet custody transition through its observation adapter"
            )
        if material.get("human_intent_authorized") is True:
            raise OublietteEvidenceError(
                "Oubliette cannot claim Human Intent authority through its observation adapter"
            )
        return self.evidence.append_fact(
            event_type=event_type,
            summary=summary,
            source=self.SOURCE,
            event_id=event_id,
            transaction_id=transaction_id,
            stage_key=stage_key,
            actor=actor,
            subject_id=subject_id,
            payload=material,
            observation_mode=ObservationMode.ADAPTER_OBSERVED,
            coverage=coverage,
            channel=channel,
            event_code=event_code,
        )

    def status(self) -> dict[str, Any]:
        capabilities = self.evidence.client.capabilities().to_dict()
        return {
            "adapter": "oubliette_blackbox_adapter",
            "source": self.SOURCE,
            "canonical_client_schema": capabilities["schema_version"],
            "transport": capabilities["transport"],
            "may_report_static_observations": True,
            "may_move_custody": False,
            "may_mint_human_intent": False,
        }
