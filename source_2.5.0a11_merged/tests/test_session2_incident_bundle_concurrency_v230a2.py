from __future__ import annotations

import multiprocessing as mp
import time
from pathlib import Path

from iteration_wallet.canonical_evidence import CanonicalEvidenceAdapter


def _request(request_id: str, count: int) -> dict:
    return {
        "request_id": request_id,
        "vault_id": "vault-one",
        "object_id": "candidate-one",
        "action": "inspect_metadata",
        "requester_id": "bot-one",
        "tool_family": "pressure-bot",
        "created_at": f"2026-07-20T00:00:{count:02d}",
        "classification": "unusual_access_pressure",
        "matching_request_count": count,
        "status": "frozen_pending_head_user_review",
    }


def _slow_incident_update(root: str, start, queue, request_id: str, count: int) -> None:
    import iteration_wallet.canonical_evidence as module

    original_read = module.strict_json_read

    def slow_read(path):
        value = original_read(path)
        time.sleep(0.6)
        return value

    module.strict_json_read = slow_read
    adapter = CanonicalEvidenceAdapter(Path(root), session_id="wallet-main")
    start.wait()
    result = adapter.update_request_incident_bundle(_request(request_id, count))
    queue.put(result["incident_id"])


def test_concurrent_incident_updates_preserve_every_request(tmp_path: Path) -> None:
    adapter = CanonicalEvidenceAdapter(tmp_path, session_id="wallet-main")
    base = adapter.update_request_incident_bundle(_request("request-base", 1))

    ctx = mp.get_context("spawn")
    start = ctx.Event()
    queue = ctx.Queue()
    workers = [
        ctx.Process(
            target=_slow_incident_update,
            args=(str(tmp_path), start, queue, request_id, count),
        )
        for request_id, count in (("request-two", 2), ("request-three", 3))
    ]
    for worker in workers:
        worker.start()
    start.set()
    ids = [queue.get(timeout=30) for _ in workers]
    for worker in workers:
        worker.join(timeout=30)
        assert worker.exitcode == 0
    queue.close()
    queue.join_thread()
    for worker in workers:
        worker.close()

    assert ids == [base["incident_id"], base["incident_id"]]
    final = adapter.update_request_incident_bundle(_request("request-base", 1))
    assert set(final["raw_request_ids"]) == {"request-base", "request-two", "request-three"}
    assert {item["request_id"] for item in final["updates"]} == {
        "request-base",
        "request-two",
        "request-three",
    }
