"""
Iteration Wallet — FastAPI Server
===================================
Serves the UI and exposes the vault API.
WebSocket broadcasts state changes to all connected clients.

Run:  python app.py
API:  http://localhost:7432/api/...
UI:   http://localhost:7432/
"""

import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import List, Optional, Set

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from iteration_wallet.version import WALLET_VERSION
from iteration_wallet.passkey_gate import PasskeyGate, PasskeyGateError

# ─── app ───────────────────────────────────────────────────────────────────

log = logging.getLogger("iw.server")

def _startup_stage_status(report: dict) -> str:
    if report.get("exception") or report.get("errors") or int(report.get("failed", 0)):
        return "failed"
    if int(report.get("ambiguous", 0)):
        return "attention_required"
    if int(report.get("pending", 0)):
        return "incomplete"
    return "complete"


def run_ordered_startup_reconciliation() -> dict:
    """Run every shipped recovery stage in an explicit, inspectable order.

    Each stage is idempotent and reported independently.  A failed stage does
    not silently suppress later recovery attempts, and ambiguous promotion
    state remains frozen by the promotion coordinator rather than being guessed
    through or automatically rolled back.
    """
    stage_calls = [
        ("state_transition_journals", _state_transition_reconciliation),
        ("promotion_journals", promotion21.reconcile_pending),
        ("oubliette_journals", _optional_oubliette_reconciliation),
        ("labcopy_journals", _labcopy_reconciliation),
        ("catalog_outbox", vault21.flush_evidence_outbox),
        ("ceremony", vault21.ceremony_ledger.reconcile_observations),
        # Repair linked request projections before observing request state so
        # the canonical observation reflects the durable approval authority.
        ("request_approval_projections", human_access.reconcile_request_projections),
        ("identity", human_access.reconcile_identity_observations),
        ("roles", human_access.reconcile_role_observations),
        ("requests", human_access.reconcile_request_observations),
        ("approvals", human_access.reconcile_approval_observations),
        ("denials", human_access.reconcile_denial_observations),
        ("incidents", human_access.reconcile_incident_observations),
    ]
    stages: dict[str, dict] = {}
    for name, call in stage_calls:
        try:
            report = dict(call())
        except Exception as exc:
            report = {
                "errors": [{"exception": f"{type(exc).__name__}: {exc}"[:500]}],
                "exception": type(exc).__name__,
            }
        report["status"] = _startup_stage_status(report)
        stages[name] = report

    failed_stages = [name for name, report in stages.items() if report["status"] == "failed"]
    attention_stages = [
        name
        for name, report in stages.items()
        if report["status"] in {"attention_required", "incomplete"}
    ]
    overall_status = "complete"
    if failed_stages or attention_stages:
        overall_status = "attention_required"
    promotion = stages["promotion_journals"]
    return {
        "status": overall_status,
        "order": [name for name, _ in stage_calls],
        "stages": stages,
        "failed_stages": failed_stages,
        "attention_stages": attention_stages,
        # Compatibility summary for existing status consumers.
        "checked": int(promotion.get("checked", 0)),
        "reconciled": int(promotion.get("reconciled", 0)),
        "failed": int(promotion.get("failed", 0)) + len(failed_stages),
        "ambiguous": int(promotion.get("ambiguous", 0)),
        "receipts": list(promotion.get("receipts") or []),
    }


@asynccontextmanager
async def app_lifespan(_: FastAPI):
    global startup_reconciliation21
    if not _canonical_runtime_is_coherent():
        raise RuntimeError("Iteration Wallet canonical v2.1 runtime is misconfigured")
    startup_reconciliation21 = run_ordered_startup_reconciliation()
    yield


app = FastAPI(
    title="Iteration Wallet",
    version=WALLET_VERSION,
    description="Local-first, non-destructive project generation custody for AI-assisted work",
    lifespan=app_lifespan,
)

_configured_origins = {
    item.strip().rstrip("/")
    for item in os.environ.get("IW_WEBAUTHN_ORIGINS", "").split(",")
    if item.strip()
}
_local_browser_origins = sorted(
    _configured_origins or {"http://127.0.0.1:7432", "http://localhost:7432"}
)
app.add_middleware(
    CORSMiddleware,
    # The UI is served by this same local process. Explicit loopback origins
    # support local development without making the custody API a wildcard
    # browser target. The launcher sets the exact custom-port origin.
    allow_origins=_local_browser_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)

vault = None  # retired v2 runtime is preserved only in historical_sources

# HTML is served from the static directory next to this file
_STATIC = Path(__file__).parent / "static"


# ─── WebSocket manager ─────────────────────────────────────────────────────

class ConnectionManager:
    def __init__(self):
        self.active: Set[WebSocket] = set()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self.active.add(ws)

    def disconnect(self, ws: WebSocket) -> None:
        self.active.discard(ws)

    async def broadcast(self, message: dict) -> None:
        dead = set()
        payload = json.dumps(message)
        for ws in self.active:
            try:
                await ws.send_text(payload)
            except Exception:
                dead.add(ws)
        self.active -= dead


manager = ConnectionManager()


async def notify(event_type: str) -> None:
    await manager.broadcast({"type": event_type})


# ─── request models ────────────────────────────────────────────────────────

class CreateProjectRequest(BaseModel):
    name: str
    path: Optional[str] = ""


# ─── routes ────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def serve_ui():
    html_path = _STATIC / "app.html"
    if not html_path.exists():
        raise HTTPException(500, "UI not found — static/app.html is missing.")
    return HTMLResponse(html_path.read_text(encoding="utf-8"))


# The pre-v2.1 HTTP API is intentionally not mounted. Its exact source and UI
# are preserved under historical_sources for audit and migration reference.
# The active server exposes only the canonical /api/v21 surface.

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await manager.connect(ws)
    try:
        while True:
            # Keep-alive ping; real messages go server → client only
            await asyncio.sleep(30)
            await ws.send_text(json.dumps({"type": "ping"}))
    except (WebSocketDisconnect, Exception):
        manager.disconnect(ws)


# ───────────────────────────────────────────────────────────────────────────
# Canonical product-model API: Sections / Raw Sources / Candidates / Prime
# The retired v2 mutation API is not mounted.
# ───────────────────────────────────────────────────────────────────────────

from iteration_wallet.vault_v21 import VaultEngine as VaultEngineV21, VaultError as VaultErrorV21
from iteration_wallet.canonical_evidence import CanonicalEvidenceAdapter, CanonicalEvidenceError
from iteration_wallet.promotion_transaction import PromotionTransactionCoordinator, PromotionTransactionError
from iteration_wallet.state_transition_transaction import (
    StateTransitionTransactionCoordinator,
    StateTransitionTransactionError,
)
from iteration_wallet.oubliette_transaction import (
    OublietteTransactionCoordinator,
    OublietteTransactionError,
)
from iteration_wallet.labcopy_transaction import (
    LabCopyTransactionCoordinator,
    LabCopyTransactionError,
)
from iteration_wallet.notification_manager import (
    NotificationError,
    NotificationManager,
)
from iteration_wallet.identity import IdentityError
from iteration_wallet.gatekeeper import (
    ProtectedActionError,
    evaluate_protected_action,
    list_protected_action_policies,
)

_v21_root = Path(os.environ.get("ITERATION_WALLET_ROOT", str(Path.home() / ".iteration_wallet_v21"))).expanduser().resolve()


def build_canonical_v21_runtime(root: Path, *, oubliette_mode: str | None = None):
    """Construct one coherent Wallet/canonical-evidence runtime.

    This is the only default runtime.  The older Wallet-native recorder remains
    importable solely for read-only legacy tooling and historical tests; it is
    not instantiated in the shipped write path.
    """
    evidence = CanonicalEvidenceAdapter(root, session_id="wallet-v21-runtime")
    vault_engine = VaultEngineV21(
        root, blackbox=evidence, strict_ceremony_tokens=True
    )
    access = NotificationManager(root, blackbox=evidence)
    promotion = PromotionTransactionCoordinator(vault_engine, evidence, access)
    state_transitions = StateTransitionTransactionCoordinator(vault_engine, evidence, access)
    vault_engine.state_transition_coordinator = state_transitions
    labcopy = LabCopyTransactionCoordinator(vault_engine, evidence, access)
    vault_engine.labcopy_coordinator = labcopy
    requested_mode = (oubliette_mode if oubliette_mode is not None else os.environ.get("IW_OUBLIETTE_MODE", "disabled")).strip().lower()
    if requested_mode not in {"disabled", "inspect", "transaction"}:
        requested_mode = "disabled"
    oubliette = None
    if requested_mode != "disabled":
        oubliette = OublietteTransactionCoordinator(
            vault_engine, evidence, access, participation_mode=requested_mode
        )
    # Oubliette is explicitly optional. Wallet + canonical BlackBox remain the
    # required runtime even when no Oubliette coordinator is attached.
    vault_engine.oubliette_coordinator = oubliette
    vault_engine.oubliette_requested_mode = requested_mode
    return evidence, vault_engine, access, promotion


blackbox21, vault21, human_access, promotion21 = build_canonical_v21_runtime(_v21_root)
oubliette21 = getattr(vault21, "oubliette_coordinator", None)
labcopy21 = getattr(vault21, "labcopy_coordinator", None)
state_transitions21 = getattr(vault21, "state_transition_coordinator", None)
canonical_evidence21 = blackbox21
passkey_gate = PasskeyGate(_v21_root)
startup_reconciliation21: dict = {
    "status": "not_run",
    "checked": 0,
    "reconciled": 0,
    "failed": 0,
    "ambiguous": 0,
    "receipts": [],
}




def _active_state_transition_coordinator() -> StateTransitionTransactionCoordinator:
    coordinator = getattr(vault21, "state_transition_coordinator", None)
    if not isinstance(coordinator, StateTransitionTransactionCoordinator):
        raise StateTransitionTransactionError(
            "Retire/Restore transaction runtime is unavailable; no custody transition was attempted"
        )
    return coordinator


def _state_transition_reconciliation() -> dict:
    return _active_state_transition_coordinator().reconcile_pending()


def _canonical_state_transition_runtime_is_coherent() -> bool:
    coordinator = getattr(vault21, "state_transition_coordinator", None)
    return bool(
        _canonical_promotion_runtime_is_coherent()
        and isinstance(coordinator, StateTransitionTransactionCoordinator)
        and coordinator.vault is vault21
        and coordinator.evidence is blackbox21
        and coordinator.human_access is human_access
    )

def _active_oubliette_coordinator() -> OublietteTransactionCoordinator:
    coordinator = getattr(vault21, "oubliette_coordinator", None)
    if not isinstance(coordinator, OublietteTransactionCoordinator):
        raise OublietteTransactionError(
            "Oubliette is disabled or unavailable; Wallet and canonical BlackBox remain active"
        )
    return coordinator


def _optional_oubliette_reconciliation() -> dict:
    coordinator = getattr(vault21, "oubliette_coordinator", None)
    if not isinstance(coordinator, OublietteTransactionCoordinator):
        return {
            "available": False,
            "disabled": True,
            "status": "complete",
            "checked": 0,
            "reconciled": 0,
            "failed": 0,
            "ambiguous": 0,
            "receipts": [],
        }
    return coordinator.reconcile_pending()




def _active_labcopy_coordinator() -> LabCopyTransactionCoordinator:
    coordinator = getattr(vault21, "labcopy_coordinator", None)
    if not isinstance(coordinator, LabCopyTransactionCoordinator):
        raise LabCopyTransactionError(
            "LabCopy is unavailable; no external package or custody transition was attempted"
        )
    return coordinator


def _labcopy_reconciliation() -> dict:
    return _active_labcopy_coordinator().reconcile_pending()


def _canonical_labcopy_runtime_is_coherent() -> bool:
    coordinator = getattr(vault21, "labcopy_coordinator", None)
    return bool(
        _canonical_promotion_runtime_is_coherent()
        and isinstance(coordinator, LabCopyTransactionCoordinator)
        and coordinator.vault is vault21
        and coordinator.evidence is blackbox21
        and coordinator.human_access is human_access
    )


def _labcopy_capability() -> dict:
    coordinator = getattr(vault21, "labcopy_coordinator", None)
    if not isinstance(coordinator, LabCopyTransactionCoordinator):
        return {
            "component": "labcopy",
            "available": False,
            "export": False,
            "result_capture": False,
            "candidate_only_return": False,
            "external_execution": False,
            "automatic_trust": False,
        }
    return coordinator.capability()

def _canonical_promotion_runtime_is_coherent() -> bool:
    return bool(
        isinstance(blackbox21, CanonicalEvidenceAdapter)
        and promotion21 is not None
        and promotion21.vault is vault21
        and promotion21.evidence is blackbox21
        and promotion21.human_access is human_access
    )


def _canonical_oubliette_runtime_is_coherent(*, require_transaction: bool = False) -> bool:
    coordinator = getattr(vault21, "oubliette_coordinator", None)
    coherent = bool(
        _canonical_promotion_runtime_is_coherent()
        and isinstance(coordinator, OublietteTransactionCoordinator)
        and coordinator.vault is vault21
        and coordinator.evidence is blackbox21
        and coordinator.human_access is human_access
    )
    if coherent and require_transaction:
        coherent = coordinator.participation_mode == "transaction"
    return coherent


def _oubliette_capability() -> dict:
    coordinator = getattr(vault21, "oubliette_coordinator", None)
    if not isinstance(coordinator, OublietteTransactionCoordinator):
        return {
            "component": "oubliette",
            "available": False,
            "participation_mode": "disabled",
            "level": "unavailable",
            "static_inspection": False,
            "wallet_owned_crossings": False,
            "execution_supported": False,
            "core_wallet_dependency": False,
            "failure_policy": "wallet_blackbox_core_remains_available",
        }
    return coordinator.capability()


def _canonical_runtime_is_coherent() -> bool:
    # Wallet + canonical BlackBox + exact Retire/Restore transactions are the
    # required core. Optional components do not define core coherence.
    return bool(
        _canonical_promotion_runtime_is_coherent()
        and _canonical_state_transition_runtime_is_coherent()
    )


MIGRATED_PROTECTED_ACTIONS = frozenset({
    "retire_object",
    "restore_retired_object",
    "promote_candidate_to_prime",
    "quarantine",
    "admit_oubliette_derivative_as_candidate",
    "export_working_copy",
    "admit_labcopy_result_as_candidate",
})


def _require_migrated_protected_action(action_key: str) -> None:
    """Fail before authorization, token creation, or custody mutation.

    Only actions that have a complete Wallet-owned transaction coordinator and
    canonical BBX1 evidence protocol may cross this boundary.
    """
    if action_key not in MIGRATED_PROTECTED_ACTIONS:
        raise HTTPException(
            503,
            f"Protected action {action_key!r} is not yet migrated to the canonical "
            "Wallet/BlackBox transaction protocol; no authority token or custody change was attempted.",
        )
    if action_key == "promote_candidate_to_prime":
        coherent = _canonical_promotion_runtime_is_coherent()
    elif action_key in {"retire_object", "restore_retired_object"}:
        coherent = _canonical_state_transition_runtime_is_coherent()
    elif action_key in {"quarantine", "admit_oubliette_derivative_as_candidate"}:
        coherent = _canonical_oubliette_runtime_is_coherent(require_transaction=True)
    else:
        coherent = _canonical_labcopy_runtime_is_coherent()
    if not coherent:
        raise HTTPException(
            503,
            "Canonical Wallet/BlackBox runtime is unavailable or internally inconsistent for "
            f"{action_key!r}; no authority token or custody change was attempted.",
        )


def _unavailable_protected_action(action_key: str) -> None:
    """Terminate an intentionally mounted but unavailable protected route.

    The route remains mounted so clients receive an explicit 503 instead of a
    misleading 404.  There is deliberately no legacy implementation after this
    call.  Migrating an action requires replacing the route with a dedicated
    Wallet-owned transaction coordinator; adding its name to a set is not enough.
    """
    _require_migrated_protected_action(action_key)
    raise HTTPException(
        503,
        f"Protected action {action_key!r} has no canonical route implementation; "
        "no authority token or custody change was attempted.",
    )


class CreateSectionRequest(BaseModel):
    name: str
    description: Optional[str] = ""

class AddMaterialRequest(BaseModel):
    path: str
    notes: Optional[str] = ""

class CeremonyTokenRequest(BaseModel):
    ceremony_token: str
    confirmation: str | None = None
    actor_kind: Optional[str] = "human"
    actor_id: Optional[str] = None
    session_id: Optional[str] = None
    human_ceremony_passed: Optional[bool] = True

class PromotePrimeRequest(BaseModel):
    ceremony_token: str
    reason: Optional[str] = ""
    actor_kind: Optional[str] = "human"
    actor_id: Optional[str] = None
    session_id: Optional[str] = None
    human_ceremony_passed: Optional[bool] = True


class StateTransitionRequest(BaseModel):
    ceremony_token: str
    session_id: str
    reason: Optional[str] = ""


class OublietteInspectionRequest(BaseModel):
    actor_kind: str = Field(default="human", pattern="^(human|local_system|ai|bot)$")
    target_label: Optional[str] = Field(default=None, max_length=256)


class OublietteQuarantineProposalRequest(BaseModel):
    report_id: str = Field(min_length=1, max_length=256)


class OublietteQuarantineRequest(BaseModel):
    report_id: str = Field(min_length=1, max_length=256)
    ceremony_token: str = Field(min_length=1, max_length=4096)
    session_id: str = Field(min_length=1, max_length=256)
    reason: str = Field(default="", max_length=2000)


class OublietteDerivativeInspectionRequest(BaseModel):
    derivative_path: str = Field(min_length=1, max_length=4096)
    allowed_root: str = Field(min_length=1, max_length=4096)
    actor_kind: str = Field(default="human", pattern="^(human|local_system|ai|bot)$")
    target_label: Optional[str] = Field(default=None, max_length=256)


class OublietteDerivativeAdmissionRequest(BaseModel):
    report_id: str = Field(min_length=1, max_length=256)
    capsule_id: Optional[str] = Field(default=None, max_length=256)
    proposal_id: Optional[str] = Field(default=None, max_length=256)
    proposal_hash: Optional[str] = Field(default=None, pattern="^[0-9a-f]{64}$")
    derivative_path: Optional[str] = Field(default=None, max_length=4096)  # compatibility label only; never authority
    ceremony_token: str = Field(min_length=1, max_length=4096)
    session_id: str = Field(min_length=1, max_length=256)
    reason: str = Field(default="", max_length=2000)


class ReviewCandidateRequest(BaseModel):
    verdict: str
    summary: Optional[str] = ""
    strengths: List[str] = Field(default_factory=list)
    risks: List[str] = Field(default_factory=list)

class LabCopyExportProposalRequest(BaseModel):
    output_dir: str = Field(min_length=1, max_length=4096)
    lab_policy: str = Field(min_length=1, max_length=256)
    requested_label: Optional[str] = Field(default=None, max_length=256)
    lab_id: Optional[str] = Field(default=None, max_length=128)


class ExportWorkingCopyRequest(BaseModel):
    proposal_id: str = Field(min_length=1, max_length=256)
    proposal_hash: str = Field(pattern="^[0-9a-f]{64}$")
    ceremony_token: str = Field(min_length=1, max_length=4096)
    session_id: str = Field(min_length=1, max_length=256)
    reason: str = Field(default="", max_length=2000)


class LabCopyResultCaptureRequest(BaseModel):
    result_path: str = Field(min_length=1, max_length=4096)
    allowed_root: str = Field(min_length=1, max_length=4096)
    source_label: Optional[str] = Field(default=None, max_length=256)
    external_assertions: List[dict] = Field(default_factory=list, max_length=64)


class LabCopyResultAdmissionRequest(BaseModel):
    proposal_id: str = Field(min_length=1, max_length=256)
    proposal_hash: str = Field(pattern="^[0-9a-f]{64}$")
    ceremony_token: str = Field(min_length=1, max_length=4096)
    session_id: str = Field(min_length=1, max_length=256)
    reason: str = Field(default="", max_length=2000)


class LabCopyReentryRequest(BaseModel):
    result_path: str = Field(min_length=1, max_length=4096)
    allowed_root: str = Field(min_length=1, max_length=4096)
    manifest_path: Optional[str] = Field(default=None, max_length=4096)
    source_label: Optional[str] = Field(default=None, max_length=256)

def require_human_intent(
    action_key: str,
    actor_kind: Optional[str],
    human_ceremony_passed: Optional[bool],
    session_id: Optional[str] = None,
    require_identity_session: bool = False,
    vault_id: Optional[str] = None,
) -> dict:
    actor_identity = None
    if require_identity_session and not session_id:
        raise HTTPException(403, "Protected custody route requires an identity session.")
    if session_id:
        try:
            actor_identity = human_access.require_identity_session(session_id)
        except IdentityError as e:
            raise HTTPException(403, f"Valid identity session required: {e}")
    try:
        decision = evaluate_protected_action(
            action_key,
            actor_kind or "unknown",
            actor_identity=actor_identity,
            human_ceremony_passed=bool(human_ceremony_passed),
            vault_id=vault_id,
            gate=human_access,
        )
    except ProtectedActionError as e:
        raise HTTPException(500, str(e))
    if not decision.get("allowed"):
        raise HTTPException(403, decision.get("reason", "Protected custody requires human intent."))
    decision["_actor_identity"] = actor_identity
    return decision


class PasskeyRegistrationOptionsRequest(BaseModel):
    label: str = Field(default="Wallet passkey", min_length=1, max_length=120)
    attachment: Optional[str] = Field(default=None, pattern="^(platform|cross-platform)$")
    hardware_gate_token: Optional[str] = Field(default=None, max_length=8192)


class PasskeyRegistrationVerifyRequest(BaseModel):
    challenge_id: str = Field(min_length=1, max_length=128)
    credential_id: str = Field(min_length=1, max_length=4096)
    client_data_json: str = Field(min_length=1, max_length=65536)
    authenticator_data: str = Field(min_length=1, max_length=65536)
    public_key_spki: str = Field(min_length=1, max_length=65536)
    algorithm: int
    transports: List[str] = Field(default_factory=list, max_length=16)
    attachment: Optional[str] = Field(default="unknown", max_length=40)
    label: str = Field(default="Wallet passkey", min_length=1, max_length=120)


class PasskeyAuthenticationOptionsRequest(BaseModel):
    action_key: str = Field(default="hardware_gate_check", min_length=1, max_length=128)
    context: dict[str, str] = Field(default_factory=dict)


class PasskeyAuthenticationVerifyRequest(BaseModel):
    challenge_id: str = Field(min_length=1, max_length=128)
    credential_id: str = Field(min_length=1, max_length=4096)
    client_data_json: str = Field(min_length=1, max_length=65536)
    authenticator_data: str = Field(min_length=1, max_length=65536)
    signature: str = Field(min_length=1, max_length=65536)
    user_handle: Optional[str] = Field(default=None, max_length=4096)


def _request_origin(request: Request) -> str:
    header = request.headers.get("origin")
    if header:
        return header.rstrip("/")
    return str(request.base_url).rstrip("/")



class PasskeyRevocationRequest(BaseModel):
    credential_id: str = Field(min_length=1, max_length=4096)
    hardware_gate_token: str = Field(min_length=1, max_length=8192)

class ExternalResultsRequest(BaseModel):
    summary: str
    passed: Optional[bool] = None
    source: Optional[str] = "external"
    artifacts: List[str] = Field(default_factory=list)

class VaultOpenRequest(BaseModel):
    session_id: str
    hardware_gate_token: Optional[str] = Field(default=None, max_length=8192)

class VaultLockRequest(BaseModel):
    session_id: str

class CeremonyTokenIssueRequest(BaseModel):
    action_key: str
    session_id: str
    project_id: Optional[str] = None
    section_id: Optional[str] = None
    object_id: Optional[str] = None
    proposal_id: Optional[str] = None
    proposal_hash: Optional[str] = None
    ttl_seconds: Optional[int] = 300
    hardware_gate_token: Optional[str] = Field(default=None, max_length=8192)

class CeremonyTokenRevokeRequest(BaseModel):
    ceremony_token: str
    reason: Optional[str] = "manual revocation"

@app.get("/api/v21/security/passkeys/status")
async def passkey_status():
    return passkey_gate.status()


@app.post("/api/v21/security/passkeys/registration/options")
async def passkey_registration_options(req: PasskeyRegistrationOptionsRequest, request: Request):
    try:
        return passkey_gate.registration_options(
            origin=_request_origin(request),
            label=req.label,
            attachment=req.attachment,
            hardware_gate_token=req.hardware_gate_token,
        )
    except PasskeyGateError as e:
        raise HTTPException(403, str(e))


@app.post("/api/v21/security/passkeys/registration/verify", status_code=201)
async def passkey_registration_verify(req: PasskeyRegistrationVerifyRequest):
    try:
        result = passkey_gate.register(req.model_dump())
        await notify("passkey_enrolled")
        return result
    except PasskeyGateError as e:
        raise HTTPException(400, str(e))


@app.post("/api/v21/security/passkeys/authentication/options")
async def passkey_authentication_options(req: PasskeyAuthenticationOptionsRequest, request: Request):
    try:
        return passkey_gate.authentication_options(
            origin=_request_origin(request), action_key=req.action_key, context=req.context
        )
    except PasskeyGateError as e:
        raise HTTPException(400, str(e))


@app.post("/api/v21/security/passkeys/authentication/verify")
async def passkey_authentication_verify(req: PasskeyAuthenticationVerifyRequest):
    try:
        return passkey_gate.authenticate(req.model_dump())
    except PasskeyGateError as e:
        raise HTTPException(403, str(e))



@app.post("/api/v21/security/passkeys/revoke")
async def passkey_revoke(req: PasskeyRevocationRequest):
    try:
        result = passkey_gate.revoke_credential(req.credential_id, req.hardware_gate_token)
        await notify("passkey_revoked")
        return result
    except PasskeyGateError as e:
        raise HTTPException(403, str(e))

@app.get("/api/v21/state")
async def v21_state():
    return vault21.get_state()


@app.get("/api/v21/capabilities")
async def v240_capabilities():
    return {
        "wallet_blackbox_core": {
            "available": _canonical_promotion_runtime_is_coherent(),
            "required": True,
        },
        "oubliette": _oubliette_capability(),
        "labcopy": _labcopy_capability(),
        "state_transitions": {
            "available": _canonical_state_transition_runtime_is_coherent(),
            "retire": _canonical_state_transition_runtime_is_coherent(),
            "restore": _canonical_state_transition_runtime_is_coherent(),
            "protected_content_preserved": True,
        },
        "passkey_gate": passkey_gate.status(),
    }

@app.get("/api/v21/custody/verify")
async def v219_verify_custody_integrity():
    try:
        return vault21.verify_custody_integrity()
    except VaultErrorV21 as e:
        raise HTTPException(400, str(e))

@app.get("/api/v21/blackbox/chain")
async def v219_blackbox_chain_status():
    return blackbox21.verify_chain()

@app.get("/api/v21/private-alpha/status")
async def v223_private_alpha_status():
    """Private-alpha readiness snapshot.

    This endpoint is intentionally a status surface, not an unlock surface. It
    summarizes whether the current local package can prove the core private
    alpha custody chain: strict ceremony tokens, protected action registry,
    BlackBox chain integrity, custody integrity, and Human Intent Receipts.
    """
    chain = blackbox21.verify_chain()
    custody = vault21.verify_custody_integrity()
    receipts = blackbox21.list_human_intent_receipts(limit=1000)
    receipt_report = blackbox21.build_human_intent_receipt_report(limit=1000)
    protected_actions = list_protected_action_policies()
    return {
        "status_type": "private_alpha_status",
        "version": WALLET_VERSION,
        "runtime_mode": "canonical_wallet_blackbox_core" if _canonical_runtime_is_coherent() else "misconfigured_or_legacy",
        "oubliette_capability": _oubliette_capability(),
        "labcopy_capability": _labcopy_capability(),
        "passkey_gate": passkey_gate.status(),
        "startup_reconciliation": startup_reconciliation21,
        "migrated_protected_actions": sorted(MIGRATED_PROTECTED_ACTIONS),
        "unmigrated_protected_actions": [],
        "strict_ceremony_tokens": bool(getattr(vault21, "strict_ceremony_tokens", False)),
        "vault_open": bool(vault21.get_state().get("is_vault_open")),
        "blackbox_chain_ok": bool(chain.get("ok")),
        "custody_integrity_ok": bool(custody.get("ok")),
        "receipt_count": len(receipts),
        "receipt_report_chain_ok": bool(receipt_report.get("chain", {}).get("ok")),
        "protected_action_count": len(protected_actions),
        "protected_actions": protected_actions,
        # The broad product remains incomplete, but promotion and the bounded
        # Oubliette intake/derivative crossing now use canonical transactions.
        "ready_for_private_alpha_flow": False,
        "ready_for_bounded_promotion_alpha": bool(
            getattr(vault21, "strict_ceremony_tokens", False)
            and chain.get("ok")
            and custody.get("ok")
            and receipt_report.get("chain", {}).get("ok")
            and len(protected_actions) >= 8
            and _canonical_runtime_is_coherent()
            and startup_reconciliation21.get("status") in {"not_run", "complete"}
        ),
        "ready_for_full_private_alpha_flow": False,
    }

@app.get("/api/v21/protected-actions")
async def v21_protected_actions():
    """Describe policy intent separately from currently reachable behavior."""
    policies = list_protected_action_policies()
    for action_key, policy in policies.items():
        if action_key == "promote_candidate_to_prime" and _canonical_promotion_runtime_is_coherent():
            runtime_status = "canonical_transaction_available"
        elif action_key in {"retire_object", "restore_retired_object"} and _canonical_state_transition_runtime_is_coherent():
            runtime_status = "canonical_transaction_available"
        elif action_key in {"quarantine", "admit_oubliette_derivative_as_candidate"} and _canonical_oubliette_runtime_is_coherent(require_transaction=True):
            runtime_status = "canonical_transaction_available"
        elif action_key in {"export_working_copy", "admit_labcopy_result_as_candidate"} and _canonical_labcopy_runtime_is_coherent():
            runtime_status = "canonical_transaction_available"
        elif action_key in MIGRATED_PROTECTED_ACTIONS:
            runtime_status = "unavailable_optional_component_not_transaction_ready"
        elif action_key == "open_vault":
            runtime_status = "session_control_available_no_general_authority_token"
        else:
            runtime_status = "unavailable_not_migrated"
        policy["runtime_status"] = runtime_status
        policy["ceremony_token_issuance_available"] = runtime_status == "canonical_transaction_available"
    return {
        "protected_actions": policies,
        "canonical_protected_actions": sorted(MIGRATED_PROTECTED_ACTIONS),
        "warning": (
            "A registered policy is not proof of an implemented custody transaction. "
            "Only actions marked canonical_transaction_available are reachable."
        ),
    }

@app.post("/api/v21/projects", status_code=201)
async def v21_create_project(req: CreateProjectRequest):
    try:
        project = vault21.create_project(req.name, req.path or "")
        await notify("v21_state_updated")
        return project
    except VaultErrorV21 as e:
        raise HTTPException(400, str(e))

@app.post("/api/v21/projects/{project_id}/sections", status_code=201)
async def v21_create_section(project_id: str, req: CreateSectionRequest):
    try:
        section = vault21.create_section(project_id, req.name, req.description or "")
        await notify("v21_state_updated")
        return section
    except VaultErrorV21 as e:
        raise HTTPException(400, str(e))

@app.get("/api/v21/projects/{project_id}/sections/{section_id}")
async def v21_section_view(project_id: str, section_id: str):
    try:
        return vault21.get_section_view(project_id, section_id)
    except VaultErrorV21 as e:
        raise HTTPException(400, str(e))


@app.get("/api/v21/projects/{project_id}/sections/{section_id}/closed-catalog")
async def v220_closed_catalog_view(project_id: str, section_id: str):
    try:
        return vault21.get_closed_catalog_view(project_id, section_id)
    except VaultErrorV21 as e:
        raise HTTPException(400, str(e))

@app.get("/api/v21/projects/{project_id}/sections/{section_id}/blackbox/closed-summary")
async def v220_section_blackbox_closed_summary(project_id: str, section_id: str):
    return blackbox21.build_closed_evidence_summary(project_id=project_id, section_id=section_id, limit=10)

@app.post("/api/v21/projects/{project_id}/sections/{section_id}/raw-sources", status_code=201)
async def v21_add_raw_source(project_id: str, section_id: str, req: AddMaterialRequest):
    try:
        record = vault21.add_raw_source(project_id, section_id, req.path, req.notes or "")
        await notify("v21_state_updated")
        return record
    except VaultErrorV21 as e:
        raise HTTPException(400, str(e))

@app.post("/api/v21/projects/{project_id}/sections/{section_id}/candidates", status_code=201)
async def v21_add_candidate(project_id: str, section_id: str, req: AddMaterialRequest):
    try:
        record = vault21.add_candidate(project_id, section_id, req.path, req.notes or "")
        await notify("v21_state_updated")
        return record
    except VaultErrorV21 as e:
        raise HTTPException(400, str(e))

@app.post("/api/v21/vault/open")
async def v21_open_vault(req: VaultOpenRequest):
    # Opening the vault is the security-relevant direction: it re-enables
    # issuance of protected-action ceremony tokens. It must not be reachable
    # by a bare, unauthenticated POST -- confirmed exploitable prior to this
    # check (an unauthenticated request could silently reopen a locked vault).
    try:
        identity = human_access.require_identity_session(req.session_id)
        if not identity.has_human_intent_proof():
            raise HTTPException(403, "Opening the Vault requires a human identity session with intent proof.")
        passkey_gate.consume_gate_token(
            req.hardware_gate_token, action_key="open_vault", context={}
        )
    except IdentityError as e:
        raise HTTPException(403, f"Valid identity session required: {e}")
    except PasskeyGateError as e:
        raise HTTPException(403, str(e))
    result = vault21.open_vault()
    await notify("v21_vault_opened")
    return result

@app.post("/api/v21/vault/lock")
async def v21_lock_vault(req: VaultLockRequest):
    # Locking is the safe direction (it can only reduce authority), so it
    # only requires a valid identity session, not the passkey gate -- an
    # emergency lock should not itself be gated behind hardware you may not
    # have to hand.
    try:
        human_access.require_identity_session(req.session_id)
    except IdentityError as e:
        raise HTTPException(403, f"Valid identity session required: {e}")
    result = vault21.lock_vault()
    await notify("v21_vault_locked")
    return result

@app.post("/api/v21/ceremony/tokens", status_code=201)
async def v222_issue_ceremony_token(req: CeremonyTokenIssueRequest):
    _require_migrated_protected_action(req.action_key)
    proposal_scoped_actions = {
        "quarantine",
        "admit_oubliette_derivative_as_candidate",
        "export_working_copy",
        "admit_labcopy_result_as_candidate",
    }
    if req.action_key in proposal_scoped_actions and (not req.proposal_id or not req.proposal_hash):
        raise HTTPException(
            400,
            f"Protected action {req.action_key!r} requires an exact proposal_id and proposal_hash.",
        )
    hardware_context = {
        key: value
        for key, value in {
            "project_id": req.project_id,
            "section_id": req.section_id,
            "object_id": req.object_id,
            "proposal_id": req.proposal_id,
            "proposal_hash": req.proposal_hash,
        }.items()
        if value
    }
    try:
        hardware_gate = passkey_gate.consume_gate_token(
            req.hardware_gate_token, action_key=req.action_key, context=hardware_context
        )
        identity = human_access.require_identity_session(req.session_id)
        if not identity.has_human_intent_proof():
            raise HTTPException(403, "Ceremony token requires a human identity session with intent proof.")
        result = vault21.issue_ceremony_token(
            req.action_key,
            req.session_id,
            actor_id=identity.actor_id,
            project_id=req.project_id,
            section_id=req.section_id,
            object_id=req.object_id,
            proposal_id=req.proposal_id,
            proposal_hash=req.proposal_hash,
            ttl_seconds=req.ttl_seconds or 300,
        )
        result["hardware_gate"] = hardware_gate
        await notify("v222_ceremony_token_issued")
        return result
    except PasskeyGateError as e:
        raise HTTPException(403, str(e))
    except VaultErrorV21 as e:
        raise HTTPException(400, str(e))
    except IdentityError as e:
        raise HTTPException(403, f"Valid identity session required: {e}")

@app.get("/api/v21/ceremony/tokens")
async def v222_list_ceremony_tokens():
    return {"tokens": vault21.list_ceremony_tokens()}

@app.post("/api/v21/ceremony/tokens/revoke")
async def v222_revoke_ceremony_token(req: CeremonyTokenRevokeRequest):
    try:
        return vault21.revoke_ceremony_token(req.ceremony_token, reason=req.reason or "manual revocation")
    except VaultErrorV21 as e:
        raise HTTPException(400, str(e))

@app.post("/api/v21/projects/{project_id}/sections/{section_id}/files/{file_id}/oubliette/inspect", include_in_schema=False)
async def v240_inspect_oubliette_object(
    project_id: str,
    section_id: str,
    file_id: str,
    req: OublietteInspectionRequest,
):
    try:
        result = _active_oubliette_coordinator().inspect_object(
            project_id=project_id,
            section_id=section_id,
            object_id=file_id,
            actor_kind=req.actor_kind,
            target_label=req.target_label,
        )
        await notify("v240_oubliette_inspection_completed")
        return result
    except (VaultErrorV21, OublietteTransactionError, CanonicalEvidenceError) as exc:
        raise HTTPException(400, str(exc))


@app.post("/api/v21/projects/{project_id}/sections/{section_id}/files/{file_id}/oubliette/quarantine-proposal", include_in_schema=False)
async def v240_oubliette_quarantine_proposal(
    project_id: str,
    section_id: str,
    file_id: str,
    req: OublietteQuarantineProposalRequest,
):
    try:
        return _active_oubliette_coordinator().quarantine_proposal(
            project_id=project_id,
            section_id=section_id,
            object_id=file_id,
            report_id=req.report_id,
        )
    except (VaultErrorV21, OublietteTransactionError, CanonicalEvidenceError) as exc:
        raise HTTPException(400, str(exc))


@app.post("/api/v21/projects/{project_id}/sections/{section_id}/files/{file_id}/quarantine")
async def v21_quarantine_file(
    project_id: str,
    section_id: str,
    file_id: str,
    req: OublietteQuarantineRequest,
):
    try:
        _require_migrated_protected_action("quarantine")
        completed = _active_oubliette_coordinator().quarantine(
            project_id=project_id,
            section_id=section_id,
            object_id=file_id,
            report_id=req.report_id,
            ceremony_token=req.ceremony_token,
            session_id=req.session_id,
            reason=req.reason,
        )
        await notify("v240_oubliette_quarantine_completed")
        return {
            "result": completed["result"],
            "human_intent_receipt": completed["receipt"],
            "verification": completed["verification"],
        }
    except (VaultErrorV21, OublietteTransactionError, CanonicalEvidenceError) as exc:
        raise HTTPException(400, str(exc))


@app.post("/api/v21/projects/{project_id}/sections/{section_id}/files/{file_id}/oubliette/derivatives/inspect", include_in_schema=False)
async def v240_inspect_oubliette_derivative(
    project_id: str,
    section_id: str,
    file_id: str,
    req: OublietteDerivativeInspectionRequest,
):
    try:
        result = _active_oubliette_coordinator().inspect_derivative(
            project_id=project_id,
            section_id=section_id,
            quarantined_object_id=file_id,
            derivative_path=req.derivative_path,
            allowed_root=req.allowed_root,
            actor_kind=req.actor_kind,
            target_label=req.target_label,
        )
        await notify("v240_oubliette_derivative_inspection_completed")
        return result
    except (VaultErrorV21, OublietteTransactionError, CanonicalEvidenceError) as exc:
        raise HTTPException(400, str(exc))


@app.post("/api/v21/projects/{project_id}/sections/{section_id}/files/{file_id}/oubliette/derivatives/admit", include_in_schema=False)
async def v240_admit_oubliette_derivative(
    project_id: str,
    section_id: str,
    file_id: str,
    req: OublietteDerivativeAdmissionRequest,
):
    try:
        _require_migrated_protected_action("admit_oubliette_derivative_as_candidate")
        completed = _active_oubliette_coordinator().admit_derivative_as_candidate(
            project_id=project_id,
            section_id=section_id,
            parent_object_id=file_id,
            derivative_path=req.derivative_path,
            capsule_id=req.capsule_id,
            proposal_id=req.proposal_id,
            proposal_hash=req.proposal_hash,
            report_id=req.report_id,
            ceremony_token=req.ceremony_token,
            session_id=req.session_id,
            reason=req.reason,
        )
        await notify("v240_oubliette_derivative_admitted")
        return {
            "result": completed["result"],
            "human_intent_receipt": completed["receipt"],
            "verification": completed["verification"],
        }
    except (VaultErrorV21, OublietteTransactionError, CanonicalEvidenceError) as exc:
        raise HTTPException(400, str(exc))

@app.post("/api/v21/projects/{project_id}/sections/{section_id}/objects/{object_id}/retire")
async def v21_retire_object(
    project_id: str, section_id: str, object_id: str, req: StateTransitionRequest
):
    try:
        _require_migrated_protected_action("retire_object")
        if not req.session_id:
            raise HTTPException(403, "Protected custody route requires an identity session.")
        completed = _active_state_transition_coordinator().retire(
            project_id=project_id,
            section_id=section_id,
            object_id=object_id,
            ceremony_token=req.ceremony_token,
            session_id=req.session_id,
            reason=req.reason or "",
        )
        await notify("v21_state_updated")
        return {
            "result": completed["result"],
            "human_intent_receipt": completed["receipt"],
            "verification": completed["verification"],
        }
    except (
        VaultErrorV21, StateTransitionTransactionError, CanonicalEvidenceError
    ) as exc:
        raise HTTPException(400, str(exc))


@app.post("/api/v21/projects/{project_id}/sections/{section_id}/objects/{object_id}/restore")
async def v21_restore_object(
    project_id: str, section_id: str, object_id: str, req: StateTransitionRequest
):
    try:
        _require_migrated_protected_action("restore_retired_object")
        if not req.session_id:
            raise HTTPException(403, "Protected custody route requires an identity session.")
        completed = _active_state_transition_coordinator().restore(
            project_id=project_id,
            section_id=section_id,
            object_id=object_id,
            ceremony_token=req.ceremony_token,
            session_id=req.session_id,
            reason=req.reason or "",
        )
        await notify("v21_state_updated")
        return {
            "result": completed["result"],
            "human_intent_receipt": completed["receipt"],
            "verification": completed["verification"],
        }
    except (
        VaultErrorV21, StateTransitionTransactionError, CanonicalEvidenceError
    ) as exc:
        raise HTTPException(400, str(exc))


@app.post("/api/v21/projects/{project_id}/sections/{section_id}/candidates/{candidate_id}/review")
async def v21_review_candidate(project_id: str, section_id: str, candidate_id: str, req: ReviewCandidateRequest):
    try:
        review = vault21.review_candidate(project_id, section_id, candidate_id, req.verdict, req.summary or "", req.strengths or [], req.risks or [])
        await notify("v21_state_updated")
        return review
    except VaultErrorV21 as e:
        raise HTTPException(400, str(e))

@app.post("/api/v21/projects/{project_id}/sections/{section_id}/candidates/{candidate_id}/external-results")
async def v21_attach_external_results(project_id: str, section_id: str, candidate_id: str, req: ExternalResultsRequest):
    try:
        result = vault21.attach_external_test_results(project_id, section_id, candidate_id, req.summary, req.passed, req.source or "external", req.artifacts or [])
        await notify("v21_state_updated")
        return result
    except VaultErrorV21 as e:
        raise HTTPException(400, str(e))

@app.post("/api/v21/projects/{project_id}/sections/{section_id}/candidates/{candidate_id}/promote")
async def v21_promote_candidate(project_id: str, section_id: str, candidate_id: str, req: PromotePrimeRequest):
    try:
        if not _canonical_promotion_runtime_is_coherent():
            raise HTTPException(
                503,
                "Canonical promotion runtime is unavailable or internally inconsistent; "
                "no custody change was attempted.",
            )
        if not req.session_id:
            raise HTTPException(403, "Protected custody route requires an identity session.")
        completed = promotion21.promote_to_prime(
            project_id=project_id,
            section_id=section_id,
            candidate_id=candidate_id,
            ceremony_token=req.ceremony_token,
            session_id=req.session_id,
            reason=req.reason or "",
        )
        await notify("v21_state_updated")
        return {
            "result": completed["result"],
            "human_intent_receipt": completed["receipt"],
            "verification": completed["verification"],
        }
    except (VaultErrorV21, PromotionTransactionError, CanonicalEvidenceError) as e:
        raise HTTPException(400, str(e))

@app.post("/api/v21/projects/{project_id}/sections/{section_id}/files/{file_id}/labcopy/proposal")
async def v250_labcopy_export_proposal(
    project_id: str, section_id: str, file_id: str, req: LabCopyExportProposalRequest
):
    try:
        _require_migrated_protected_action("export_working_copy")
        return _active_labcopy_coordinator().export_proposal(
            project_id=project_id,
            section_id=section_id,
            object_id=file_id,
            output_root=req.output_dir,
            lab_policy=req.lab_policy,
            requested_label=req.requested_label,
            lab_id=req.lab_id,
        )
    except (VaultErrorV21, LabCopyTransactionError, CanonicalEvidenceError) as exc:
        raise HTTPException(400, str(exc))


@app.post("/api/v21/projects/{project_id}/sections/{section_id}/files/{file_id}/export-working-copy")
async def v250_export_working_copy(
    project_id: str, section_id: str, file_id: str, req: ExportWorkingCopyRequest
):
    try:
        _require_migrated_protected_action("export_working_copy")
        completed = _active_labcopy_coordinator().export(
            project_id=project_id,
            section_id=section_id,
            object_id=file_id,
            proposal_id=req.proposal_id,
            proposal_hash=req.proposal_hash,
            ceremony_token=req.ceremony_token,
            session_id=req.session_id,
            reason=req.reason,
        )
        await notify("v250_labcopy_exported")
        return {
            "result": completed["result"],
            "human_intent_receipt": completed["receipt"],
            "verification": completed["verification"],
        }
    except (VaultErrorV21, LabCopyTransactionError, CanonicalEvidenceError) as exc:
        raise HTTPException(400, str(exc))


@app.post("/api/v21/projects/{project_id}/sections/{section_id}/labcopy/reenter")
async def v250_classify_labcopy_reentry(
    project_id: str, section_id: str, req: LabCopyReentryRequest
):
    try:
        result = _active_labcopy_coordinator().classify_reentry(
            project_id=project_id,
            section_id=section_id,
            result_path=req.result_path,
            allowed_root=req.allowed_root,
            manifest_path=req.manifest_path,
            source_label=req.source_label,
        )
        await notify("v250_labcopy_reentry_classified")
        return result
    except (VaultErrorV21, LabCopyTransactionError, CanonicalEvidenceError) as exc:
        raise HTTPException(400, str(exc))


@app.post("/api/v21/labcopy/{lab_id}/results/capture")
async def v250_capture_labcopy_result(lab_id: str, req: LabCopyResultCaptureRequest):
    try:
        result = _active_labcopy_coordinator().capture_result(
            lab_id=lab_id,
            result_path=req.result_path,
            allowed_root=req.allowed_root,
            source_label=req.source_label,
            external_assertions=req.external_assertions,
        )
        await notify("v250_labcopy_result_captured")
        return result
    except (VaultErrorV21, LabCopyTransactionError, CanonicalEvidenceError) as exc:
        raise HTTPException(400, str(exc))


@app.post("/api/v21/labcopy/{lab_id}/results/{capsule_id}/admission-proposal")
async def v250_labcopy_result_admission_proposal(lab_id: str, capsule_id: str):
    try:
        _require_migrated_protected_action("admit_labcopy_result_as_candidate")
        return _active_labcopy_coordinator().result_admission_proposal(
            lab_id=lab_id, capsule_id=capsule_id
        )
    except (VaultErrorV21, LabCopyTransactionError, CanonicalEvidenceError) as exc:
        raise HTTPException(400, str(exc))


@app.post("/api/v21/labcopy/{lab_id}/results/{capsule_id}/admit")
async def v250_admit_labcopy_result(
    lab_id: str, capsule_id: str, req: LabCopyResultAdmissionRequest
):
    try:
        _require_migrated_protected_action("admit_labcopy_result_as_candidate")
        completed = _active_labcopy_coordinator().admit_result(
            lab_id=lab_id,
            capsule_id=capsule_id,
            proposal_id=req.proposal_id,
            proposal_hash=req.proposal_hash,
            ceremony_token=req.ceremony_token,
            session_id=req.session_id,
            reason=req.reason,
        )
        await notify("v250_labcopy_result_admitted")
        return {
            "result": completed["result"],
            "human_intent_receipt": completed["receipt"],
            "verification": completed["verification"],
        }
    except (VaultErrorV21, LabCopyTransactionError, CanonicalEvidenceError) as exc:
        raise HTTPException(400, str(exc))

# ───────────────────────────────────────────────────────────────────────────
# v2.1.5 Human Access / BlackBox Request Control API
# Bots can request. Humans approve. BlackBox records. Bots do not fetch custody.
# ───────────────────────────────────────────────────────────────────────────

class ProtectedAccessRequestModel(BaseModel):
    vault_id: str
    object_id: str
    action: str
    requester_id: str
    claimed_purpose: str
    requester_kind: Optional[str] = "unknown"
    recipients: List[str] = Field(default_factory=list)
    head_user_id: Optional[str] = None
    section_id: Optional[str] = None
    tool_family: Optional[str] = None

class IdentitySessionRequest(BaseModel):
    actor_id: str
    actor_kind: str = "unknown"
    device_id: Optional[str] = None
    verified_methods: List[str] = Field(default_factory=list)
    role_claims: dict = Field(default_factory=dict)
    ttl_minutes: Optional[int] = 480

class ApprovalDecisionRequest(BaseModel):
    approved: bool
    decision_by: Optional[str] = None
    decision_session_id: Optional[str] = None
    reason: Optional[str] = None
    hardware_gate_token: Optional[str] = Field(default=None, max_length=8192)

class DirectAccessEvaluationRequest(BaseModel):
    actor_kind: str
    action: str
    protected: Optional[bool] = True
    human_ceremony_passed: Optional[bool] = False
    session_id: Optional[str] = None

@app.post("/api/v21/identity/sessions", status_code=201)
async def v218_issue_identity_session(req: IdentitySessionRequest):
    try:
        identity = human_access.issue_identity_session(
            actor_id=req.actor_id,
            actor_kind=req.actor_kind,
            device_id=req.device_id,
            verified_methods=req.verified_methods or [],
            role_claims=req.role_claims or {},
            ttl_minutes=int(req.ttl_minutes or 480),
        )
        await notify("v218_identity_session_issued")
        return identity.to_dict()
    except Exception as e:
        raise HTTPException(400, str(e))

@app.get("/api/v21/identity/sessions/{session_id}")
async def v218_get_identity_session(session_id: str):
    identity = human_access.get_identity_session(session_id)
    if not identity:
        raise HTTPException(404, "Identity session not found")
    return identity.to_dict()

@app.post("/api/v21/blackbox/access-requests", status_code=201)
async def v215_create_access_request(req: ProtectedAccessRequestModel):
    try:
        request = human_access.create_access_request(
            vault_id=req.vault_id,
            object_id=req.object_id,
            action=req.action,
            requester_id=req.requester_id,
            claimed_purpose=req.claimed_purpose,
            requester_kind=req.requester_kind or "unknown",
            recipients=req.recipients or [],
            head_user_id=req.head_user_id,
            section_id=req.section_id,
            tool_family=req.tool_family,
        )
        await notify("v215_blackbox_request_logged")
        return request.to_dict()
    except Exception as e:
        raise HTTPException(400, str(e))

@app.get("/api/v21/blackbox/access-requests")
async def v215_get_access_requests():
    return {"requests": human_access.get_all_access_requests()}

@app.get("/api/v21/blackbox/access-requests/{request_id}")
async def v215_get_access_request(request_id: str):
    request = human_access.get_access_request(request_id)
    if not request:
        raise HTTPException(404, "Request not found")
    return request.to_dict()

@app.get("/api/v21/blackbox/report")
async def v215_blackbox_request_report():
    return human_access.build_blackbox_request_report()

@app.get("/api/v21/blackbox/receipts")
async def v221_list_human_intent_receipts():
    return {"receipts": blackbox21.list_human_intent_receipts()}

@app.get("/api/v21/blackbox/receipts/report")
async def v221_human_intent_receipt_report():
    return blackbox21.build_human_intent_receipt_report()

@app.get("/api/v21/blackbox/receipts/{receipt_id}")
async def v221_get_human_intent_receipt(receipt_id: str):
    receipt = blackbox21.get_human_intent_receipt(receipt_id)
    if not receipt:
        raise HTTPException(404, "Human Intent Receipt not found")
    verification = blackbox21.verify_human_intent_receipt(receipt_id)
    return {"receipt": receipt, "verification": verification}

@app.get("/api/v21/notifications/{recipient_id}")
async def v215_get_notifications(recipient_id: str):
    return {"notifications": human_access.get_inbox(recipient_id)}

@app.post("/api/v21/approvals/{approval_id}/decision")
async def v215_submit_approval_decision(approval_id: str, req: ApprovalDecisionRequest):
    try:
        passkey_gate.consume_gate_token(
            req.hardware_gate_token,
            action_key="decide_approval",
            context={"approval_id": approval_id},
        )
        approval = human_access.submit_approval_decision(
            approval_id,
            req.approved,
            decision_by=req.decision_by,
            reason=req.reason,
            decision_session_id=req.decision_session_id,
        )
        if not approval:
            raise HTTPException(404, "Approval not found")
        await notify("v215_approval_decided")
        return approval.to_dict()
    except PasskeyGateError as exc:
        raise HTTPException(403, str(exc)) from exc
    except (IdentityError, NotificationError) as exc:
        raise HTTPException(403, str(exc)) from exc

@app.post("/api/v21/access/evaluate")
async def v215_evaluate_direct_access(req: DirectAccessEvaluationRequest):
    try:
        actor_identity = None
        if req.session_id:
            actor_identity = human_access.require_identity_session(req.session_id)
        return human_access.evaluate_direct_access(
            req.actor_kind,
            req.action,
            protected=bool(req.protected),
            human_ceremony_passed=bool(req.human_ceremony_passed),
            actor_identity=actor_identity,
        )
    except Exception as e:
        raise HTTPException(400, str(e))
