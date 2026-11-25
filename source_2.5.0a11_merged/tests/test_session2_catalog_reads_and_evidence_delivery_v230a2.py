from __future__ import annotations

from pathlib import Path

import pytest

from iteration_wallet import server
from iteration_wallet.canonical_evidence import CanonicalEvidenceAdapter
from iteration_wallet.promotion_transaction import PromotionTransactionError
from iteration_wallet.vault_v21 import VaultEngine


def _source(root: Path, name: str, text: str) -> Path:
    path = root / name
    path.write_text(text, encoding="utf-8")
    return path


class FailOnceCustodyEvidence:
    """Delegate to BBX1 except for the first selected custody event."""

    def __init__(self, delegate: CanonicalEvidenceAdapter, event_type: str, *, fail_until_released: bool = False) -> None:
        self.delegate = delegate
        self.event_type = event_type
        self.failed = False
        self.fail_until_released = fail_until_released
        self.released = False

    def __getattr__(self, name):
        return getattr(self.delegate, name)

    def write_custody_event(self, event_type: str, summary: str, **extra):
        should_fail = event_type == self.event_type and (
            (self.fail_until_released and not self.released) or not self.failed
        )
        if should_fail:
            self.failed = True
            raise RuntimeError("simulated canonical evidence outage")
        return self.delegate.write_custody_event(event_type, summary, **extra)


def _human_and_token(runtime, project_id: str, section_id: str, candidate_id: str):
    _, vault, humans, _ = runtime
    identity = humans.issue_identity_session(
        actor_id="fresh-reader-human",
        actor_kind="human",
        verified_methods=["human_ceremony", "typing_challenge"],
    )
    vault.open_vault()
    token = vault.issue_ceremony_token(
        "promote_candidate_to_prime",
        identity.session_id,
        actor_id=identity.actor_id,
        project_id=project_id,
        section_id=section_id,
        object_id=candidate_id,
    )["ceremony_token"]
    return identity, token


def test_long_lived_reader_refreshes_project_and_section_views(tmp_path: Path) -> None:
    reader_evidence = CanonicalEvidenceAdapter(tmp_path, session_id="wallet-main")
    reader = VaultEngine(tmp_path, blackbox=reader_evidence)

    writer_runtime = server.build_canonical_v21_runtime(tmp_path)
    writer = writer_runtime[1]
    project = writer.create_project("Fresh Reads")
    section = writer.create_section(project["id"], "Core")
    candidate = writer.add_candidate(
        project["id"], section["id"], str(_source(tmp_path, "fresh.txt", "candidate"))
    )

    # The reader was constructed before any of the records existed.
    assert reader.get_project(project["id"])["name"] == "Fresh Reads"
    assert reader.get_section(project["id"], section["id"])["name"] == "Core"
    assert reader._find_file(project["id"], section["id"], candidate["id"])["state"] == "candidate"
    assert any(item["id"] == project["id"] for item in reader.get_state()["projects"])

    identity, token = _human_and_token(
        writer_runtime, project["id"], section["id"], candidate["id"]
    )
    writer_runtime[3].promote_to_prime(
        project_id=project["id"],
        section_id=section["id"],
        candidate_id=candidate["id"],
        ceremony_token=token,
        session_id=identity.session_id,
        reason="reader must observe durable truth",
    )

    assert reader.get_section(project["id"], section["id"])["prime"] == candidate["id"]
    assert reader._find_file(project["id"], section["id"], candidate["id"])["state"] == "prime"
    assert reader.get_section_view(project["id"], section["id"])["cradle"]["id"] == candidate["id"]


def test_candidate_intake_survives_evidence_outage_with_durable_pending_delivery(tmp_path: Path) -> None:
    canonical = CanonicalEvidenceAdapter(tmp_path, session_id="wallet-main")
    flaky = FailOnceCustodyEvidence(canonical, "CANDIDATE_ADDED")
    vault = VaultEngine(tmp_path, blackbox=flaky)
    project = vault.create_project("Evidence Outbox")
    section = vault.create_section(project["id"], "Core")

    candidate = vault.add_candidate(
        project["id"], section["id"], str(_source(tmp_path, "pending.txt", "candidate"))
    )

    # Custody intake is preserved once, and its missing canonical append is made
    # explicit rather than being reported as a failed/no-op operation.
    assert Path(candidate["vault_path"]).is_file()
    status = vault.get_evidence_outbox_status()
    assert status["pending"] == 1
    assert status["delivered"] >= 2  # project and section creation already recorded
    pending = status["pending_items"][0]
    assert pending["event_type"] == "CANDIDATE_ADDED"
    assert pending["file_id"] == candidate["id"]

    restarted_runtime = server.build_canonical_v21_runtime(tmp_path)
    restarted_vault = restarted_runtime[1]
    refreshed = restarted_vault._find_file(project["id"], section["id"], candidate["id"])
    assert refreshed["id"] == candidate["id"]
    assert Path(refreshed["vault_path"]).is_file()

    report = restarted_vault.flush_evidence_outbox()
    assert report["delivered"] == 1
    assert report["pending"] == 0
    assert restarted_vault.get_evidence_outbox_status()["pending"] == 0

    events = [
        event
        for event in restarted_runtime[0].iter_events()
        if event["event_type"] == "CANDIDATE_ADDED"
        and event["payload"].get("file_id") == candidate["id"]
    ]
    assert len(events) == 1


def test_pending_candidate_intake_evidence_blocks_trust_expansion_without_consuming_token(tmp_path: Path) -> None:
    canonical = CanonicalEvidenceAdapter(tmp_path, session_id="wallet-main")
    flaky = FailOnceCustodyEvidence(
        canonical, "CANDIDATE_ADDED", fail_until_released=True
    )
    runtime = server.build_canonical_v21_runtime(tmp_path)
    # Replace the runtime's evidence writer before creating the candidate.
    runtime[1].attach_blackbox(flaky)
    runtime[3].evidence = flaky

    vault = runtime[1]
    project = vault.create_project("Pending Trust")
    section = vault.create_section(project["id"], "Core")
    candidate = vault.add_candidate(
        project["id"], section["id"], str(_source(tmp_path, "blocked.txt", "candidate"))
    )
    identity, token = _human_and_token(runtime, project["id"], section["id"], candidate["id"])

    with pytest.raises(PromotionTransactionError, match="pending canonical evidence"):
        runtime[3].promote_to_prime(
            project_id=project["id"],
            section_id=section["id"],
            candidate_id=candidate["id"],
            ceremony_token=token,
            session_id=identity.session_id,
            reason="must not outrun evidence",
        )

    token_record = vault.ceremony_ledger.get_record(
        vault.ceremony_ledger.parse_token_id(token)
    )
    assert token_record["consumed_at"] is None
    assert vault._find_file(project["id"], section["id"], candidate["id"])["state"] == "candidate"

    flaky.released = True
    assert vault.flush_evidence_outbox()["pending"] == 0
    completed = runtime[3].promote_to_prime(
        project_id=project["id"],
        section_id=section["id"],
        candidate_id=candidate["id"],
        ceremony_token=token,
        session_id=identity.session_id,
        reason="evidence caught up",
    )
    assert completed["result"]["state"] == "prime"


class AppendThenTripEvidence:
    def __init__(self, delegate: CanonicalEvidenceAdapter, event_type: str, trip: dict) -> None:
        self.delegate = delegate
        self.event_type = event_type
        self.trip = trip

    def __getattr__(self, name):
        return getattr(self.delegate, name)

    def write_custody_event(self, event_type: str, summary: str, **extra):
        result = self.delegate.write_custody_event(event_type, summary, **extra)
        if event_type == self.event_type:
            self.trip["fail_next_catalog_ack"] = True
        return result


def _matching_events(evidence: CanonicalEvidenceAdapter, event_type: str, file_id: str):
    return [
        event
        for event in evidence.iter_events()
        if event["event_type"] == event_type
        and event["payload"].get("file_id") == file_id
    ]


def test_crash_after_canonical_append_before_outbox_ack_retries_without_duplicate_fact(
    tmp_path: Path, monkeypatch
) -> None:
    from iteration_wallet import vault_v21 as vault_module
    from iteration_wallet.durable_io import DurableIOError

    canonical = CanonicalEvidenceAdapter(tmp_path, session_id="wallet-main")
    trip = {"fail_next_catalog_ack": False}
    evidence = AppendThenTripEvidence(canonical, "CANDIDATE_ADDED", trip)
    vault = VaultEngine(tmp_path, blackbox=evidence)
    project = vault.create_project("Ack Crash")
    section = vault.create_section(project["id"], "Core")

    real_atomic_json = vault_module.atomic_json

    def fail_ack_once(path, payload):
        if Path(path) == vault.state_file and trip["fail_next_catalog_ack"]:
            trip["fail_next_catalog_ack"] = False
            raise DurableIOError("simulated crash before outbox acknowledgement")
        return real_atomic_json(path, payload)

    monkeypatch.setattr(vault_module, "atomic_json", fail_ack_once)
    candidate = vault.add_candidate(
        project["id"], section["id"], str(_source(tmp_path, "ack.txt", "candidate"))
    )
    monkeypatch.setattr(vault_module, "atomic_json", real_atomic_json)

    assert vault.get_evidence_outbox_status()["pending"] == 1
    assert len(_matching_events(canonical, "CANDIDATE_ADDED", candidate["id"])) == 1

    restarted = VaultEngine(tmp_path, blackbox=canonical)
    report = restarted.flush_evidence_outbox()
    assert report["pending"] == 0
    assert restarted.get_evidence_outbox_status()["pending"] == 0
    assert len(_matching_events(canonical, "CANDIDATE_ADDED", candidate["id"])) == 1


def _outbox_flush_worker(root_text: str, barrier, queue) -> None:
    try:
        root = Path(root_text)
        evidence = CanonicalEvidenceAdapter(root, session_id="wallet-main")
        vault = VaultEngine(root, blackbox=evidence)
        barrier.wait(timeout=20)
        queue.put({"ok": True, "report": vault.flush_evidence_outbox()})
    except BaseException as exc:
        queue.put({"ok": False, "error": f"{type(exc).__name__}: {exc}"})


def test_concurrent_outbox_flush_has_one_canonical_delivery(tmp_path: Path) -> None:
    import multiprocessing as mp

    canonical = CanonicalEvidenceAdapter(tmp_path, session_id="wallet-main")
    flaky = FailOnceCustodyEvidence(
        canonical, "CANDIDATE_ADDED", fail_until_released=True
    )
    vault = VaultEngine(tmp_path, blackbox=flaky)
    project = vault.create_project("Concurrent Delivery")
    section = vault.create_section(project["id"], "Core")
    candidate = vault.add_candidate(
        project["id"], section["id"], str(_source(tmp_path, "delivery.txt", "candidate"))
    )
    assert vault.get_evidence_outbox_status()["pending"] == 1

    context = mp.get_context("spawn")
    barrier = context.Barrier(2)
    queue = context.Queue()
    processes = [
        context.Process(target=_outbox_flush_worker, args=(str(tmp_path), barrier, queue))
        for _ in range(2)
    ]
    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=40)
    assert not any(process.is_alive() for process in processes)
    assert all(process.exitcode == 0 for process in processes)
    results = [queue.get(timeout=5) for _ in processes]
    assert all(result["ok"] for result in results), results
    assert sum(result["report"]["delivered"] for result in results) == 1
    queue.close()
    queue.join_thread()
    for process in processes:
        process.close()

    fresh_evidence = CanonicalEvidenceAdapter(tmp_path, session_id="wallet-main")
    fresh_vault = VaultEngine(tmp_path, blackbox=fresh_evidence)
    assert fresh_vault.get_evidence_outbox_status()["pending"] == 0
    assert len(_matching_events(fresh_evidence, "CANDIDATE_ADDED", candidate["id"])) == 1


def test_malformed_pending_outbox_entry_fails_closed_and_remains_visible(tmp_path: Path) -> None:
    evidence = CanonicalEvidenceAdapter(tmp_path, session_id="wallet-main")
    vault = VaultEngine(tmp_path, blackbox=evidence)
    project = vault.create_project("Malformed Outbox")
    section = vault.create_section(project["id"], "Core")

    with vault.catalog_transaction():
        vault._state["evidence_outbox"].append(
            {
                "outbox_id": "broken-entry",
                "status": "pending",
                "project_id": project["id"],
                "section_id": section["id"],
                "file_id": "future-file",
                # event_type and summary deliberately absent
            }
        )
        vault._save()

    report = vault.flush_evidence_outbox()
    assert report["delivered"] == 0
    assert report["pending"] == 1
    assert report["errors"]
    status = vault.get_evidence_outbox_status()
    assert status["pending_items"][0]["outbox_id"] == "broken-entry"
