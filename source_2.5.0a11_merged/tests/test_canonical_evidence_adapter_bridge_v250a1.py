from __future__ import annotations

from pathlib import Path

import pytest

from blackbox_plugin import BlackBoxCapabilities, RecordValidationError
from iteration_wallet.canonical_evidence import CanonicalEvidenceAdapter, CanonicalEvidenceError


class _BaseFakeClient:
    def capabilities(self):
        return BlackBoxCapabilities(
            schema_version="bbx1-client/1",
            transport="test",
            operation_id_idempotency=True,
            durable_append=True,
            receipt_verification=True,
            closed_views=False,
            sealing=False,
        )

    def status(self):
        return {"available": True, "health": {"session_id": "wallet-main", "sequence": 0, "last_record_hash": "0" * 64}}

    def verify(self):
        return {"ok": True, "checked": 0, "sealed": False}

    def iter_records(self):
        return ()

    def verify_receipt(self, receipt):
        raise AssertionError("not used")


class _UnavailableClient(_BaseFakeClient):
    def submit(self, event, *, expected_previous_hash=None):
        raise OSError("simulated recorder outage")


class _RejectingClient(_BaseFakeClient):
    def submit(self, event, *, expected_previous_hash=None):
        raise RecordValidationError("simulated permanent rejection")


def test_canonical_adapter_uses_durable_wallet_outbox(tmp_path: Path):
    adapter = CanonicalEvidenceAdapter(tmp_path / "wallet")
    result = adapter.write_event("CANDIDATE_ADDED", "candidate entered custody", project_id="project:one", file_id="file:one")
    assert result["event_hash"]
    status = adapter.outbox.closed_status()
    assert status["verified"] is True
    assert status["pending_count"] == 0
    assert status["acknowledged_count"] == 1
    assert status["rejected_count"] == 0


def test_canonical_adapter_preserves_temporary_delivery_gap(tmp_path: Path):
    adapter = CanonicalEvidenceAdapter(tmp_path / "wallet", client=_UnavailableClient())
    with pytest.raises(CanonicalEvidenceError, match="acknowledgement unavailable"):
        adapter.write_event("CANDIDATE_ADDED", "candidate entered custody", project_id="project:one", file_id="file:one")
    status = adapter.outbox.closed_status()
    assert status["pending_count"] == 1
    assert status["rejected_count"] == 0
    assert status["coverage_gap_count"] == 1


def test_canonical_adapter_preserves_permanent_rejection_distinctly(tmp_path: Path):
    adapter = CanonicalEvidenceAdapter(tmp_path / "wallet", client=_RejectingClient())
    with pytest.raises(CanonicalEvidenceError, match="rejected Wallet evidence"):
        adapter.write_event("CANDIDATE_ADDED", "candidate entered custody", project_id="project:one", file_id="file:one")
    status = adapter.outbox.closed_status()
    assert status["pending_count"] == 0
    assert status["rejected_count"] == 1
    assert status["coverage_gap_count"] == 0
