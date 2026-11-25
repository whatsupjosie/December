from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from blackbox_plugin import EvidenceEvent, SegmentedBlackBoxRecorder, verify_session
from blackbox_plugin.errors import RecordValidationError


def _event(index: int, *, operation_id: str | None = None) -> EvidenceEvent:
    return EvidenceEvent(
        event_type="part2.concurrent_append",
        source="test-suite",
        actor="system:test",
        subject_id="candidate",
        operation_id=operation_id or f"op-{index}",
        payload={"index": index},
    )


@pytest.mark.parametrize(
    "session_id",
    ["../escape", "a/b", r"a\\b", "/absolute", "C:drive", ".", "..", "trailing."],
)
def test_session_storage_id_rejects_path_syntax(tmp_path: Path, session_id: str) -> None:
    with pytest.raises(RecordValidationError):
        SegmentedBlackBoxRecorder(tmp_path, session_id)


def test_existing_session_symlink_cannot_escape_storage_root(tmp_path: Path) -> None:
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()
    try:
        (sessions / "escaped").symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("directory symlinks unavailable")
    with pytest.raises(RecordValidationError):
        SegmentedBlackBoxRecorder(tmp_path, "escaped")


def test_two_stale_recorders_reload_authoritative_head_under_lock(tmp_path: Path) -> None:
    first = SegmentedBlackBoxRecorder(tmp_path, "shared")
    second = SegmentedBlackBoxRecorder(tmp_path, "shared")

    receipt_0 = first.append(_event(0))
    receipt_1 = second.append(_event(1))

    assert receipt_0.sequence == 0
    assert receipt_1.sequence == 1
    result = verify_session(tmp_path / "sessions" / "shared")
    assert result.ok, result.errors
    records = tuple(first.iter_records())
    assert [record["seq"] for record in records] == [0, 1]


def test_checkpoint_files_are_unique_and_write_once(tmp_path: Path) -> None:
    recorder = SegmentedBlackBoxRecorder(tmp_path, "checkpointed")
    recorder.append(_event(0))

    first_id = recorder.checkpoint()
    first_path = recorder.checkpoint_dir / f"{first_id}.json"
    first_bytes = first_path.read_bytes()

    second_id = recorder.checkpoint()
    second_path = recorder.checkpoint_dir / f"{second_id}.json"

    assert first_id != second_id
    assert first_path.read_bytes() == first_bytes
    assert second_path.exists()


def test_seal_is_idempotent_without_replacement(tmp_path: Path) -> None:
    recorder = SegmentedBlackBoxRecorder(tmp_path, "sealed")
    recorder.append(_event(0))
    path = recorder.seal("first")
    first = path.read_bytes()
    stat = path.stat()

    same_path = recorder.seal("second-should-not-replace")

    assert same_path == path
    assert path.read_bytes() == first
    assert path.stat().st_ino == stat.st_ino


def test_corrupt_derived_head_is_rebuilt_from_verified_tail(tmp_path: Path) -> None:
    recorder = SegmentedBlackBoxRecorder(tmp_path, "derived-head")
    receipt = recorder.append(_event(0))
    state_path = recorder.state_path
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["chain_head"] = "f" * 64
    state["next_sequence"] = 999
    state_path.write_text(json.dumps(state), encoding="utf-8")

    restored = SegmentedBlackBoxRecorder(tmp_path, "derived-head")

    assert restored.previous_hash == receipt.event_hash
    assert restored.next_sequence == 1
    rebuilt = json.loads(state_path.read_text(encoding="utf-8"))
    assert rebuilt["chain_head"] == receipt.event_hash
    assert rebuilt["next_sequence"] == 1


def test_expected_head_is_compared_after_authoritative_reload(tmp_path: Path) -> None:
    first = SegmentedBlackBoxRecorder(tmp_path, "expected-head")
    stale = SegmentedBlackBoxRecorder(tmp_path, "expected-head")
    old_head = stale.previous_hash
    first.append(_event(0))

    from blackbox_plugin.errors import RecorderIntegrityError

    with pytest.raises(RecorderIntegrityError, match="expected previous hash"):
        stale.append(_event(1), expected_previous_hash=old_head)


def test_fsync_failure_does_not_duplicate_a_fully_written_operation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    recorder = SegmentedBlackBoxRecorder(tmp_path, "fsync-recovery")
    original_fsync = os.fsync
    calls = {"count": 0}

    def fail_first_fsync(fd: int) -> None:
        calls["count"] += 1
        if calls["count"] == 1:
            raise OSError("injected fsync failure")
        original_fsync(fd)

    # Keep this fault focused on the evidence segment rather than the derived
    # active-state cache, which also uses fsync during authoritative reload.
    monkeypatch.setattr(recorder, "_write_state", lambda: None)
    monkeypatch.setattr(os, "fsync", fail_first_fsync)
    event = _event(0, operation_id="durable-operation")
    with pytest.raises(OSError, match="injected fsync failure"):
        recorder.append(event)

    retry = recorder.append(event)
    assert retry.duplicate is True
    records = tuple(recorder.iter_records())
    assert len(records) == 1
    assert records[0]["operation_id"] == "durable-operation"
    assert recorder.verify().ok


def test_automatic_checkpoints_are_distinct_immutable_objects(tmp_path: Path) -> None:
    recorder = SegmentedBlackBoxRecorder(tmp_path, "automatic-checkpoints", checkpoint_every_events=1)
    first = recorder.append(_event(0))
    second = recorder.append(_event(1))

    assert first.checkpoint_id
    assert second.checkpoint_id
    assert first.checkpoint_id != second.checkpoint_id
    checkpoint_files = sorted(recorder.checkpoint_dir.glob("checkpoint_*.json"))
    assert len(checkpoint_files) == 2
    assert all(path.stat().st_size > 0 for path in checkpoint_files)


def test_four_processes_append_one_verified_chain(tmp_path: Path) -> None:
    import subprocess
    import sys

    source_root = Path(__file__).resolve().parents[1]
    script = r'''
import sys
from pathlib import Path
from blackbox_plugin import EvidenceEvent, SegmentedBlackBoxRecorder
root = Path(sys.argv[1])
worker = int(sys.argv[2])
recorder = SegmentedBlackBoxRecorder(root, "multiprocess", checkpoint_every_events=1000)
for index in range(15):
    recorder.append(EvidenceEvent(
        event_type="part2.multiprocess_append",
        source=f"worker-{worker}",
        actor="system:test-worker",
        subject_id="candidate",
        operation_id=f"worker-{worker}-op-{index}",
        payload={"worker": worker, "index": index},
    ))
'''
    env = dict(os.environ)
    env["PYTHONPATH"] = str(source_root)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    processes = [
        subprocess.Popen(
            [sys.executable, "-c", script, str(tmp_path), str(worker)],
            cwd=source_root,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for worker in range(4)
    ]
    failures = []
    for process in processes:
        stdout, stderr = process.communicate(timeout=30)
        if process.returncode != 0:
            failures.append((process.returncode, stdout, stderr))
    assert not failures, failures

    session_dir = tmp_path / "sessions" / "multiprocess"
    result = verify_session(session_dir)
    assert result.ok, result.errors
    recorder = SegmentedBlackBoxRecorder(tmp_path, "multiprocess")
    records = tuple(recorder.iter_records())
    assert len(records) == 60
    assert [record["seq"] for record in records] == list(range(60))
    assert len({record["operation_id"] for record in records}) == 60
