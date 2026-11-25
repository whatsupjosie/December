"""
Manual verification harness for the P0 fix: submit_approval_decision now
requires decision_session_id and no longer accepts an unauthenticated
decision_by-only fallback.

pytest is not installable in this offline sandbox (no network egress), so
this exercises the exact same NotificationManager code path the real pytest
suite (tests/test_notification_manager_v215.py,
tests/test_human_intent_gatekeeper_v216.py,
tests/test_session2_authority_storage_regressions_v230a2.py,
tests/test_identity_session_v218.py) covers, using stdlib unittest instead.
This is a supplement to, not a replacement for, running the real suite with
pytest once network/pip access is available -- see the handoff notes.
"""
import sys
import tempfile
import threading
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "source_2.5.0a11_merged"))

from iteration_wallet.notification_manager import (  # noqa: E402
    ActorKind,
    NotificationError,
    NotificationManager,
    RequestStatus,
)
from iteration_wallet.identity import IdentityError  # noqa: E402

PASSED = []
FAILED = []


def check(name, fn):
    try:
        fn()
        PASSED.append(name)
        print(f"PASS  {name}")
    except Exception as exc:
        FAILED.append((name, exc))
        print(f"FAIL  {name}: {exc}")
        traceback.print_exc()


def tmp():
    return Path(tempfile.mkdtemp())


# ---------------------------------------------------------------------------
# THE EXPLOIT, RE-RUN AGAINST THE PATCHED CODE
# ---------------------------------------------------------------------------
def exploit_no_session_no_decision_by_is_rejected():
    """The original, unpatched bug: omit decision_session_id entirely and
    supply nothing else. Pre-fix this fell through to
    `if not decision_by or not is_head_user_or_admin(...)` and was rejected
    only because decision_by was also empty -- but a caller who *knew* a
    valid head/admin id string could pass just that and get approval power
    with zero identity proof. Confirm the new code rejects unconditionally
    on missing session, before it ever looks at decision_by."""
    nm = NotificationManager(tmp())
    nm.configure_vault_roles("vault", head_user_id="head", admins=["admin-a"])
    approval = nm.create_approval_request("vault", "prime", "export working copy", "bot", "compare", "head")
    try:
        nm.submit_approval_decision(approval.approval_id, True, decision_by="admin-a")
        raise AssertionError("expected NotificationError: bare decision_by with no session must be rejected")
    except NotificationError as e:
        assert "identity session" in str(e), f"wrong error: {e}"


def exploit_known_admin_string_without_session_still_rejected():
    """This is the actual exploit shape from 01_VERIFIED_STATE.md §2: caller
    knows a real admin identifier and supplies exactly that as decision_by,
    with no session at all. Must still be rejected post-fix."""
    nm = NotificationManager(tmp())
    nm.configure_vault_roles("vault", head_user_id="head-user", admins=["known-admin-id"])
    approval = nm.create_approval_request("vault", "prime", "promote_to_prime", "bot", "review", "head-user")
    try:
        nm.submit_approval_decision(approval.approval_id, True, decision_by="known-admin-id")
        raise AssertionError("SECURITY REGRESSION: unauthenticated decision_by with a real admin id was accepted")
    except NotificationError:
        pass
    stored = nm.get_approval_request(approval.approval_id)
    assert stored.status == RequestStatus.PENDING_APPROVAL, "approval must remain pending, not silently decided"


def valid_session_head_user_can_approve():
    nm = NotificationManager(tmp())
    nm.configure_vault_roles("vault", head_user_id="head", admins=["admin-a"])
    approval = nm.create_approval_request("vault", "prime", "export working copy", "bot", "compare", "head")
    head_session = nm.issue_identity_session("head", ActorKind.HUMAN, verified_methods=["human_ceremony"])
    decided = nm.submit_approval_decision(approval.approval_id, True, decision_session_id=head_session.session_id)
    assert decided.status == RequestStatus.APPROVED
    assert decided.decision_by == "head"


def valid_session_non_admin_is_rejected():
    nm = NotificationManager(tmp())
    nm.configure_vault_roles("vault", head_user_id="head", admins=["admin-a"])
    approval = nm.create_approval_request("vault", "prime", "export working copy", "bot", "compare", "head")
    random_session = nm.issue_identity_session("random-user", ActorKind.HUMAN, verified_methods=["human_ceremony"])
    try:
        nm.submit_approval_decision(approval.approval_id, True, decision_session_id=random_session.session_id)
        raise AssertionError("random authenticated user must not be able to approve")
    except NotificationError:
        pass


def decision_by_mismatch_still_rejected():
    nm = NotificationManager(tmp())
    nm.configure_vault_roles("vault", head_user_id="head", admins=["admin-a"])
    approval = nm.create_approval_request("vault", "prime", "export working copy", "bot", "compare", "head")
    head_session = nm.issue_identity_session("head", ActorKind.HUMAN, verified_methods=["human_ceremony"])
    try:
        nm.submit_approval_decision(
            approval.approval_id, True, decision_by="spoofed-other-user", decision_session_id=head_session.session_id
        )
        raise AssertionError("decision_by spoofing a different identity than the session must be rejected")
    except NotificationError as e:
        assert "does not match" in str(e)


def bot_session_without_human_intent_rejected():
    nm = NotificationManager(tmp())
    nm.configure_vault_roles("vault", head_user_id="head")
    approval = nm.create_approval_request("vault", "prime", "open cradle", "bot", "fetch", "head")
    bot_session = nm.issue_identity_session("head", ActorKind.BOT, verified_methods=["api_token"])
    try:
        nm.submit_approval_decision(approval.approval_id, True, decision_session_id=bot_session.session_id)
        raise AssertionError("bot session lacking human-intent proof must not approve")
    except NotificationError as e:
        assert "human-intent" in str(e) or "human_intent" in str(e)


def unknown_session_id_rejected():
    nm = NotificationManager(tmp())
    nm.configure_vault_roles("vault", head_user_id="head")
    approval = nm.create_approval_request("vault", "prime", "promote_to_prime", "bot", "review", "head")
    try:
        nm.submit_approval_decision(approval.approval_id, True, decision_session_id="totally-made-up-session-id")
        raise AssertionError("unknown/forged session id must be rejected")
    except NotificationError:
        pass


def write_once_still_enforced():
    nm = NotificationManager(tmp())
    nm.configure_vault_roles("vault", head_user_id="head")
    approval = nm.create_approval_request("vault", "prime", "promote_to_prime", "requester", "review", "head")
    head_session = nm.issue_identity_session("head", ActorKind.HUMAN, verified_methods=["human_ceremony"])
    first = nm.submit_approval_decision(approval.approval_id, True, decision_session_id=head_session.session_id, reason="approved")
    assert first.status is RequestStatus.APPROVED
    try:
        nm.submit_approval_decision(approval.approval_id, False, decision_session_id=head_session.session_id, reason="changed mind")
        raise AssertionError("terminal approval must not be re-decidable")
    except NotificationError as e:
        assert "already terminal" in str(e)


def concurrent_decisions_exactly_one_winner():
    nm = NotificationManager(tmp())
    nm.configure_vault_roles("vault", head_user_id="head")
    approval = nm.create_approval_request("vault", "prime", "promote_to_prime", "requester", "review", "head")
    head_session = nm.issue_identity_session("head", ActorKind.HUMAN, verified_methods=["human_ceremony"])

    barrier = threading.Barrier(2)
    outcomes = []
    lock = threading.Lock()

    def decide(approved):
        barrier.wait()
        try:
            result = nm.submit_approval_decision(
                approval.approval_id, approved, decision_session_id=head_session.session_id,
                reason="yes" if approved else "no",
            )
            outcome = result.status.value if result else "missing"
        except NotificationError as exc:
            outcome = f"error:{exc}"
        with lock:
            outcomes.append(outcome)

    threads = [threading.Thread(target=decide, args=(True,)), threading.Thread(target=decide, args=(False,))]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)

    winners = [v for v in outcomes if v in {"approved", "denied"}]
    losers = [v for v in outcomes if v.startswith("error:")]
    assert len(winners) == 1, outcomes
    assert len(losers) == 1, outcomes
    assert "already terminal" in losers[0]


if __name__ == "__main__":
    check("exploit: bare decision_by, no session -> rejected", exploit_no_session_no_decision_by_is_rejected)
    check("exploit: known-admin-id string, no session -> rejected (THE FIX)", exploit_known_admin_string_without_session_still_rejected)
    check("valid session + head user -> approved", valid_session_head_user_can_approve)
    check("valid session, non-admin actor -> rejected", valid_session_non_admin_is_rejected)
    check("decision_by mismatched vs session identity -> rejected", decision_by_mismatch_still_rejected)
    check("bot session without human-intent proof -> rejected", bot_session_without_human_intent_rejected)
    check("unknown/forged session_id -> rejected", unknown_session_id_rejected)
    check("write-once terminal state still enforced", write_once_still_enforced)
    check("concurrent decisions: exactly one winner", concurrent_decisions_exactly_one_winner)

    print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
    if FAILED:
        sys.exit(1)
