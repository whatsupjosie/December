from pathlib import Path

import pytest

from iteration_wallet.ceremony import CeremonyTokenError, CeremonyTokenLedger


def test_ceremony_token_binds_exact_proposal_without_breaking_legacy_scope(tmp_path: Path):
    ledger = CeremonyTokenLedger(tmp_path)
    issued = ledger.issue_token(
        action_key="admit_oubliette_derivative_as_candidate",
        session_id="identity1",
        open_session_id="open1",
        project_id="project1",
        section_id="section1",
        object_id="parent1",
        proposal_id="proposal1",
        proposal_hash="a" * 64,
    )
    raw = issued["ceremony_token"]
    with pytest.raises(CeremonyTokenError, match="proposal_id"):
        ledger.validate_and_consume(
            raw,
            action_key="admit_oubliette_derivative_as_candidate",
            session_id="identity1",
            open_session_id="open1",
            project_id="project1",
            section_id="section1",
            object_id="parent1",
            proposal_id="proposal2",
            proposal_hash="b" * 64,
        )
    assert ledger.get_record(issued["token_id"])["consumed_at"] is None
    consumed = ledger.validate_and_consume(
        raw,
        action_key="admit_oubliette_derivative_as_candidate",
        session_id="identity1",
        open_session_id="open1",
        project_id="project1",
        section_id="section1",
        object_id="parent1",
        proposal_id="proposal1",
        proposal_hash="a" * 64,
    )
    assert consumed["proposal_id"] == "proposal1"
    assert consumed["proposal_hash"] == "a" * 64


def test_proposal_fields_must_be_paired(tmp_path: Path):
    ledger = CeremonyTokenLedger(tmp_path)
    with pytest.raises(CeremonyTokenError, match="together"):
        ledger.issue_token(
            action_key="quarantine",
            session_id="identity1",
            open_session_id="open1",
            proposal_id="proposal1",
        )
