"""Regression tests for Iteration Wallet Session One constitutional cleanup."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from iteration_wallet import cli
from iteration_wallet.guard import CommitGuard
from iteration_wallet.notification_manager import NotificationLevel, NotificationManager


def test_source_checkout_private_alpha_wrapper_runs(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[1]
    run_root = tmp_path / "run"
    report_dir = tmp_path / "report"
    result = subprocess.run(
        [
            sys.executable,
            str(repo_root / "tools" / "private_alpha_flow_runner.py"),
            "--run-root",
            str(run_root),
            "--report-dir",
            str(report_dir),
        ],
        cwd=repo_root,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Bounded canonical promotion flow PASS" in result.stdout
    assert (report_dir / "private_alpha_flow_report.json").is_file()


def test_commit_guard_is_static_and_requires_caller_supplied_git_facts():
    guard_source = Path(__file__).resolve().parents[1] / "iteration_wallet" / "guard.py"
    source = guard_source.read_text(encoding="utf-8")
    assert "import subprocess" not in source
    assert "subprocess." not in source

    guard = CommitGuard(
        project="demo",
        staged_files=["src/app.py", ".env"],
        git_user="Josie",
        git_branch="main",
    )
    assessment = guard.assess()
    assert assessment["allowed"] is False
    assert assessment["blocked"] == [".env"]
    assert assessment["project"] == "demo"


def test_legacy_hook_commands_refuse_without_mutating_repository(tmp_path: Path, monkeypatch):
    git_hooks = tmp_path / ".git" / "hooks"
    git_hooks.mkdir(parents=True)
    hook = git_hooks / "pre-commit"
    original = "#!/bin/sh\necho original\n"
    hook.write_text(original, encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    with pytest.raises(cli.ExternalIntegrationRequired):
        cli.cmd_install_hook(SimpleNamespace(project="demo"))
    assert hook.read_text(encoding="utf-8") == original

    with pytest.raises(cli.ExternalIntegrationRequired):
        cli.cmd_uninstall_hook(SimpleNamespace())
    assert hook.read_text(encoding="utf-8") == original


def test_priority_notification_archives_instead_of_deleting(tmp_path: Path):
    limits = {
        "per_recipient_max": 5,
        "total_system_max": 3,
    }
    (tmp_path / "notification_limits.json").write_text(json.dumps(limits), encoding="utf-8")
    nm = NotificationManager(tmp_path)

    for index in range(3):
        assert nm.create_notification(f"user-{index}", f"info-{index}", NotificationLevel.INFO)

    critical = nm.create_notification("head-user", "critical", NotificationLevel.CRITICAL)
    assert critical is not None

    active = list((tmp_path / "notifications").glob("*.json"))
    archived = list((tmp_path / "notification_archive").glob("*.json"))
    assert len(active) == 3
    assert len(archived) == 1
    assert len(active) + len(archived) == 4

    archived_payload = json.loads(archived[0].read_text(encoding="utf-8"))
    assert "auto-suppressed" in (archived_payload.get("action_taken") or "")
    status = nm.get_notification_status()
    assert status["active_notifications"] == 3
    assert status["archived_notifications"] == 1


def test_current_version_and_package_claims_are_consistent():
    import iteration_wallet
    from iteration_wallet import server

    repo_root = Path(__file__).resolve().parents[1]
    setup_text = (repo_root / "setup.py").read_text(encoding="utf-8")
    requirements = (repo_root / "requirements.txt").read_text(encoding="utf-8")
    from iteration_wallet.version import WALLET_VERSION
    assert iteration_wallet.__version__ == WALLET_VERSION
    assert "version=WALLET_VERSION" in setup_text
    assert server.app.version == WALLET_VERSION
    assert "watchdog" not in requirements.lower()
    assert "watchdog" not in setup_text.lower()


def test_v21_public_surface_exposes_exact_preserving_state_transition_routes_only():
    from iteration_wallet import server

    paths = set(server.app.openapi()["paths"])
    exact = {
        "/api/v21/projects/{project_id}/sections/{section_id}/objects/{object_id}/retire",
        "/api/v21/projects/{project_id}/sections/{section_id}/objects/{object_id}/restore",
    }
    assert exact <= paths
    forbidden_fragments = (
        "/restore-from-removed",
        "/files/{file_id}/restore",
        "/files/{file_id}/remove",
        "/files/{file_id}/release",
    )
    assert all(not any(fragment in path for fragment in forbidden_fragments) for path in paths)
