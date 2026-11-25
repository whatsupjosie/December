from __future__ import annotations

from pathlib import Path

import pytest

from blackbox_plugin import BlackBoxPlugin
from iteration_wallet_blackbox import (
    DurableOutbox,
    WalletBlackBoxConnector,
    WalletFact,
    WitnessDelivery,
    WitnessRejectedError,
)


def _fact(operation_id: str = "operation:one") -> WalletFact:
    return WalletFact(
        event_type="candidate.added",
        actor="human:owner",
        object_id="file:one",
        project_id="project:one",
        operation_id=operation_id,
        session_id="wallet-session",
        payload={"state": "candidate"},
    )


def test_unavailable_and_rejected_are_not_conflated(tmp_path: Path):
    outbox = DurableOutbox(tmp_path / "outbox.jsonl")
    connector = WalletBlackBoxConnector(outbox, None)
    state, receipt = connector.submit(_fact())
    assert state is WitnessDelivery.NOT_CONFIGURED
    assert receipt is None
    assert outbox.closed_status()["pending_count"] == 1
    assert outbox.closed_status()["rejected_count"] == 0

    plugin = BlackBoxPlugin(tmp_path / "bbx", "wallet-session")
    plugin.seal("intentional rejection test")
    connector.sink = plugin
    connector.__post_init__()
    assert connector.flush() == 0
    status = outbox.closed_status()
    assert status["pending_count"] == 0
    assert status["rejected_count"] == 1


def test_required_ack_raises_distinct_rejection_error(tmp_path: Path):
    plugin = BlackBoxPlugin(tmp_path / "bbx", "wallet-session")
    plugin.seal("intentional rejection test")
    connector = WalletBlackBoxConnector(DurableOutbox(tmp_path / "outbox.jsonl"), plugin)
    with pytest.raises(WitnessRejectedError):
        connector.submit(_fact(), require_ack=True)
    status = connector.outbox.closed_status()
    assert status["pending_count"] == 0
    assert status["rejected_count"] == 1


def test_permanently_rejected_operation_cannot_be_silently_retried(tmp_path: Path):
    plugin = BlackBoxPlugin(tmp_path / "bbx", "wallet-session")
    plugin.seal("intentional rejection test")
    connector = WalletBlackBoxConnector(DurableOutbox(tmp_path / "outbox.jsonl"), plugin)
    state, receipt = connector.submit(_fact())
    assert state is WitnessDelivery.REJECTED
    assert receipt is None
    with pytest.raises(Exception, match="permanently rejected"):
        connector.submit(_fact())
