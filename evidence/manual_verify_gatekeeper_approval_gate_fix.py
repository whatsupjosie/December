"""
Manual verification: the head-user-approval gate that protected the old
`release_from_custody` action was found dropped when it was renamed to
`retire_object` during the Permanent Preservation Hardening rewrite. This
confirms the fix restores it, and documents the separate, NOT-yet-fixed gap
found alongside it (see 02_TODO.md P1): the flag is necessary but not
sufficient, because iteration_wallet/state_transition_transaction.py never
threads a vault_id through to the gatekeeper check, so
`gate is not None and vault_id` is currently always False for retire/restore
regardless of this flag. Fixing that requires adding a vault_id concept to
the transaction coordinator, which was not attempted this session (untestable
without a live server; see handoff for why).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "source_2.5.0a11_merged"))

from iteration_wallet.gatekeeper import get_protected_action_policy  # noqa: E402

PASSED, FAILED = [], []


def check(name, fn):
    try:
        fn()
        PASSED.append(name)
        print(f"PASS  {name}")
    except Exception as exc:
        FAILED.append((name, exc))
        print(f"FAIL  {name}: {exc}")


def retire_object_requires_approval_gate_when_configured():
    policy = get_protected_action_policy("retire_object")
    assert policy.requires_head_user_approval_when_configured is True, (
        "retire_object should carry the same opt-in approval gate its predecessor "
        "action (release_from_custody) had -- this was found dropped during the "
        "Permanent Preservation Hardening rename/restructure."
    )


def restore_action_exists_and_is_the_lower_stakes_counterpart():
    # restore_retired_object intentionally does NOT carry the gate (mirrors
    # restore_to_active in the other lineage, which also had no approval
    # requirement -- only the *outbound* action was ever gated).
    policy = get_protected_action_policy("restore_retired_object")
    assert policy.requires_head_user_approval_when_configured is False


if __name__ == "__main__":
    check(
        "retire_object approval gate restored (was silently dropped)",
        retire_object_requires_approval_gate_when_configured,
    )
    check(
        "restore_retired_object correctly has no approval gate (matches predecessor)",
        restore_action_exists_and_is_the_lower_stakes_counterpart,
    )
    print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
    if FAILED:
        sys.exit(1)
