import pytest
from fastapi import HTTPException

from iteration_wallet.gatekeeper import (
    PROTECTED_ACTIONS,
    ProtectedActionError,
    evaluate_protected_action,
    get_protected_action_policy,
)
from iteration_wallet.notification_manager import ActorKind, NotificationManager
from iteration_wallet import server


def test_required_protected_actions_are_registered():
    expected = {
        "retire_object",
        "restore_retired_object",
        "quarantine",
        "promote_candidate_to_prime",
        "export_working_copy",
        "open_vault",
        "open_cradle",
    }
    assert expected.issubset(set(PROTECTED_ACTIONS))
    assert all(PROTECTED_ACTIONS[k].allows_bot_direct_access is False for k in expected)


def test_unknown_protected_action_fails_closed():
    with pytest.raises(ProtectedActionError):
        get_protected_action_policy("new_route_forgot_to_register")
    with pytest.raises(ProtectedActionError):
        evaluate_protected_action("new_route_forgot_to_register", ActorKind.HUMAN, human_ceremony_passed=True)


def test_registered_action_denies_bot_and_allows_human_ceremony(tmp_path):
    gate = NotificationManager(tmp_path)
    denied = evaluate_protected_action(
        "export_working_copy",
        ActorKind.AI_ASSISTANT,
        human_ceremony_passed=True,
        gate=gate,
    )
    assert denied["allowed"] is False
    assert denied["action_key"] == "export_working_copy"
    assert "No autonomous bot" in denied["reason"]

    allowed = evaluate_protected_action(
        "export_working_copy",
        ActorKind.HUMAN,
        human_ceremony_passed=True,
        gate=gate,
    )
    assert allowed["allowed"] is True
    assert allowed["policy"]["blackbox_event_type"] == "EXPORT_WORKING_COPY_REQUESTED"


def test_registry_state_requirements_fail_when_explicitly_false():
    closed = evaluate_protected_action(
        "export_working_copy",
        ActorKind.HUMAN,
        human_ceremony_passed=True,
        vault_open=False,
    )
    assert closed["allowed"] is False
    assert "Vault must be open" in closed["reason"]

    locked = evaluate_protected_action(
        "promote_candidate_to_prime",
        ActorKind.HUMAN,
        human_ceremony_passed=True,
        cradle_unlocked=False,
    )
    assert locked["allowed"] is False
    assert "Cradle must be unlocked" in locked["reason"]


def test_server_protected_helper_uses_registry_and_fails_closed(monkeypatch, tmp_path):
    monkeypatch.setattr(server, "human_access", NotificationManager(tmp_path))
    server.require_human_intent("export_working_copy", "human", True)
    with pytest.raises(HTTPException) as exc:
        server.require_human_intent("unregistered_new_route", "human", True)
    assert exc.value.status_code == 500
    assert "not registered" in exc.value.detail
