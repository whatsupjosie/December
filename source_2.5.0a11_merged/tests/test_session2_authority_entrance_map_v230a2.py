from __future__ import annotations

import inspect
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import iteration_wallet
from iteration_wallet import server
from iteration_wallet.canonical_evidence import CanonicalEvidenceAdapter
from iteration_wallet.vault_v21 import VaultEngine, VaultError


def test_package_does_not_export_retired_writable_blackbox() -> None:
    assert not hasattr(iteration_wallet, "BlackBox")


def test_active_server_does_not_import_retired_writable_blackbox() -> None:
    source = Path(server.__file__).read_text(encoding="utf-8")
    assert "from iteration_wallet.blackbox import BlackBox" not in source


def test_vault_engine_defaults_to_strict_canonical_mode() -> None:
    parameter = inspect.signature(VaultEngine).parameters["strict_ceremony_tokens"]
    assert parameter.default is True


def test_direct_prime_promotion_is_never_a_public_authority_path(tmp_path: Path) -> None:
    evidence = CanonicalEvidenceAdapter(tmp_path, session_id="entrance-map")
    vault = VaultEngine(tmp_path, blackbox=evidence)
    project = vault.create_project("Entrance")
    section = vault.create_section(project["id"], "Core")
    source = tmp_path / "candidate.txt"
    source.write_text("candidate", encoding="utf-8")
    candidate = vault.add_candidate(project["id"], section["id"], str(source))
    vault.open_vault()
    with pytest.raises(VaultError, match="transaction coordinator"):
        vault.promote_to_prime(
            project["id"], section["id"], candidate["id"], "not-authority"
        )


def test_canonical_retirement_token_requires_valid_human_intent_session(tmp_path: Path) -> None:
    evidence, vault, humans, promotion = server.build_canonical_v21_runtime(tmp_path, oubliette_mode="transaction")
    old = (server.blackbox21, server.canonical_evidence21, server.vault21, server.human_access, server.promotion21)
    server.blackbox21 = evidence
    server.canonical_evidence21 = evidence
    server.vault21 = vault
    server.human_access = humans
    server.promotion21 = promotion
    try:
        with TestClient(server.app) as client:
            session = client.post(
                "/api/v21/identity/sessions",
                json={
                    "actor_id": "josie",
                    "actor_kind": "human",
                    "verified_methods": ["human_ceremony", "typing_challenge"],
                },
            ).json()
            client.post("/api/v21/vault/open", json={"session_id": session["session_id"]})
            response = client.post(
                "/api/v21/ceremony/tokens",
                json={
                    "action_key": "retire_object",
                    "session_id": session["session_id"],
                    "project_id": "p",
                    "section_id": "s",
                    "object_id": "f",
                },
            )
            assert response.status_code == 201, response.text
            token = response.json()
            assert token["action_key"] == "retire_object"
            assert token["object_id"] == "f"
            assert len(vault.list_ceremony_tokens()) == 1
    finally:
        (
            server.blackbox21,
            server.canonical_evidence21,
            server.vault21,
            server.human_access,
            server.promotion21,
        ) = old


def test_retired_wallet_native_blackbox_fails_at_construction(tmp_path: Path) -> None:
    from iteration_wallet.blackbox import BlackBox, LegacyBlackBoxRetiredError

    with pytest.raises(LegacyBlackBoxRetiredError, match="second canonical evidence chain"):
        BlackBox(tmp_path)
    assert not (tmp_path / "blackbox").exists()


def test_retired_v2_vault_engine_fails_at_construction(tmp_path: Path) -> None:
    from iteration_wallet.vault import VaultEngine as RetiredVaultEngine
    from iteration_wallet.vault import VaultError as RetiredVaultError

    with pytest.raises(RetiredVaultError, match="retired"):
        RetiredVaultEngine(tmp_path)
    assert not (tmp_path / "state.json").exists()


def test_preserving_state_transitions_have_no_direct_engine_bypass_methods() -> None:
    for method_name in (
        "remove_file",
        "restore_file",
        "release_from_custody",
        "delete_file",
    ):
        assert not hasattr(VaultEngine, method_name)


def test_legacy_ambiguous_custody_routes_are_absent_and_exact_routes_are_published() -> None:
    paths = set(server.app.openapi()["paths"])
    forbidden_fragments = (
        "/restore-from-removed",
        "/files/{file_id}/restore",
        "/files/{file_id}/remove",
        "/files/{file_id}/release",
    )
    assert all(not any(fragment in path for fragment in forbidden_fragments) for path in paths)
    assert "/api/v21/projects/{project_id}/sections/{section_id}/objects/{object_id}/retire" in paths
    assert "/api/v21/projects/{project_id}/sections/{section_id}/objects/{object_id}/restore" in paths


def test_protected_action_registry_reports_runtime_availability(tmp_path: Path) -> None:
    evidence, vault, humans, promotion = server.build_canonical_v21_runtime(tmp_path, oubliette_mode="transaction")
    old = (
        server.blackbox21,
        server.canonical_evidence21,
        server.vault21,
        server.human_access,
        server.promotion21,
    )
    server.blackbox21 = evidence
    server.canonical_evidence21 = evidence
    server.vault21 = vault
    server.human_access = humans
    server.promotion21 = promotion
    try:
        with TestClient(server.app) as client:
            response = client.get("/api/v21/protected-actions")
            assert response.status_code == 200
            body = response.json()
            actions = body["protected_actions"]
            assert actions["promote_candidate_to_prime"]["runtime_status"] == "canonical_transaction_available"
            assert actions["promote_candidate_to_prime"]["ceremony_token_issuance_available"] is True
            assert actions["quarantine"]["runtime_status"] == "canonical_transaction_available"
            assert actions["quarantine"]["ceremony_token_issuance_available"] is True
            assert actions["admit_oubliette_derivative_as_candidate"]["runtime_status"] == "canonical_transaction_available"
            assert actions["retire_object"]["runtime_status"] == "canonical_transaction_available"
            assert actions["retire_object"]["ceremony_token_issuance_available"] is True
            assert actions["restore_retired_object"]["runtime_status"] == "canonical_transaction_available"
            assert actions["restore_retired_object"]["ceremony_token_issuance_available"] is True
            assert actions["open_vault"]["runtime_status"] == "session_control_available_no_general_authority_token"
            assert body["canonical_protected_actions"] == [
                "admit_labcopy_result_as_candidate",
                "admit_oubliette_derivative_as_candidate",
                "export_working_copy",
                "promote_candidate_to_prime",
                "quarantine",
                "restore_retired_object",
                "retire_object",
            ]
    finally:
        (
            server.blackbox21,
            server.canonical_evidence21,
            server.vault21,
            server.human_access,
            server.promotion21,
        ) = old


def test_unchecked_promotion_has_no_optional_direct_evidence_bypass() -> None:
    signature = inspect.signature(VaultEngine._promote_candidate_to_prime_unchecked)
    assert "emit_blackbox" not in signature.parameters
    source = inspect.getsource(VaultEngine._promote_candidate_to_prime_unchecked)
    assert "_blackbox_custody_event" not in source
    assert "write_custody_event" not in source
