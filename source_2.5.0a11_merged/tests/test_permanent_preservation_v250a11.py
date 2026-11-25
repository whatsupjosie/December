from __future__ import annotations

import ast
from pathlib import Path

from iteration_wallet import server
from iteration_wallet.preservation import (
    BLACKBOX_PRESERVATION_RULE,
    PERMANENT_PRESERVATION_RULE,
    RUNTIME_RESIDUE_RULE,
)


def test_preservation_laws_are_canonical_and_unambiguous():
    assert "remains preserved" in PERMANENT_PRESERVATION_RULE
    assert "remains preserved" in BLACKBOX_PRESERVATION_RULE
    assert "Only program-created, non-authoritative operating residue" in RUNTIME_RESIDUE_RULE


def test_unimplemented_legacy_custody_routes_are_absent():
    paths = set(server.app.openapi()["paths"])
    forbidden = (
        "/files/{file_id}/remove",
        "/files/{file_id}/release",
        "/restore-from-removed",
        "/files/{file_id}/restore",
    )
    assert all(not any(fragment in path for fragment in forbidden) for path in paths)


def test_runtime_residue_module_is_only_production_physical_cleanup_authority():
    root = Path(__file__).resolve().parents[1]
    packages = (
        root / "iteration_wallet",
        root / "iteration_wallet_blackbox",
        root / "blackbox_source" / "blackbox_plugin",
    )
    offenders: list[str] = []
    for path in (candidate for package in packages for candidate in package.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = ""
            if isinstance(func, ast.Attribute):
                root = func.value.id if isinstance(func.value, ast.Name) else ""
                name = f"{root}.{func.attr}" if root else func.attr
            if name in {"os.unlink", "os.remove", "shutil.rmtree"} or (
                isinstance(func, ast.Attribute) and func.attr == "unlink"
            ):
                if path.name != "runtime_residue.py":
                    offenders.append(f"{path.relative_to(root)}:{node.lineno}:{name}")
    assert offenders == []


def test_user_interface_contains_no_destructive_custody_action():
    html = (Path(__file__).resolve().parents[1] / "iteration_wallet" / "static" / "app.html").read_text(
        encoding="utf-8"
    )
    forbidden_phrases = (
        "Delete file",
        "Remove from active",
        "Release from custody",
        "Permanently destroy",
    )
    assert all(phrase.lower() not in html.lower() for phrase in forbidden_phrases)
