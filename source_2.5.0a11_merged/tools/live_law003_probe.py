#!/usr/bin/env python3
"""Exercise LAW-003 through the real FastAPI Prime-promotion route.

This is supplemental evidence for the frozen debut benchmark.  The frozen
LAW-003 gate intentionally remains unchanged and still shares the historical
compatibility-adapter probe; this tool proves the integrated Wallet route
separately without rewriting benchmark history.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Direct source-checkout execution places tools/ rather than the repository
# root on sys.path.  Add the root explicitly without altering installed-wheel
# behavior.
_REPO_ROOT = Path(__file__).resolve().parents[1]
# Set RVF_PROBE_PREFER_INSTALLED=1 when this source-side tool is being used to
# verify a wheel installed into PYTHONPATH. Otherwise prefer the checkout that
# owns the tool.
if os.environ.get("RVF_PROBE_PREFER_INSTALLED") != "1":
    if str(_REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(_REPO_ROOT))

from fastapi.testclient import TestClient

from iteration_wallet import __version__ as wallet_version
from iteration_wallet import server
from iteration_wallet.canonical_evidence import CanonicalEvidenceAdapter
from iteration_wallet.notification_manager import ActorKind, NotificationManager
from iteration_wallet.promotion_transaction import PromotionTransactionCoordinator
from iteration_wallet.vault_v21 import VaultEngine


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json_once(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False).encode("utf-8")
    with path.open("xb") as handle:
        handle.write(encoded)
        handle.flush()


def run_probe(run_root: Path) -> dict[str, Any]:
    run_root.mkdir(parents=True, exist_ok=False)
    source = run_root / "candidate.txt"
    source.write_text("Rearview Foresight canonical LAW-003 live-route probe\n", encoding="utf-8")

    evidence = CanonicalEvidenceAdapter(run_root, session_id="law003-live")
    vault = VaultEngine(run_root, blackbox=evidence, strict_ceremony_tokens=True)
    humans = NotificationManager(run_root, blackbox=evidence)
    promotion = PromotionTransactionCoordinator(vault, evidence, humans)

    previous = {
        "blackbox21": server.blackbox21,
        "vault21": server.vault21,
        "human_access": server.human_access,
        "canonical_evidence21": getattr(server, "canonical_evidence21", None),
        "promotion21": getattr(server, "promotion21", None),
    }
    try:
        server.blackbox21 = evidence
        server.vault21 = vault
        server.human_access = humans
        server.canonical_evidence21 = evidence
        server.promotion21 = promotion
        client = TestClient(server.app)

        project_response = client.post("/api/v21/projects", json={"name": "LAW-003 Live Route"})
        project_response.raise_for_status()
        project = project_response.json()

        section_response = client.post(
            f"/api/v21/projects/{project['id']}/sections",
            json={"name": "Core", "description": "canonical promotion proof"},
        )
        section_response.raise_for_status()
        section = section_response.json()

        candidate_response = client.post(
            f"/api/v21/projects/{project['id']}/sections/{section['id']}/candidates",
            json={"path": str(source), "notes": "supplemental LAW-003 proof"},
        )
        candidate_response.raise_for_status()
        candidate = candidate_response.json()

        identity = humans.issue_identity_session(
            "reviewer-human",
            ActorKind.HUMAN,
            device_id="local-probe",
            verified_methods=["human_ceremony", "typing_challenge"],
        )
        open_response = client.post("/api/v21/vault/open", json={"session_id": identity.session_id})
        open_response.raise_for_status()

        token_response = client.post(
            "/api/v21/ceremony/tokens",
            json={
                "action_key": "promote_candidate_to_prime",
                "session_id": identity.session_id,
                "project_id": project["id"],
                "section_id": section["id"],
                "object_id": candidate["id"],
                "ttl_seconds": 300,
            },
        )
        token_response.raise_for_status()
        token = token_response.json()["ceremony_token"]

        promotion_response = client.post(
            f"/api/v21/projects/{project['id']}/sections/{section['id']}/candidates/{candidate['id']}/promote",
            json={
                "ceremony_token": token,
                "reason": "supplemental live-route authority proof",
                "actor_kind": "human",
                "session_id": identity.session_id,
                "human_ceremony_passed": True,
            },
        )
        body = promotion_response.json()
        receipt = body.get("human_intent_receipt") or {}
        receipt_id = str(receipt.get("receipt_id") or "")
        verification = promotion.verify_receipt(receipt_id) if receipt_id else {
            "ok": False,
            "reason": "route returned no receipt id",
        }
        operation_id = str(receipt.get("operation_id") or "")
        graph = evidence.records_for_operation(operation_id) if operation_id else []
        chain = evidence.verify_chain()
        native_chain_path = run_root / "blackbox" / "events"
        promoted = body.get("result") or {}
        expected_types = [
            "HUMAN_INTENT_RESERVED",
            "HUMAN_INTENT_AUTHORIZED",
            "PRIME_PROMOTED",
            "HUMAN_INTENT_COMPLETED",
            "HUMAN_INTENT_RECEIPT_ANCHORED",
        ]
        actual_types = [record.get("event_type") for record in graph]
        raw_receipt = json.dumps(receipt, sort_keys=True)
        passed = all(
            [
                promotion_response.status_code == 200,
                promoted.get("state") == "prime",
                receipt.get("receipt_type") == "human_intent_receipt_v2",
                bool(receipt.get("ceremony_token_id")),
                bool(receipt.get("ceremony_consumption_hash")),
                "ceremony_token" not in receipt,
                token not in raw_receipt,
                actual_types == expected_types,
                bool(verification.get("ok")),
                bool(chain.get("ok")),
                not native_chain_path.exists(),
            ]
        )
        return {
            "probe_id": "LAW-003-LIVE-WALLET-PROMOTION",
            "generated_at": utc_now(),
            "pass": passed,
            "wallet_version": wallet_version,
            "route": (
                "/api/v21/projects/{project_id}/sections/{section_id}/"
                "candidates/{candidate_id}/promote"
            ),
            "http_status": promotion_response.status_code,
            "project_id": project.get("id"),
            "section_id": section.get("id"),
            "candidate_id": candidate.get("id"),
            "candidate_source_sha256": sha256(source),
            "result_state": promoted.get("state"),
            "receipt_id": receipt_id,
            "receipt_type": receipt.get("receipt_type"),
            "receipt_hash": receipt.get("receipt_hash"),
            "ceremony_token_bound": bool(receipt.get("ceremony_token_id")),
            "ceremony_consumption_bound": bool(receipt.get("ceremony_consumption_hash")),
            "raw_token_absent_from_receipt": token not in raw_receipt,
            "event_types": actual_types,
            "expected_event_types": expected_types,
            "receipt_verification": verification,
            "chain_verification": chain,
            "wallet_native_parallel_chain_absent": not native_chain_path.exists(),
            "evidence_limit": receipt.get("evidence_limits"),
            "frozen_benchmark_limitation": (
                "The frozen LAW-003 score still proxies through the historical "
                "compatibility-adapter forgery probe. This supplemental artifact "
                "exercises the live Wallet FastAPI promotion pathway instead."
            ),
        }
    finally:
        server.blackbox21 = previous["blackbox21"]
        server.vault21 = previous["vault21"]
        server.human_access = previous["human_access"]
        server.canonical_evidence21 = previous["canonical_evidence21"]
        server.promotion21 = previous["promotion21"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = run_probe(args.run_root.resolve())
    write_json_once(args.output.resolve(), result)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("pass") else 1


if __name__ == "__main__":
    raise SystemExit(main())
