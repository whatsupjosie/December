#!/usr/bin/env python3
"""Run the bounded Iteration Wallet 2.4 Oubliette intake story.

This is a demonstration and evidence generator, not a benchmark override. It
uses the shipped FastAPI routes against a fresh local run root and preserves all
created evidence for review.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

# Allow `python tools/oubliette_boundary_demo.py` from a source checkout.
_SOURCE_ROOT = Path(__file__).resolve().parents[1]
if str(_SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(_SOURCE_ROOT))

from fastapi.testclient import TestClient

from iteration_wallet import __version__, server


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_demo(run_root: Path) -> dict[str, Any]:
    run_root = run_root.resolve()
    if run_root.exists():
        raise RuntimeError(f"Demo run root already exists; refusing to overwrite: {run_root}")
    run_root.mkdir(parents=True)
    wallet_root = run_root / "wallet"
    external_root = run_root / "external_lab"
    external_root.mkdir()

    previous = {
        "blackbox21": server.blackbox21,
        "canonical_evidence21": server.canonical_evidence21,
        "vault21": server.vault21,
        "human_access": server.human_access,
        "promotion21": server.promotion21,
        "startup_reconciliation21": server.startup_reconciliation21,
    }
    evidence, vault, humans, promotion = server.build_canonical_v21_runtime(wallet_root, oubliette_mode="transaction")
    server.blackbox21 = evidence
    server.canonical_evidence21 = evidence
    server.vault21 = vault
    server.human_access = humans
    server.promotion21 = promotion
    server.startup_reconciliation21 = {"status": "not_run", "checked": 0}

    marker = run_root / "EXECUTION_WOULD_HAVE_CREATED_THIS.txt"
    unknown = run_root / "unknown_intake.py"
    unknown.write_text(
        "from pathlib import Path\n"
        f"Path({str(marker)!r}).write_text('EXECUTED', encoding='utf-8')\n"
        "import subprocess\n"
        "subprocess.run(['echo', 'unknown code ran'])\n",
        encoding="utf-8",
    )
    unknown_hash = sha256(unknown)
    derivative = external_root / "reviewed_derivative.py"
    derivative.write_text(
        "print('This derivative remains external until a human admits it as a Candidate.')\n",
        encoding="utf-8",
    )
    derivative_hash = sha256(derivative)

    try:
        with TestClient(server.app) as client:
            project_response = client.post("/api/v21/projects", json={"name": "Oubliette Debut Story"})
            project_response.raise_for_status()
            project = project_response.json()
            section_response = client.post(
                f"/api/v21/projects/{project['id']}/sections",
                json={"name": "Protected Intake"},
            )
            section_response.raise_for_status()
            section = section_response.json()
            candidate_response = client.post(
                f"/api/v21/projects/{project['id']}/sections/{section['id']}/candidates",
                json={
                    "path": str(unknown),
                    "notes": "Unknown intake preserved before interpretation",
                },
            )
            candidate_response.raise_for_status()
            candidate = candidate_response.json()
            session_response = client.post(
                "/api/v21/identity/sessions",
                json={
                    "actor_id": "demo-local-human",
                    "actor_kind": "human",
                    "device_id": "demo-console",
                    "verified_methods": ["human_ceremony", "typing_challenge"],
                    "role_claims": {"local_continuity_only": True},
                },
            )
            session_response.raise_for_status()
            session = session_response.json()
            client.post("/api/v21/vault/open", json={"session_id": session["session_id"]}).raise_for_status()

            inspect_response = client.post(
                f"/api/v21/projects/{project['id']}/sections/{section['id']}/files/{candidate['id']}/oubliette/inspect",
                json={"actor_kind": "human", "target_label": "unknown_intake.py"},
            )
            inspect_response.raise_for_status()
            inspection = inspect_response.json()
            if marker.exists():
                raise RuntimeError("Oubliette executed the intake target")

            quarantine_token_response = client.post(
                "/api/v21/ceremony/tokens",
                json={
                    "action_key": "quarantine",
                    "session_id": session["session_id"],
                    "project_id": project["id"],
                    "section_id": section["id"],
                    "object_id": candidate["id"],
                    "proposal_id": inspection["quarantine_proposal"]["proposal_id"],
                    "proposal_hash": inspection["quarantine_proposal"]["proposal_hash"],
                },
            )
            quarantine_token_response.raise_for_status()
            quarantine_response = client.post(
                f"/api/v21/projects/{project['id']}/sections/{section['id']}/files/{candidate['id']}/quarantine",
                json={
                    "report_id": inspection["report"]["report_id"],
                    "ceremony_token": quarantine_token_response.json()["ceremony_token"],
                    "session_id": session["session_id"],
                    "reason": "Static indicators warrant fenced review; no malware verdict is claimed",
                },
            )
            quarantine_response.raise_for_status()
            quarantine = quarantine_response.json()

            derivative_inspection_response = client.post(
                f"/api/v21/projects/{project['id']}/sections/{section['id']}/files/{candidate['id']}/oubliette/derivatives/inspect",
                json={
                    "derivative_path": str(derivative),
                    "allowed_root": str(external_root),
                    "actor_kind": "human",
                    "target_label": "reviewed_derivative.py",
                },
            )
            derivative_inspection_response.raise_for_status()
            derivative_inspection = derivative_inspection_response.json()

            admission_token_response = client.post(
                "/api/v21/ceremony/tokens",
                json={
                    "action_key": "admit_oubliette_derivative_as_candidate",
                    "session_id": session["session_id"],
                    "project_id": project["id"],
                    "section_id": section["id"],
                    "object_id": candidate["id"],
                    "proposal_id": derivative_inspection["admission_proposal"]["proposal_id"],
                    "proposal_hash": derivative_inspection["admission_proposal"]["proposal_hash"],
                },
            )
            admission_token_response.raise_for_status()
            admission_response = client.post(
                f"/api/v21/projects/{project['id']}/sections/{section['id']}/files/{candidate['id']}/oubliette/derivatives/admit",
                json={
                    "capsule_id": derivative_inspection["capsule"]["capsule_id"],
                    "proposal_id": derivative_inspection["admission_proposal"]["proposal_id"],
                    "proposal_hash": derivative_inspection["admission_proposal"]["proposal_hash"],
                    "report_id": derivative_inspection["report"]["report_id"],
                    "ceremony_token": admission_token_response.json()["ceremony_token"],
                    "session_id": session["session_id"],
                    "reason": "Admit this inspected derivative only as an untrusted Candidate",
                },
            )
            admission_response.raise_for_status()
            admission = admission_response.json()
            state = client.get("/api/v21/state").json()
            chain = client.get("/api/v21/blackbox/chain").json()
            custody = client.get("/api/v21/custody/verify").json()

        section_state = next(
            section_item
            for project_item in state["projects"]
            if project_item["id"] == project["id"]
            for section_item in project_item["sections"]
            if section_item["id"] == section["id"]
        )
        original_record = next(item for item in section_state["files"] if item["id"] == candidate["id"])
        derivative_record = next(
            item for item in section_state["files"] if item["id"] == admission["result"]["id"]
        )
        original_custody_path = Path(original_record["vault_path"])
        derivative_custody_path = Path(derivative_record["vault_path"])

        assertions = {
            "intake_never_executed": not marker.exists(),
            "original_bytes_preserved": sha256(original_custody_path) == unknown_hash,
            "original_remains_quarantined": original_record["state"] == "quarantined",
            "derivative_external_copy_unchanged": sha256(derivative) == derivative_hash,
            "derivative_enters_as_new_candidate": (
                derivative_record["state"] == "candidate"
                and derivative_record["id"] != original_record["id"]
                and derivative_record["parent_quarantined_id"] == original_record["id"]
            ),
            "no_automatic_trust": derivative_record["trust_status"] == "candidate_only_no_automatic_trust",
            "quarantine_receipt_verified": bool(quarantine["verification"]["ok"]),
            "derivative_receipt_verified": bool(admission["verification"]["ok"]),
            "canonical_chain_verified": bool(chain.get("ok")),
            "custody_integrity_verified": bool(custody.get("ok")),
            "derivative_custody_hash_matches": sha256(derivative_custody_path) == derivative_hash,
        }
        return {
            "ok": all(assertions.values()),
            "version": __version__,
            "scope": "wallet_intake_capsule_quarantine_candidate_return",
            "run_root": str(run_root),
            "project_id": project["id"],
            "section_id": section["id"],
            "original_object_id": original_record["id"],
            "derivative_candidate_id": derivative_record["id"],
            "inspection_report_id": inspection["report"]["report_id"],
            "intake_capsule_id": derivative_inspection["capsule"]["capsule_id"],
            "intake_manifest_hash": derivative_inspection["capsule"]["manifest_hash"],
            "admission_proposal_id": derivative_inspection["admission_proposal"]["proposal_id"],
            "derivative_report_id": derivative_inspection["report"]["report_id"],
            "quarantine_receipt_id": quarantine["human_intent_receipt"]["receipt_id"],
            "derivative_receipt_id": admission["human_intent_receipt"]["receipt_id"],
            "assertions": assertions,
            "limitations": [
                "Static inspection reports indicators, not safety or malware determinations.",
                "Identity evidence is local continuity, not legal identity or independent witnessing.",
                "This demo does not implement complete LabCopy export authority or Bridgewright execution.",
                "The returned derivative is Candidate-only and receives no automatic trust.",
            ],
        }
    finally:
        for key, value in previous.items():
            setattr(server, key, value)


def markdown_report(report: dict[str, Any]) -> str:
    checks = "\n".join(
        f"- [{'x' if value else ' '}] {name.replace('_', ' ')}"
        for name, value in report["assertions"].items()
    )
    limits = "\n".join(f"- {item}" for item in report["limitations"])
    return f"""# Iteration Wallet 2.5.0a5 Wallet Intake Capsule Demo

- **Result:** {'PASS' if report['ok'] else 'FAIL'}
- **Version:** `{report['version']}`
- **Scope:** `{report['scope']}`
- **Original object:** `{report['original_object_id']}`
- **Intake Capsule:** `{report['intake_capsule_id']}`
- **Admission proposal:** `{report['admission_proposal_id']}`
- **Derivative Candidate:** `{report['derivative_candidate_id']}`
- **Quarantine receipt:** `{report['quarantine_receipt_id']}`
- **Derivative receipt:** `{report['derivative_receipt_id']}`

## Proved observations

{checks}

## Honest limitations

{limits}
"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-root", required=True, type=Path)
    parser.add_argument("--json-output", required=True, type=Path)
    parser.add_argument("--markdown-output", required=True, type=Path)
    args = parser.parse_args()
    for output in (args.json_output, args.markdown_output):
        if output.exists():
            raise RuntimeError(f"Output already exists; refusing to overwrite: {output}")
        output.parent.mkdir(parents=True, exist_ok=True)
    report = run_demo(args.run_root)
    args.json_output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    args.markdown_output.write_text(markdown_report(report), encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
