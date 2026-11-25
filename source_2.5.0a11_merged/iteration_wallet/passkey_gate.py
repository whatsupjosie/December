"""Local WebAuthn/passkey gate for protected Iteration Wallet ceremonies.

The browser owns biometric collection.  Wallet receives only WebAuthn public
credential material and verifies subsequent signed assertions server-side.
This module is deliberately local-first: credentials, counters, and the token
signing secret live under the Wallet runtime root with private file modes.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import os
import re
import secrets
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlparse
from uuid import uuid4

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, ed25519, padding, rsa

from iteration_wallet.durable_io import atomic_json, strict_json_read


class PasskeyGateError(RuntimeError):
    """A registration, authentication, or gate-token check failed closed."""


def _b64e(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64d(value: str) -> bytes:
    if not isinstance(value, str) or not value:
        raise PasskeyGateError("missing base64url value")
    if re.fullmatch(r"[A-Za-z0-9_-]+", value) is None:
        raise PasskeyGateError("invalid base64url value")
    try:
        return base64.b64decode(
            value + "=" * (-len(value) % 4),
            altchars=b"-_",
            validate=True,
        )
    except (binascii.Error, ValueError) as exc:
        raise PasskeyGateError("invalid base64url value") from exc


def _canonical(value: Mapping[str, Any]) -> bytes:
    return json.dumps(dict(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _now() -> int:
    return int(time.time())


@dataclass(frozen=True)
class ChallengeRecord:
    challenge_id: str
    ceremony: str
    challenge: bytes
    origin: str
    rp_id: str
    expires_at: int
    action_key: str | None = None
    context: dict[str, str] | None = None
    authorized_by_passkey: bool = False


class PasskeyGate:
    """Issue WebAuthn options, verify assertions, and mint one-use gate tokens."""

    STATE_SCHEMA = "iteration-wallet-passkeys/2"
    LEGACY_STATE_SCHEMA = "iteration-wallet-passkeys/1"
    TOKEN_SCHEMA = "iteration-wallet-hardware-gate/1"

    def __init__(self, root: Path):
        self.root = Path(root).expanduser().resolve()
        self.security_dir = self.root / "security"
        self.state_path = self.security_dir / "passkeys.json"
        self.secret_path = self.security_dir / "hardware_gate_secret.json"
        self._lock = threading.RLock()
        self._challenges: dict[str, ChallengeRecord] = {}
        self.security_dir.mkdir(parents=True, exist_ok=True)
        self._state = self._load_state()
        self._used_token_nonces = {
            str(nonce): int(expires_at)
            for nonce, expires_at in (
                self._state.get("used_token_nonces") or {}
            ).items()
        }
        before_prune = dict(self._used_token_nonces)
        self._prune()
        if self._used_token_nonces != before_prune:
            self._state["used_token_nonces"] = dict(self._used_token_nonces)
            self._save_state()
        self._token_secret = self._load_or_create_secret()

    @property
    def rp_id(self) -> str:
        return os.environ.get("IW_WEBAUTHN_RP_ID", "localhost").strip() or "localhost"

    @property
    def allowed_origins(self) -> set[str]:
        configured = os.environ.get("IW_WEBAUTHN_ORIGINS", "")
        origins = {item.strip().rstrip("/") for item in configured.split(",") if item.strip()}
        if not origins:
            origins = {"http://localhost:7432", "http://127.0.0.1:7432"}
        return origins

    @property
    def require_for_protected_actions(self) -> bool:
        raw = os.environ.get("IW_REQUIRE_PASSKEY", "required").strip().lower()
        if raw in {"0", "false", "no", "off"}:
            return False
        return True

    def _default_state(self) -> dict[str, Any]:
        return {
            "schema": self.STATE_SCHEMA,
            "user_handle": _b64e(secrets.token_bytes(32)),
            "display_name": "Wallet Owner",
            "credentials": [],
            "revoked_credentials": [],
            "used_token_nonces": {},
            "updated_at": _now(),
        }

    def _load_state(self) -> dict[str, Any]:
        if not self.state_path.exists():
            state = self._default_state()
            atomic_json(self.state_path, state)
            return state
        value = strict_json_read(self.state_path)
        if not isinstance(value, dict):
            raise PasskeyGateError("passkey state has an unsupported schema")
        schema = value.get("schema")
        if schema == self.LEGACY_STATE_SCHEMA:
            value = dict(value)
            value["schema"] = self.STATE_SCHEMA
            value.setdefault("revoked_credentials", [])
            value.setdefault("migrations", []).append(
                {
                    "schema": "iteration-wallet-passkey-state-migration/1",
                    "from_schema": self.LEGACY_STATE_SCHEMA,
                    "to_schema": self.STATE_SCHEMA,
                    "migrated_at": _now(),
                    "credential_history_preserved": True,
                }
            )
            atomic_json(self.state_path, value)
        elif schema != self.STATE_SCHEMA:
            raise PasskeyGateError("passkey state has an unsupported schema")
        if not isinstance(value.get("credentials"), list):
            raise PasskeyGateError("passkey credential catalog is malformed")
        if not isinstance(value.get("revoked_credentials"), list):
            raise PasskeyGateError("revoked passkey history is malformed")
        value.setdefault("used_token_nonces", {})
        if not isinstance(value.get("used_token_nonces"), dict):
            raise PasskeyGateError("used hardware-gate token ledger is malformed")
        try:
            value["used_token_nonces"] = {
                str(nonce): int(expires_at)
                for nonce, expires_at in value["used_token_nonces"].items()
            }
        except (TypeError, ValueError) as exc:
            raise PasskeyGateError(
                "used hardware-gate token ledger is malformed"
            ) from exc
        return value

    def _save_state(self) -> None:
        self._state["updated_at"] = _now()
        atomic_json(self.state_path, self._state)

    def _load_or_create_secret(self) -> bytes:
        if self.secret_path.exists():
            value = strict_json_read(self.secret_path)
            if not isinstance(value, dict) or value.get("schema") != "iteration-wallet-hardware-secret/1":
                raise PasskeyGateError("hardware gate secret record is malformed")
            secret = _b64d(str(value.get("secret", "")))
            if len(secret) < 32:
                raise PasskeyGateError("hardware gate secret is too short")
            return secret
        secret = secrets.token_bytes(32)
        atomic_json(
            self.secret_path,
            {
                "schema": "iteration-wallet-hardware-secret/1",
                "secret": _b64e(secret),
                "created_at": _now(),
            },
        )
        return secret

    def _validate_origin(self, origin: str) -> str:
        normalized = str(origin or "").rstrip("/")
        parsed = urlparse(normalized)
        if normalized not in self.allowed_origins:
            raise PasskeyGateError("unexpected WebAuthn origin")
        if parsed.scheme not in {"https", "http"}:
            raise PasskeyGateError("WebAuthn origin must use HTTP or HTTPS")
        if parsed.scheme == "http" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise PasskeyGateError("insecure non-loopback WebAuthn origin is forbidden")
        return normalized

    def _new_challenge(
        self,
        ceremony: str,
        *,
        origin: str,
        action_key: str | None = None,
        context: Mapping[str, Any] | None = None,
        authorized_by_passkey: bool = False,
        ttl_seconds: int = 300,
    ) -> ChallengeRecord:
        origin = self._validate_origin(origin)
        now = _now()
        clean_context = {
            str(key): str(value)
            for key, value in (context or {}).items()
            if value is not None and str(value) != ""
        }
        record = ChallengeRecord(
            challenge_id=uuid4().hex,
            ceremony=ceremony,
            challenge=secrets.token_bytes(32),
            origin=origin,
            rp_id=self.rp_id,
            expires_at=now + max(30, min(int(ttl_seconds), 600)),
            action_key=action_key,
            context=clean_context,
            authorized_by_passkey=bool(authorized_by_passkey),
        )
        with self._lock:
            self._prune(now)
            self._challenges[record.challenge_id] = record
        return record

    def _take_challenge(self, challenge_id: str, ceremony: str) -> ChallengeRecord:
        with self._lock:
            record = self._challenges.pop(str(challenge_id), None)
        if record is None:
            raise PasskeyGateError("WebAuthn challenge is unknown or already used")
        if record.ceremony != ceremony:
            raise PasskeyGateError("WebAuthn challenge ceremony mismatch")
        if record.expires_at < _now():
            raise PasskeyGateError("WebAuthn challenge expired")
        return record

    def _prune(self, now: int | None = None) -> None:
        now = _now() if now is None else now
        self._challenges = {key: value for key, value in self._challenges.items() if value.expires_at >= now}
        self._used_token_nonces = {key: exp for key, exp in self._used_token_nonces.items() if exp >= now}

    def status(self) -> dict[str, Any]:
        credentials = list(self._state.get("credentials") or [])
        return {
            "schema": self.STATE_SCHEMA,
            "enrolled": bool(credentials),
            "credential_count": len(credentials),
            "revoked_credential_count": len(self._state.get("revoked_credentials") or []),
            "enrollment_required": self.require_for_protected_actions and not bool(credentials),
            "require_for_protected_actions": self.require_for_protected_actions,
            "rp_id": self.rp_id,
            "allowed_origins": sorted(self.allowed_origins),
            "credentials": [
                {
                    "credential_id": item.get("credential_id"),
                    "label": item.get("label"),
                    "attachment": item.get("attachment"),
                    "transports": item.get("transports") or [],
                    "algorithm": item.get("algorithm"),
                    "created_at": item.get("created_at"),
                    "last_used_at": item.get("last_used_at"),
                }
                for item in credentials
            ],
            "revoked_credentials": [
                {
                    "credential_id": item.get("credential_id"),
                    "label": item.get("label"),
                    "attachment": item.get("attachment"),
                    "created_at": item.get("created_at"),
                    "revoked_at": item.get("revoked_at"),
                    "status": "revoked",
                }
                for item in self._state.get("revoked_credentials") or []
            ],
            "security_boundary": (
                "The authenticator verifies the human and signs a server challenge. "
                "Wallet verifies the signature and grants one protected action; biometric data never enters Wallet."
            ),
        }

    def registration_options(
        self,
        *,
        origin: str,
        label: str,
        attachment: str | None = None,
        hardware_gate_token: str | None = None,
    ) -> dict[str, Any]:
        """Begin enrollment, requiring an existing passkey after bootstrap.

        The first credential is the local first-run bootstrap. Once any active
        credential exists, adding another credential is itself a protected
        passkey-management action. The authorization is carried by the
        single-use in-memory challenge so the verify endpoint cannot be called
        separately to bypass the gate.
        """
        with self._lock:
            has_credentials = bool(self._state.get("credentials") or [])
        authorized_by_passkey = False
        if has_credentials:
            approval = self.consume_gate_token(
                hardware_gate_token,
                action_key="manage_passkeys",
                context={"operation": "enroll_passkey"},
            )
            authorized_by_passkey = bool(
                not approval.get("required") or approval.get("verified")
            )
        record = self._new_challenge(
            "registration",
            origin=origin,
            authorized_by_passkey=authorized_by_passkey,
        )
        attachment = attachment if attachment in {"platform", "cross-platform"} else None
        options: dict[str, Any] = {
            "challenge": _b64e(record.challenge),
            "rp": {"id": record.rp_id, "name": "Iteration Wallet"},
            "user": {
                "id": self._state["user_handle"],
                "name": "wallet-owner",
                "displayName": self._state.get("display_name") or "Wallet Owner",
            },
            "pubKeyCredParams": [
                {"type": "public-key", "alg": -7},
                {"type": "public-key", "alg": -257},
                {"type": "public-key", "alg": -8},
            ],
            "timeout": 300000,
            "attestation": "none",
            "authenticatorSelection": {
                "residentKey": "preferred",
                "requireResidentKey": False,
                "userVerification": "required",
            },
            "excludeCredentials": [
                {
                    "type": "public-key",
                    "id": item["credential_id"],
                    "transports": item.get("transports") or [],
                }
                for item in [
                    *(self._state.get("credentials") or []),
                    *(self._state.get("revoked_credentials") or []),
                ]
            ],
        }
        if attachment:
            options["authenticatorSelection"]["authenticatorAttachment"] = attachment
        return {
            "challenge_id": record.challenge_id,
            "label": (label or "Passkey").strip()[:120],
            "publicKey": options,
        }

    def _verify_client_data(self, encoded: str, record: ChallengeRecord, expected_type: str) -> bytes:
        raw = _b64d(encoded)
        try:
            value = json.loads(raw.decode("utf-8"))
        except Exception as exc:
            raise PasskeyGateError("clientDataJSON is invalid") from exc
        if value.get("type") != expected_type:
            raise PasskeyGateError("WebAuthn client-data type mismatch")
        if _b64d(str(value.get("challenge", ""))) != record.challenge:
            raise PasskeyGateError("WebAuthn challenge mismatch")
        if str(value.get("origin", "")).rstrip("/") != record.origin:
            raise PasskeyGateError("WebAuthn origin mismatch")
        if value.get("crossOrigin") is True:
            raise PasskeyGateError("cross-origin WebAuthn ceremonies are forbidden")
        return raw

    def _verify_authenticator_data(self, encoded: str, record: ChallengeRecord) -> tuple[bytes, int, int]:
        raw = _b64d(encoded)
        if len(raw) < 37:
            raise PasskeyGateError("authenticator data is truncated")
        expected_rp_hash = hashlib.sha256(record.rp_id.encode("utf-8")).digest()
        if not hmac.compare_digest(raw[:32], expected_rp_hash):
            raise PasskeyGateError("authenticator RP ID hash mismatch")
        flags = raw[32]
        if flags & 0x01 == 0:
            raise PasskeyGateError("authenticator did not prove user presence")
        if flags & 0x04 == 0:
            raise PasskeyGateError("authenticator did not prove user verification")
        sign_count = int.from_bytes(raw[33:37], "big")
        return raw, flags, sign_count

    def register(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        record = self._take_challenge(str(payload.get("challenge_id", "")), "registration")
        self._verify_client_data(str(payload.get("client_data_json", "")), record, "webauthn.create")
        _, flags, sign_count = self._verify_authenticator_data(str(payload.get("authenticator_data", "")), record)
        credential_id = str(payload.get("credential_id", ""))
        _b64d(credential_id)
        public_key_der = _b64d(str(payload.get("public_key_spki", "")))
        try:
            public_key = serialization.load_der_public_key(public_key_der)
        except Exception as exc:
            raise PasskeyGateError("credential public key is invalid") from exc
        try:
            algorithm = int(payload.get("algorithm"))
        except (TypeError, ValueError) as exc:
            raise PasskeyGateError("credential algorithm is invalid") from exc
        if algorithm == -7 and not isinstance(public_key, ec.EllipticCurvePublicKey):
            raise PasskeyGateError("credential key does not match ES256")
        if algorithm == -257 and not isinstance(public_key, rsa.RSAPublicKey):
            raise PasskeyGateError("credential key does not match RS256")
        if algorithm == -8 and not isinstance(public_key, ed25519.Ed25519PublicKey):
            raise PasskeyGateError("credential key does not match EdDSA")
        if algorithm not in {-7, -257, -8}:
            raise PasskeyGateError("credential algorithm is not supported")
        transports = [str(item)[:32] for item in payload.get("transports") or []]
        entry = {
            "credential_id": credential_id,
            "label": str(payload.get("label") or "Passkey")[:120],
            "public_key_spki": _b64e(public_key_der),
            "algorithm": algorithm,
            "sign_count": sign_count,
            "flags": flags,
            "transports": transports,
            "attachment": str(payload.get("attachment") or "unknown")[:40],
            "created_at": _now(),
            "last_used_at": None,
        }
        with self._lock:
            credentials = self._state.setdefault("credentials", [])
            if credentials and not record.authorized_by_passkey:
                raise PasskeyGateError(
                    "adding another passkey requires approval from an active passkey"
                )
            if any(item.get("credential_id") == credential_id for item in credentials):
                raise PasskeyGateError("credential is already enrolled")
            if any(
                item.get("credential_id") == credential_id
                for item in self._state.get("revoked_credentials") or []
            ):
                raise PasskeyGateError("a revoked credential identifier cannot be re-enrolled")
            if len(credentials) >= 12:
                raise PasskeyGateError("credential limit reached; revoke an old passkey first")
            credentials.append(entry)
            self._save_state()
        return {"registered": True, "credential": self.status()["credentials"][-1]}

    def authentication_options(
        self,
        *,
        origin: str,
        action_key: str,
        context: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        credentials = self._state.get("credentials") or []
        if not credentials:
            raise PasskeyGateError("no passkey is enrolled")
        record = self._new_challenge(
            "authentication",
            origin=origin,
            action_key=str(action_key or "hardware_gate_check")[:128],
            context=context,
        )
        return {
            "challenge_id": record.challenge_id,
            "action_key": record.action_key,
            "publicKey": {
                "challenge": _b64e(record.challenge),
                "timeout": 300000,
                "rpId": record.rp_id,
                "userVerification": "required",
                "allowCredentials": [
                    {
                        "type": "public-key",
                        "id": item["credential_id"],
                        "transports": item.get("transports") or [],
                    }
                    for item in credentials
                ],
            },
        }

    def _credential(self, credential_id: str) -> dict[str, Any]:
        for item in self._state.get("credentials") or []:
            if item.get("credential_id") == credential_id:
                return item
        raise PasskeyGateError("credential is not enrolled")

    def authenticate(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        record = self._take_challenge(str(payload.get("challenge_id", "")), "authentication")
        client_data = self._verify_client_data(
            str(payload.get("client_data_json", "")), record, "webauthn.get"
        )
        authenticator_data, _, sign_count = self._verify_authenticator_data(
            str(payload.get("authenticator_data", "")), record
        )
        credential_id = str(payload.get("credential_id", ""))
        credential = self._credential(credential_id)
        supplied_user_handle = payload.get("user_handle")
        if supplied_user_handle not in {None, ""} and supplied_user_handle != self._state.get("user_handle"):
            raise PasskeyGateError("WebAuthn user handle does not match this Wallet owner")
        signature = _b64d(str(payload.get("signature", "")))
        signed_data = authenticator_data + hashlib.sha256(client_data).digest()
        public_key = serialization.load_der_public_key(_b64d(credential["public_key_spki"]))
        algorithm = int(credential["algorithm"])
        try:
            if algorithm == -7 and isinstance(public_key, ec.EllipticCurvePublicKey):
                public_key.verify(signature, signed_data, ec.ECDSA(hashes.SHA256()))
            elif algorithm == -257 and isinstance(public_key, rsa.RSAPublicKey):
                public_key.verify(signature, signed_data, padding.PKCS1v15(), hashes.SHA256())
            elif algorithm == -8 and isinstance(public_key, ed25519.Ed25519PublicKey):
                public_key.verify(signature, signed_data)
            else:
                raise PasskeyGateError("stored credential algorithm is unsupported")
        except InvalidSignature as exc:
            raise PasskeyGateError("WebAuthn assertion signature is invalid") from exc
        previous_count = int(credential.get("sign_count") or 0)
        if previous_count and sign_count and sign_count <= previous_count:
            raise PasskeyGateError("authenticator counter did not advance; possible cloned credential")
        credential["sign_count"] = max(previous_count, sign_count)
        credential["last_used_at"] = _now()
        with self._lock:
            self._save_state()
        token = self._mint_token(
            action_key=record.action_key or "hardware_gate_check",
            context=record.context or {},
            credential_id=credential_id,
            ttl_seconds=180,
        )
        return {
            "verified": True,
            "action_key": record.action_key,
            "context": record.context or {},
            "credential_id": credential_id,
            "expires_in": 180,
            "hardware_gate_token": token,
        }


    def revoke_credential(self, credential_id: str, hardware_gate_token: str | None) -> dict[str, Any]:
        """Revoke one enrolled credential while preserving its complete history."""
        credential_id = str(credential_id or "")
        if not credential_id:
            raise PasskeyGateError("credential id is required")
        approval = self.consume_gate_token(
            hardware_gate_token,
            action_key="manage_passkeys",
            context={"credential_id": credential_id},
        )
        with self._lock:
            credentials = list(self._state.get("credentials") or [])
            selected = next(
                (item for item in credentials if item.get("credential_id") == credential_id),
                None,
            )
            if selected is None:
                raise PasskeyGateError("credential is not enrolled")
            if len(credentials) <= 1:
                raise PasskeyGateError(
                    "the final active passkey cannot be revoked until another passkey is enrolled"
                )
            active = [item for item in credentials if item.get("credential_id") != credential_id]
            revoked = dict(selected)
            revoked.update(
                {
                    "status": "revoked",
                    "revoked_at": _now(),
                    "revocation_approval": {
                        "credential_id": approval.get("credential_id"),
                        "action_key": approval.get("action_key"),
                        "context": approval.get("context") or {},
                        "verified": bool(approval.get("verified")),
                    },
                }
            )
            self._state["credentials"] = active
            self._state.setdefault("revoked_credentials", []).append(revoked)
            self._save_state()
        return {
            "revoked": True,
            "credential_id": credential_id,
            "remaining": len(active),
            "revoked_history_count": len(self._state.get("revoked_credentials") or []),
            "approval": approval,
        }

    def _mint_token(
        self,
        *,
        action_key: str,
        context: Mapping[str, Any],
        credential_id: str,
        ttl_seconds: int,
    ) -> str:
        now = _now()
        payload = {
            "schema": self.TOKEN_SCHEMA,
            "action_key": action_key,
            "context": {str(k): str(v) for k, v in context.items()},
            "credential_id": credential_id,
            "iat": now,
            "exp": now + max(30, min(int(ttl_seconds), 300)),
            "nonce": uuid4().hex,
        }
        encoded = _b64e(_canonical(payload))
        signature = _b64e(hmac.new(self._token_secret, encoded.encode("ascii"), hashlib.sha256).digest())
        return f"{encoded}.{signature}"

    def consume_gate_token(
        self,
        token: str | None,
        *,
        action_key: str,
        context: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not self.require_for_protected_actions:
            return {"required": False, "verified": False, "reason": "passkey gate not required"}
        if not (self._state.get("credentials") or []):
            raise PasskeyGateError(
                "protected operation is unavailable until passkey enrollment is complete"
            )
        if not token:
            raise PasskeyGateError("protected action requires a verified passkey or phone approval")
        try:
            encoded, signature = token.split(".", 1)
        except ValueError as exc:
            raise PasskeyGateError("hardware gate token is malformed") from exc
        try:
            encoded_bytes = encoded.encode("ascii")
        except UnicodeEncodeError as exc:
            raise PasskeyGateError("hardware gate token is malformed") from exc
        supplied_signature = _b64d(signature)
        expected = hmac.new(self._token_secret, encoded_bytes, hashlib.sha256).digest()
        if not hmac.compare_digest(expected, supplied_signature):
            raise PasskeyGateError("hardware gate token signature is invalid")
        try:
            payload = json.loads(_b64d(encoded).decode("utf-8"))
        except Exception as exc:
            raise PasskeyGateError("hardware gate token payload is invalid") from exc
        now = _now()
        if payload.get("schema") != self.TOKEN_SCHEMA:
            raise PasskeyGateError("hardware gate token schema mismatch")
        if int(payload.get("exp") or 0) < now:
            raise PasskeyGateError("hardware gate token expired")
        if payload.get("action_key") != action_key:
            raise PasskeyGateError("hardware gate token is scoped to a different action")
        expected_context = {
            str(key): str(value)
            for key, value in (context or {}).items()
            if value is not None and str(value) != ""
        }
        if dict(payload.get("context") or {}) != expected_context:
            raise PasskeyGateError("hardware gate token context does not match the protected action")
        credential_id = str(payload.get("credential_id") or "")
        nonce = str(payload.get("nonce") or "")
        with self._lock:
            if not any(
                item.get("credential_id") == credential_id
                for item in self._state.get("credentials") or []
            ):
                raise PasskeyGateError(
                    "hardware gate token was issued by a credential that is no longer active"
                )
            self._prune(now)
            if nonce in self._used_token_nonces:
                raise PasskeyGateError("hardware gate token was already used")
            self._used_token_nonces[nonce] = int(payload["exp"])
            self._state["used_token_nonces"] = dict(self._used_token_nonces)
            self._save_state()
        return {
            "required": True,
            "verified": True,
            "credential_id": payload.get("credential_id"),
            "action_key": action_key,
            "context": expected_context,
        }
