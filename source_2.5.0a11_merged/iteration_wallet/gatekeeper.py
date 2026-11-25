"""
Iteration Wallet v2.1.7 — Protected Action Registry / Human Intent Gatekeeper
=============================================================================

This module centralizes the custody actions that require the human-intent gate.

Product law:
- Protected custody actions must be known, named, and registered.
- Bots/AI/tools may request protected access, but may not directly perform it.
- A protected route that uses an unregistered action key must fail closed.

This module is deliberately policy-only. It does not open, export, promote,
retire, restore, or mutate custody objects. Engines and API routes must call this module
before performing any protected action.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Dict, Optional

from iteration_wallet.identity import ActorIdentity
from iteration_wallet.notification_manager import ActorKind, NotificationManager


class ProtectedActionError(Exception):
    """Raised when a protected action is unknown or denied by policy."""


@dataclass(frozen=True)
class ProtectedActionPolicy:
    """Policy for one protected custody action."""

    action_key: str
    label: str
    requires_human: bool = True
    requires_vault_open: bool = True
    requires_cradle_unlock: bool = False
    allows_bot_direct_access: bool = False
    requires_head_user_approval_when_configured: bool = False
    allowed_fallbacks: tuple[str, ...] = ()
    blackbox_event_type: str = "PROTECTED_ACTION_ATTEMPT"

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["allowed_fallbacks"] = list(self.allowed_fallbacks)
        return data


PROTECTED_ACTIONS: Dict[str, ProtectedActionPolicy] = {
    "retire_object": ProtectedActionPolicy(
        action_key="retire_object",
        label="retire protected object",
        # Restored: the predecessor action (release_from_custody, in the
        # other build lineage this was reconciled against) carried this same
        # opt-in Head User/admin approval gate. It was silently dropped when
        # the action was renamed/restructured into retire/restore as part of
        # the Permanent Preservation Hardening work -- retiring is the most
        # sensitive of the two (it moves material out of active use), so the
        # protection is restored here rather than left dropped.
        requires_head_user_approval_when_configured=True,
        blackbox_event_type="RETIRE_OBJECT_REQUESTED",
    ),
    "restore_retired_object": ProtectedActionPolicy(
        action_key="restore_retired_object",
        label="restore retired object",
        blackbox_event_type="RESTORE_RETIRED_OBJECT_REQUESTED",
    ),
    "quarantine": ProtectedActionPolicy(
        action_key="quarantine",
        label="quarantine file",
        blackbox_event_type="QUARANTINE_REQUESTED",
    ),
    "admit_oubliette_derivative_as_candidate": ProtectedActionPolicy(
        action_key="admit_oubliette_derivative_as_candidate",
        label="admit cleared Oubliette derivative as a new Candidate",
        blackbox_event_type="OUBLIETTE_DERIVATIVE_ADMISSION_REQUESTED",
    ),
    "promote_candidate_to_prime": ProtectedActionPolicy(
        action_key="promote_candidate_to_prime",
        label="promote Candidate to Prime",
        requires_cradle_unlock=True,
        blackbox_event_type="PROMOTE_CANDIDATE_TO_PRIME_REQUESTED",
    ),
    "export_working_copy": ProtectedActionPolicy(
        action_key="export_working_copy",
        label="export working copy",
        allowed_fallbacks=("head_user_override", "trusted_device", "configured_external_lab"),
        blackbox_event_type="EXPORT_WORKING_COPY_REQUESTED",
    ),
    "admit_labcopy_result_as_candidate": ProtectedActionPolicy(
        action_key="admit_labcopy_result_as_candidate",
        label="admit returned LabCopy result as a new Candidate",
        blackbox_event_type="LABCOPY_RESULT_ADMISSION_REQUESTED",
    ),
    "open_vault": ProtectedActionPolicy(
        action_key="open_vault",
        label="open Vault",
        requires_vault_open=False,
        allowed_fallbacks=("head_user_override", "email_confirmation", "camera_verification"),
        blackbox_event_type="OPEN_VAULT_REQUESTED",
    ),
    "open_cradle": ProtectedActionPolicy(
        action_key="open_cradle",
        label="open Cradle",
        requires_cradle_unlock=False,
        allowed_fallbacks=("head_user_override", "camera_verification", "typing_challenge"),
        blackbox_event_type="OPEN_CRADLE_REQUESTED",
    ),
}


def get_protected_action_policy(action_key: str) -> ProtectedActionPolicy:
    """Return registered policy or fail closed for unknown protected actions."""
    try:
        return PROTECTED_ACTIONS[action_key]
    except KeyError as exc:
        raise ProtectedActionError(
            f"Protected action is not registered: {action_key!r}. "
            "Failing closed so no route can invent its own custody gate."
        ) from exc


def list_protected_action_policies() -> Dict[str, Dict[str, Any]]:
    """Return serializable registered policy map for diagnostics/UI."""
    return {key: policy.to_dict() for key, policy in PROTECTED_ACTIONS.items()}


def _coerce_actor_kind(actor_kind: ActorKind | str | None) -> ActorKind:
    if isinstance(actor_kind, ActorKind):
        return actor_kind
    try:
        return ActorKind(str(actor_kind or ActorKind.UNKNOWN.value))
    except ValueError:
        return ActorKind.UNKNOWN


def evaluate_protected_action(
    action_key: str,
    actor_kind: ActorKind | str | None,
    *,
    actor_identity: Optional[ActorIdentity] = None,
    human_ceremony_passed: bool = False,
    vault_open: Optional[bool] = None,
    cradle_unlocked: Optional[bool] = None,
    vault_id: Optional[str] = None,
    gate: Optional[NotificationManager] = None,
) -> Dict[str, Any]:
    """Evaluate a registered protected action and return a decision dict.

    Unknown actions fail closed. Optional `vault_open` / `cradle_unlocked`
    checks only deny when explicitly supplied as False; engines may still enforce
    their own state and ceremony tokens internally.
    """
    policy = get_protected_action_policy(action_key)
    if actor_identity is not None:
        actor_kind = actor_identity.actor_kind
        human_ceremony_passed = bool(human_ceremony_passed or actor_identity.has_human_intent_proof())
    kind = _coerce_actor_kind(actor_kind)

    if policy.requires_head_user_approval_when_configured and gate is not None and vault_id:
        roles = gate.get_vault_roles(vault_id)
        configured_head = roles.get("head_user_id")
        configured_admins = set(roles.get("admins") or [])
        if configured_head or configured_admins:
            actor_id = actor_identity.actor_id if actor_identity is not None else None
            if not actor_id or (actor_id != configured_head and actor_id not in configured_admins):
                return {
                    "allowed": False,
                    "action_key": action_key,
                    "action": policy.label,
                    "reason": "Configured Head User or admin approval is required for this protected action.",
                    "reason_code": "head_user_approval_required",
                    "policy": policy.to_dict(),
                    "blackbox_event_type": policy.blackbox_event_type,
                }

    if policy.requires_vault_open and vault_open is False:
        return {
            "allowed": False,
            "action_key": action_key,
            "action": policy.label,
            "reason": "Vault must be open for this protected custody action.",
            "blackbox_event_type": policy.blackbox_event_type,
        }
    if policy.requires_cradle_unlock and cradle_unlocked is False:
        return {
            "allowed": False,
            "action_key": action_key,
            "action": policy.label,
            "reason": "Cradle must be unlocked for this protected custody action.",
            "blackbox_event_type": policy.blackbox_event_type,
        }

    if gate is not None:
        decision = gate.evaluate_direct_access(
            kind,
            policy.label,
            protected=True,
            human_ceremony_passed=bool(human_ceremony_passed),
            actor_identity=actor_identity,
        )
    else:
        if not policy.allows_bot_direct_access and kind in {
            ActorKind.AI_ASSISTANT,
            ActorKind.BOT,
            ActorKind.TOOL,
            ActorKind.SCRIPT,
            ActorKind.UNKNOWN,
        }:
            decision = {
                "allowed": False,
                "reason": "No autonomous bot/AI/tool access to protected custody. Request human approval instead.",
            }
        elif policy.requires_human and not human_ceremony_passed:
            decision = {
                "allowed": False,
                "reason": "Protected custody requires live authorized human ceremony.",
            }
        else:
            decision = {"allowed": True, "reason": "registered human-intent policy passed"}

    decision.update(
        {
            "action_key": action_key,
            "action": policy.label,
            "policy": policy.to_dict(),
            "blackbox_event_type": policy.blackbox_event_type,
        }
    )
    return decision


def require_protected_action(
    action_key: str,
    actor_kind: ActorKind | str | None,
    *,
    actor_identity: Optional[ActorIdentity] = None,
    human_ceremony_passed: bool = False,
    vault_open: Optional[bool] = None,
    cradle_unlocked: Optional[bool] = None,
    vault_id: Optional[str] = None,
    gate: Optional[NotificationManager] = None,
) -> Dict[str, Any]:
    """Return decision if allowed; raise ProtectedActionError otherwise."""
    decision = evaluate_protected_action(
        action_key,
        actor_kind,
        actor_identity=actor_identity,
        human_ceremony_passed=human_ceremony_passed,
        vault_open=vault_open,
        cradle_unlocked=cradle_unlocked,
        vault_id=vault_id,
        gate=gate,
    )
    if not decision.get("allowed"):
        raise ProtectedActionError(decision.get("reason", "Protected custody action denied."))
    return decision
