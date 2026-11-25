#!/usr/bin/env python3
"""Coordinate migration from legacy overlapping alpha wheels.

The 2.4.x / 0.5.x alpha wheels could both claim files from the same runtime
package. A one-at-a-time pip upgrade can therefore remove files needed by the
new companion wheel. This tool performs the safe sequence explicitly:

1. verify both replacement wheels exist;
2. uninstall both legacy distributions from the selected Python environment;
3. install both replacement wheels together;
4. verify import versions, client schema, and sole package ownership.

The tool mutates only the Python environment selected by --python or the current
interpreter. It never edits Wallet custody data.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from importlib import metadata
from pathlib import Path
from typing import Any

WALLET_DIST = "iteration-wallet"
BBX_DIST = "bbx1-iteration-wallet-plugin"


def _run(python: Path, args: list[str], *, dry_run: bool) -> None:
    cmd = [str(python), "-m", "pip", *args]
    print("+", " ".join(cmd))
    if not dry_run:
        subprocess.run(cmd, check=True)


def _verify(python: Path) -> dict[str, Any]:
    probe = r'''
import json
from importlib import metadata
import blackbox_plugin, iteration_wallet, iteration_wallet_blackbox
owners = metadata.packages_distributions()
print(json.dumps({
    "iteration_wallet_version": iteration_wallet.__version__,
    "blackbox_version": blackbox_plugin.__version__,
    "blackbox_client_schema": getattr(blackbox_plugin, "CLIENT_SCHEMA_VERSION", None),
    "blackbox_plugin_owners": sorted(owners.get("blackbox_plugin", [])),
    "iteration_wallet_blackbox_owners": sorted(owners.get("iteration_wallet_blackbox", [])),
}, sort_keys=True))
'''
    result = subprocess.run([str(python), "-c", probe], check=True, text=True, capture_output=True)
    return json.loads(result.stdout)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Safely migrate legacy overlapping Wallet/BlackBox alpha installs")
    parser.add_argument("--python", default=sys.executable, help="Python interpreter whose environment should be migrated")
    parser.add_argument("--wallet-wheel", required=True)
    parser.add_argument("--blackbox-wheel", required=True)
    parser.add_argument("--dry-run", action="store_true", help="Print actions without modifying the environment")
    args = parser.parse_args(argv)

    python = Path(args.python)
    wallet_wheel = Path(args.wallet_wheel)
    blackbox_wheel = Path(args.blackbox_wheel)
    if not python.exists():
        raise SystemExit(f"selected Python does not exist: {python}")
    if not wallet_wheel.is_file():
        raise SystemExit(f"wallet wheel not found: {wallet_wheel}")
    if not blackbox_wheel.is_file():
        raise SystemExit(f"blackbox wheel not found: {blackbox_wheel}")

    _run(python, ["uninstall", "-y", WALLET_DIST, BBX_DIST], dry_run=args.dry_run)
    _run(python, ["install", str(blackbox_wheel), str(wallet_wheel)], dry_run=args.dry_run)
    if args.dry_run:
        print(json.dumps({"ok": True, "dry_run": True, "mutated": False}, indent=2))
        return 0

    verification = _verify(python)
    expected = {
        "iteration_wallet_version": "2.5.0a11",
        "blackbox_version": "0.6.0a4",
        "blackbox_client_schema": "bbx1-client/1",
        "blackbox_plugin_owners": [BBX_DIST],
        "iteration_wallet_blackbox_owners": [WALLET_DIST],
    }
    errors = {key: {"expected": value, "actual": verification.get(key)} for key, value in expected.items() if verification.get(key) != value}
    result = {"ok": not errors, "verification": verification, "errors": errors}
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
