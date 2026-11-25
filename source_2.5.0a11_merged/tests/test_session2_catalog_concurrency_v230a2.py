from __future__ import annotations

from pathlib import Path

import pytest

from iteration_wallet import server
from iteration_wallet.vault_v21 import VaultEngine


def _source(root: Path, name: str, text: str) -> Path:
    path = root / name
    path.write_text(text, encoding="utf-8")
    return path


def _human(runtime, actor_id: str):
    _, vault, humans, _ = runtime
    identity = humans.issue_identity_session(
        actor_id=actor_id,
        actor_kind="human",
        verified_methods=["human_ceremony", "typing_challenge"],
    )
    vault.open_vault()
    return identity


def _token(runtime, identity, project_id: str, section_id: str, candidate_id: str) -> str:
    _, vault, _, _ = runtime
    return vault.issue_ceremony_token(
        "promote_candidate_to_prime",
        identity.session_id,
        actor_id=identity.actor_id,
        project_id=project_id,
        section_id=section_id,
        object_id=candidate_id,
    )["ceremony_token"]


def test_two_stale_runtimes_cannot_lose_promotions_in_different_sections(tmp_path: Path) -> None:
    seed = server.build_canonical_v21_runtime(tmp_path)
    _, seed_vault, _, _ = seed
    project = seed_vault.create_project("Concurrent Project")
    section_a = seed_vault.create_section(project["id"], "A")
    section_b = seed_vault.create_section(project["id"], "B")
    candidate_a = seed_vault.add_candidate(
        project["id"], section_a["id"], str(_source(tmp_path, "a.txt", "A"))
    )
    candidate_b = seed_vault.add_candidate(
        project["id"], section_b["id"], str(_source(tmp_path, "b.txt", "B"))
    )

    runtime_a = server.build_canonical_v21_runtime(tmp_path)
    runtime_b = server.build_canonical_v21_runtime(tmp_path)
    identity_a = _human(runtime_a, "human-a")
    identity_b = _human(runtime_b, "human-b")
    token_a = _token(runtime_a, identity_a, project["id"], section_a["id"], candidate_a["id"])
    token_b = _token(runtime_b, identity_b, project["id"], section_b["id"], candidate_b["id"])

    runtime_a[3].promote_to_prime(
        project_id=project["id"], section_id=section_a["id"], candidate_id=candidate_a["id"],
        ceremony_token=token_a, session_id=identity_a.session_id, reason="A",
    )
    runtime_b[3].promote_to_prime(
        project_id=project["id"], section_id=section_b["id"], candidate_id=candidate_b["id"],
        ceremony_token=token_b, session_id=identity_b.session_id, reason="B",
    )

    fresh = VaultEngine(tmp_path, blackbox=runtime_b[0])
    assert fresh.get_section(project["id"], section_a["id"])["prime"] == candidate_a["id"]
    assert fresh.get_section(project["id"], section_b["id"])["prime"] == candidate_b["id"]
    assert fresh.verify_custody_integrity()["ok"] is True


def test_second_stale_runtime_reloads_before_promoting_in_same_section(tmp_path: Path) -> None:
    seed = server.build_canonical_v21_runtime(tmp_path)
    _, seed_vault, _, _ = seed
    project = seed_vault.create_project("Same Section")
    section = seed_vault.create_section(project["id"], "Core")
    candidate_a = seed_vault.add_candidate(
        project["id"], section["id"], str(_source(tmp_path, "one.txt", "one"))
    )
    candidate_b = seed_vault.add_candidate(
        project["id"], section["id"], str(_source(tmp_path, "two.txt", "two"))
    )

    runtime_a = server.build_canonical_v21_runtime(tmp_path)
    runtime_b = server.build_canonical_v21_runtime(tmp_path)
    identity_a = _human(runtime_a, "human-a")
    identity_b = _human(runtime_b, "human-b")
    token_a = _token(runtime_a, identity_a, project["id"], section["id"], candidate_a["id"])
    token_b = _token(runtime_b, identity_b, project["id"], section["id"], candidate_b["id"])

    runtime_a[3].promote_to_prime(
        project_id=project["id"], section_id=section["id"], candidate_id=candidate_a["id"],
        ceremony_token=token_a, session_id=identity_a.session_id, reason="first",
    )
    runtime_b[3].promote_to_prime(
        project_id=project["id"], section_id=section["id"], candidate_id=candidate_b["id"],
        ceremony_token=token_b, session_id=identity_b.session_id, reason="second",
    )

    fresh = VaultEngine(tmp_path, blackbox=runtime_b[0])
    fresh_section = fresh.get_section(project["id"], section["id"])
    fresh_a = fresh._find_file(project["id"], section["id"], candidate_a["id"])
    fresh_b = fresh._find_file(project["id"], section["id"], candidate_b["id"])
    assert fresh_section["prime"] == candidate_b["id"]
    assert candidate_a["id"] in fresh_section["archive"]
    assert fresh_a["state"] == "archived"
    assert fresh_b["state"] == "prime"
    assert fresh.verify_custody_integrity()["ok"] is True


def _promotion_worker(
    root_text: str,
    project_id: str,
    section_id: str,
    candidate_id: str,
    actor_id: str,
    barrier,
    queue,
) -> None:
    try:
        runtime = server.build_canonical_v21_runtime(Path(root_text))
        identity = _human(runtime, actor_id)
        token = _token(runtime, identity, project_id, section_id, candidate_id)
        barrier.wait(timeout=20)
        result = runtime[3].promote_to_prime(
            project_id=project_id,
            section_id=section_id,
            candidate_id=candidate_id,
            ceremony_token=token,
            session_id=identity.session_id,
            reason=f"concurrent:{actor_id}",
        )
        queue.put({"ok": True, "receipt_id": result["receipt"]["receipt_id"]})
    except BaseException as exc:  # process boundary must report every failure
        queue.put({"ok": False, "error": f"{type(exc).__name__}: {exc}"})


def _run_spawned_promotions(tmp_path: Path, jobs: list[tuple[str, str, str, str]]):
    import multiprocessing as mp

    context = mp.get_context("spawn")
    barrier = context.Barrier(len(jobs))
    queue = context.Queue()
    processes = [
        context.Process(
            target=_promotion_worker,
            args=(str(tmp_path), project_id, section_id, candidate_id, actor_id, barrier, queue),
        )
        for project_id, section_id, candidate_id, actor_id in jobs
    ]
    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=40)
    assert not any(process.is_alive() for process in processes)
    assert all(process.exitcode == 0 for process in processes)
    results = [queue.get(timeout=5) for _ in jobs]
    assert all(item["ok"] for item in results), results
    assert len({item["receipt_id"] for item in results}) == len(jobs)
    queue.close()
    queue.join_thread()
    for process in processes:
        process.close()
    return results


def test_spawned_processes_preserve_promotions_in_different_sections(tmp_path: Path) -> None:
    seed = server.build_canonical_v21_runtime(tmp_path)
    vault = seed[1]
    project = vault.create_project("Spawned Sections")
    section_a = vault.create_section(project["id"], "A")
    section_b = vault.create_section(project["id"], "B")
    candidate_a = vault.add_candidate(
        project["id"], section_a["id"], str(_source(tmp_path, "spawn-a.txt", "A"))
    )
    candidate_b = vault.add_candidate(
        project["id"], section_b["id"], str(_source(tmp_path, "spawn-b.txt", "B"))
    )

    _run_spawned_promotions(
        tmp_path,
        [
            (project["id"], section_a["id"], candidate_a["id"], "spawn-a"),
            (project["id"], section_b["id"], candidate_b["id"], "spawn-b"),
        ],
    )

    fresh = VaultEngine(tmp_path, blackbox=server.build_canonical_v21_runtime(tmp_path)[0])
    assert fresh.get_section(project["id"], section_a["id"])["prime"] == candidate_a["id"]
    assert fresh.get_section(project["id"], section_b["id"])["prime"] == candidate_b["id"]
    assert fresh.verify_custody_integrity()["ok"] is True


def test_spawned_processes_serialize_two_promotions_in_one_section(tmp_path: Path) -> None:
    seed = server.build_canonical_v21_runtime(tmp_path)
    vault = seed[1]
    project = vault.create_project("Spawned Same Section")
    section = vault.create_section(project["id"], "Core")
    candidate_a = vault.add_candidate(
        project["id"], section["id"], str(_source(tmp_path, "spawn-one.txt", "one"))
    )
    candidate_b = vault.add_candidate(
        project["id"], section["id"], str(_source(tmp_path, "spawn-two.txt", "two"))
    )

    _run_spawned_promotions(
        tmp_path,
        [
            (project["id"], section["id"], candidate_a["id"], "spawn-one"),
            (project["id"], section["id"], candidate_b["id"], "spawn-two"),
        ],
    )

    fresh_runtime = server.build_canonical_v21_runtime(tmp_path)
    fresh = fresh_runtime[1]
    final_section = fresh.get_section(project["id"], section["id"])
    assert final_section["prime"] in {candidate_a["id"], candidate_b["id"]}
    archived = set(final_section["archive"])
    assert archived == ({candidate_a["id"], candidate_b["id"]} - {final_section["prime"]})
    assert fresh.verify_custody_integrity()["ok"] is True
    assert fresh_runtime[0].verify_chain()["ok"] is True


def test_disk_full_during_catalog_commit_freezes_ambiguous_promotion(tmp_path: Path, monkeypatch) -> None:
    from iteration_wallet import vault_v21 as vault_module
    from iteration_wallet.durable_io import DurableIOError
    from iteration_wallet.promotion_transaction import PromotionTransactionError

    runtime = server.build_canonical_v21_runtime(tmp_path)
    evidence, vault, humans, coordinator = runtime
    project = vault.create_project("Disk Full")
    section = vault.create_section(project["id"], "Core")
    candidate = vault.add_candidate(
        project["id"], section["id"], str(_source(tmp_path, "disk-full.txt", "candidate"))
    )
    identity = _human(runtime, "disk-full-human")
    token = _token(runtime, identity, project["id"], section["id"], candidate["id"])

    real_atomic_json = vault_module.atomic_json

    def fail_catalog_commit(path, payload):
        if Path(path) == vault.state_file:
            raise DurableIOError("simulated ENOSPC during state_v21.json commit")
        return real_atomic_json(path, payload)

    monkeypatch.setattr(vault_module, "atomic_json", fail_catalog_commit)
    try:
        with pytest.raises(PromotionTransactionError, match="simulated ENOSPC"):
            coordinator.promote_to_prime(
                project_id=project["id"],
                section_id=section["id"],
                candidate_id=candidate["id"],
                ceremony_token=token,
                session_id=identity.session_id,
                reason="must freeze",
            )
    finally:
        monkeypatch.setattr(vault_module, "atomic_json", real_atomic_json)

    restarted = server.build_canonical_v21_runtime(tmp_path)
    report = restarted[3].reconcile_pending()
    assert report["ambiguous"] == 1
    assert report["reconciled"] == 0
    assert report["failed"] == 0
    fresh_candidate = restarted[1]._find_file(project["id"], section["id"], candidate["id"])
    assert fresh_candidate["trust_locked"] is True
    assert fresh_candidate["trust_lock_reason"] == "promotion_reconciliation_required"
    fresh_section = restarted[1].get_section(project["id"], section["id"])
    assert fresh_section["reconciliation_required"] is True
    assert restarted[0].list_human_intent_receipts() == []
