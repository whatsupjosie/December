from __future__ import annotations

from pathlib import Path

import pytest

from iteration_wallet import server
from iteration_wallet.oubliette_transaction import OublietteTransactionError


def test_disabled_oubliette_does_not_block_wallet_blackbox_core(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("IW_OUBLIETTE_MODE", "disabled")
    evidence, vault, humans, promotion = server.build_canonical_v21_runtime(tmp_path / "disabled")

    assert vault.oubliette_coordinator is None
    assert vault.oubliette_requested_mode == "disabled"
    project = vault.create_project("Core without Oubliette")
    section = vault.create_section(project["id"], "Core")
    assert section["id"]
    assert evidence.verify_chain()["ok"] is True
    assert promotion.vault is vault
    assert promotion.evidence is evidence
    assert promotion.human_access is humans


def test_inspect_only_oubliette_refuses_custody_crossings_without_hindering_core(
    tmp_path: Path, monkeypatch
):
    monkeypatch.setenv("IW_OUBLIETTE_MODE", "inspect")
    evidence, vault, humans, promotion = server.build_canonical_v21_runtime(tmp_path / "inspect")
    coordinator = vault.oubliette_coordinator

    capability = coordinator.capability()
    assert capability["level"] == "inspect_and_request"
    assert capability["static_inspection"] is True
    assert capability["wallet_owned_crossings"] is False
    assert capability["execution_supported"] is False
    assert promotion.vault is vault
    assert evidence.verify_chain()["ok"] is True

    with pytest.raises(OublietteTransactionError, match="inspect-only mode"):
        coordinator.quarantine(
            project_id="not-used",
            section_id="not-used",
            object_id="not-used",
            report_id="not-used",
            ceremony_token="not-used",
            session_id="not-used",
            reason="must fail before custody lookup",
        )


def test_transaction_mode_is_explicit_and_invalid_mode_fails_to_disabled(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("IW_OUBLIETTE_MODE", "transaction")
    _, transaction_vault, _, _ = server.build_canonical_v21_runtime(tmp_path / "transaction")
    assert transaction_vault.oubliette_coordinator.capability()["level"] == "transaction_ready"

    monkeypatch.setenv("IW_OUBLIETTE_MODE", "surprise-me")
    _, invalid_vault, _, _ = server.build_canonical_v21_runtime(tmp_path / "invalid")
    assert invalid_vault.oubliette_coordinator is None
    assert invalid_vault.oubliette_requested_mode == "disabled"
