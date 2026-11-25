from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient

from iteration_wallet.passkey_gate import PasskeyGate, PasskeyGateError, _b64d
from iteration_wallet import server


def b64e(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def client_data(kind: str, challenge: str, origin: str = "http://localhost:7432") -> tuple[bytes, str]:
    raw = json.dumps(
        {"type": kind, "challenge": challenge, "origin": origin, "crossOrigin": False},
        separators=(",", ":"),
    ).encode("utf-8")
    return raw, b64e(raw)


def auth_data(counter: int, rp_id: str = "localhost", flags: int = 0x05) -> bytes:
    return hashlib.sha256(rp_id.encode("utf-8")).digest() + bytes([flags]) + counter.to_bytes(4, "big")


def enroll_es256(
    gate: PasskeyGate,
    *,
    credential_id: str = "credential-one",
    hardware_gate_token: str | None = None,
):
    private_key = ec.generate_private_key(ec.SECP256R1())
    public_der = private_key.public_key().public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    options = gate.registration_options(
        origin="http://localhost:7432",
        label="Windows Hello",
        attachment="platform",
        hardware_gate_token=hardware_gate_token,
    )
    _, encoded_client = client_data("webauthn.create", options["publicKey"]["challenge"])
    result = gate.register(
        {
            "challenge_id": options["challenge_id"],
            "credential_id": b64e(credential_id.encode()),
            "client_data_json": encoded_client,
            "authenticator_data": b64e(auth_data(0)),
            "public_key_spki": b64e(public_der),
            "algorithm": -7,
            "transports": ["internal"],
            "attachment": "platform",
            "label": "Windows Hello",
        }
    )
    return private_key, result["credential"]["credential_id"]


def authenticate(
    gate: PasskeyGate,
    private_key,
    credential_id: str,
    *,
    action_key: str,
    context: dict[str, str],
    counter: int = 1,
):
    options = gate.authentication_options(
        origin="http://localhost:7432", action_key=action_key, context=context
    )
    raw_client, encoded_client = client_data("webauthn.get", options["publicKey"]["challenge"])
    raw_auth = auth_data(counter)
    signature = private_key.sign(raw_auth + hashlib.sha256(raw_client).digest(), ec.ECDSA(hashes.SHA256()))
    return gate.authenticate(
        {
            "challenge_id": options["challenge_id"],
            "credential_id": credential_id,
            "client_data_json": encoded_client,
            "authenticator_data": b64e(raw_auth),
            "signature": b64e(signature),
            "user_handle": None,
        }
    )


def test_passkey_assertion_mints_exact_single_use_gate_token(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("IW_REQUIRE_PASSKEY", "auto")
    gate = PasskeyGate(tmp_path / "wallet")
    private_key, credential_id = enroll_es256(gate)
    context = {"project_id": "project-1", "proposal_id": "proposal-1"}
    assertion = authenticate(
        gate,
        private_key,
        credential_id,
        action_key="export_working_copy",
        context=context,
    )

    consumed = gate.consume_gate_token(
        assertion["hardware_gate_token"],
        action_key="export_working_copy",
        context=context,
    )
    assert consumed["verified"] is True
    assert consumed["credential_id"] == credential_id

    with pytest.raises(PasskeyGateError, match="already used"):
        gate.consume_gate_token(
            assertion["hardware_gate_token"],
            action_key="export_working_copy",
            context=context,
        )


def test_passkey_token_rejects_wrong_action_and_context(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("IW_REQUIRE_PASSKEY", "auto")
    gate = PasskeyGate(tmp_path / "wallet")
    private_key, credential_id = enroll_es256(gate)
    assertion = authenticate(
        gate,
        private_key,
        credential_id,
        action_key="promote_candidate_to_prime",
        context={"project_id": "p", "object_id": "candidate-a"},
    )
    token = assertion["hardware_gate_token"]
    with pytest.raises(PasskeyGateError, match="different action"):
        gate.consume_gate_token(token, action_key="export_working_copy", context={"project_id": "p"})
    with pytest.raises(PasskeyGateError, match="context"):
        gate.consume_gate_token(
            token,
            action_key="promote_candidate_to_prime",
            context={"project_id": "p", "object_id": "candidate-b"},
        )


def test_passkey_token_replay_remains_blocked_after_restart(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("IW_REQUIRE_PASSKEY", "required")
    wallet_root = tmp_path / "wallet"
    gate = PasskeyGate(wallet_root)
    private_key, credential_id = enroll_es256(gate)
    assertion = authenticate(
        gate,
        private_key,
        credential_id,
        action_key="hardware_gate_check",
        context={},
    )
    token = assertion["hardware_gate_token"]
    assert gate.consume_gate_token(
        token,
        action_key="hardware_gate_check",
        context={},
    )["verified"] is True

    restarted = PasskeyGate(wallet_root)
    with pytest.raises(PasskeyGateError, match="already used"):
        restarted.consume_gate_token(
            token,
            action_key="hardware_gate_check",
            context={},
        )


def test_token_from_revoked_credential_is_rejected(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("IW_REQUIRE_PASSKEY", "required")
    gate = PasskeyGate(tmp_path / "wallet")
    first_key, first_id = enroll_es256(gate, credential_id="credential-one")
    enrollment_approval = authenticate(
        gate,
        first_key,
        first_id,
        action_key="manage_passkeys",
        context={"operation": "enroll_passkey"},
        counter=1,
    )
    second_key, second_id = enroll_es256(
        gate,
        credential_id="credential-two",
        hardware_gate_token=enrollment_approval["hardware_gate_token"],
    )
    stale = authenticate(
        gate,
        second_key,
        second_id,
        action_key="hardware_gate_check",
        context={},
        counter=1,
    )
    revocation = authenticate(
        gate,
        first_key,
        first_id,
        action_key="manage_passkeys",
        context={"credential_id": second_id},
        counter=2,
    )
    gate.revoke_credential(second_id, revocation["hardware_gate_token"])

    with pytest.raises(PasskeyGateError, match="no longer active"):
        gate.consume_gate_token(
            stale["hardware_gate_token"],
            action_key="hardware_gate_check",
            context={},
        )


def test_passkey_signature_and_counter_fail_closed(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("IW_REQUIRE_PASSKEY", "auto")
    gate = PasskeyGate(tmp_path / "wallet")
    private_key, credential_id = enroll_es256(gate)
    other_key = ec.generate_private_key(ec.SECP256R1())
    options = gate.authentication_options(
        origin="http://localhost:7432", action_key="hardware_gate_check", context={}
    )
    raw_client, encoded_client = client_data("webauthn.get", options["publicKey"]["challenge"])
    raw_auth = auth_data(1)
    bad_signature = other_key.sign(raw_auth + hashlib.sha256(raw_client).digest(), ec.ECDSA(hashes.SHA256()))
    with pytest.raises(PasskeyGateError, match="signature"):
        gate.authenticate(
            {
                "challenge_id": options["challenge_id"],
                "credential_id": credential_id,
                "client_data_json": encoded_client,
                "authenticator_data": b64e(raw_auth),
                "signature": b64e(bad_signature),
            }
        )

    authenticate(gate, private_key, credential_id, action_key="hardware_gate_check", context={}, counter=2)
    with pytest.raises(PasskeyGateError, match="counter"):
        authenticate(gate, private_key, credential_id, action_key="hardware_gate_check", context={}, counter=1)


def test_passkey_revocation_preserves_history_and_requires_another_active_key(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("IW_REQUIRE_PASSKEY", "required")
    gate = PasskeyGate(tmp_path / "wallet")
    first_key, first_id = enroll_es256(gate, credential_id="credential-one")
    enrollment_approval = authenticate(
        gate,
        first_key,
        first_id,
        action_key="manage_passkeys",
        context={"operation": "enroll_passkey"},
    )
    _, second_id = enroll_es256(
        gate,
        credential_id="credential-two",
        hardware_gate_token=enrollment_approval["hardware_gate_token"],
    )
    assertion = authenticate(
        gate,
        first_key,
        first_id,
        action_key="manage_passkeys",
        context={"credential_id": second_id},
        counter=2,
    )
    result = gate.revoke_credential(second_id, assertion["hardware_gate_token"])
    assert result["revoked"] is True
    assert result["remaining"] == 1
    assert result["revoked_history_count"] == 1
    status = gate.status()
    assert status["enrolled"] is True
    assert status["credential_count"] == 1
    assert status["revoked_credential_count"] == 1
    assert status["revoked_credentials"][0]["credential_id"] == second_id


def test_final_active_passkey_cannot_be_revoked(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("IW_REQUIRE_PASSKEY", "required")
    gate = PasskeyGate(tmp_path / "wallet")
    private_key, credential_id = enroll_es256(gate)
    assertion = authenticate(
        gate,
        private_key,
        credential_id,
        action_key="manage_passkeys",
        context={"credential_id": credential_id},
    )
    with pytest.raises(PasskeyGateError, match="final active passkey"):
        gate.revoke_credential(credential_id, assertion["hardware_gate_token"])
    assert gate.status()["credential_count"] == 1
    assert gate.status()["revoked_credential_count"] == 0


def test_additional_passkey_enrollment_requires_an_active_passkey(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("IW_REQUIRE_PASSKEY", "required")
    gate = PasskeyGate(tmp_path / "wallet")
    first_key, first_id = enroll_es256(gate)

    with pytest.raises(PasskeyGateError, match="requires a verified passkey"):
        gate.registration_options(
            origin="http://localhost:7432",
            label="Unauthorized second key",
            attachment="platform",
        )

    approval = authenticate(
        gate,
        first_key,
        first_id,
        action_key="manage_passkeys",
        context={"operation": "enroll_passkey"},
    )
    _, second_id = enroll_es256(
        gate,
        credential_id="credential-two",
        hardware_gate_token=approval["hardware_gate_token"],
    )
    assert gate.status()["credential_count"] == 2
    assert second_id != first_id


def test_parallel_first_run_challenge_cannot_add_an_unauthorized_second_key(
    tmp_path: Path,
    monkeypatch,
):
    monkeypatch.setenv("IW_REQUIRE_PASSKEY", "required")
    gate = PasskeyGate(tmp_path / "wallet")
    first_options = gate.registration_options(
        origin="http://localhost:7432", label="First", attachment="platform"
    )
    stale_options = gate.registration_options(
        origin="http://localhost:7432", label="Stale", attachment="platform"
    )

    def complete(options, credential_id):
        private_key = ec.generate_private_key(ec.SECP256R1())
        public_der = private_key.public_key().public_bytes(
            serialization.Encoding.DER,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        _, encoded_client = client_data(
            "webauthn.create", options["publicKey"]["challenge"]
        )
        return gate.register(
            {
                "challenge_id": options["challenge_id"],
                "credential_id": b64e(credential_id.encode()),
                "client_data_json": encoded_client,
                "authenticator_data": b64e(auth_data(0)),
                "public_key_spki": b64e(public_der),
                "algorithm": -7,
                "transports": ["internal"],
                "attachment": "platform",
                "label": credential_id,
            }
        )

    complete(first_options, "credential-one")
    with pytest.raises(PasskeyGateError, match="requires approval"):
        complete(stale_options, "credential-two")
    assert gate.status()["credential_count"] == 1


def test_protected_operation_requires_enrollment_on_first_run(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("IW_REQUIRE_PASSKEY", "required")
    gate = PasskeyGate(tmp_path / "wallet")
    with pytest.raises(PasskeyGateError, match="enrollment is complete"):
        gate.consume_gate_token(None, action_key="export_working_copy", context={})


def test_passkey_rejects_non_loopback_insecure_origin(tmp_path: Path):
    gate = PasskeyGate(tmp_path / "wallet")
    with pytest.raises(PasskeyGateError, match="origin"):
        gate.registration_options(origin="http://example.test", label="unsafe")


def test_passkey_rejects_noncanonical_base64url_and_unicode_tokens(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with pytest.raises(PasskeyGateError, match="invalid base64url"):
        _b64d("$not-base64url$")

    monkeypatch.setenv("IW_REQUIRE_PASSKEY", "required")
    gate = PasskeyGate(tmp_path / "wallet")
    enroll_es256(gate)
    with pytest.raises(PasskeyGateError, match="malformed"):
        gate.consume_gate_token(
            "é.invalid",
            action_key="hardware_gate_check",
            context={},
        )


def test_passkey_http_status_and_options_are_available(tmp_path: Path, monkeypatch):
    replacement = PasskeyGate(tmp_path / "wallet")
    monkeypatch.setattr(server, "passkey_gate", replacement)
    with TestClient(server.app) as client:
        status = client.get("/api/v21/security/passkeys/status")
        assert status.status_code == 200
        assert status.json()["enrolled"] is False
        options = client.post(
            "/api/v21/security/passkeys/registration/options",
            headers={"origin": "http://localhost:7432"},
            json={"label": "Phone", "attachment": "cross-platform"},
        )
        assert options.status_code == 200
        body = options.json()
        assert body["publicKey"]["rp"]["id"] == "localhost"
        assert body["publicKey"]["authenticatorSelection"]["userVerification"] == "required"
        paths = set(client.get("/openapi.json").json()["paths"])
        assert "/api/v21/security/passkeys/revoke" in paths
        assert "/api/v21/security/passkeys/remove" not in paths
