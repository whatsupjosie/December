from __future__ import annotations

import json
from pathlib import Path

import pytest

from blackbox_plugin import BlackBoxPlugin
from iteration_wallet_blackbox import DurableOutbox, OutboxIntegrityError, WalletBlackBoxConnector, WalletFact
from iteration_wallet_blackbox.compat import WalletBlackBoxCompat
from iteration_wallet_blackbox.connector import WitnessDelivery


def _fact() -> WalletFact:
    return WalletFact(
        event_type="candidate.added",
        actor="human:owner",
        object_id="candidate:one",
        project_id="project:one",
        operation_id="operation:one",
        payload={"state": "candidate"},
        session_id="session-one",
    )


def test_sink_acknowledged_but_local_ack_interrupted_recovers_idempotently(tmp_path: Path, monkeypatch):
    outbox = DurableOutbox(tmp_path / "outbox.jsonl")
    sink = BlackBoxPlugin(tmp_path / "blackbox", "session-one")
    connector = WalletBlackBoxConnector(outbox=outbox, sink=sink)
    fact = _fact()
    original_ack = outbox.acknowledge
    calls = 0

    def interrupted_ack(operation_id: str, record_id: str) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("simulated acknowledgement persistence interruption")
        original_ack(operation_id, record_id)

    monkeypatch.setattr(outbox, "acknowledge", interrupted_ack)
    with pytest.raises(OSError, match="interruption"):
        connector.submit(fact)

    # The canonical recorder accepted the event, while the outbox correctly
    # remains pending because local acknowledgement did not persist.
    assert len(sink.recorder.iter_records()) == 1
    assert [item.fact.operation_id for item in outbox.pending()] == [fact.operation_id]

    assert connector.flush() == 1
    assert tuple(outbox.pending()) == ()
    # Recorder operation-id idempotency returns the original receipt; no duplicate.
    assert len(sink.recorder.iter_records()) == 1
    assert outbox.closed_status()["acknowledged_count"] == 1


def test_connector_refuses_to_deliver_when_outbox_history_is_tampered(tmp_path: Path):
    path = tmp_path / "outbox.jsonl"
    outbox = DurableOutbox(path)
    sink = BlackBoxPlugin(tmp_path / "blackbox", "session-one")
    connector = WalletBlackBoxConnector(outbox=outbox, sink=sink)
    fact = _fact()
    outbox.enqueue(fact)

    record = json.loads(path.read_text(encoding="utf-8"))
    record["fact"]["payload"]["state"] = "prime"
    path.write_text(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")

    with pytest.raises(OutboxIntegrityError):
        connector.flush()
    assert sink.recorder.iter_records() == ()


def test_compat_adapter_fails_closed_if_require_ack_contract_is_broken(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plugin = BlackBoxPlugin(tmp_path / "blackbox", "session-one")
    compat = WalletBlackBoxCompat(plugin, tmp_path / "outbox.jsonl")

    def broken_submit(*_args, **_kwargs):
        return WitnessDelivery.PENDING, None

    monkeypatch.setattr(WalletBlackBoxConnector, "submit", broken_submit)

    with pytest.raises(RuntimeError, match="without a durable acknowledgement"):
        compat.write_event("candidate.added", "candidate preserved")
