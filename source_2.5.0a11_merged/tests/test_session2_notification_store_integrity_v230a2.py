from __future__ import annotations

import json
from pathlib import Path

import pytest

from iteration_wallet.canonical_evidence import CanonicalEvidenceAdapter
from iteration_wallet.notification_manager import (
    NotificationError,
    NotificationLevel,
    NotificationManager,
)


def test_long_lived_manager_reads_notifications_created_by_another_runtime(tmp_path: Path) -> None:
    first = NotificationManager(tmp_path, blackbox=CanonicalEvidenceAdapter(tmp_path, session_id="one"))
    second = NotificationManager(tmp_path, blackbox=CanonicalEvidenceAdapter(tmp_path, session_id="two"))
    assert second.get_inbox("josie") == []  # warm any internal read state

    created = first.create_notification("josie", "Candidate is ready.", NotificationLevel.INFO)
    assert created is not None
    inbox = second.get_inbox("josie")
    assert [item["notification_id"] for item in inbox] == [created.notification_id]


def test_corrupt_notification_is_reported_not_silently_hidden(tmp_path: Path) -> None:
    manager = NotificationManager(tmp_path)
    (manager.notification_dir / "broken.json").write_text('{"notification_id":"broken",', encoding="utf-8")

    with pytest.raises(NotificationError, match="unreadable notification"):
        manager.get_inbox("josie")


def test_duplicate_notification_keys_are_rejected(tmp_path: Path) -> None:
    manager = NotificationManager(tmp_path)
    payload = (
        '{"notification_id":"notice1","notification_id":"notice2",'
        '"recipient_id":"josie","message":"hello","level":"info",'
        '"created_at":"2026-07-20T00:00:00"}'
    )
    (manager.notification_dir / "notice1.json").write_text(payload, encoding="utf-8")

    with pytest.raises(NotificationError, match="unreadable notification"):
        manager.get_inbox("josie")


def test_notification_id_must_match_storage_name(tmp_path: Path) -> None:
    manager = NotificationManager(tmp_path)
    record = {
        "notification_id": "other-id",
        "recipient_id": "josie",
        "message": "hello",
        "level": "info",
        "action_url": None,
        "created_at": "2026-07-20T00:00:00",
        "read_at": None,
        "action_taken": None,
        "blackbox_event_id": None,
    }
    (manager.notification_dir / "notice1.json").write_text(json.dumps(record), encoding="utf-8")

    with pytest.raises(NotificationError, match="does not match its storage name"):
        manager.get_inbox("josie")


def test_corrupt_approval_cannot_disappear_from_status_report(tmp_path: Path) -> None:
    manager = NotificationManager(tmp_path)
    (manager.approval_dir / "broken.json").write_text('{"approval_id":"broken",', encoding="utf-8")

    with pytest.raises(NotificationError, match="unreadable approval record"):
        manager.get_notification_status()


def _create_one_notification(root: str, start, queue, recipient: str) -> None:
    manager = NotificationManager(Path(root))
    manager._limits["total_system_max"] = 1
    start.wait()
    created = manager.create_notification(recipient, "one", NotificationLevel.INFO)
    queue.put(created.notification_id if created else None)


def test_concurrent_notification_creation_respects_global_limit(tmp_path: Path) -> None:
    import multiprocessing as mp

    ctx = mp.get_context("spawn")
    start = ctx.Event()
    queue = ctx.Queue()
    workers = [
        ctx.Process(target=_create_one_notification, args=(str(tmp_path), start, queue, recipient))
        for recipient in ("josie", "alex")
    ]
    for worker in workers:
        worker.start()
    start.set()
    results = [queue.get(timeout=20) for _ in workers]
    for worker in workers:
        worker.join(timeout=20)
        assert worker.exitcode == 0
    queue.close()
    queue.join_thread()
    for worker in workers:
        worker.close()

    assert sum(value is not None for value in results) == 1
    manager = NotificationManager(tmp_path)
    assert len(manager._get_all_notifications()) == 1


def test_notification_create_is_exclusive_and_cannot_overwrite_existing_record(tmp_path: Path) -> None:
    from iteration_wallet.notification_manager import Notification

    manager = NotificationManager(tmp_path)
    first = Notification(
        recipient_id="josie",
        message="first",
        level=NotificationLevel.INFO,
        notification_id="notice1",
    )
    second = Notification(
        recipient_id="josie",
        message="second",
        level=NotificationLevel.INFO,
        notification_id="notice1",
    )
    manager._save_notification(first, create=True)
    with pytest.raises(NotificationError, match="notification_id already exists"):
        manager._save_notification(second, create=True)
    assert manager._load_notification_file(manager._notification_path("notice1")).message == "first"


def test_notification_creation_reads_one_coherent_snapshot_at_capacity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from datetime import datetime, timedelta

    from iteration_wallet.notification_manager import Notification

    manager = NotificationManager(tmp_path)
    base = datetime(2026, 7, 20, 0, 0, 0)
    for index in range(manager._limits["total_system_max"]):
        manager._save_notification(
            Notification(
                recipient_id=f"user-{index}",
                message=f"notice-{index}",
                level=NotificationLevel.INFO,
                notification_id=f"notice{index:04d}",
                created_at=base + timedelta(microseconds=index),
            ),
            create=True,
        )

    reads = 0
    original = manager._load_notification_file

    def counted(path: Path):
        nonlocal reads
        reads += 1
        return original(path)

    monkeypatch.setattr(manager, "_load_notification_file", counted)
    assert manager.create_notification("extra", "blocked", NotificationLevel.INFO) is None
    assert reads == manager._limits["total_system_max"]
