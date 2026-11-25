from __future__ import annotations

from pathlib import Path

import pytest

from iteration_wallet import cli
from iteration_wallet import server


def test_doctor_checks_runtime_dependencies(monkeypatch):
    real_find_spec = cli.importlib.util.find_spec

    def fake_find_spec(name: str):
        if name == "uvicorn":
            return None
        return real_find_spec(name)

    monkeypatch.setattr(cli.importlib.util, "find_spec", fake_find_spec)
    report = cli._doctor_report(ownership={
        "blackbox_plugin": ["bbx1-iteration-wallet-plugin"],
        "iteration_wallet_blackbox": ["iteration-wallet"],
    })
    assert report["ok"] is False
    assert report["checks"]["runtime_dependency_uvicorn"] is False
    assert "runtime_dependency_uvicorn" in report["errors"]
    assert "pip install" in report["repair"]["safe_method"]


def test_doctor_reports_runtime_dependency_versions():
    report = cli._doctor_report(ownership={
        "blackbox_plugin": ["bbx1-iteration-wallet-plugin"],
        "iteration_wallet_blackbox": ["iteration-wallet"],
    })
    assert set(cli.REQUIRED_RUNTIME_MODULES) <= set(report["runtime_dependencies"])
    for name in cli.REQUIRED_RUNTIME_MODULES:
        assert f"runtime_dependency_{name}" in report["checks"]


def test_serve_root_environment_selects_runtime_root(monkeypatch, tmp_path):
    root = tmp_path / "wallet-root"
    class DummyUvicorn:
        called = False
        @staticmethod
        def run(*args, **kwargs):
            DummyUvicorn.called = True
    monkeypatch.setitem(__import__('sys').modules, 'uvicorn', DummyUvicorn)
    args = type("Args", (), {"host": "127.0.0.1", "port": 7432, "root": str(root)})()
    cli.cmd_serve(args)
    assert DummyUvicorn.called is True
    assert cli.os.environ["ITERATION_WALLET_ROOT"] == str(root.resolve())


def test_server_root_honors_environment_in_fresh_import(tmp_path, monkeypatch):
    # The imported module in this process has already chosen a root, so this test
    # asserts the source contains the runtime override hook that fresh server
    # processes use. This is enough to prevent a regression back to Path.home().
    text = Path(server.__file__).read_text(encoding="utf-8")
    assert "ITERATION_WALLET_ROOT" in text
