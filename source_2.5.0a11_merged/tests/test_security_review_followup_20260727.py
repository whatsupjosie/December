import asyncio
from pathlib import Path

import pytest
from fastapi import HTTPException

from iteration_wallet import server
from iteration_wallet.canonical_evidence import CanonicalEvidenceAdapter
from iteration_wallet.notification_manager import (
    ActorKind,
    NotificationManager,
    RequestStatus,
)
from iteration_wallet.passkey_gate import PasskeyGate
from iteration_wallet.state_transition_transaction import (
    StateTransitionTransactionCoordinator,
    StateTransitionTransactionError,
)
from iteration_wallet.vault_v21 import VaultEngine


def test_http_approval_decision_requires_hardware_gate_in_hardened_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A caller-created "human" session cannot approve without a passkey."""
    evidence = CanonicalEvidenceAdapter(tmp_path, session_id="approval-gate-test")
    humans = NotificationManager(tmp_path, blackbox=evidence)
    humans.configure_vault_roles("vault", head_user_id="head")
    approval = humans.create_approval_request(
        "vault", "candidate", "retire object", "bot", "test", "head"
    )
    self_declared = humans.issue_identity_session(
        "head", ActorKind.HUMAN, verified_methods=["human_ceremony"]
    )

    monkeypatch.setenv("IW_REQUIRE_PASSKEY", "required")
    monkeypatch.setattr(server, "human_access", humans)
    monkeypatch.setattr(server, "passkey_gate", PasskeyGate(tmp_path / "passkey"))

    with pytest.raises(HTTPException) as blocked:
        asyncio.run(
            server.v215_submit_approval_decision(
                approval.approval_id,
                server.ApprovalDecisionRequest(
                    approved=True,
                    decision_session_id=self_declared.session_id,
                ),
            )
        )

    assert blocked.value.status_code == 403
    assert "passkey enrollment" in blocked.value.detail
    assert (
        humans.get_approval_request(approval.approval_id).status
        is RequestStatus.PENDING_APPROVAL
    )


def test_retire_enforces_configured_vault_head_user_scope(tmp_path: Path) -> None:
    """The Retire policy must receive the vault ID or its role gate is inert."""
    evidence = CanonicalEvidenceAdapter(tmp_path, session_id="retire-role-test")
    vault = VaultEngine(tmp_path, blackbox=evidence, strict_ceremony_tokens=True)
    humans = NotificationManager(tmp_path, blackbox=evidence)
    humans.configure_vault_roles("vault", head_user_id="josie")
    transitions = StateTransitionTransactionCoordinator(vault, evidence, humans)
    vault.state_transition_coordinator = transitions

    project = vault.create_project("Role Test")
    section = vault.create_section(project["id"], "Core")
    source = tmp_path / "candidate.txt"
    source.write_text("preserve me", encoding="utf-8")
    candidate = vault.add_candidate(project["id"], section["id"], str(source))
    foreign = humans.issue_identity_session(
        "mallory",
        ActorKind.HUMAN,
        verified_methods=["human_ceremony", "typing_challenge"],
    )
    vault.open_vault()
    token = vault.issue_ceremony_token(
        "retire_object",
        foreign.session_id,
        actor_id=foreign.actor_id,
        project_id=project["id"],
        section_id=section["id"],
        object_id=candidate["id"],
    )["ceremony_token"]

    with pytest.raises(
        StateTransitionTransactionError,
        match="Configured Head User or admin approval",
    ):
        transitions.retire(
            project_id=project["id"],
            section_id=section["id"],
            object_id=candidate["id"],
            ceremony_token=token,
            session_id=foreign.session_id,
        )

    assert vault._find_file(project["id"], section["id"], candidate["id"])["state"] == "candidate"


def test_browser_vault_open_calls_supply_session_and_hardware_approval() -> None:
    html = (
        Path(server.__file__).parent / "static" / "app.html"
    ).read_text(encoding="utf-8")

    assert "ensureVaultOpen(actorId,existingSession=null)" in html
    assert (
        "api('POST','/vault/open',{session_id:session.session_id,hardware_gate_token})"
        in html
    )
    assert "api('POST','/vault/open')" not in html
    assert "api('POST', open?'/vault/lock':'/vault/open')" not in html
