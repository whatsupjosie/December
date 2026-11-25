from __future__ import annotations

from pathlib import Path

import pytest

from iteration_wallet.canonical_evidence import CanonicalEvidenceAdapter
from iteration_wallet.ceremony import CeremonyTokenError, CeremonyTokenLedger


class SwitchableEventEvidence:
    def __init__(self, delegate: CanonicalEvidenceAdapter) -> None:
        self.delegate = delegate
        self.fail = False

    def __getattr__(self, name):
        return getattr(self.delegate, name)

    def write_event(self, event_type: str, summary: str, **extra):
        if self.fail:
            raise RuntimeError("simulated observational evidence outage")
        return self.delegate.write_event(event_type, summary, **extra)


def _events(evidence: CanonicalEvidenceAdapter, event_type: str, token_id: str):
    return [
        event
        for event in evidence.iter_events()
        if event["event_type"] == event_type
        and event["payload"].get("token_id") == token_id
    ]


def _issue(ledger: CeremonyTokenLedger):
    return ledger.issue_token(
        action_key="promote_candidate_to_prime",
        session_id="identity-session",
        open_session_id="open-session",
        actor_id="josie",
        project_id="project-one",
        section_id="section-one",
        object_id="candidate-one",
    )


def test_token_issuance_succeeds_during_observation_outage_and_reconciles_once(tmp_path: Path) -> None:
    canonical = CanonicalEvidenceAdapter(tmp_path, session_id="wallet-main")
    evidence = SwitchableEventEvidence(canonical)
    evidence.fail = True
    ledger = CeremonyTokenLedger(tmp_path, blackbox=evidence)

    issued = _issue(ledger)
    token_id = issued["token_id"]
    assert ledger.get_record(token_id)["consumed_at"] is None
    assert _events(canonical, "CEREMONY_TOKEN_ISSUED", token_id) == []

    evidence.fail = False
    first = ledger.reconcile_observations()
    second = ledger.reconcile_observations()
    assert first["delivered"] == 1
    assert first["errors"] == []
    assert second["delivered"] == 1  # idempotent duplicate acknowledgement
    assert len(_events(canonical, "CEREMONY_TOKEN_ISSUED", token_id)) == 1


def test_consumed_record_hash_is_immutable_across_observation_reconciliation(tmp_path: Path) -> None:
    canonical = CanonicalEvidenceAdapter(tmp_path, session_id="wallet-main")
    evidence = SwitchableEventEvidence(canonical)
    ledger = CeremonyTokenLedger(tmp_path, blackbox=evidence)
    issued = _issue(ledger)

    evidence.fail = True
    consumed = ledger.validate_and_consume(
        issued["ceremony_token"],
        action_key="promote_candidate_to_prime",
        session_id="identity-session",
        open_session_id="open-session",
        project_id="project-one",
        section_id="section-one",
        object_id="candidate-one",
    )
    assert consumed["consumed_at"] is not None
    before = ledger.record_hash(issued["token_id"])

    evidence.fail = False
    report = ledger.reconcile_observations(issued["token_id"])
    after = ledger.record_hash(issued["token_id"])
    assert report["errors"] == []
    assert before == after
    assert len(_events(canonical, "CEREMONY_TOKEN_CONSUMED", issued["token_id"])) == 1


def test_revocation_succeeds_during_observation_outage_and_reconciles(tmp_path: Path) -> None:
    canonical = CanonicalEvidenceAdapter(tmp_path, session_id="wallet-main")
    evidence = SwitchableEventEvidence(canonical)
    ledger = CeremonyTokenLedger(tmp_path, blackbox=evidence)
    issued = _issue(ledger)

    evidence.fail = True
    revoked = ledger.revoke_token(issued["ceremony_token"], reason="user changed her mind")
    assert revoked["revoked_at"] is not None

    evidence.fail = False
    report = ledger.reconcile_observations(issued["token_id"])
    assert report["errors"] == []
    assert len(_events(canonical, "CEREMONY_TOKEN_REVOKED", issued["token_id"])) == 1


def test_denial_is_preserved_without_raw_secret_and_reconciles(tmp_path: Path) -> None:
    canonical = CanonicalEvidenceAdapter(tmp_path, session_id="wallet-main")
    evidence = SwitchableEventEvidence(canonical)
    ledger = CeremonyTokenLedger(tmp_path, blackbox=evidence)
    issued = _issue(ledger)

    evidence.fail = True
    with pytest.raises(CeremonyTokenError, match="not valid for this action"):
        ledger.validate_and_consume(
            issued["ceremony_token"],
            action_key="retire_object",
            session_id="identity-session",
            open_session_id="open-session",
            project_id="project-one",
            section_id="section-one",
            object_id="candidate-one",
        )

    denials = ledger.list_denials()
    assert len(denials) == 1
    assert denials[0]["reason"] == "Ceremony token is not valid for this action"
    assert issued["ceremony_token"] not in str(denials[0])
    assert "token_hash" not in denials[0]

    evidence.fail = False
    report = ledger.reconcile_observations(issued["token_id"])
    assert report["errors"] == []
    denial_events = _events(canonical, "CEREMONY_TOKEN_DENIED", issued["token_id"])
    assert len(denial_events) == 1
    assert denial_events[0]["payload"]["reason"] == denials[0]["reason"]
