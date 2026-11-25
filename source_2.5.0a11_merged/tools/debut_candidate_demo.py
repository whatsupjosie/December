#!/usr/bin/env python3
"""Run the bounded Iteration Wallet / BBX1 debut Candidate story.

The demo proves the canonical human-gated Candidate-to-Prime route, a static
Runtime Continuity comparison outside custody, and preserved compact-legacy
BlackBox migration.  It does not claim completed Oubliette crossings, full
laboratory authority, or universal protected-route cutover.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from blackbox_plugin import BlackBoxPlugin
from blackbox_plugin.migration import migrate_legacy_compact_session
from iteration_wallet.runtime_continuity import ContinuityPolicy, capture_snapshot, compare_snapshots
from iteration_wallet.oubliette import inspect_static
from live_law003_probe import run_probe

ZERO_HASH = "0" * 64


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def write_once(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(data)
        handle.flush()


def legacy_wire(sequence: int, previous_hash: str, payload: dict[str, Any]) -> tuple[str, str]:
    body = {
        "seq": sequence,
        "t": f"2025-09-23T00:00:0{sequence}+00:00",
        "ch": "ACT",
        "src": "SYS",
        "act": "legacy:demo",
        "ev": "OBS",
        "cov": "F",
        "sid": "legacy-debut",
        "rid": f"legacy-debut:{sequence}",
        "ph": previous_hash,
        "p": payload,
    }
    digest = hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    fields = [
        "BBX1",
        f"seq={body['seq']}",
        f"t={body['t']}",
        f"ch={body['ch']}",
        f"src={body['src']}",
        f"act={body['act']}",
        f"ev={body['ev']}",
        f"cov={body['cov']}",
        f"sid={body['sid']}",
        f"rid={body['rid']}",
        f"ph={body['ph']}",
        f"h={digest}",
        f"p={json.dumps(payload, sort_keys=True, separators=(',', ':'))}",
    ]
    return "|".join(fields), digest


def run_demo(run_root: Path) -> dict[str, Any]:
    run_root.mkdir(parents=True, exist_ok=False)

    promotion = run_probe(run_root / "canonical_promotion")

    reference_root = run_root / "external_reference"
    reference_root.mkdir()
    (reference_root / "app.py").write_text("print('trusted reference')\n", encoding="utf-8")
    (reference_root / "config.ini").write_text("mode=alpha\n", encoding="utf-8")
    (reference_root / "cache").mkdir()
    (reference_root / "cache" / "session.tmp").write_text("temporary\n", encoding="utf-8")
    reference = capture_snapshot(reference_root, root_label="debut-external-program")

    lab_copy = run_root / "external_lab_copy"
    shutil.copytree(reference_root, lab_copy)
    (lab_copy / "app.py").write_text("print('deliberately changed outside custody')\n", encoding="utf-8")
    (lab_copy / "config.ini").write_text("mode=review\n", encoding="utf-8")
    (lab_copy / "cache" / "session.tmp").write_text("new temporary state\n", encoding="utf-8")
    observed = capture_snapshot(
        lab_copy,
        root_label="debut-external-program",
        previous_snapshot_id=reference.snapshot_id,
    )
    # Deliberately present a human-sounding but unverified evidence identifier.
    # The hardened comparator must refuse to convert that string into authority.
    continuity = compare_snapshots(
        reference,
        observed,
        policy=ContinuityPolicy(),
        authorized_configuration={"config.ini": "demo-human-config-receipt"},
    )

    suspicious_candidate = run_root / "suspicious_candidate.py"
    suspicious_candidate.write_text(
        "import subprocess\nsubprocess.run(['echo', 'never executed by Oubliette'])\n",
        encoding="utf-8",
    )
    suspicious_before = suspicious_candidate.read_bytes()
    oubliette = inspect_static(
        suspicious_candidate,
        actor_kind="human",
        allowed_root=run_root,
        target_label="returned-candidate",
    )
    oubliette_unchanged = suspicious_candidate.read_bytes() == suspicious_before

    legacy_path = run_root / "legacy_session.bbx"
    first, first_hash = legacy_wire(0, ZERO_HASH, {"state": "candidate", "origin": "early-build"})
    second, _ = legacy_wire(1, first_hash, {"state": "observed", "note": "preserve, do not upgrade"})
    write_once(legacy_path, (first + "\n" + second + "\n").encode("utf-8"))
    migration_plugin = BlackBoxPlugin(run_root / "migration_blackbox", "migration-demo")
    migration = migrate_legacy_compact_session(legacy_path, migration_plugin.recorder)
    migration_verification = migration_plugin.verify()

    continuity_counts = continuity.to_dict()["counts"]
    limitations = [
        "Only Candidate-to-Prime is demonstrated through the canonical Human Intent transaction.",
        "The lab copy in this specimen is created by the external demo tool; full Wallet laboratory crossing authority remains open.",
        "Oubliette static inspection is demonstrated; physical quarantine crossing remains Wallet-owned and unavailable until its canonical Human Intent transaction is implemented.",
        "Legacy migration proves the compact Phase 1/1.2 format only and remains local-consistency evidence, not independent authentication.",
        "The official locked benchmark remains Candidate because mandatory manual and implementation gates are still open.",
    ]
    passed = bool(
        promotion.get("pass")
        and continuity_counts.get("unexplained") == 2
        and continuity_counts.get("authorized_configuration", 0) == 0
        and continuity_counts.get("disposable") == 1
        and oubliette_unchanged
        and oubliette.target_executed is False
        and oubliette.target_extracted is False
        and oubliette.custody_changed is False
        and "process_launch" in {item.code for item in oubliette.findings}
        and migration.imported_record_count == 2
        and migration_verification.get("ok") is True
        and migration.independently_authenticated is False
    )
    return {
        "demo_id": "RVF-IW-BBX1-DEBUT-CANDIDATE-20260720",
        "generated_at": utc_now(),
        "pass": passed,
        "steps": {
            "canonical_human_promotion": {
                "pass": promotion.get("pass"),
                "wallet_version": promotion.get("wallet_version"),
                "result_state": promotion.get("result_state"),
                "receipt_type": promotion.get("receipt_type"),
                "ceremony_token_bound": promotion.get("ceremony_token_bound"),
                "event_types": promotion.get("event_types"),
                "chain_verified": (promotion.get("chain_verification") or {}).get("ok"),
            },
            "runtime_continuity": {
                "reference_snapshot_id": reference.snapshot_id,
                "observed_snapshot_id": observed.snapshot_id,
                "coverage": continuity.coverage,
                "confidence": continuity.confidence,
                "counts": continuity_counts,
                "repair_attempted": continuity.to_dict()["repair_attempted"],
                "trust_inferred": continuity.to_dict()["trust_inferred"],
            },
            "oubliette_static_inspection": {
                "report_id": oubliette.report_id,
                "coverage": oubliette.coverage.value,
                "finding_codes": [item.code for item in oubliette.findings],
                "quarantine_review_recommended": oubliette.quarantine_review_recommended,
                "target_executed": oubliette.target_executed,
                "target_extracted": oubliette.target_extracted,
                "target_modified": oubliette.target_modified,
                "custody_changed": oubliette.custody_changed,
                "malware_determined": oubliette.malware_determined,
                "bytes_unchanged": oubliette_unchanged,
            },
            "legacy_migration": {
                "legacy_record_count": migration.legacy_record_count,
                "imported_record_count": migration.imported_record_count,
                "source_capture_stable": migration.source_capture_stable,
                "source_sha256": migration.source_sha256,
                "canonical_chain_verified": migration_verification.get("ok"),
                "independently_authenticated": migration.independently_authenticated,
                "authentication_scope": migration.authentication_scope,
            },
        },
        "limitations": limitations,
    }


def markdown_report(result: dict[str, Any]) -> str:
    promotion = result["steps"]["canonical_human_promotion"]
    continuity = result["steps"]["runtime_continuity"]
    oubliette = result["steps"]["oubliette_static_inspection"]
    migration = result["steps"]["legacy_migration"]
    lines = [
        "# Rearview Foresight Debut Candidate Demo",
        "",
        f"- Overall bounded demo: **{'PASS' if result['pass'] else 'FAIL'}**",
        f"- Generated: `{result['generated_at']}`",
        "",
        "## 1. Human-gated trust expansion",
        "",
        f"A Candidate was promoted to `{promotion['result_state']}` through the real Wallet route. The receipt type was `{promotion['receipt_type']}`, ceremony binding was `{promotion['ceremony_token_bound']}`, and the canonical chain verified as `{promotion['chain_verified']}`.",
        "",
        "Canonical event graph:",
        "",
        *[f"1. `{event}`" for event in promotion["event_types"]],
        "",
        "## 2. Static Runtime Continuity outside custody",
        "",
        f"Coverage: `{continuity['coverage']}`. Confidence: `{continuity['confidence']}`. Both the deliberately changed executable and the configuration change carrying only an unverified human-sounding evidence ID remained unexplained; temporary cache state was disposable. Repair attempted: `{continuity['repair_attempted']}`.",
        "",
        "## 3. Static Oubliette inspection",
        "",
        f"Oubliette reported `{oubliette['coverage']}` static coverage and findings `{', '.join(oubliette['finding_codes'])}`. Target executed: `{oubliette['target_executed']}`; extracted: `{oubliette['target_extracted']}`; modified: `{oubliette['target_modified']}`; custody changed: `{oubliette['custody_changed']}`. The source bytes remained unchanged: `{oubliette['bytes_unchanged']}`. This is a review recommendation, not a malware verdict or quarantine crossing.",
        "",
        "## 4. Preserved legacy evidence",
        "",
        f"The compact legacy source contained `{migration['legacy_record_count']}` records and imported `{migration['imported_record_count']}` canonical facts. The new chain verified as `{migration['canonical_chain_verified']}`. The old proof is explicitly `{migration['authentication_scope']}` and independently authenticated remains `{migration['independently_authenticated']}`.",
        "",
        "## Honest limits",
        "",
        *[f"- {item}" for item in result["limitations"]],
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", required=True, type=Path)
    parser.add_argument("--json-output", required=True, type=Path)
    parser.add_argument("--markdown-output", required=True, type=Path)
    args = parser.parse_args()
    result = run_demo(args.run_root.resolve())
    write_once(args.json_output.resolve(), (json.dumps(result, indent=2, sort_keys=True) + "\n").encode("utf-8"))
    write_once(args.markdown_output.resolve(), markdown_report(result).encode("utf-8"))
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
