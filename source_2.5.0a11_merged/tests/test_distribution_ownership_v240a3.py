from __future__ import annotations

import ast
from pathlib import Path

import iteration_wallet
from blackbox_plugin import __version__ as blackbox_version
from iteration_wallet import server
from iteration_wallet.version import WALLET_VERSION, BLACKBOX_VERSION


ROOT = Path(__file__).resolve().parents[1]


def _setup_call_keywords() -> dict[str, ast.AST]:
    tree = ast.parse((ROOT / "setup.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "setup":
            return {item.arg: item.value for item in node.keywords if item.arg}
    raise AssertionError("setup() call not found")


def test_active_versions_are_distinct_and_coherent():
    assert iteration_wallet.__version__ == WALLET_VERSION
    assert server.app.version == WALLET_VERSION
    assert blackbox_version == BLACKBOX_VERSION


def test_wallet_distribution_does_not_own_blackbox_plugin():
    text = (ROOT / "setup.py").read_text(encoding="utf-8")
    assert '"blackbox_plugin", "blackbox_plugin.*"' in text
    assert f'f"bbx1-iteration-wallet-plugin=={{BLACKBOX_VERSION}}"' in text


def test_dependency_pin_declares_separate_installed_owners():
    import json

    pin = json.loads((ROOT / "BLACKBOX_DEPENDENCY_PIN.json").read_text(encoding="utf-8"))
    assert pin["blackbox_version"] == BLACKBOX_VERSION
    assert pin["core_package_owner"] == "bbx1-iteration-wallet-plugin"
    assert pin["wallet_adapter_owner"] == "iteration-wallet"
    assert pin["wallet_wheel_contains_blackbox_core"] is False
    assert pin["blackbox_wheel_contains_wallet_adapter"] is False
    assert pin["client_schema"] == "bbx1-client/1"
