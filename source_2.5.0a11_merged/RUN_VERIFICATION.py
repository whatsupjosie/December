#!/usr/bin/env python3
"""Non-destructive source-bundle verification for Iteration Wallet 2.5.0a11."""
from __future__ import annotations

import ast
import json
import os
import py_compile
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from html.parser import HTMLParser

ROOT = Path(__file__).resolve().parent


def check(name: str, ok: bool, detail: str = "") -> bool:
    state = "PASS" if ok else "FAIL"
    print(f"{state:4}  {name}{': ' + detail if detail else ''}")
    return ok



class _VisibleTextParser(HTMLParser):
    """Collect visible UI copy and user-facing attribute values."""

    def __init__(self) -> None:
        super().__init__()
        self._skip_depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in {"script", "style"}:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        for name, value in attrs:
            if name.lower() in {"aria-label", "title", "placeholder", "alt", "value"} and value:
                self.parts.append(value)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style"} and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            self.parts.append(data)


def visible_ui_copy(html: str) -> str:
    parser = _VisibleTextParser()
    parser.feed(html)
    return " ".join(parser.parts)

def physical_cleanup_offenders() -> list[str]:
    packages = (
        ROOT / "iteration_wallet",
        ROOT / "iteration_wallet_blackbox",
        ROOT / "blackbox_source" / "blackbox_plugin",
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
            physical = name in {"os.unlink", "os.remove", "shutil.rmtree"}
            physical = physical or (isinstance(func, ast.Attribute) and func.attr == "unlink")
            if physical and path.name != "runtime_residue.py":
                offenders.append(f"{path.relative_to(ROOT)}:{node.lineno}:{name}")
    return offenders


def main() -> int:
    passed: list[bool] = []
    sys.path.insert(0, str(ROOT / "blackbox_source"))
    sys.path.insert(0, str(ROOT))

    from iteration_wallet.version import WALLET_VERSION, BLACKBOX_VERSION, BLACKBOX_CLIENT_SCHEMA
    import iteration_wallet
    from blackbox_plugin import __version__ as blackbox_version
    from blackbox_plugin import CLIENT_SCHEMA_VERSION
    from iteration_wallet import server
    from iteration_wallet.preservation import (
        BLACKBOX_PRESERVATION_RULE,
        PERMANENT_PRESERVATION_RULE,
        RUNTIME_RESIDUE_RULE,
    )

    passed.append(check("Wallet version", iteration_wallet.__version__ == WALLET_VERSION, WALLET_VERSION))
    passed.append(check("BlackBox version", blackbox_version == BLACKBOX_VERSION, BLACKBOX_VERSION))
    passed.append(check("BlackBox client schema", CLIENT_SCHEMA_VERSION == BLACKBOX_CLIENT_SCHEMA, BLACKBOX_CLIENT_SCHEMA))

    pin = json.loads((ROOT / "BLACKBOX_DEPENDENCY_PIN.json").read_text(encoding="utf-8"))
    passed.append(check("Dependency pin", pin.get("blackbox_version") == BLACKBOX_VERSION))

    compile_errors: list[str] = []
    roots = [ROOT / "iteration_wallet", ROOT / "iteration_wallet_blackbox", ROOT / "blackbox_source" / "blackbox_plugin"]
    source_count = 0
    for source_root in roots:
        for path in source_root.rglob("*.py"):
            source_count += 1
            try:
                py_compile.compile(str(path), doraise=True)
            except Exception as exc:
                compile_errors.append(f"{path.relative_to(ROOT)}: {exc}")
    passed.append(check("Python compile scan", not compile_errors, f"{source_count} files"))
    for item in compile_errors:
        print("      ", item)

    passed.append(check(
        "Permanent-preservation laws",
        "remains preserved" in PERMANENT_PRESERVATION_RULE
        and "remains preserved" in BLACKBOX_PRESERVATION_RULE
        and "Only program-created" in RUNTIME_RESIDUE_RULE,
    ))
    cleanup_offenders = physical_cleanup_offenders()
    passed.append(check(
        "Single physical-cleanup authority",
        not cleanup_offenders,
        "runtime_residue.py only" if not cleanup_offenders else ", ".join(cleanup_offenders),
    ))

    paths = set(server.app.openapi()["paths"])
    forbidden_route_fragments = (
        "/files/{file_id}/remove",
        "/files/{file_id}/release",
        "/restore-from-removed",
        "/files/{file_id}/restore",
    )
    old_routes_absent = all(not any(fragment in path for fragment in forbidden_route_fragments) for path in paths)
    passed.append(check("No legacy destructive custody routes", old_routes_absent))
    exact_transition_routes = {
        "/api/v21/projects/{project_id}/sections/{section_id}/objects/{object_id}/retire",
        "/api/v21/projects/{project_id}/sections/{section_id}/objects/{object_id}/restore",
    }
    passed.append(check(
        "Exact preserving state-transition routes",
        exact_transition_routes <= paths,
        ", ".join(sorted(exact_transition_routes - paths)),
    ))
    passed.append(check("Passkey revocation route", "/api/v21/security/passkeys/revoke" in paths))
    passed.append(check("Old passkey route absent", "/api/v21/security/passkeys/remove" not in paths))

    html_path = ROOT / "iteration_wallet" / "static" / "app.html"
    html = html_path.read_text(encoding="utf-8")
    tray_ids = re.findall(r'data-tray-id="([^"]+)"', html)
    onclick = set(re.findall(r'onclick="([A-Za-z_$][\w$]*)\s*\(', html))
    functions = set(re.findall(r'(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*\(', html))
    passed.append(check("Nine spatial trays", len(tray_ids) == 9 and len(set(tray_ids)) == 9, ", ".join(tray_ids)))
    passed.append(check("No dead inline handlers", onclick <= functions, ", ".join(sorted(onclick - functions))))
    passed.append(check("LabCopy active path", "/labcopy/proposal" in html and "/results/capture" in html))
    passed.append(check("Oubliette absent from active UI", "/oubliette/" not in html))
    passed.append(check(
        "Passkey UI wired",
        "/security/passkeys/authentication/options" in html
        and "/security/passkeys/revoke" in html
        and "hardware_gate_token" in html,
    ))
    passed.append(check(
        "Retire and Restore UI wired",
        "openStateTransitionModal" in html
        and "retire_object" in html
        and "restore_retired_object" in html
        and "/objects/${transition.objectId}/${endpoint}" in html
        and "protected content, identity, history, and evidence remain preserved" in html,
    ))
    passed.append(check(
        "No ambiguous custody actions in UI",
        all(phrase not in html.lower() for phrase in (
            "remove from active",
            "release from custody",
            "permanently destroy",
            "delete file",
        )),
    ))
    visible_copy = visible_ui_copy(html).lower()
    forbidden_visible_words = ("delete", "remove", "discard", "erase", "purge", "destroy")
    visible_word_hits = [word for word in forbidden_visible_words if re.search(rf"\b{word}\w*\b", visible_copy)]
    passed.append(check(
        "Exact preservation vocabulary in visible UI",
        not visible_word_hits,
        ", ".join(visible_word_hits),
    ))
    responsive_contract = all(fragment in html for fragment in (
        "overflow-x:hidden!important",
        ".grid.tray-field{display:flex!important;flex-direction:column!important",
        "width:100%!important;max-width:100%!important;min-width:0!important;height:auto!important",
    ))
    passed.append(check("Responsive one-column custody contract", responsive_contract))

    with tempfile.TemporaryDirectory(prefix="iw-js-") as temp:
        scripts = re.findall(r"<script(?:\s[^>]*)?>(.*?)</script>", html, flags=re.S | re.I)
        combined = "\n".join(scripts)
        js_path = Path(temp) / "app.js"
        js_path.write_text(combined, encoding="utf-8")
        node = subprocess.run(["node", "--check", str(js_path)], text=True, capture_output=True, timeout=30)
        passed.append(check("Browser JavaScript syntax", node.returncode == 0, node.stderr.strip()))

    cli_source = (ROOT / "iteration_wallet" / "cli.py").read_text(encoding="utf-8")
    tree = ast.parse(cli_source)
    passed.append(check("CLI source parses", isinstance(tree, ast.Module)))
    from iteration_wallet import cli
    commands = set(cli.build_parser()._subparsers._group_actions[0].choices)
    passed.append(check("LabCopy CLI commands", {"labcopy-export", "labcopy-reenter"} <= commands))
    passed.append(check("No unsupported custody commands", not ({"remove", "restore", "release"} & commands)))

    with tempfile.TemporaryDirectory(prefix="iw-verification-") as temp:
        required_env = os.environ.copy()
        required_env.update({
            "PYTHONPATH": os.pathsep.join([str(ROOT), str(ROOT / "blackbox_source")]),
            "ITERATION_WALLET_ROOT": str(Path(temp) / "wallet-required"),
            "IW_OUBLIETTE_MODE": "disabled",
            "IW_REQUIRE_PASSKEY": "required",
            "IW_WEBAUTHN_RP_ID": "localhost",
            "IW_WEBAUTHN_ORIGINS": "http://localhost:7432",
        })
        probe = subprocess.run(
            [sys.executable, "-c", (
                "from iteration_wallet import server; s=server.passkey_gate.status(); "
                "print(server.app.version, s['enrollment_required'], sep='; enrollment_required=')"
            )],
            cwd=ROOT,
            env=required_env,
            text=True,
            capture_output=True,
            timeout=30,
        )
        passed.append(check(
            "Fresh runtime requires passkey enrollment",
            probe.returncode == 0 and "enrollment_required=True" in probe.stdout,
            probe.stdout.strip() or probe.stderr.strip(),
        ))

        test_env = required_env.copy()
        test_env["ITERATION_WALLET_ROOT"] = str(Path(temp) / "wallet-test")
        test_env["IW_REQUIRE_PASSKEY"] = "off"
        bounded = subprocess.run(
            [sys.executable, str(ROOT / "tools" / "private_alpha_flow_runner.py"),
             "--run-root", str(Path(temp) / "flow"),
             "--report-dir", str(Path(temp) / "flow-report")],
            cwd=ROOT,
            env=test_env,
            text=True,
            capture_output=True,
            timeout=90,
        )
        passed.append(check(
            "Bounded canonical flow",
            bounded.returncode == 0 and "PASS" in bounded.stdout,
            bounded.stdout.strip().splitlines()[-1] if bounded.stdout.strip() else bounded.stderr.strip(),
        ))

    required = [
        "START_ITERATION_WALLET.bat",
        "START_ITERATION_WALLET.ps1",
        "README.md",
        "INSTALLATION.md",
        "SECURITY_BOUNDARY_2.5.0a11.md",
        "UI_WORKSPACE_GUIDE_2.5.0a11.md",
        "CONTINUOUS_AGENT_RUN_REPORT_20260725.md",
        "KNOWN_LIMITATIONS_2.5.0a11.md",
        "TEST_REPORT_2.5.0a11.txt",
        "RELEASE_MANIFEST_2.5.0a11.json",
        "RELEASE_SMOKE_2.5.0a11.json",
        "WHEEL_SHA256SUMS.txt",
        "tools/run_release_smoke.py",
        f"dist/iteration_wallet-{WALLET_VERSION}-py3-none-any.whl",
        f"dist/bbx1_iteration_wallet_plugin-{BLACKBOX_VERSION}-py3-none-any.whl",
    ]
    missing = [item for item in required if not (ROOT / item).is_file()]
    passed.append(check("Release files present", not missing, ", ".join(missing)))

    print()
    print(f"Result: {sum(passed)}/{len(passed)} checks passed")
    return 0 if all(passed) else 1


if __name__ == "__main__":
    raise SystemExit(main())
