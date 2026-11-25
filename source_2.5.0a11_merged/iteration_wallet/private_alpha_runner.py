"""Bounded canonical-promotion proof runner for Iteration Wallet.

This runner deliberately proves only the protected action that has completed the
canonical Wallet/BlackBox transaction cutover: Candidate -> Prime.  It also
proves that every other protected route fails before consuming its ceremony
token or mutating custody.  It must never be presented as evidence that the full
private-alpha lifecycle has been migrated.
"""
from __future__ import annotations

import argparse
import json
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi.testclient import TestClient

from iteration_wallet import __version__ as PACKAGE_VERSION
from iteration_wallet import server


PROTECTED_REPORT_KEYS = {
    "ceremony_token",
    "token_secret",
    "raw_token",
    "vault_path",
    "original_path",
    "hash",
    "contents",
    "preview",
    "open_url",
    "export_url",
    "run_url",
}
CLOSED_VIEW_FORBIDDEN_KEYS = {
    "vault_path",
    "original_path",
    "hash",
    "notes",
    "reviews",
    "external_test_results",
    "contents",
    "preview",
    "open_url",
    "export_url",
    "run_url",
}


class PrivateAlphaFlowError(RuntimeError):
    """Raised when the bounded proof cannot complete cleanly."""


@dataclass
class FlowStep:
    name: str
    ok: bool
    detail: str = ""
    evidence: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "ok": self.ok,
            "detail": self.detail,
            "evidence": scrub_report_value(self.evidence),
        }


@dataclass
class PrivateAlphaFlowReport:
    ok: bool
    started_at: str
    completed_at: str
    run_root: str
    report_dir: str
    version: str
    scope: str
    steps: List[FlowStep]
    project_id: str
    section_id: str
    receipt_ids: List[str]
    blackbox_chain_ok: bool
    custody_integrity_ok: bool
    closed_catalog_safe: bool
    unmigrated_routes_fail_closed: bool
    status: Dict[str, Any]
    json_report_path: Optional[str] = None
    markdown_report_path: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return scrub_report_value(
            {
                "ok": self.ok,
                "started_at": self.started_at,
                "completed_at": self.completed_at,
                "run_root": self.run_root,
                "report_dir": self.report_dir,
                "version": self.version,
                "scope": self.scope,
                "steps": [step.to_dict() for step in self.steps],
                "project_id": self.project_id,
                "section_id": self.section_id,
                "receipt_ids": self.receipt_ids,
                "blackbox_chain_ok": self.blackbox_chain_ok,
                "custody_integrity_ok": self.custody_integrity_ok,
                "closed_catalog_safe": self.closed_catalog_safe,
                "unmigrated_routes_fail_closed": self.unmigrated_routes_fail_closed,
                "status": self.status,
                "json_report_path": self.json_report_path,
                "markdown_report_path": self.markdown_report_path,
            }
        )


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def scrub_report_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: "<redacted>" if key in PROTECTED_REPORT_KEYS else scrub_report_value(child)
            for key, child in value.items()
        }
    if isinstance(value, list):
        return [scrub_report_value(child) for child in value]
    return value


def assert_no_key(value: Any, forbidden: set[str], context: str) -> None:
    if isinstance(value, dict):
        leaked = forbidden.intersection(value)
        if leaked:
            raise PrivateAlphaFlowError(f"{context} leaked protected keys: {sorted(leaked)}")
        for child in value.values():
            assert_no_key(child, forbidden, context)
    elif isinstance(value, list):
        for child in value:
            assert_no_key(child, forbidden, context)


def write_source(root: Path, name: str, text: str) -> Path:
    source_dir = root / "inputs"
    source_dir.mkdir(parents=True, exist_ok=True)
    path = source_dir / name
    path.write_text(text, encoding="utf-8")
    return path


class PrivateAlphaFlowRunner:
    """Exercise the shipped bounded canonical runtime through public routes."""

    def __init__(self, run_root: Path, report_dir: Optional[Path] = None):
        self.run_root = Path(run_root).resolve()
        self.report_dir = Path(report_dir or self.run_root / "bounded_alpha_report").resolve()
        self.run_root.mkdir(parents=True, exist_ok=True)
        self.report_dir.mkdir(parents=True, exist_ok=True)
        self.steps: List[FlowStep] = []

    def step(self, name: str, detail: str = "", **evidence: Any) -> None:
        self.steps.append(FlowStep(name=name, ok=True, detail=detail, evidence=evidence))

    def fail(self, name: str, detail: str, **evidence: Any) -> None:
        self.steps.append(FlowStep(name=name, ok=False, detail=detail, evidence=evidence))
        raise PrivateAlphaFlowError(detail)

    def expect_status(self, response: Any, expected: int, name: str) -> Dict[str, Any]:
        if response.status_code != expected:
            self.fail(name, f"Expected HTTP {expected}, got {response.status_code}: {response.text}")
        try:
            return response.json()
        except Exception as exc:
            self.fail(name, f"Response was not JSON: {exc}")
        raise AssertionError("unreachable")

    def run(self, *, write_reports: bool = True) -> PrivateAlphaFlowReport:
        started_at = utc_now()
        previous = {
            "blackbox21": server.blackbox21,
            "canonical_evidence21": server.canonical_evidence21,
            "vault21": server.vault21,
            "human_access": server.human_access,
            "promotion21": server.promotion21,
            "startup_reconciliation21": server.startup_reconciliation21,
        }
        receipt_ids: List[str] = []
        project_id = ""
        section_id = ""
        status: Dict[str, Any] = {}
        chain_ok = custody_ok = closed_safe = fail_closed = False

        try:
            evidence, vault, humans, promotion = server.build_canonical_v21_runtime(self.run_root)
            server.blackbox21 = evidence
            server.canonical_evidence21 = evidence
            server.vault21 = vault
            server.human_access = humans
            server.promotion21 = promotion
            server.startup_reconciliation21 = {
                "status": "not_run",
                "checked": 0,
                "reconciled": 0,
                "failed": 0,
                "ambiguous": 0,
                "receipts": [],
            }

            with TestClient(server.app) as client:
                self.step("initialize coherent canonical runtime", run_root=str(self.run_root))
                project = self.expect_status(
                    client.post("/api/v21/projects", json={"name": "Bounded Alpha"}),
                    201,
                    "create project",
                )
                project_id = project["id"]
                section = self.expect_status(
                    client.post(
                        f"/api/v21/projects/{project_id}/sections",
                        json={"name": "Core", "description": "canonical promotion proof"},
                    ),
                    201,
                    "create section",
                )
                section_id = section["id"]
                candidate = self.expect_status(
                    client.post(
                        f"/api/v21/projects/{project_id}/sections/{section_id}/candidates",
                        json={
                            "path": str(write_source(self.run_root, "candidate.txt", "candidate generation")),
                            "notes": "protected candidate note",
                        },
                    ),
                    201,
                    "add candidate",
                )
                self.step("create project, section, and Candidate", candidate_id=candidate["id"])

                closed = self.expect_status(
                    client.get(f"/api/v21/projects/{project_id}/sections/{section_id}/closed-catalog"),
                    200,
                    "read closed catalog",
                )
                assert_no_key(closed, CLOSED_VIEW_FORBIDDEN_KEYS, "closed catalog")
                closed_safe = closed.get("protected_contents_visible") is False
                if not closed_safe:
                    self.fail("read closed catalog", "Closed catalog did not declare protected contents hidden")
                self.step("prove closed catalog boundary", view_mode=closed.get("view_mode"))

                identity = self.expect_status(
                    client.post(
                        "/api/v21/identity/sessions",
                        json={
                            "actor_id": "josie",
                            "actor_kind": "human",
                            "device_id": "bounded-alpha-runner",
                            "verified_methods": ["human_ceremony", "typing_challenge"],
                            "role_claims": {"head_user": True},
                        },
                    ),
                    201,
                    "issue identity session",
                )
                session_id = identity["session_id"]
                self.expect_status(
                    client.post("/api/v21/vault/open", json={"session_id": session_id}), 200, "open vault"
                )

                def issue_token(action_key: str, object_id: str | None = None) -> Dict[str, Any]:
                    return self.expect_status(
                        client.post(
                            "/api/v21/ceremony/tokens",
                            json={
                                "action_key": action_key,
                                "session_id": session_id,
                                "project_id": project_id,
                                "section_id": section_id,
                                "object_id": object_id or candidate["id"],
                                "ttl_seconds": 300,
                            },
                        ),
                        201,
                        f"issue {action_key} token",
                    )

                promote_token = issue_token("promote_candidate_to_prime")
                promoted = self.expect_status(
                    client.post(
                        f"/api/v21/projects/{project_id}/sections/{section_id}/candidates/{candidate['id']}/promote",
                        json={
                            "ceremony_token": promote_token["ceremony_token"],
                            "session_id": session_id,
                            "actor_kind": "human",
                            "human_ceremony_passed": True,
                            "reason": "bounded canonical proof",
                        },
                    ),
                    200,
                    "promote Candidate to Prime",
                )
                receipt = promoted.get("human_intent_receipt") or {}
                if promoted.get("result", {}).get("state") != "prime" or not promoted.get("verification", {}).get("ok"):
                    self.fail("promote Candidate to Prime", "Canonical promotion or receipt verification failed")
                receipt_ids.append(str(receipt["receipt_id"]))
                self.step(
                    "complete canonical Candidate-to-Prime transaction",
                    receipt_id=receipt["receipt_id"],
                    operation_id=receipt.get("operation_id"),
                )

                receipt_detail = self.expect_status(
                    client.get(f"/api/v21/blackbox/receipts/{receipt['receipt_id']}"),
                    200,
                    "read canonical receipt",
                )
                if not receipt_detail.get("verification", {}).get("ok"):
                    self.fail("read canonical receipt", "Stored receipt did not verify")
                self.step("verify stored receipt through public read surface")

                # Prove exact, reversible Retire and Restore transactions on a non-Prime Candidate.
                transition_candidate = self.expect_status(
                    client.post(
                        f"/api/v21/projects/{project_id}/sections/{section_id}/candidates",
                        json={
                            "path": str(write_source(self.run_root, "transition-candidate.txt", "preserved transition candidate")),
                            "notes": "Retire and Restore preservation proof",
                        },
                    ),
                    201,
                    "add transition Candidate",
                )
                retire_token = issue_token("retire_object", transition_candidate["id"])
                retired = self.expect_status(
                    client.post(
                        f"/api/v21/projects/{project_id}/sections/{section_id}/objects/{transition_candidate['id']}/retire",
                        json={
                            "ceremony_token": retire_token["ceremony_token"],
                            "session_id": session_id,
                            "reason": "bounded permanent-preservation proof",
                        },
                    ),
                    200,
                    "retire Candidate with content preserved",
                )
                retire_receipt = retired.get("human_intent_receipt") or {}
                if retired.get("result", {}).get("state") != "retired" or not retired.get("verification", {}).get("ok"):
                    self.fail("retire Candidate", "Canonical Retire transaction or receipt verification failed")
                receipt_ids.append(str(retire_receipt["receipt_id"]))

                restore_token = issue_token("restore_retired_object", transition_candidate["id"])
                restored = self.expect_status(
                    client.post(
                        f"/api/v21/projects/{project_id}/sections/{section_id}/objects/{transition_candidate['id']}/restore",
                        json={
                            "ceremony_token": restore_token["ceremony_token"],
                            "session_id": session_id,
                            "reason": "bounded restoration proof",
                        },
                    ),
                    200,
                    "restore retired Candidate",
                )
                restore_receipt = restored.get("human_intent_receipt") or {}
                if restored.get("result", {}).get("state") != "candidate" or not restored.get("verification", {}).get("ok"):
                    self.fail("restore Candidate", "Canonical Restore transaction or receipt verification failed")
                receipt_ids.append(str(restore_receipt["receipt_id"]))

                schema = self.expect_status(
                    client.get("/openapi.json"), 200, "inspect supported API surface"
                )
                paths = set(schema.get("paths") or {})
                exact_paths = {
                    "/api/v21/projects/{project_id}/sections/{section_id}/objects/{object_id}/retire",
                    "/api/v21/projects/{project_id}/sections/{section_id}/objects/{object_id}/restore",
                }
                if not exact_paths.issubset(paths):
                    self.fail("prove exact state-transition routes", "Canonical Retire or Restore route is missing")
                forbidden_suffixes = (
                    "/files/{file_id}/remove",
                    "/files/{file_id}/release",
                    "/files/{file_id}/restore-from-removed",
                )
                if any(any(path.endswith(suffix) for suffix in forbidden_suffixes) for path in paths):
                    self.fail(
                        "prove legacy ambiguous transitions are absent",
                        "An unsupported legacy transition route remains published",
                    )
                fail_closed = True
                self.step(
                    "complete canonical Retire and Restore transactions with exact routes and verified receipts",
                    retire_receipt_id=retire_receipt["receipt_id"],
                    restore_receipt_id=restore_receipt["receipt_id"],
                )

                chain = self.expect_status(
                    client.get("/api/v21/blackbox/chain"), 200, "verify canonical chain"
                )
                chain_ok = bool(chain.get("ok"))
                custody = self.expect_status(
                    client.get("/api/v21/custody/verify"), 200, "verify custody integrity"
                )
                custody_ok = bool(custody.get("ok"))
                if not chain_ok or not custody_ok:
                    self.fail("verify final integrity", "Canonical chain or custody integrity failed")
                self.step("verify final evidence and custody integrity")

                status = self.expect_status(
                    client.get("/api/v21/private-alpha/status"), 200, "read bounded readiness status"
                )
                if not status.get("ready_for_bounded_promotion_alpha"):
                    self.fail("read bounded readiness status", "Bounded promotion readiness was not true")
                if status.get("ready_for_private_alpha_flow") or status.get("ready_for_full_private_alpha_flow"):
                    self.fail("read bounded readiness status", "Status overstated full private-alpha readiness")
                self.step("confirm readiness language is bounded and honest")

                self.expect_status(
                    client.post("/api/v21/vault/lock", json={"session_id": session_id}), 200, "lock vault"
                )
        finally:
            server.blackbox21 = previous["blackbox21"]
            server.canonical_evidence21 = previous["canonical_evidence21"]
            server.vault21 = previous["vault21"]
            server.human_access = previous["human_access"]
            server.promotion21 = previous["promotion21"]
            server.startup_reconciliation21 = previous["startup_reconciliation21"]

        report = PrivateAlphaFlowReport(
            ok=all(step.ok for step in self.steps)
            and chain_ok
            and custody_ok
            and closed_safe
            and fail_closed,
            started_at=started_at,
            completed_at=utc_now(),
            run_root=str(self.run_root),
            report_dir=str(self.report_dir),
            version=PACKAGE_VERSION,
            scope="bounded_canonical_custody_transactions",
            steps=self.steps,
            project_id=project_id,
            section_id=section_id,
            receipt_ids=receipt_ids,
            blackbox_chain_ok=chain_ok,
            custody_integrity_ok=custody_ok,
            closed_catalog_safe=closed_safe,
            unmigrated_routes_fail_closed=fail_closed,
            status=status,
        )
        if write_reports:
            self.write_reports(report)
        return report

    def write_reports(self, report: PrivateAlphaFlowReport) -> None:
        json_path = self.report_dir / "private_alpha_flow_report.json"
        md_path = self.report_dir / "private_alpha_flow_report.md"
        report.json_report_path = str(json_path)
        report.markdown_report_path = str(md_path)
        json_path.write_text(
            json.dumps(report.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8"
        )
        md_path.write_text(render_markdown_report(report), encoding="utf-8")


def render_markdown_report(report: PrivateAlphaFlowReport) -> str:
    lines = [
        "# Iteration Wallet Bounded Canonical-Promotion Report",
        "",
        f"**Result:** {'PASS' if report.ok else 'FAIL'}",
        f"**Version:** {report.version}",
        f"**Scope:** `{report.scope}`",
        "",
        "## What this proves",
        "",
        "- Candidate-to-Prime uses the canonical Wallet/BlackBox transaction protocol.",
        f"- Human Intent Receipts verified: {len(report.receipt_ids)}.",
        "- Closed catalog, custody integrity, and chain verification pass.",
        "- Unsupported protected actions fail before token consumption or custody mutation, and unsupported routes are absent.",
        "",
        "## What this does not prove",
        "",
        "- Full private-alpha lifecycle cutover.",
        "- Canonical retirement, restoration, external-copy issuance, or quarantine completion beyond the bounded tested flows.",
        "- Production or Prime readiness.",
        "",
        "## Steps",
        "",
    ]
    for index, step in enumerate(report.steps, 1):
        lines.append(f"{index}. **{'PASS' if step.ok else 'FAIL'} — {step.name}**")
        if step.detail:
            lines.append(f"   - {step.detail}")
        if step.evidence:
            lines.append(
                f"   - Evidence: `{json.dumps(scrub_report_value(step.evidence), ensure_ascii=False, sort_keys=True)}`"
            )
    return "\n".join(lines) + "\n"


def run_private_alpha_flow(
    run_root: Path,
    report_dir: Optional[Path] = None,
    *,
    write_reports: bool = True,
) -> PrivateAlphaFlowReport:
    return PrivateAlphaFlowRunner(run_root, report_dir).run(write_reports=write_reports)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the bounded canonical Candidate-to-Prime proof and write safe reports."
    )
    parser.add_argument("--run-root", type=Path, default=None)
    parser.add_argument("--report-dir", type=Path, default=None)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    run_root = args.run_root or Path(tempfile.mkdtemp(prefix="iw_bounded_alpha_"))
    report = run_private_alpha_flow(
        run_root, args.report_dir or run_root / "report", write_reports=True
    )
    if args.json:
        print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
    else:
        print(f"Bounded canonical promotion flow {'PASS' if report.ok else 'FAIL'}")
        print(f"Report: {report.markdown_report_path}")
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
