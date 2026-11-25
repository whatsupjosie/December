from pathlib import Path

import pytest
from fastapi import HTTPException

from iteration_wallet.identity import ActorIdentity, IdentityError, LocalIdentityProvider
from iteration_wallet.notification_manager import ActorKind, NotificationError, NotificationManager, RequestStatus
from iteration_wallet.gatekeeper import evaluate_protected_action
from iteration_wallet import server


def test_local_identity_session_shape_and_human_intent_methods(tmp_path: Path):
    provider = LocalIdentityProvider(tmp_path)
    session = provider.issue_session(
        actor_id="josie",
        actor_kind="human",
        device_id="laptop-1",
        verified_methods=["human_ceremony", "typing_challenge"],
        role_claims={"vaults": ["vault"]},
    )

    loaded = provider.require_session(session.session_id)
    assert loaded.actor_id == "josie"
    assert loaded.actor_kind == "human"
    assert loaded.device_id == "laptop-1"
    assert loaded.has_human_intent_proof() is True
    assert loaded.is_valid() is True


def test_approval_decision_uses_session_identity_not_arbitrary_string(tmp_path: Path):
    nm = NotificationManager(tmp_path)
    nm.configure_vault_roles("vault", head_user_id="head", admins=["admin-a"])
    approval = nm.create_approval_request("vault", "prime", "export working copy", "bot", "compare", "head")

    head_session = nm.issue_identity_session(
        "head",
        ActorKind.HUMAN,
        verified_methods=["human_ceremony"],
        device_id="phone-1",
    )
    with pytest.raises(NotificationError):
        nm.submit_approval_decision(
            approval.approval_id,
            True,
            decision_by="spoofed-other-user",
            decision_session_id=head_session.session_id,
        )

    decided = nm.submit_approval_decision(
        approval.approval_id,
        True,
        decision_session_id=head_session.session_id,
    )
    assert decided.status == RequestStatus.APPROVED
    assert decided.decision_by == "head"


def test_bot_session_with_head_user_id_cannot_approve_without_human_intent(tmp_path: Path):
    nm = NotificationManager(tmp_path)
    nm.configure_vault_roles("vault", head_user_id="head")
    approval = nm.create_approval_request("vault", "prime", "open cradle", "bot", "fetch", "head")
    bot_session = nm.issue_identity_session("head", ActorKind.BOT, verified_methods=["api_token"])

    with pytest.raises(NotificationError):
        nm.submit_approval_decision(
            approval.approval_id,
            True,
            decision_session_id=bot_session.session_id,
        )

    assert nm.blackbox.records(), "blocked approval should leave BlackBox evidence"


def test_gatekeeper_accepts_human_identity_session_and_denies_bot_identity(tmp_path: Path):
    nm = NotificationManager(tmp_path)
    human = nm.issue_identity_session("head", ActorKind.HUMAN, verified_methods=["human_ceremony"])
    bot = nm.issue_identity_session("tool", ActorKind.TOOL, verified_methods=["api_token"])

    allowed = evaluate_protected_action(
        "export_working_copy",
        None,
        actor_identity=human,
        gate=nm,
    )
    assert allowed["allowed"] is True
    assert allowed["session_id"] == human.session_id

    denied = evaluate_protected_action(
        "export_working_copy",
        None,
        actor_identity=bot,
        gate=nm,
    )
    assert denied["allowed"] is False
    assert "No autonomous bot" in denied["reason"]


def test_server_protected_routes_require_identity_session_when_route_requests_it(monkeypatch, tmp_path: Path):
    nm = NotificationManager(tmp_path)
    monkeypatch.setattr(server, "human_access", nm)

    with pytest.raises(HTTPException) as missing:
        server.require_human_intent(
            "export_working_copy",
            "human",
            True,
            session_id=None,
            require_identity_session=True,
        )
    assert missing.value.status_code == 403
    assert "identity session" in missing.value.detail

    session = nm.issue_identity_session("head", ActorKind.HUMAN, verified_methods=["human_ceremony"])
    server.require_human_intent(
        "export_working_copy",
        "human",
        False,
        session_id=session.session_id,
        require_identity_session=True,
    )
