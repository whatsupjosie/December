from __future__ import annotations

import json
from pathlib import Path

import pytest

from iteration_wallet import durable_io


def test_failed_atomic_write_preserves_temporary_in_recovery_storage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "authority.json"
    real_replace = durable_io.os.replace
    calls = 0

    def fail_target_replace_then_allow_preservation(source, destination):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("simulated target replacement failure")
        return real_replace(source, destination)

    monkeypatch.setattr(durable_io.os, "replace", fail_target_replace_then_allow_preservation)
    with pytest.raises(OSError, match="simulated target replacement failure"):
        durable_io.atomic_json(target, {"state": "candidate"})

    assert not target.exists()
    recovery = list((tmp_path / ".failed_atomic_writes").glob("authority.json.*.failed"))
    assert len(recovery) == 1
    assert json.loads(recovery[0].read_text(encoding="utf-8")) == {"state": "candidate"}
    assert not list(tmp_path.glob(".authority.json.*.tmp"))


def test_failed_atomic_write_leaves_unique_temp_when_recovery_move_also_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "authority.json"

    def always_fail_replace(source, destination):
        raise OSError("simulated storage failure")

    monkeypatch.setattr(durable_io.os, "replace", always_fail_replace)
    with pytest.raises(OSError, match="simulated storage failure"):
        durable_io.atomic_json(target, {"state": "candidate"})

    abandoned = list(tmp_path.glob(".authority.json.*.tmp"))
    assert len(abandoned) == 1
    assert json.loads(abandoned[0].read_text(encoding="utf-8")) == {"state": "candidate"}
