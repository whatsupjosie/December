from __future__ import annotations

import os
from pathlib import Path

import pytest

from iteration_wallet import durable_io
from iteration_wallet.durable_io import atomic_json
from iteration_wallet.oubliette import inspect_static
from iteration_wallet.runtime_continuity import capture_snapshot, compare_snapshots


def test_unicode_and_long_path_static_observation(tmp_path: Path):
    long_component = "長い名前_" + ("é" * 90)
    app = tmp_path / "程序_Δ" / long_component
    app.mkdir(parents=True)
    candidate = app / "候補_script.py"
    candidate.write_text("print('静的観測')\n", encoding="utf-8")

    inspection = inspect_static(candidate, actor_kind="human", allowed_root=tmp_path)
    reference = capture_snapshot(app, root_label="unicode-long-path")
    candidate.write_text("print('変更')\n", encoding="utf-8")
    observed = capture_snapshot(
        app,
        root_label="unicode-long-path",
        previous_snapshot_id=reference.snapshot_id,
    )
    assessment = compare_snapshots(reference, observed)

    assert inspection.target_executed is False
    assert inspection.target_sha256
    assert assessment.to_dict()["counts"]["unexplained"] == 1
    assert "候補_script.py" in {item.relative_path for item in observed.entries}


def test_permission_denied_during_atomic_write_is_visible_and_not_reported_as_success(tmp_path: Path, monkeypatch):
    target = tmp_path / "authority.json"
    original_open = durable_io._open_exclusive_private

    def deny_temp(path: Path):
        if path.name.startswith(".authority.json") and path.name.endswith(".tmp"):
            raise PermissionError("simulated read-only media")
        return original_open(path)

    monkeypatch.setattr(durable_io, "_open_exclusive_private", deny_temp)
    with pytest.raises(PermissionError, match="read-only"):
        atomic_json(target, {"state": "candidate"})
    assert target.exists() is False


def test_read_only_candidate_can_be_inspected_without_write_attempt(tmp_path: Path):
    target = tmp_path / "read_only_candidate.txt"
    target.write_text("evidence", encoding="utf-8")
    target.chmod(0o444)
    before_mode = stat_mode = target.stat().st_mode
    before = target.read_bytes()

    report = inspect_static(target, actor_kind="local_system", allowed_root=tmp_path)

    assert report.target_modified is False
    assert target.read_bytes() == before
    assert target.stat().st_mode == before_mode
