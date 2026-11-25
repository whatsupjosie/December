"""
Iteration Wallet private-alpha runner regression tests
==========================================================

The runner is a developer-facing proof surface, not a pytest-only helper. These
checks verify it can produce safe JSON/Markdown reports from a clean isolated
runtime without leaking raw ceremony-token secrets or protected closed-view
fields.
"""

from __future__ import annotations

import json
from pathlib import Path

from iteration_wallet.private_alpha_runner import (
    CLOSED_VIEW_FORBIDDEN_KEYS,
    PROTECTED_REPORT_KEYS,
    run_private_alpha_flow,
)


def _find_keys(value):
    if isinstance(value, dict):
        for key, child in value.items():
            yield key
            yield from _find_keys(child)
    elif isinstance(value, list):
        for child in value:
            yield from _find_keys(child)


def test_private_alpha_runner_creates_safe_reports(tmp_path: Path):
    report = run_private_alpha_flow(tmp_path / "run", tmp_path / "report")

    assert report.ok is True
    from iteration_wallet.version import WALLET_VERSION
    assert report.version == WALLET_VERSION
    assert report.blackbox_chain_ok is True
    assert report.custody_integrity_ok is True
    assert report.closed_catalog_safe is True
    assert len(report.receipt_ids) == 3
    assert report.json_report_path
    assert report.markdown_report_path

    json_path = Path(report.json_report_path)
    markdown_path = Path(report.markdown_report_path)
    assert json_path.exists()
    assert markdown_path.exists()

    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert data["ok"] is True
    assert data["status"]["ready_for_bounded_promotion_alpha"] is True
    assert data["status"]["ready_for_private_alpha_flow"] is False
    assert data["unmigrated_routes_fail_closed"] is True
    assert data["status"]["unmigrated_protected_actions"] == []
    from iteration_wallet.version import WALLET_VERSION
    assert data["status"]["version"] == WALLET_VERSION

    # Report must be useful evidence, but not a secret dump.
    all_keys = set(_find_keys(data))
    assert "ceremony_token" not in all_keys
    assert not (CLOSED_VIEW_FORBIDDEN_KEYS & all_keys)
    assert not ({"token_secret", "raw_token"} & all_keys)

    text = markdown_path.read_text(encoding="utf-8")
    assert "Result:** PASS" in text
    assert "What this does not prove" in text
    assert "Human Intent Receipts" in text
    assert "\"ceremony_token\"" not in text


def test_private_alpha_runner_report_scrubs_protected_keys(tmp_path: Path):
    report = run_private_alpha_flow(tmp_path / "run", tmp_path / "report", write_reports=False)
    data = report.to_dict()
    all_keys = set(_find_keys(data))
    assert not ({"ceremony_token", "token_secret", "raw_token"} & all_keys)
    assert not (PROTECTED_REPORT_KEYS & all_keys)
