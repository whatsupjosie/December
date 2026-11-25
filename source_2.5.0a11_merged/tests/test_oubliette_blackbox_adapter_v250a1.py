from __future__ import annotations

from pathlib import Path

import pytest

from blackbox_plugin import Coverage
from iteration_wallet.canonical_evidence import CanonicalEvidenceAdapter
from iteration_wallet.oubliette_blackbox_adapter import OublietteBlackBoxAdapter, OublietteEvidenceError


def test_oubliette_adapter_records_static_observation_under_its_own_source(tmp_path: Path):
    evidence = CanonicalEvidenceAdapter(tmp_path / "wallet")
    adapter = OublietteBlackBoxAdapter(evidence)
    result = adapter.append_observation(
        event_type="OUBLIETTE_STATIC_INSPECTION_COMPLETED",
        summary="static observation",
        event_id="event-one",
        transaction_id="operation-one",
        stage_key="operation-one:inspection",
        actor="human:operator",
        subject_id="capsule:one",
        payload={"coverage": "full", "custody_changed": False},
        coverage=Coverage.FULL,
        event_code="INSPECT",
    )
    record = evidence.record_by_id(result["event_id"])
    assert record is not None
    assert record["source"] == "oubliette"
    assert record["channel"] == "OUB"
    assert record["payload"]["custody_changed"] is False
    assert adapter.status()["may_move_custody"] is False


def test_oubliette_adapter_cannot_claim_wallet_authority(tmp_path: Path):
    adapter = OublietteBlackBoxAdapter(CanonicalEvidenceAdapter(tmp_path / "wallet"))
    with pytest.raises(OublietteEvidenceError, match="custody transition"):
        adapter.append_observation(
            event_type="OUBLIETTE_STATIC_INSPECTION_COMPLETED",
            summary="invalid authority claim",
            event_id="event-two",
            transaction_id="operation-two",
            stage_key="operation-two:inspection",
            actor="human:operator",
            subject_id="capsule:two",
            payload={"custody_changed": True},
            coverage=Coverage.FULL,
        )
