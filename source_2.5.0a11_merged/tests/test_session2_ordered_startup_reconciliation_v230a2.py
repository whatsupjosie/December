from __future__ import annotations

from pathlib import Path
import os

from iteration_wallet import server


def _install_isolated_runtime(root: Path):
    previous = {
        "blackbox21": server.blackbox21,
        "canonical_evidence21": server.canonical_evidence21,
        "vault21": server.vault21,
        "human_access": server.human_access,
        "promotion21": server.promotion21,
        "startup_reconciliation21": server.startup_reconciliation21,
    }
    prior_mode = os.environ.get("IW_OUBLIETTE_MODE")
    os.environ["IW_OUBLIETTE_MODE"] = "transaction"
    try:
        evidence, vault, humans, promotion = server.build_canonical_v21_runtime(root)
    finally:
        if prior_mode is None:
            os.environ.pop("IW_OUBLIETTE_MODE", None)
        else:
            os.environ["IW_OUBLIETTE_MODE"] = prior_mode
    server.blackbox21 = evidence
    server.canonical_evidence21 = evidence
    server.vault21 = vault
    server.human_access = humans
    server.promotion21 = promotion
    server.startup_reconciliation21 = {"status": "not_run", "checked": 0}
    return previous


def _restore(previous):
    for key, value in previous.items():
        setattr(server, key, value)


def test_ordered_startup_reconciliation_runs_every_independent_stage(tmp_path: Path, monkeypatch):
    previous = _install_isolated_runtime(tmp_path)
    calls: list[str] = []
    try:
        stage_targets = [
            (server.vault21.state_transition_coordinator, "reconcile_pending", "state_transition_journals", {"checked": 0, "reconciled": 0, "failed": 0, "ambiguous": 0, "receipts": []}),
            (server.promotion21, "reconcile_pending", "promotion_journals", {"checked": 0, "reconciled": 0, "failed": 0, "ambiguous": 0, "receipts": []}),
            (server.vault21.oubliette_coordinator, "reconcile_pending", "oubliette_journals", {"checked": 0, "reconciled": 0, "failed": 0, "ambiguous": 0, "receipts": []}),
            (server.vault21.labcopy_coordinator, "reconcile_pending", "labcopy_journals", {"checked": 0, "reconciled": 0, "failed": 0, "ambiguous": 0, "receipts": []}),
            (server.vault21, "flush_evidence_outbox", "catalog_outbox", {"pending": 0, "delivered": 0, "errors": []}),
            (server.vault21.ceremony_ledger, "reconcile_observations", "ceremony", {"checked": 0, "delivered": 0, "errors": []}),
            (server.human_access, "reconcile_request_projections", "request_approval_projections", {"checked": 0, "repaired": 0, "errors": []}),
            (server.human_access, "reconcile_identity_observations", "identity", {"checked": 0, "delivered": 0, "errors": []}),
            (server.human_access, "reconcile_role_observations", "roles", {"checked": 0, "delivered": 0, "errors": []}),
            (server.human_access, "reconcile_request_observations", "requests", {"checked": 0, "delivered": 0, "errors": []}),
            (server.human_access, "reconcile_approval_observations", "approvals", {"checked": 0, "delivered": 0, "errors": []}),
            (server.human_access, "reconcile_denial_observations", "denials", {"checked": 0, "delivered": 0, "errors": []}),
            (server.human_access, "reconcile_incident_observations", "incidents", {"checked": 0, "delivered": 0, "errors": []}),
        ]
        for target, attribute, name, result in stage_targets:
            def fake(name=name, result=result):
                calls.append(name)
                return dict(result)
            monkeypatch.setattr(target, attribute, fake)

        report = server.run_ordered_startup_reconciliation()
        expected = [item[2] for item in stage_targets]
        assert calls == expected
        assert report["order"] == expected
        assert report["status"] == "complete"
        assert all(report["stages"][name]["status"] == "complete" for name in expected)
    finally:
        _restore(previous)


def test_startup_reconciliation_reports_failure_and_continues(tmp_path: Path, monkeypatch):
    previous = _install_isolated_runtime(tmp_path)
    later_stage_ran = False
    try:
        def broken_outbox():
            raise RuntimeError("simulated outbox failure")

        def incidents():
            nonlocal later_stage_ran
            later_stage_ran = True
            return {"checked": 0, "delivered": 0, "errors": []}

        monkeypatch.setattr(server.vault21, "flush_evidence_outbox", broken_outbox)
        monkeypatch.setattr(server.human_access, "reconcile_incident_observations", incidents)
        report = server.run_ordered_startup_reconciliation()
        assert report["status"] == "attention_required"
        assert report["stages"]["catalog_outbox"]["status"] == "failed"
        assert "catalog_outbox" in report["failed_stages"]
        assert later_stage_ran is True
    finally:
        _restore(previous)


def test_fresh_runtime_startup_reconciliation_is_idempotent(tmp_path: Path):
    previous = _install_isolated_runtime(tmp_path)
    try:
        first = server.run_ordered_startup_reconciliation()
        second = server.run_ordered_startup_reconciliation()
        assert first["status"] == "complete"
        assert second["status"] == "complete"
        assert first["order"] == second["order"]
        assert first["failed_stages"] == []
        assert second["failed_stages"] == []
    finally:
        _restore(previous)
