from __future__ import annotations

import os
import zipfile
from pathlib import Path

import pytest

from iteration_wallet.oubliette import ActorKind, OublietteError, inspect_static


def test_static_script_inspection_never_executes_or_modifies(tmp_path: Path):
    marker = tmp_path / "executed.txt"
    target = tmp_path / "candidate.py"
    target.write_text(
        f"from pathlib import Path\nPath({str(marker)!r}).write_text('ran')\n"
        "import subprocess\nsubprocess.run(['echo', 'x'])\n",
        encoding="utf-8",
    )
    before = target.read_bytes()

    report = inspect_static(target, actor_kind=ActorKind.HUMAN, allowed_root=tmp_path)

    assert marker.exists() is False
    assert target.read_bytes() == before
    assert report.target_executed is False
    assert report.target_extracted is False
    assert report.target_modified is False
    assert report.custody_changed is False
    assert report.malware_determined is False
    assert "process_launch" in {item.code for item in report.findings}
    assert report.quarantine_review_recommended is True


def test_archive_paths_and_executable_members_are_observed_without_extraction(tmp_path: Path):
    target = tmp_path / "candidate.zip"
    with zipfile.ZipFile(target, "w") as archive:
        archive.writestr("../escape.py", "print('do not run')")
        archive.writestr("safe/readme.txt", "hello")
    before = set(tmp_path.iterdir())

    report = inspect_static(target, actor_kind="human", allowed_root=tmp_path)

    assert set(tmp_path.iterdir()) == before
    codes = {item.code for item in report.findings}
    assert "archive_path_escape" in codes
    assert "archive_executable_member" in codes
    assert report.archive_members_observed == 2


def test_ai_and_bot_cannot_operate_oubliette(tmp_path: Path):
    target = tmp_path / "candidate.txt"
    target.write_text("hello", encoding="utf-8")
    for actor in ("ai", "bot"):
        with pytest.raises(OublietteError, match="prohibited"):
            inspect_static(target, actor_kind=actor, allowed_root=tmp_path)


def test_symlink_target_and_root_escape_fail_closed(tmp_path: Path):
    outside = tmp_path.parent / f"{tmp_path.name}-outside.txt"
    outside.write_text("outside", encoding="utf-8")
    try:
        with pytest.raises(OublietteError, match="escapes"):
            inspect_static(outside, actor_kind="human", allowed_root=tmp_path)
        link = tmp_path / "link.txt"
        try:
            os.symlink(outside, link)
        except (OSError, NotImplementedError):
            pytest.skip("symlink unavailable")
        with pytest.raises(OublietteError, match="symlink"):
            inspect_static(link, actor_kind="human", allowed_root=tmp_path)
    finally:
        if outside.exists():
            outside.unlink()


def test_evidence_envelope_is_bounded_and_does_not_claim_custody_action(tmp_path: Path):
    target = tmp_path / "candidate.txt"
    target.write_text("plain", encoding="utf-8")
    report = inspect_static(target, actor_kind="local_system", allowed_root=tmp_path)

    event = report.canonical_evidence_event(subject_id="candidate:one", operation_id="inspect:one")

    assert event["event_type"] == "oubliette.static_inspection_completed"
    assert event["observation_mode"] == "static_only"
    assert event["payload"]["custody_changed"] is False
    assert event["payload"]["malware_determined"] is False
    assert "target_path" not in event["payload"]
