#!/usr/bin/env python3
"""Installed-wheel and live-loopback smoke verification for a release bundle."""
from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


def _free_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _http_json(base: str, path: str, *, timeout: float = 5.0) -> dict[str, Any]:
    with urllib.request.urlopen(base + path, timeout=timeout) as response:
        if response.status != 200:
            raise RuntimeError(f"{path} returned HTTP {response.status}")
        value = json.loads(response.read().decode("utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"{path} did not return a JSON object")
    return value


def _wait_for_ui(base: str, *, timeout: float = 20.0) -> None:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(base + "/", timeout=1.0) as response:
                body = response.read().decode("utf-8", "replace")
                if response.status == 200 and "Iteration Wallet" in body:
                    return
        except (OSError, urllib.error.URLError) as exc:
            last_error = exc
        time.sleep(0.15)
    raise RuntimeError(f"loopback UI did not become ready: {last_error}")


def _run_python(*, pythonpath: Path, runtime_root: Path, code: str) -> dict[str, Any]:
    env = os.environ.copy()
    env.update(
        {
            "PYTHONPATH": str(pythonpath),
            "ITERATION_WALLET_ROOT": str(runtime_root),
            "IW_REQUIRE_PASSKEY": "required",
        }
    )
    completed = subprocess.run(
        [sys.executable, "-c", code],
        cwd=runtime_root,
        env=env,
        text=True,
        capture_output=True,
        timeout=60,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            "installed-wheel probe failed\n"
            + completed.stdout
            + completed.stderr
        )
    value = json.loads(completed.stdout)
    if not isinstance(value, dict):
        raise RuntimeError("installed-wheel probe did not return a JSON object")
    return value


def run(root: Path) -> dict[str, Any]:
    sys.path.insert(0, str(root))
    from iteration_wallet.version import BLACKBOX_VERSION, WALLET_VERSION

    wallet_wheel = root / "dist" / f"iteration_wallet-{WALLET_VERSION}-py3-none-any.whl"
    blackbox_wheel = root / "dist" / f"bbx1_iteration_wallet_plugin-{BLACKBOX_VERSION}-py3-none-any.whl"
    for wheel in (wallet_wheel, blackbox_wheel):
        if not wheel.is_file():
            raise FileNotFoundError(wheel)

    with tempfile.TemporaryDirectory(prefix="iw-release-smoke-") as temp_text:
        temp = Path(temp_text)
        packages = temp / "packages"
        runtime = temp / "runtime"
        packages.mkdir()
        runtime.mkdir()

        install = subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                "--no-deps",
                "--target",
                str(packages),
                str(wallet_wheel),
                str(blackbox_wheel),
            ],
            cwd=temp,
            text=True,
            capture_output=True,
            timeout=120,
        )
        if install.returncode != 0:
            raise RuntimeError("wheel installation failed\n" + install.stdout + install.stderr)

        probe = _run_python(
            pythonpath=packages,
            runtime_root=runtime,
            code=(
                "import json; "
                "from importlib import metadata; "
                "from iteration_wallet.cli import _doctor_report; "
                "from iteration_wallet.version import WALLET_VERSION, BLACKBOX_VERSION; "
                "import iteration_wallet.server as server; "
                "r=_doctor_report(); "
                "assert r['ok'], r; "
                "assert metadata.version('iteration-wallet') == WALLET_VERSION; "
                "assert metadata.version('bbx1-iteration-wallet-plugin') == BLACKBOX_VERSION; "
                "print(json.dumps({"
                "'wallet_version': WALLET_VERSION, "
                "'blackbox_version': BLACKBOX_VERSION, "
                "'doctor_ok': r['ok'], "
                "'server_app_version': server.app.version"
                "}))"
            ),
        )
        if probe["wallet_version"] != WALLET_VERSION:
            raise RuntimeError("installed Wallet version mismatch")
        if probe["blackbox_version"] != BLACKBOX_VERSION:
            raise RuntimeError("installed BlackBox version mismatch")
        if probe["server_app_version"] != WALLET_VERSION:
            raise RuntimeError("installed server application version mismatch")

        port = _free_loopback_port()
        base = f"http://127.0.0.1:{port}"
        env = os.environ.copy()
        env.update(
            {
                "PYTHONPATH": str(packages),
                "ITERATION_WALLET_ROOT": str(runtime),
                "IW_REQUIRE_PASSKEY": "required",
                "IW_WEBAUTHN_RP_ID": "localhost",
                "IW_WEBAUTHN_ORIGINS": f"http://127.0.0.1:{port},http://localhost:{port}",
            }
        )
        server = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "iteration_wallet.server:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--log-level",
                "warning",
            ],
            cwd=runtime,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        try:
            _wait_for_ui(base)
            capabilities = _http_json(base, "/api/v21/capabilities")
            custody = _http_json(base, "/api/v21/custody/verify")
            chain = _http_json(base, "/api/v21/blackbox/chain")
            status = _http_json(base, "/api/v21/private-alpha/status")
            passkeys = _http_json(base, "/api/v21/security/passkeys/status")

            transitions = capabilities.get("state_transitions")
            expected_transitions = {
                "available": True,
                "retire": True,
                "restore": True,
                "protected_content_preserved": True,
            }
            if transitions != expected_transitions:
                raise RuntimeError(f"state-transition capability mismatch: {transitions!r}")
            if custody.get("ok") is not True:
                raise RuntimeError(f"custody verification failed: {custody!r}")
            if chain.get("ok") is not True:
                raise RuntimeError(f"BlackBox chain verification failed: {chain!r}")
            if status.get("version") != WALLET_VERSION:
                raise RuntimeError(f"live version mismatch: {status.get('version')!r}")
            if passkeys.get("enrollment_required") is not True:
                raise RuntimeError("fresh runtime did not require passkey enrollment")
            if passkeys.get("require_for_protected_actions") is not True:
                raise RuntimeError("protected actions did not require the passkey gate")
        finally:
            server.terminate()
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait(timeout=5)
            output = server.stdout.read() if server.stdout is not None else ""
            if server.returncode not in {0, -15}:
                raise RuntimeError(f"loopback server exited unexpectedly ({server.returncode})\n{output}")
            if "Traceback" in output or "ERROR" in output:
                raise RuntimeError("loopback server logged an unexpected error\n" + output)

        return {
            "schema": "iteration-wallet-release-smoke/1",
            "clean_wheel_install": True,
            "doctor_ok": True,
            "live_loopback_smoke": True,
            "ui_http_200": True,
            "bind_host": "127.0.0.1",
            "wallet_version": WALLET_VERSION,
            "blackbox_version": BLACKBOX_VERSION,
            "server_app_version": probe["server_app_version"],
            "custody_integrity_ok": True,
            "blackbox_chain_ok": True,
            "passkey_enrollment_required": True,
            "passkey_required_for_protected_actions": True,
            "state_transitions": expected_transitions,
        }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--json-report", type=Path)
    args = parser.parse_args()

    report = run(args.root.resolve())
    encoded = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.json_report:
        args.json_report.write_text(encoded, encoding="utf-8")
    print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
