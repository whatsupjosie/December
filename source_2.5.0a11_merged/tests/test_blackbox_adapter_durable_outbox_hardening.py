from __future__ import annotations

import json
import multiprocessing as mp
from pathlib import Path

import pytest

from iteration_wallet_blackbox import DurableOutbox, OutboxIntegrityError, WalletFact


def _fact(index: int) -> WalletFact:
    return WalletFact(
        event_type="candidate.added",
        actor="human:owner",
        object_id=f"file:{index}",
        project_id="project:one",
        operation_id=f"operation:{index}",
        payload={"index": index},
        session_id="wallet-session",
    )


def _enqueue_worker(path: str, start: int, count: int) -> None:
    outbox = DurableOutbox(path)
    for index in range(start, start + count):
        outbox.enqueue(_fact(index))


def test_operation_id_is_semantically_idempotent_after_acknowledgement(tmp_path: Path):
    outbox = DurableOutbox(tmp_path / "outbox.jsonl")
    fact = _fact(1)
    outbox.enqueue(fact)
    outbox.acknowledge(fact.operation_id, "record:one")

    outbox.enqueue(fact)
    assert tuple(outbox.pending()) == ()
    status = outbox.closed_status()
    assert status["acknowledged_count"] == 1
    assert status["verified"] is True

    conflicting = WalletFact(
        event_type=fact.event_type,
        actor=fact.actor,
        object_id=fact.object_id,
        project_id=fact.project_id,
        operation_id=fact.operation_id,
        payload={"different": True},
        session_id=fact.session_id,
    )
    with pytest.raises(OutboxIntegrityError, match="different Wallet fact"):
        outbox.enqueue(conflicting)


def test_hash_chain_detects_record_tampering(tmp_path: Path):
    path = tmp_path / "outbox.jsonl"
    outbox = DurableOutbox(path)
    outbox.enqueue(_fact(1))
    outbox.fail("operation:1", "temporary")

    lines = path.read_text(encoding="utf-8").splitlines()
    record = json.loads(lines[0])
    record["fact"]["payload"]["index"] = 999
    lines[0] = json.dumps(record, sort_keys=True, separators=(",", ":"))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    verification = outbox.verify()
    assert verification.ok is False
    assert any("record hash mismatch" in error or "fingerprint mismatch" in error for error in verification.errors)
    with pytest.raises(OutboxIntegrityError, match="failed verification"):
        outbox.enqueue(_fact(2))


def test_partial_final_line_is_preserved_and_new_writes_rotate(tmp_path: Path):
    path = tmp_path / "outbox.jsonl"
    outbox = DurableOutbox(path)
    outbox.enqueue(_fact(1))
    with path.open("ab") as handle:
        handle.write(b'{"version":2,"sequence":')
        handle.flush()

    verification = outbox.verify()
    assert verification.ok is True
    assert verification.recoverable_tail is True

    outbox.enqueue(_fact(2))
    segment = path.with_name(path.name + ".segment_000002.jsonl")
    assert segment.is_file()
    pending = tuple(outbox.pending())
    assert {item.fact.operation_id for item in pending} == {"operation:1", "operation:2"}
    assert outbox.verify().ok is True


def test_cross_process_enqueues_have_one_chain_and_no_lost_facts(tmp_path: Path):
    path = tmp_path / "outbox.jsonl"
    DurableOutbox(path)
    context = mp.get_context("spawn")
    workers = [
        context.Process(target=_enqueue_worker, args=(str(path), offset, 20))
        for offset in (0, 20, 40, 60)
    ]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(20)
        assert worker.exitcode == 0

    outbox = DurableOutbox(path)
    verification = outbox.verify()
    assert verification.ok is True
    assert verification.checked == 80
    pending = tuple(outbox.pending())
    assert len(pending) == 80
    assert len({item.fact.operation_id for item in pending}) == 80


def test_unknown_failure_or_acknowledgement_cannot_create_fake_state(tmp_path: Path):
    outbox = DurableOutbox(tmp_path / "outbox.jsonl")
    with pytest.raises(OutboxIntegrityError, match="unknown"):
        outbox.acknowledge("operation:missing", "record:fake")
    with pytest.raises(OutboxIntegrityError, match="unknown, acknowledged, or rejected"):
        outbox.fail("operation:missing", "fake")


def test_wallet_fact_rejects_unbounded_or_non_json_payloads():
    with pytest.raises(ValueError):
        WalletFact(
            event_type="bad event with spaces",
            actor="human:owner",
            object_id="file:1",
            project_id="project:one",
        )
    with pytest.raises(Exception):
        WalletFact(
            event_type="candidate.added",
            actor="human:owner",
            object_id="file:1",
            project_id="project:one",
            payload={"bad": float("nan")},
        )


def test_first_v2_record_anchors_exact_legacy_prefix_bytes(tmp_path: Path):
    path = tmp_path / "outbox.jsonl"
    legacy_fact = _fact(7)
    legacy_line = json.dumps(
        {
            "transition": "queued",
            "at": "2026-07-20T00:00:00+00:00",
            "operation_id": legacy_fact.operation_id,
            "fact": legacy_fact.to_dict(),
        },
        sort_keys=True,
        separators=(",", ":"),
    ) + "\n"
    path.write_text(legacy_line, encoding="utf-8")

    outbox = DurableOutbox(path)
    outbox.enqueue(_fact(8))

    records = path.read_text(encoding="utf-8").splitlines()
    first_v2 = json.loads(records[1])
    import hashlib
    assert first_v2["previous_hash"] == hashlib.sha256(legacy_line.encode("utf-8")).hexdigest()
    verification = outbox.verify()
    assert verification.ok is True
    assert verification.legacy_prefix_records == 1
    assert {item.fact.operation_id for item in outbox.pending()} == {"operation:7", "operation:8"}
