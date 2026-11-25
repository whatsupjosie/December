from __future__ import annotations

from pathlib import Path

from blackbox_plugin import (
    BlackBoxPlugin,
    Coverage,
    EvidenceEvent,
    LocalBlackBoxClient,
    ObservationMode,
)


def _event(session: str, *, operation_id: str = "op-one") -> EvidenceEvent:
    return EvidenceEvent(
        event_type="candidate.observed",
        source="test-host",
        actor="human:owner",
        subject_id="object:one",
        session_id=session,
        operation_id=operation_id,
        coverage=Coverage.FULL,
        observation_mode=ObservationMode.DIRECT,
        payload={"state": "candidate"},
    )


def test_local_client_is_a_real_transport_neutral_contract(tmp_path: Path):
    client = LocalBlackBoxClient(BlackBoxPlugin(tmp_path / "bbx", "client-one"))
    capabilities = client.capabilities().to_dict()
    assert capabilities["schema_version"] == "bbx1-client/1"
    assert capabilities["transport"] == "local-in-process"
    assert capabilities["direct_storage_access"] is False

    receipt = client.submit(_event("client-one"))
    retry = client.submit(_event("client-one"))
    assert retry.duplicate is True
    assert retry.record_id == receipt.record_id
    assert client.verify_receipt(receipt).ok is True
    assert client.verify()["ok"] is True
    status = client.status()
    assert status["available"] is True
    assert status["verification"]["ok"] is True


def test_receipt_verification_rejects_forged_material(tmp_path: Path):
    client = LocalBlackBoxClient(BlackBoxPlugin(tmp_path / "bbx", "client-two"))
    receipt = client.submit(_event("client-two"))
    forged = receipt.to_dict()
    forged["event_hash"] = "0" * 64
    result = client.verify_receipt(forged)
    assert result.ok is False
    assert "hash" in result.reason
