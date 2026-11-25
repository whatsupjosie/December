from __future__ import annotations

from pathlib import Path

from blackbox_plugin.cli import main


def test_sentinel_commission_normalizes_human_actor_without_traceback(tmp_path, capsys):
    target = tmp_path / "target"
    target.mkdir()
    (target / "file.txt").write_text("hello", encoding="utf-8")
    manifest = tmp_path / "reference.json"
    rc = main([
        "sentinel-commission",
        "--target", str(target),
        "--manifest", str(manifest),
        "--human-actor", "josie",
        "--confirm-human",
    ])
    assert rc == 0
    assert manifest.exists()
    assert '"ok": true' in capsys.readouterr().out.lower()


def test_sentinel_commission_missing_confirmation_is_controlled_error(tmp_path, capsys):
    target = tmp_path / "target"
    target.mkdir()
    (target / "file.txt").write_text("hello", encoding="utf-8")
    manifest = tmp_path / "reference.json"
    rc = main([
        "sentinel-commission",
        "--target", str(target),
        "--manifest", str(manifest),
        "--human-actor", "josie",
    ])
    captured = capsys.readouterr()
    assert rc == 1
    assert "Error:" in captured.out
    assert "Traceback" not in captured.out
    assert not manifest.exists()
