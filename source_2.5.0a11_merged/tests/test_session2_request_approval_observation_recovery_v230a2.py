from __future__ import annotations

from pathlib import Path

import pytest

from iteration_wallet.canonical_evidence import CanonicalEvidenceAdapter
from iteration_wallet.notification_manager import (
    ActorKind,
    NotificationError,
    NotificationManager,
    RequestStatus,
)


class SwitchableEventEvidence:
    def __init__(self, delegate: CanonicalEvidenceAdapter) -> None:
        self.delegate = delegate
        self.fail = False

    def __getattr__(self, name):
        return getattr(self.delegate, name)

    def write_event(self, event_type: str, summary: str, **extra):
        if self.fail:
            raise RuntimeError("simulated request-observation outage")
        return self.delegate.write_event(event_type, summary, **extra)


def _events(evidence: CanonicalEvidenceAdapter, event_type: str, field: str, value: str):
    return [
        event
        for event in evidence.iter_events()
        if event["event_type"] == event_type
        and event["payload"].get(field) == value
    ]


def test_access_request_and_approval_creation_survive_observation_outage(tmp_path: Path) -> None:
    canonical = CanonicalEvidenceAdapter(tmp_path, session_id="wallet-main")
    evidence = SwitchableEventEvidence(canonical)
    manager = NotificationManager(tmp_path, blackbox=evidence)
    evidence.fail = True

    request = manager.create_access_request(
        vault_id="vault-one",
        object_id="candidate-one",
        action="inspect_metadata",
        requester_id="bot-one",
        claimed_purpose="check status",
        requester_kind=ActorKind.BOT,
        recipients=["josie"],
        head_user_id="josie",
    )

    assert request.approval_id
    approval = manager.get_approval_request(request.approval_id)
    assert approval is not None
    assert approval.status is RequestStatus.PENDING_APPROVAL
    assert manager.get_inbox("josie")

    evidence.fail = False
    first = manager.reconcile_authority_observations()
    second = manager.reconcile_authority_observations()
    assert first["errors"] == []
    assert second["errors"] == []
    assert len(_events(canonical, "PROTECTED_ACCESS_REQUEST_LOGGED", "request_id", request.request_id)) == 1
    assert len(_events(canonical, "HEAD_USER_APPROVAL_CREATED", "approval_id", approval.approval_id)) == 1


def test_terminal_approval_decision_survives_observation_outage_and_updates_request(tmp_path: Path) -> None:
    canonical = CanonicalEvidenceAdapter(tmp_path, session_id="wallet-main")
    evidence = SwitchableEventEvidence(canonical)
    manager = NotificationManager(tmp_path, blackbox=evidence)
    evidence.fail = True
    manager.configure_vault_roles("vault-one", "josie")
    identity = manager.issue_identity_session(
        "josie", "human", verified_methods=["human_ceremony", "typing_challenge"]
    )
    request = manager.create_access_request(
        vault_id="vault-one",
        object_id="candidate-one",
        action="inspect_metadata",
        requester_id="bot-one",
        claimed_purpose="check status",
        requester_kind=ActorKind.BOT,
        recipients=["josie"],
        head_user_id="josie",
    )

    decision = manager.submit_approval_decision(
        request.approval_id,
        approved=True,
        decision_by="josie",
        decision_session_id=identity.session_id,
        reason="allowed for this request",
    )
    assert decision is not None and decision.status is RequestStatus.APPROVED
    stored_request = manager.get_access_request(request.request_id)
    assert stored_request is not None and stored_request.status is RequestStatus.APPROVED

    evidence.fail = False
    report = manager.reconcile_authority_observations()
    assert report["errors"] == []
    assert len(_events(canonical, "HEAD_USER_APPROVAL_DECISION", "approval_id", decision.approval_id)) == 1


def test_unauthorized_decision_is_preserved_and_original_error_is_not_masked(tmp_path: Path) -> None:
    canonical = CanonicalEvidenceAdapter(tmp_path, session_id="wallet-main")
    evidence = SwitchableEventEvidence(canonical)
    manager = NotificationManager(tmp_path, blackbox=evidence)
    manager.configure_vault_roles("vault-one", "josie")
    approval = manager.create_approval_request(
        "vault-one", "candidate-one", "inspect_metadata", "bot-one", "check", "josie"
    )
    mallory_session = manager.issue_identity_session(
        "mallory",
        ActorKind.HUMAN,
        verified_methods=["human_ceremony"],
    )

    evidence.fail = True
    with pytest.raises(NotificationError, match="Only the Head User"):
        manager.submit_approval_decision(
            approval.approval_id,
            approved=True,
            decision_by="mallory",
            decision_session_id=mallory_session.session_id,
        )

    denials = manager.list_authority_denials()
    assert len(denials) == 1
    assert denials[0]["denial_type"] == "UNAUTHORIZED_APPROVAL_DECISION_BLOCKED"
    assert denials[0]["approval_id"] == approval.approval_id

    evidence.fail = False
    assert manager.reconcile_authority_observations()["errors"] == []
    assert len(
        _events(
            canonical,
            "UNAUTHORIZED_APPROVAL_DECISION_BLOCKED",
            "denial_id",
            denials[0]["denial_id"],
        )
    ) == 1


def test_direct_access_denial_never_depends_on_observation_availability(tmp_path: Path) -> None:
    canonical = CanonicalEvidenceAdapter(tmp_path, session_id="wallet-main")
    evidence = SwitchableEventEvidence(canonical)
    manager = NotificationManager(tmp_path, blackbox=evidence)
    evidence.fail = True

    result = manager.evaluate_direct_access(
        actor_kind=ActorKind.BOT,
        action="promote_candidate_to_prime",
        protected=True,
    )
    assert result["allowed"] is False
    assert result["blackbox_event_id"] is None
    denials = manager.list_authority_denials()
    assert len(denials) == 1
    assert denials[0]["denial_type"] == "PROTECTED_DIRECT_ACCESS_DENIED"

    evidence.fail = False
    assert manager.reconcile_authority_observations()["errors"] == []
    assert len(
        _events(
            canonical,
            "PROTECTED_DIRECT_ACCESS_DENIED",
            "denial_id",
            denials[0]["denial_id"],
        )
    ) == 1


def test_incident_bundle_storage_survives_observation_outage_and_reconciles(tmp_path: Path) -> None:
    canonical = CanonicalEvidenceAdapter(tmp_path, session_id="wallet-main")
    evidence = SwitchableEventEvidence(canonical)
    manager = NotificationManager(tmp_path, blackbox=evidence)
    manager._limits["warning_threshold"] = 2
    evidence.fail = True

    manager.create_access_request(
        vault_id="vault-one",
        object_id="candidate-one",
        action="inspect_metadata",
        requester_id="bot-one",
        claimed_purpose="first",
        requester_kind=ActorKind.BOT,
        recipients=["josie"],
        tool_family="test-bot",
    )
    second = manager.create_access_request(
        vault_id="vault-one",
        object_id="candidate-one",
        action="inspect_metadata",
        requester_id="bot-one",
        claimed_purpose="second",
        requester_kind=ActorKind.BOT,
        recipients=["josie"],
        tool_family="test-bot",
    )
    assert "incident_bundle=" in second.system_action
    bundles = list(canonical.incident_dir.glob("*.json"))
    assert len(bundles) == 1

    evidence.fail = False
    report = manager.reconcile_authority_observations()
    assert report["errors"] == []
    incident_id = bundles[0].stem
    assert len(_events(canonical, "REQUEST_INCIDENT_BUNDLE_UPDATED", "incident_id", incident_id)) == 1


def test_terminal_decision_survives_request_projection_write_failure_and_reconciles(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    canonical = CanonicalEvidenceAdapter(tmp_path, session_id="wallet-main")
    manager = NotificationManager(tmp_path, blackbox=canonical)
    manager.configure_vault_roles("vault-one", "josie")
    identity = manager.issue_identity_session(
        "josie", "human", verified_methods=["human_ceremony", "typing_challenge"]
    )
    request = manager.create_access_request(
        vault_id="vault-one",
        object_id="candidate-one",
        action="inspect_metadata",
        requester_id="bot-one",
        claimed_purpose="check status",
        requester_kind=ActorKind.BOT,
        recipients=["josie"],
        head_user_id="josie",
    )

    original_update = manager._update_access_request_status

    def fail_projection(*_args, **_kwargs):
        raise NotificationError("simulated request projection write failure")

    monkeypatch.setattr(manager, "_update_access_request_status", fail_projection)
    decision = manager.submit_approval_decision(
        request.approval_id,
        approved=True,
        decision_by="josie",
        decision_session_id=identity.session_id,
    )
    assert decision is not None and decision.status is RequestStatus.APPROVED
    assert manager.get_approval_request(request.approval_id).status is RequestStatus.APPROVED
    assert manager.get_access_request(request.request_id).status is not RequestStatus.APPROVED

    monkeypatch.setattr(manager, "_update_access_request_status", original_update)
    report = manager.reconcile_authority_observations()
    assert report["errors"] == []
    assert report["request_projections_repaired"] == 1
    assert manager.get_access_request(request.request_id).status is RequestStatus.APPROVED


def test_reconciliation_repairs_missing_request_to_approval_link(tmp_path: Path) -> None:
    canonical = CanonicalEvidenceAdapter(tmp_path, session_id="wallet-main")
    manager = NotificationManager(tmp_path, blackbox=canonical)
    request = manager.create_access_request(
        vault_id="vault-one",
        object_id="candidate-one",
        action="inspect_metadata",
        requester_id="bot-one",
        claimed_purpose="check status",
        requester_kind=ActorKind.BOT,
        recipients=["josie"],
        head_user_id="josie",
    )
    approval_id = request.approval_id
    assert approval_id

    broken_projection = manager.get_access_request(request.request_id)
    broken_projection.approval_id = None
    manager._save_access_request(broken_projection)

    report = manager.reconcile_authority_observations()
    assert report["errors"] == []
    assert report["request_projections_repaired"] == 1
    repaired = manager.get_access_request(request.request_id)
    assert repaired.approval_id == approval_id
