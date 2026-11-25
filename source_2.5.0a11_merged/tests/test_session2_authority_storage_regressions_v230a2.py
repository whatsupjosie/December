from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from iteration_wallet.canonical_evidence import CanonicalEvidenceAdapter
from iteration_wallet.notification_manager import (
    ActorKind,
    NotificationError,
    NotificationManager,
    RequestStatus,
)


def test_notification_manager_defaults_to_canonical_evidence(tmp_path: Path) -> None:
    manager = NotificationManager(tmp_path)
    assert isinstance(manager.blackbox, CanonicalEvidenceAdapter)
    assert manager.request_dir == tmp_path / "canonical_blackbox_support" / "requests"
    assert not (tmp_path / "blackbox").exists()


def test_corrupt_role_file_fails_closed_instead_of_erasing_roles(tmp_path: Path) -> None:
    manager = NotificationManager(tmp_path)
    manager.configure_vault_roles("vault", head_user_id="head", admins=["admin"])
    manager.role_file.write_text('{"vaults": {}, "vaults": {}}', encoding="utf-8")

    with pytest.raises(NotificationError, match="role configuration"):
        manager.get_vault_roles("vault")


def test_approval_storage_rejects_traversal_identifier(tmp_path: Path) -> None:
    manager = NotificationManager(tmp_path)
    with pytest.raises(NotificationError, match="approval_id"):
        manager.get_approval_request("../outside")


def test_terminal_approval_decision_is_write_once(tmp_path: Path) -> None:
    manager = NotificationManager(tmp_path)
    manager.configure_vault_roles("vault", head_user_id="head")
    approval = manager.create_approval_request(
        "vault", "prime", "promote_to_prime", "requester", "review", "head"
    )
    head_session = manager.issue_identity_session(
        "head",
        ActorKind.HUMAN,
        verified_methods=["human_ceremony"],
    )

    first = manager.submit_approval_decision(
        approval.approval_id,
        True,
        decision_session_id=head_session.session_id,
        reason="approved",
    )
    assert first is not None and first.status is RequestStatus.APPROVED

    with pytest.raises(NotificationError, match="already terminal"):
        manager.submit_approval_decision(
            approval.approval_id,
            False,
            decision_session_id=head_session.session_id,
            reason="changed mind",
        )

    stored = manager.get_approval_request(approval.approval_id)
    assert stored is not None
    assert stored.status is RequestStatus.APPROVED
    assert stored.decision_reason == "approved"


def test_concurrent_approval_decisions_have_exactly_one_winner(tmp_path: Path) -> None:
    manager = NotificationManager(tmp_path)
    manager.configure_vault_roles("vault", head_user_id="head")
    approval = manager.create_approval_request(
        "vault", "prime", "promote_to_prime", "requester", "review", "head"
    )
    head_session = manager.issue_identity_session(
        "head",
        ActorKind.HUMAN,
        verified_methods=["human_ceremony"],
    )

    barrier = threading.Barrier(3)
    outcomes: list[str] = []
    lock = threading.Lock()

    def decide(approved: bool) -> None:
        barrier.wait()
        try:
            result = manager.submit_approval_decision(
                approval.approval_id,
                approved,
                decision_session_id=head_session.session_id,
                reason="yes" if approved else "no",
            )
            outcome = result.status.value if result else "missing"
        except NotificationError as exc:
            outcome = f"error:{exc}"
        with lock:
            outcomes.append(outcome)

    threads = [
        threading.Thread(target=decide, args=(True,)),
        threading.Thread(target=decide, args=(False,)),
    ]
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join(timeout=5)

    assert len(outcomes) == 2
    winners = [value for value in outcomes if value in {"approved", "denied"}]
    losers = [value for value in outcomes if value.startswith("error:")]
    assert len(winners) == 1
    assert len(losers) == 1
    assert "already terminal" in losers[0]

    stored = manager.get_approval_request(approval.approval_id)
    assert stored is not None
    assert stored.status.value == winners[0]


def test_corrupt_approval_record_is_not_silently_treated_as_missing(tmp_path: Path) -> None:
    manager = NotificationManager(tmp_path)
    approval = manager.create_approval_request(
        "vault", "prime", "promote_to_prime", "requester", "review", "head"
    )
    path = manager.approval_dir / f"{approval.approval_id}.json"
    path.write_text('{"approval_id":"x","approval_id":"y"}', encoding="utf-8")

    with pytest.raises(NotificationError, match="approval record"):
        manager.get_approval_request(approval.approval_id)


def test_role_updates_do_not_lose_concurrent_vault_entries(tmp_path: Path) -> None:
    manager_a = NotificationManager(tmp_path)
    manager_b = NotificationManager(tmp_path)
    barrier = threading.Barrier(3)
    errors: list[BaseException] = []

    def configure(manager: NotificationManager, vault_id: str, head: str) -> None:
        barrier.wait()
        try:
            manager.configure_vault_roles(vault_id, head_user_id=head)
        except BaseException as exc:  # pragma: no cover - captured for assertion
            errors.append(exc)

    threads = [
        threading.Thread(target=configure, args=(manager_a, "vault-a", "head-a")),
        threading.Thread(target=configure, args=(manager_b, "vault-b", "head-b")),
    ]
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join(timeout=5)

    assert not errors
    manager_c = NotificationManager(tmp_path)
    assert manager_c.get_vault_roles("vault-a")["head_user_id"] == "head-a"
    assert manager_c.get_vault_roles("vault-b")["head_user_id"] == "head-b"
