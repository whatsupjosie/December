#!/usr/bin/env python3
"""Run the complete Wallet and BlackBox regression suites in isolated batches.

The source suite includes multiprocessing and fault-injection campaigns. Running
bounded batches in fresh interpreter processes prevents one completed campaign's
process resources or module globals from influencing later campaigns. This tool
changes no Wallet data and writes no product-state files.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Sequence

ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class CommandResult:
    name: str
    passed: bool
    returncode: int
    elapsed_seconds: float
    tests: int
    command: list[str]
    stdout: str
    stderr: str
    failure: str | None = None


def _environment() -> dict[str, str]:
    env = os.environ.copy()
    existing = env.get("PYTHONPATH", "")
    entries = [str(ROOT), str(ROOT / "blackbox_source")]
    if existing:
        entries.append(existing)
    env.update(
        {
            "PYTHONPATH": os.pathsep.join(entries),
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONHASHSEED": "0",
        }
    )
    return env


def _run(
    name: str,
    command: Sequence[str],
    *,
    tests: int,
    timeout_seconds: int,
    env: dict[str, str],
) -> CommandResult:
    started = time.monotonic()
    # Use seekable temporary files rather than stdout/stderr pipes. Several
    # regression campaigns spawn child processes; inherited pipes can keep EOF
    # open after pytest exits and make a correct run appear hung. Regular files
    # preserve complete output without that process-tree coupling.
    with tempfile.TemporaryFile(mode="w+b") as stdout_file, tempfile.TemporaryFile(mode="w+b") as stderr_file:
        try:
            completed = subprocess.run(
                list(command),
                cwd=ROOT,
                env=env,
                stdout=stdout_file,
                stderr=stderr_file,
                timeout=timeout_seconds,
                check=False,
            )
            elapsed = time.monotonic() - started
            stdout_file.seek(0)
            stderr_file.seek(0)
            stdout = stdout_file.read().decode("utf-8", errors="replace")
            stderr = stderr_file.read().decode("utf-8", errors="replace")
            return CommandResult(
                name=name,
                passed=completed.returncode == 0,
                returncode=completed.returncode,
                elapsed_seconds=round(elapsed, 2),
                tests=tests,
                command=list(command),
                stdout=stdout,
                stderr=stderr,
            )
        except subprocess.TimeoutExpired:
            elapsed = time.monotonic() - started
            stdout_file.seek(0)
            stderr_file.seek(0)
            return CommandResult(
                name=name,
                passed=False,
                returncode=124,
                elapsed_seconds=round(elapsed, 2),
                tests=tests,
                command=list(command),
                stdout=stdout_file.read().decode("utf-8", errors="replace"),
                stderr=stderr_file.read().decode("utf-8", errors="replace"),
                failure=f"timed out after {timeout_seconds} seconds",
            )


def _collect_wallet_nodes(env: dict[str, str], timeout_seconds: int) -> list[str]:
    command = [sys.executable, "-m", "pytest", "--collect-only", "-q", "tests"]
    result = _run(
        "wallet collection",
        command,
        tests=0,
        timeout_seconds=timeout_seconds,
        env=env,
    )
    if not result.passed:
        sys.stderr.write(result.stdout)
        sys.stderr.write(result.stderr)
        raise RuntimeError(result.failure or "Wallet test collection failed")
    nodes = [line.strip() for line in result.stdout.splitlines() if "::" in line]
    if not nodes:
        raise RuntimeError("Wallet test collection returned no node identifiers")
    if len(nodes) != len(set(nodes)):
        raise RuntimeError("Wallet test collection returned duplicate node identifiers")
    return nodes


def _chunks(items: Sequence[str], size: int) -> list[list[str]]:
    return [list(items[index : index + size]) for index in range(0, len(items), size)]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-size", type=int, default=25)
    parser.add_argument("--timeout", type=int, default=180, help="timeout per subprocess")
    parser.add_argument("--json-report", type=Path)
    args = parser.parse_args()
    if not 1 <= args.batch_size <= 200:
        parser.error("--batch-size must be between 1 and 200")
    if not 10 <= args.timeout <= 1800:
        parser.error("--timeout must be between 10 and 1800 seconds")

    env = _environment()
    try:
        wallet_nodes = _collect_wallet_nodes(env, args.timeout)
    except RuntimeError as exc:
        print(f"FAIL  {exc}", file=sys.stderr)
        return 2

    results: list[CommandResult] = []
    for index, nodes in enumerate(_chunks(wallet_nodes, args.batch_size), start=1):
        name = f"Wallet batch {index}"
        result = _run(
            name,
            [sys.executable, "-m", "pytest", "-vv", "--tb=short", *nodes],
            tests=len(nodes),
            timeout_seconds=args.timeout,
            env=env,
        )
        results.append(result)
        state = "PASS" if result.passed else "FAIL"
        print(f"{state:4}  {name}: {len(nodes)} tests in {result.elapsed_seconds:.2f}s")
        if result.passed:
            summary_lines = [line for line in result.stdout.splitlines() if " passed in " in line]
            if summary_lines:
                print(summary_lines[-1])
        else:
            if result.stdout.strip():
                print(result.stdout.rstrip())
            if result.stderr.strip():
                print(result.stderr.rstrip(), file=sys.stderr)
            break

    if all(result.passed for result in results) and sum(result.tests for result in results) == len(wallet_nodes):
        blackbox = _run(
            "Standalone BlackBox",
            [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                "blackbox_source/plugin_tests",
                "blackbox_source/tests",
            ],
            tests=43,
            timeout_seconds=args.timeout,
            env=env,
        )
        results.append(blackbox)
        state = "PASS" if blackbox.passed else "FAIL"
        print(f"{state:4}  {blackbox.name}: {blackbox.tests} tests in {blackbox.elapsed_seconds:.2f}s")
        if blackbox.passed:
            summary_lines = [line for line in blackbox.stdout.splitlines() if " passed in " in line]
            if summary_lines:
                print(summary_lines[-1])
        else:
            if blackbox.stdout.strip():
                print(blackbox.stdout.rstrip())
            if blackbox.stderr.strip():
                print(blackbox.stderr.rstrip(), file=sys.stderr)

    wallet_executed = sum(
        result.tests for result in results if result.name.startswith("Wallet batch") and result.passed
    )
    blackbox_passed = any(result.name == "Standalone BlackBox" and result.passed for result in results)
    passed = wallet_executed == len(wallet_nodes) and blackbox_passed and all(result.passed for result in results)
    report = {
        "schema": "iteration-wallet-release-test-run/1",
        "passed": passed,
        "wallet_collected": len(wallet_nodes),
        "wallet_passed": wallet_executed,
        "blackbox_expected": 43,
        "blackbox_passed": 43 if blackbox_passed else 0,
        "batch_size": args.batch_size,
        "timeout_seconds": args.timeout,
        "results": [asdict(result) for result in results],
    }
    if args.json_report:
        report_path = args.json_report.resolve()
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"Report: {report_path}")

    print(
        f"Result: Wallet {wallet_executed}/{len(wallet_nodes)}; "
        f"BlackBox {43 if blackbox_passed else 0}/43"
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
