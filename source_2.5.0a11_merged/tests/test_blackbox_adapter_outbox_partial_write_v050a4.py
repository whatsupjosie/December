from __future__ import annotations

from pathlib import Path

from iteration_wallet_blackbox.models import WalletFact
from iteration_wallet_blackbox.outbox import DurableOutbox


def test_outbox_loops_until_full_record_is_written(tmp_path: Path, monkeypatch):
    from iteration_wallet_blackbox import outbox as module

    outbox = DurableOutbox(tmp_path / "outbox.jsonl")
    fact = WalletFact(
        operation_id="partial-write-operation",
        event_type="TEST_EVENT",
        object_id="subject-one",
        project_id="project-one",
        actor="human:tester",
        payload={"summary": "partial write hardening", "value": "x" * 200},
    )
    original_write = module.os.write

    def partial_write(fd: int, data):
        chunk = bytes(data[:7])
        return original_write(fd, chunk)

    monkeypatch.setattr(module.os, "write", partial_write)
    outbox.enqueue(fact)
    verification = outbox.verify()
    assert verification.ok is True
    pending = tuple(outbox.pending())
    assert len(pending) == 1
    assert pending[0].fact.operation_id == fact.operation_id
