from __future__ import annotations

from pathlib import Path

import pytest

from iteration_wallet.canonical_evidence import CanonicalEvidenceAdapter
from iteration_wallet.identity import IdentityError
from iteration_wallet.notification_manager import NotificationManager


class SwitchableEventEvidence:
    def __init__(self, delegate: CanonicalEvidenceAdapter) -> None:
        self.delegate = delegate
        self.fail = False

    def __getattr__(self, name):
        return getattr(self.delegate, name)

    def write_event(self, event_type: str, summary: str, **extra):
        if self.fail:
            raise RuntimeError("simulated authority-observation outage")
        return self.delegate.write_event(event_type, summary, **extra)


def _events(evidence: CanonicalEvidenceAdapter, event_type: str, field: str, value: str):
    return [
        event
        for event in evidence.iter_events()
        if event["event_type"] == event_type
        and event["payload"].get(field) == value
    ]


def test_identity_issuance_and_revocation_survive_observation_outage(tmp_path: Path) -> None:
    canonical = CanonicalEvidenceAdapter(tmp_path, session_id="wallet-main")
    evidence = SwitchableEventEvidence(canonical)
    manager = NotificationManager(tmp_path, blackbox=evidence)

    evidence.fail = True
    identity = manager.issue_identity_session(
        actor_id="josie",
        actor_kind="human",
        verified_methods=["human_ceremony", "typing_challenge"],
    )
    assert manager.require_identity_session(identity.session_id).actor_id == "josie"

    revoked = manager.revoke_identity_session(identity.session_id, "manual logout")
    assert revoked is not None and revoked.revoked_at is not None

    evidence.fail = False
    first = manager.reconcile_authority_observations()
    second = manager.reconcile_authority_observations()
    assert first["errors"] == []
    assert second["errors"] == []
    assert len(_events(canonical, "IDENTITY_SESSION_ISSUED", "session_id", identity.session_id)) == 1
    assert len(_events(canonical, "IDENTITY_SESSION_REVOKED", "session_id", identity.session_id)) == 1


def test_invalid_identity_rejection_is_preserved_without_masking_identity_error(tmp_path: Path) -> None:
    canonical = CanonicalEvidenceAdapter(tmp_path, session_id="wallet-main")
    evidence = SwitchableEventEvidence(canonical)
    manager = NotificationManager(tmp_path, blackbox=evidence)

    evidence.fail = True
    with pytest.raises(IdentityError, match="Unknown identity session"):
        manager.require_identity_session("missing-session")

    denials = manager.list_identity_denials()
    assert len(denials) == 1
    assert denials[0]["session_id"] == "missing-session"
    assert denials[0]["reason"] == "Unknown identity session"

    evidence.fail = False
    report = manager.reconcile_authority_observations()
    assert report["errors"] == []
    events = _events(canonical, "IDENTITY_SESSION_INVALID", "session_id", "missing-session")
    assert len(events) == 1


def test_role_changes_are_append_only_locally_and_reconcile_idempotently(tmp_path: Path) -> None:
    canonical = CanonicalEvidenceAdapter(tmp_path, session_id="wallet-main")
    evidence = SwitchableEventEvidence(canonical)
    manager = NotificationManager(tmp_path, blackbox=evidence)

    evidence.fail = True
    first = manager.configure_vault_roles(
        "vault-one", "josie", admins=["alice"], authorized_users=["bob"]
    )
    second = manager.configure_vault_roles(
        "vault-one", "josie", admins=["alice", "carol"], authorized_users=["bob"]
    )
    assert first["admins"] == ["alice"]
    assert second["admins"] == ["alice", "carol"]

    history = manager.list_role_history("vault-one")
    assert len(history) == 2
    assert history[0]["change_id"] != history[1]["change_id"]
    assert history[0]["vault_roles"]["admins"] == ["alice"]
    assert history[1]["vault_roles"]["admins"] == ["alice", "carol"]

    evidence.fail = False
    first_report = manager.reconcile_authority_observations()
    second_report = manager.reconcile_authority_observations()
    assert first_report["errors"] == []
    assert second_report["errors"] == []
    events = _events(canonical, "VAULT_ROLES_CONFIGURED", "vault_id", "vault-one")
    assert len(events) == 2
    assert {event["payload"]["change_id"] for event in events} == {
        history[0]["change_id"], history[1]["change_id"]
    }
