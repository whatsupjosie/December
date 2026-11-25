from __future__ import annotations

import ast
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PRODUCTION_ROOTS = (
    ROOT / "iteration_wallet",
    ROOT / "iteration_wallet_blackbox",
    ROOT / "blackbox_source" / "blackbox_plugin",
)
TEXT_SUFFIXES = {
    ".bat",
    ".css",
    ".html",
    ".ini",
    ".js",
    ".json",
    ".md",
    ".ps1",
    ".py",
    ".toml",
    ".txt",
}
EXCLUDED_PARTS = {
    ".pytest_cache",
    "__pycache__",
    "build",
    "dist",
    "historical_alpha",
}


def _active_text_files() -> list[Path]:
    return [
        path
        for path in ROOT.rglob("*")
        if path.is_file()
        and path.suffix.lower() in TEXT_SUFFIXES
        and not (set(path.parts) & EXCLUDED_PARTS)
        and not any(part.endswith(".egg-info") for part in path.parts)
    ]


def _production_python_files() -> list[Path]:
    return [
        path
        for source_root in PRODUCTION_ROOTS
        for path in source_root.rglob("*.py")
        if not (set(path.parts) & EXCLUDED_PARTS)
    ]


def test_active_release_text_has_clean_line_endings() -> None:
    failures: list[str] = []
    for path in _active_text_files():
        content = path.read_bytes()
        relative = path.relative_to(ROOT)
        if content and not content.endswith(b"\n"):
            failures.append(f"{relative}: missing final newline")
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError as exc:
            failures.append(f"{relative}: not UTF-8 ({exc})")
            continue
        for line_number, line in enumerate(text.splitlines(), 1):
            if line.endswith((" ", "\t")):
                failures.append(f"{relative}:{line_number}: trailing whitespace")
    assert not failures, "\n".join(failures)


def test_production_invariants_do_not_depend_on_assert() -> None:
    failures: list[str] = []
    for path in _production_python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Assert):
                failures.append(f"{path.relative_to(ROOT)}:{node.lineno}")
    assert not failures, "production assert statements: " + ", ".join(failures)


def test_production_dict_literals_have_no_duplicate_string_keys() -> None:
    failures: list[str] = []
    for path in _production_python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Dict):
                continue
            keys = [
                key.value
                for key in node.keys
                if isinstance(key, ast.Constant) and isinstance(key.value, str)
            ]
            duplicates = sorted({key for key in keys if keys.count(key) > 1})
            if duplicates:
                failures.append(
                    f"{path.relative_to(ROOT)}:{node.lineno}:{','.join(duplicates)}"
                )
    assert not failures, "duplicate dictionary keys: " + ", ".join(failures)


def test_production_has_no_runtime_stub_bodies() -> None:
    failures: list[str] = []
    for path in _production_python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        parents: dict[ast.AST, ast.AST] = {
            child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)
        }
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            statements = list(node.body)
            if statements and isinstance(statements[0], ast.Expr) and isinstance(
                statements[0].value, ast.Constant
            ) and isinstance(statements[0].value.value, str):
                statements = statements[1:]
            is_stub = len(statements) == 1 and (
                isinstance(statements[0], ast.Pass)
                or (
                    isinstance(statements[0], ast.Expr)
                    and isinstance(statements[0].value, ast.Constant)
                    and statements[0].value.value is Ellipsis
                )
            )
            if not is_stub:
                continue
            owner = parents.get(node)
            is_protocol_contract = isinstance(owner, ast.ClassDef) and any(
                isinstance(base, ast.Name) and base.id == "Protocol" for base in owner.bases
            )
            if not is_protocol_contract:
                failures.append(f"{path.relative_to(ROOT)}:{node.lineno}:{node.name}")
    assert not failures, "runtime stub bodies: " + ", ".join(failures)


def test_active_source_has_no_unresolved_work_markers() -> None:
    marker_names = ("TO" + "DO", "FIX" + "ME", "X" * 3)
    marker = re.compile(rf"\b(?:{'|'.join(marker_names)})\b", re.IGNORECASE)
    failures: list[str] = []
    for path in _active_text_files():
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if marker.search(line):
                failures.append(f"{path.relative_to(ROOT)}:{line_number}")
    assert not failures, "unresolved work markers: " + ", ".join(failures)


def test_browser_markup_has_unique_ids_and_live_dom_references() -> None:
    html = (ROOT / "iteration_wallet" / "static" / "app.html").read_text(encoding="utf-8")
    ids = re.findall(r'(?:^|\s)id="([^"]+)"', html)
    duplicates = sorted({item for item in ids if ids.count(item) > 1})
    dom_references = set(re.findall(r"""getElementById\(['"]([^'"]+)['"]\)""", html))
    missing = sorted(dom_references - set(ids))
    assert not duplicates, "duplicate HTML IDs: " + ", ".join(duplicates)
    assert not missing, "JavaScript references missing HTML IDs: " + ", ".join(missing)
