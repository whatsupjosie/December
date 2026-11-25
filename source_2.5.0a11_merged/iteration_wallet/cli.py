#!/usr/bin/env python3
"""Iteration Wallet canonical command-line client.

The CLI intentionally exposes only the active v2.1 canonical surface.  It does
not provide compatibility aliases for retired mutation routes.
"""

from __future__ import annotations

import argparse
import json
import os
from importlib import metadata
import importlib.util
import sys
from pathlib import Path
from typing import Any

from iteration_wallet.version import WALLET_VERSION, BLACKBOX_VERSION, BLACKBOX_CLIENT_SCHEMA
from iteration_wallet.network_policy import NetworkPolicyError, require_loopback_host


VAULT_API = os.environ.get(
    "ITERATION_WALLET_API", "http://127.0.0.1:7432/api/v21"
).rstrip("/")
TIMEOUT = 10

REQUIRED_BLACKBOX_VERSION = BLACKBOX_VERSION
REQUIRED_BLACKBOX_CLIENT_SCHEMA = BLACKBOX_CLIENT_SCHEMA
REQUIRED_RUNTIME_MODULES = {
    "fastapi": "fastapi>=0.111.0",
    "uvicorn": "uvicorn[standard]>=0.29.0",
    "pydantic": "pydantic>=2.0.0",
    "requests": "requests>=2.31.0",
    "cryptography": "cryptography>=42.0.0",
}



def _normalized_owners(values: list[str] | None) -> list[str]:
    return sorted({str(item).lower().replace("_", "-") for item in (values or [])})


def _runtime_dependency_report() -> dict[str, dict[str, str | bool | None]]:
    results: dict[str, dict[str, str | bool | None]] = {}
    for module_name, requirement in REQUIRED_RUNTIME_MODULES.items():
        entry: dict[str, str | bool | None] = {"ok": False, "requirement": requirement, "version": None, "error": None}
        spec = importlib.util.find_spec(module_name)
        if spec is None:
            entry["error"] = f"missing importable module {module_name!r}"
        else:
            try:
                entry["version"] = metadata.version(module_name)
            except metadata.PackageNotFoundError:
                # Some modules may be importable from an editable/source path.
                entry["version"] = "importable-no-distribution-metadata"
            entry["ok"] = True
        results[module_name] = entry
    return results


def _doctor_report(*, ownership: dict[str, list[str]] | None = None) -> dict[str, Any]:
    """Inspect distribution ownership without requiring a healthy runtime import."""
    import importlib

    owners = ownership if ownership is not None else metadata.packages_distributions()
    blackbox_owners = _normalized_owners(owners.get("blackbox_plugin"))
    adapter_owners = _normalized_owners(owners.get("iteration_wallet_blackbox"))

    versions: dict[str, str | None] = {
        "iteration_wallet": None,
        "blackbox": None,
        "blackbox_client_schema": None,
    }
    errors: dict[str, str] = {}
    try:
        versions["iteration_wallet"] = metadata.version("iteration-wallet")
    except metadata.PackageNotFoundError:
        errors["iteration_wallet_distribution"] = "iteration-wallet distribution is not installed"
    try:
        versions["blackbox"] = metadata.version("bbx1-iteration-wallet-plugin")
    except metadata.PackageNotFoundError:
        errors["blackbox_distribution"] = "bbx1-iteration-wallet-plugin distribution is not installed"

    try:
        blackbox = importlib.import_module("blackbox_plugin")
        versions["blackbox_client_schema"] = str(
            getattr(blackbox, "CLIENT_SCHEMA_VERSION", "missing")
        )
        imported_blackbox_version = str(getattr(blackbox, "__version__", "missing"))
        if versions["blackbox"] is not None and imported_blackbox_version != versions["blackbox"]:
            errors["blackbox_import_version"] = (
                f"imported blackbox_plugin reports {imported_blackbox_version}, "
                f"distribution metadata reports {versions['blackbox']}"
            )
    except Exception as exc:
        errors["blackbox_import"] = f"{type(exc).__name__}: {exc}"

    try:
        importlib.import_module("iteration_wallet_blackbox")
    except Exception as exc:
        errors["wallet_adapter_import"] = f"{type(exc).__name__}: {exc}"

    runtime_dependencies = _runtime_dependency_report()
    runtime_dependency_checks = {
        f"runtime_dependency_{module_name}": bool(entry["ok"])
        for module_name, entry in runtime_dependencies.items()
    }
    for module_name, entry in runtime_dependencies.items():
        if not entry["ok"]:
            errors[f"runtime_dependency_{module_name}"] = str(entry["error"] or f"{module_name} missing")

    checks = {
        "wallet_version": versions["iteration_wallet"] == WALLET_VERSION,
        "blackbox_version": versions["blackbox"] == REQUIRED_BLACKBOX_VERSION,
        "client_schema": versions["blackbox_client_schema"] == REQUIRED_BLACKBOX_CLIENT_SCHEMA,
        "blackbox_importable": "blackbox_import" not in errors,
        "wallet_adapter_importable": "wallet_adapter_import" not in errors,
        "blackbox_single_owner": blackbox_owners == ["bbx1-iteration-wallet-plugin"],
        "wallet_adapter_single_owner": adapter_owners == ["iteration-wallet"],
        "no_shared_package_owner": not bool(set(blackbox_owners) & set(adapter_owners)),
        **runtime_dependency_checks,
    }
    ok = all(checks.values()) and not errors
    return {
        "ok": ok,
        "checks": checks,
        "versions": versions,
        "runtime_dependencies": runtime_dependencies,
        "ownership": {
            "blackbox_plugin": blackbox_owners,
            "iteration_wallet_blackbox": adapter_owners,
        },
        "errors": errors,
        "repair": {
            "reason": (
                "Versions 2.4.0a2/0.5.0a3 shared package ownership. "
                "Sequential upgrades can leave the companion installation incomplete."
            ),
            "safe_method": (
                f"For normal installs, run: python -m pip install iteration_wallet-{WALLET_VERSION}-py3-none-any.whl "
                f"bbx1_iteration_wallet_plugin-{BLACKBOX_VERSION}-py3-none-any.whl. "
                "For legacy overlapping installs, use tools/migrate_alpha_install.py with both wheels. "
                "It first uninstalls the overlapping legacy distributions, then installs and verifies both new wheels."
            ),
        },
        "scope": "installed-distribution ownership and client compatibility; not runtime custody verification",
    }


def cmd_doctor(args: argparse.Namespace) -> None:
    report = _doctor_report()
    if getattr(args, "json", False):
        _print_json(report)
    else:
        print("\nIteration Wallet installation doctor")
        for name, ok in report["checks"].items():
            print(f"  {'OK' if ok else 'FAIL':4}  {name}")
        print(f"  Wallet:   {report['versions']['iteration_wallet']}")
        print(f"  BlackBox: {report['versions']['blackbox']}")
        print(f"  Client:   {report['versions']['blackbox_client_schema']}")
        print("  Runtime dependencies:")
        for module_name, entry in report.get("runtime_dependencies", {}).items():
            print(f"    {'OK' if entry.get('ok') else 'FAIL':4}  {module_name}: {entry.get('version') or entry.get('error')}")
        if report["errors"]:
            print("\n  Detected problems:")
            for name, message in report["errors"].items():
                print(f"    - {name}: {message}")
            print(f"\n  Repair: {report['repair']['safe_method']}")
        print()
    if not report["ok"]:
        raise CLIError("Installation ownership or BlackBox compatibility check failed.")


class CLIError(RuntimeError):
    """Controlled user-facing CLI failure."""



class ExternalIntegrationRequired(CLIError):
    """A legacy integration command belongs outside Wallet custody."""


def cmd_install_hook(_: argparse.Namespace) -> None:
    raise ExternalIntegrationRequired(
        "Iteration Wallet does not install Git hooks. Use a separately reviewed external adapter."
    )


def cmd_uninstall_hook(_: argparse.Namespace) -> None:
    raise ExternalIntegrationRequired(
        "Iteration Wallet does not manage Git-hook retirement. Manage repository hooks outside Wallet custody."
    )


def _extract_error(response: Any) -> str:
    try:
        body = response.json()
    except ValueError:
        text = response.text.strip()
        return text or f"HTTP {response.status_code}"
    if isinstance(body, dict):
        detail = body.get("detail")
        if isinstance(detail, list):
            return "; ".join(str(item.get("msg", item)) for item in detail)
        if detail:
            return str(detail)
    return json.dumps(body, ensure_ascii=False)


def _req(method: str, path: str, data: dict[str, Any] | None = None, *, timeout: int = TIMEOUT) -> Any:
    if not path.startswith("/"):
        raise CLIError("Internal client error: API path must start with '/'.")
    try:
        import requests
    except ModuleNotFoundError as exc:
        raise CLIError(
            "Missing runtime dependency 'requests'. Install Iteration Wallet with declared dependencies: "
            f"python -m pip install iteration_wallet-{WALLET_VERSION}-py3-none-any.whl "
            f"bbx1_iteration_wallet_plugin-{BLACKBOX_VERSION}-py3-none-any.whl"
        ) from exc
    url = VAULT_API + path
    try:
        response = requests.request(method, url, json=data, timeout=timeout)
    except requests.ConnectionError as exc:
        raise CLIError(
            f"Cannot connect to Iteration Wallet at {VAULT_API}. Start it with: iw serve"
        ) from exc
    except requests.Timeout as exc:
        raise CLIError(f"Iteration Wallet timed out while calling {path}.") from exc
    if response.status_code >= 400:
        raise CLIError(_extract_error(response))
    try:
        return response.json()
    except ValueError as exc:
        raise CLIError(f"Wallet returned invalid JSON for {path}.") from exc


def _print_json(value: Any) -> None:
    print(json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True))


def _require_typed(expected: str, provided: str | None, prompt: str) -> None:
    typed = provided if provided is not None else input(prompt).strip()
    if typed != expected:
        raise CLIError(f"Ceremony cancelled: expected exactly {expected!r}.")


def cmd_serve(args: argparse.Namespace) -> None:
    try:
        import uvicorn
    except ModuleNotFoundError as exc:
        raise CLIError(
            "Missing runtime dependency 'uvicorn'. Install Iteration Wallet with declared dependencies: "
            f"python -m pip install iteration_wallet-{WALLET_VERSION}-py3-none-any.whl "
            f"bbx1_iteration_wallet_plugin-{BLACKBOX_VERSION}-py3-none-any.whl"
        ) from exc

    if getattr(args, "root", None):
        os.environ["ITERATION_WALLET_ROOT"] = str(Path(args.root).expanduser().resolve())
    try:
        bind_host, browser_host = require_loopback_host(args.host)
    except NetworkPolicyError as exc:
        raise CLIError(str(exc)) from exc
    url = f"http://{browser_host}:{args.port}"
    os.environ.setdefault("IW_REQUIRE_PASSKEY", "required")
    os.environ["IW_WEBAUTHN_RP_ID"] = "localhost"
    os.environ["IW_WEBAUTHN_ORIGINS"] = url
    print("\n  ⚿  Iteration Wallet — protected local custody")
    print(f"     UI       →  {url}")
    print(f"     API docs →  {url}/docs\n")
    uvicorn.run(
        "iteration_wallet.server:app",
        host=bind_host,
        port=args.port,
        log_level="warning",
    )


def cmd_status(_: argparse.Namespace) -> None:
    state = _req("GET", "/state")
    status = _req("GET", "/private-alpha/status")
    capabilities = _req("GET", "/capabilities")
    projects = state.get("projects", [])
    sections = sum(len(project.get("sections", [])) for project in projects)
    candidates = sum(
        1
        for project in projects
        for section in project.get("sections", [])
        for item in section.get("files", [])
        if item.get("state") == "candidate"
    )
    print("\nIteration Wallet")
    print(f"  Runtime:    {status.get('runtime_mode', 'unknown')}")
    print(f"  Vault:      {'OPEN' if state.get('is_vault_open') else 'LOCKED'}")
    print(f"  Projects:   {len(projects)}")
    print(f"  Sections:   {sections}")
    print(f"  Candidates: {candidates}")
    print(f"  Receipts:   {status.get('receipt_count', 0)}")
    print(f"  Chain:      {'OK' if status.get('blackbox_chain_ok') else 'CHECK REQUIRED'}")
    labcopy = capabilities.get("labcopy", {})
    passkey = capabilities.get("passkey_gate", {})
    print(f"  LabCopy:    {'READY' if labcopy.get('available') else 'UNAVAILABLE'}")
    print(f"  Passkey:    {'REQUIRED' if passkey.get('require_for_protected_actions') else 'OPTIONAL UNTIL ENROLLED'}")
    print("  Scope:      Wallet + canonical BlackBox + LabCopy; legacy Oubliette compatibility is backend-only.\n")


def cmd_open(args: argparse.Namespace) -> None:
    _require_typed("OPEN", args.confirm, 'Type OPEN to start a local Vault session: ')
    if args.session_id:
        session = _req("GET", f"/identity/sessions/{args.session_id}")
    else:
        session = _start_session(args.actor_id, args.ttl_minutes)
    result = _req(
        "POST",
        "/vault/open",
        {
            "session_id": session["session_id"],
            "hardware_gate_token": args.hardware_gate_token,
        },
    )
    print(f"Vault opened. Session: {result.get('open_session_id', 'unknown')}")


def cmd_lock(args: argparse.Namespace) -> None:
    if args.session_id:
        session = _req("GET", f"/identity/sessions/{args.session_id}")
    else:
        session = _start_session(args.actor_id, args.ttl_minutes)
    result = _req("POST", "/vault/lock", {"session_id": session["session_id"]})
    print(f"Vault locked. Revoked ceremony tokens: {result.get('revoked_ceremony_tokens', 0)}")


def cmd_create_project(args: argparse.Namespace) -> None:
    result = _req("POST", "/projects", {"name": args.name, "path": args.path or ""})
    print(f"Created project {result['name']} ({result['id']})")


def cmd_create_section(args: argparse.Namespace) -> None:
    result = _req(
        "POST",
        f"/projects/{args.project_id}/sections",
        {"name": args.name, "description": args.description or ""},
    )
    print(f"Created section {result['name']} ({result['id']})")


def cmd_ls(args: argparse.Namespace) -> None:
    state = _req("GET", "/state")
    projects = state.get("projects", [])
    for project in projects:
        if args.project and project.get("id") != args.project:
            continue
        print(f"\n{project.get('name')} [{project.get('id')}]")
        sections = project.get("sections", [])
        if not sections:
            print("  (no sections)")
        for section in sections:
            if args.section and section.get("id") != args.section:
                continue
            prime = section.get("prime") or "—"
            print(f"  {section.get('name')} [{section.get('id')}]  Prime: {prime}")
            for item in section.get("files", []):
                print(
                    f"    {item.get('state', '?'):10} {item.get('name', '?')} "
                    f"[{item.get('id', '?')}]"
                )
    if not projects:
        print("(no projects)")


def _add_material(args: argparse.Namespace, kind: str) -> None:
    path = Path(args.file).expanduser()
    if path.is_symlink():
        raise CLIError(f"Source file cannot be a symlink: {path}")
    if not path.is_file():
        raise CLIError(f"Source file does not exist: {path}")
    endpoint = "candidates" if kind == "candidate" else "raw-sources"
    result = _req(
        "POST",
        f"/projects/{args.project_id}/sections/{args.section_id}/{endpoint}",
        {"path": str(path.absolute()), "notes": args.notes or ""},
    )
    print(f"Added {kind}: {result['name']} ({result['id']})")


def cmd_add_candidate(args: argparse.Namespace) -> None:
    _add_material(args, "candidate")


def cmd_add_raw_source(args: argparse.Namespace) -> None:
    _add_material(args, "raw source")


def _start_session(actor_id: str, ttl_minutes: int) -> dict[str, Any]:
    return _req(
        "POST",
        "/identity/sessions",
        {
            "actor_id": actor_id,
            "actor_kind": "human",
            "device_id": "iteration-wallet-cli",
            "verified_methods": ["human_ceremony", "interactive_cli", "typed_human_ceremony"],
            "role_claims": {"local_continuity_only": True},
            "ttl_minutes": ttl_minutes,
        },
    )


def cmd_start_session(args: argparse.Namespace) -> None:
    _require_typed("I AM HERE", args.confirm, 'Type I AM HERE to create a local human session: ')
    session = _start_session(args.actor_id, args.ttl_minutes)
    print(f"Local identity session: {session['session_id']}")
    print("This proves local continuity only; it is not real-world authentication or nonrepudiation.")


def cmd_promote(args: argparse.Namespace) -> None:
    _require_typed("PROMOTE", args.confirm, 'Type PROMOTE to authorize Candidate → Prime: ')
    if args.session_id:
        session = _req("GET", f"/identity/sessions/{args.session_id}")
    else:
        session = _start_session(args.actor_id, args.ttl_minutes)
    session_id = session["session_id"]

    state = _req("GET", "/state")
    if not state.get("is_vault_open"):
        _require_typed("OPEN", args.open_confirm, 'Vault is locked. Type OPEN to continue: ')
        _req("POST", "/vault/open", {"session_id": session_id, "hardware_gate_token": getattr(args, "hardware_gate_token", None)})

    token = _req(
        "POST",
        "/ceremony/tokens",
        {
            "action_key": "promote_candidate_to_prime",
            "session_id": session_id,
            "project_id": args.project_id,
            "section_id": args.section_id,
            "object_id": args.candidate_id,
            "ttl_seconds": args.token_ttl_seconds,
        },
    )
    result = _req(
        "POST",
        f"/projects/{args.project_id}/sections/{args.section_id}/candidates/{args.candidate_id}/promote",
        {
            "ceremony_token": token["ceremony_token"],
            "session_id": session_id,
            "actor_kind": "human",
            "actor_id": session.get("actor_id", args.actor_id),
            "human_ceremony_passed": True,
            "reason": args.reason or "",
        },
        timeout=max(TIMEOUT, 30),
    )
    receipt = result.get("human_intent_receipt", {})
    verification = result.get("verification", {})
    promoted = result.get("result", {})
    print(f"Promoted to Prime: {promoted.get('name', args.candidate_id)}")
    print(f"Receipt: {receipt.get('receipt_id', 'missing')}")
    print(f"Verification: {'OK' if verification.get('ok') else 'FAILED'}")
    if not verification.get("ok"):
        raise CLIError(verification.get("reason", "Receipt verification failed."))



def _ensure_open_human_session(args: argparse.Namespace, confirmation_word: str) -> dict[str, Any]:
    session_id = getattr(args, "session_id", None)
    if session_id:
        session = _req("GET", f"/identity/sessions/{session_id}")
    else:
        session = _start_session(args.actor_id, args.ttl_minutes)

    state = _req("GET", "/state")
    if not state.get("is_vault_open"):
        _require_typed("OPEN", getattr(args, "open_confirm", None), "Vault is locked. Type OPEN to continue: ")
        _req("POST", "/vault/open", {
            "session_id": session["session_id"],
            "hardware_gate_token": getattr(args, "hardware_gate_token", None),
        })
    return session


def cmd_oubliette_inspect(args: argparse.Namespace) -> None:
    result = _req(
        "POST",
        f"/projects/{args.project_id}/sections/{args.section_id}/files/{args.object_id}/oubliette/inspect",
        {"actor_kind": "human", "target_label": args.target_label},
        timeout=max(TIMEOUT, 30),
    )
    report = result.get("report", {})
    print(f"Static inspection report: {report.get('report_id', 'missing')}")
    print(f"Target hash: {report.get('target_sha256', 'missing')}")
    print("Custody changed: no")
    print("Trust decided: no")
    codes = report.get("finding_codes") or [item.get("code") for item in report.get("findings", [])]
    print("Risk indicators: " + (", ".join(filter(None, codes)) if codes else "none observed"))


def cmd_oubliette_quarantine(args: argparse.Namespace) -> None:
    _require_typed("QUARANTINE", args.confirm, "Type QUARANTINE to authorize fenced custody: ")
    session = _ensure_open_human_session(args, "QUARANTINE")
    proposal = _req(
        "POST",
        f"/projects/{args.project_id}/sections/{args.section_id}/files/{args.object_id}/oubliette/quarantine-proposal",
        {"report_id": args.report_id},
    )
    token = _req(
        "POST",
        "/ceremony/tokens",
        {
            "action_key": "quarantine",
            "session_id": session["session_id"],
            "project_id": args.project_id,
            "section_id": args.section_id,
            "object_id": args.object_id,
            "proposal_id": proposal["proposal_id"],
            "proposal_hash": proposal["proposal_hash"],
            "ttl_seconds": args.token_ttl_seconds,
        },
    )
    result = _req(
        "POST",
        f"/projects/{args.project_id}/sections/{args.section_id}/files/{args.object_id}/quarantine",
        {
            "report_id": args.report_id,
            "ceremony_token": token["ceremony_token"],
            "session_id": session["session_id"],
            "reason": args.reason or "",
        },
        timeout=max(TIMEOUT, 30),
    )
    receipt = result.get("human_intent_receipt", {})
    verification = result.get("verification", {})
    print(f"Quarantined; protected content remains preserved: {result.get('result', {}).get('name', args.object_id)}")
    print(f"Receipt: {receipt.get('receipt_id', 'missing')}")
    print(f"Verification: {'OK' if verification.get('ok') else 'FAILED'}")
    if not verification.get("ok"):
        raise CLIError(verification.get("reason", "Receipt verification failed."))


def cmd_oubliette_inspect_derivative(args: argparse.Namespace) -> None:
    derivative_input = Path(args.derivative).expanduser()
    if derivative_input.is_symlink():
        raise CLIError(f"Derivative file cannot be a symlink: {derivative_input}")
    derivative = derivative_input.absolute()
    allowed_root = Path(args.allowed_root).expanduser().absolute() if args.allowed_root else derivative.parent
    result = _req(
        "POST",
        f"/projects/{args.project_id}/sections/{args.section_id}/files/{args.parent_id}/oubliette/derivatives/inspect",
        {
            "derivative_path": str(derivative),
            "allowed_root": str(allowed_root),
            "actor_kind": "human",
            "target_label": args.target_label,
        },
        timeout=max(TIMEOUT, 30),
    )
    report = result.get("report", {})
    capsule = result.get("capsule", {})
    proposal = result.get("admission_proposal", {})
    if getattr(args, "json", False):
        print(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True))
        return
    print(f"Wallet Intake Capsule: {capsule.get('capsule_id', 'missing')}")
    print(f"Manifest hash: {capsule.get('manifest_hash', 'missing')}")
    print(f"Static report: {report.get('report_id', 'missing')}")
    print(f"Admission proposal: {proposal.get('proposal_id', 'missing')}")
    print(f"Proposal hash: {proposal.get('proposal_hash', 'missing')}")
    print("Candidate admitted: no — a separate capsule-scoped Human Intent ceremony is required")


def cmd_oubliette_admit_derivative(args: argparse.Namespace) -> None:
    derivative_input = Path(args.derivative).expanduser()
    if derivative_input.is_symlink():
        raise CLIError(f"Derivative file cannot be a symlink: {derivative_input}")
    derivative = derivative_input.absolute()
    _require_typed("ADMIT", args.confirm, "Type ADMIT to create a new untrusted Candidate: ")
    session = _ensure_open_human_session(args, "ADMIT")
    token = _req(
        "POST",
        "/ceremony/tokens",
        {
            "action_key": "admit_oubliette_derivative_as_candidate",
            "session_id": session["session_id"],
            "project_id": args.project_id,
            "section_id": args.section_id,
            "object_id": args.parent_id,
            "proposal_id": args.proposal_id,
            "proposal_hash": args.proposal_hash,
            "ttl_seconds": args.token_ttl_seconds,
        },
    )
    result = _req(
        "POST",
        f"/projects/{args.project_id}/sections/{args.section_id}/files/{args.parent_id}/oubliette/derivatives/admit",
        {
            "derivative_path": str(derivative),
            "capsule_id": args.capsule_id,
            "proposal_id": args.proposal_id,
            "proposal_hash": args.proposal_hash,
            "report_id": args.report_id,
            "ceremony_token": token["ceremony_token"],
            "session_id": session["session_id"],
            "reason": args.reason or "",
        },
        timeout=max(TIMEOUT, 30),
    )
    admitted = result.get("result", {})
    receipt = result.get("human_intent_receipt", {})
    verification = result.get("verification", {})
    print(f"New Candidate: {admitted.get('name', admitted.get('id', 'missing'))}")
    print(f"Parent remains quarantined: {args.parent_id}")
    print(f"Trust status: {admitted.get('trust_status', 'candidate_only')}")
    print(f"Receipt: {receipt.get('receipt_id', 'missing')}")
    print(f"Verification: {'OK' if verification.get('ok') else 'FAILED'}")
    if not verification.get("ok"):
        raise CLIError(verification.get("reason", "Receipt verification failed."))

def cmd_labcopy_export(args: argparse.Namespace) -> None:
    _require_typed("EXPORT", args.confirm, "Type EXPORT to authorize a traceable LabCopy: ")
    session = _ensure_open_human_session(args, "EXPORT")
    proposal = _req(
        "POST",
        f"/projects/{args.project_id}/sections/{args.section_id}/files/{args.object_id}/labcopy/proposal",
        {
            "output_dir": str(Path(args.output_dir).expanduser().absolute()),
            "lab_policy": args.lab_policy,
            "requested_label": args.requested_label,
        },
    )
    token = _req(
        "POST", "/ceremony/tokens",
        {
            "action_key": "export_working_copy",
            "session_id": session["session_id"],
            "project_id": args.project_id,
            "section_id": args.section_id,
            "object_id": args.object_id,
            "proposal_id": proposal["proposal_id"],
            "proposal_hash": proposal["proposal_hash"],
            "ttl_seconds": args.token_ttl_seconds,
        },
    )
    result = _req(
        "POST",
        f"/projects/{args.project_id}/sections/{args.section_id}/files/{args.object_id}/export-working-copy",
        {
            "proposal_id": proposal["proposal_id"],
            "proposal_hash": proposal["proposal_hash"],
            "ceremony_token": token["ceremony_token"],
            "session_id": session["session_id"],
            "reason": args.reason or "",
        },
        timeout=max(TIMEOUT, 30),
    )
    exported=result.get("result", {})
    print(f"LabCopy: {exported.get('external_package_path', proposal.get('external_package_path'))}")
    print(f"Parent SHA-256: {exported.get('manifest', {}).get('parent_sha256', proposal.get('source_sha256'))}")
    print(f"Receipt: {result.get('human_intent_receipt', {}).get('receipt_id', 'missing')}")
    print(f"Verification: {'OK' if result.get('verification', {}).get('ok') else 'FAILED'}")


def cmd_labcopy_reenter(args: argparse.Namespace) -> None:
    result_input = Path(args.result_file).expanduser()
    if result_input.is_symlink():
        raise CLIError(f"Result file cannot be a symlink: {result_input}")
    result_path = result_input.absolute()
    if args.manifest:
        manifest_input = Path(args.manifest).expanduser()
        if manifest_input.is_symlink():
            raise CLIError(f"Manifest file cannot be a symlink: {manifest_input}")
    allowed_root=Path(args.allowed_root).expanduser().absolute() if args.allowed_root else result_path.parent
    classified=_req(
        "POST",
        f"/projects/{args.project_id}/sections/{args.section_id}/labcopy/reenter",
        {
            "result_path": str(result_path),
            "allowed_root": str(allowed_root),
            "manifest_path": str(Path(args.manifest).expanduser().absolute()) if args.manifest else None,
            "source_label": args.source_label,
        },
        timeout=max(TIMEOUT, 30),
    )
    disposition=classified.get("disposition")
    if disposition != "candidate_pending_authorization":
        print(f"Disposition: {disposition}")
        print(f"Object: {classified.get('result', {}).get('id', 'none')}")
        return
    _require_typed("ADMIT", args.confirm, "Type ADMIT to create the linked Candidate: ")
    session=_ensure_open_human_session(args, "ADMIT")
    proposal=classified["proposal"]
    capsule=classified["capsule"]
    token=_req(
        "POST", "/ceremony/tokens",
        {
            "action_key": "admit_labcopy_result_as_candidate",
            "session_id": session["session_id"],
            "project_id": args.project_id,
            "section_id": args.section_id,
            "object_id": proposal["object_id"],
            "proposal_id": proposal["proposal_id"],
            "proposal_hash": proposal["proposal_hash"],
            "ttl_seconds": args.token_ttl_seconds,
        },
    )
    admitted=_req(
        "POST",
        f"/labcopy/{proposal['lab_id']}/results/{capsule['capsule_id']}/admit",
        {
            "proposal_id": proposal["proposal_id"],
            "proposal_hash": proposal["proposal_hash"],
            "ceremony_token": token["ceremony_token"],
            "session_id": session["session_id"],
            "reason": args.reason or "",
        },
        timeout=max(TIMEOUT, 30),
    )
    created=admitted.get("result", {})
    print("Disposition: new_candidate")
    print(f"Candidate: {created.get('id', 'missing')}")
    print(f"Derived from: {created.get('derived_from_hash', 'missing')}")
    print(f"Receipt: {admitted.get('human_intent_receipt', {}).get('receipt_id', 'missing')}")
    print(f"Verification: {'OK' if admitted.get('verification', {}).get('ok') else 'FAILED'}")


def cmd_receipts(args: argparse.Namespace) -> None:
    result = _req("GET", "/blackbox/receipts")
    receipts = result.get("receipts", [])
    if args.json:
        _print_json(result)
        return
    if not receipts:
        print("(no Human Intent receipts)")
        return
    for receipt in receipts:
        print(
            f"{receipt.get('receipt_id')}  {receipt.get('action_key')}  "
            f"{receipt.get('object_id')}  {receipt.get('created_at')}"
        )


def cmd_receipt(args: argparse.Namespace) -> None:
    _print_json(_req("GET", f"/blackbox/receipts/{args.receipt_id}"))


def cmd_chain(_: argparse.Namespace) -> None:
    _print_json(_req("GET", "/blackbox/chain"))


def cmd_custody(_: argparse.Namespace) -> None:
    _print_json(_req("GET", "/custody/verify"))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="iw",
        description="Iteration Wallet — canonical promotion and Oubliette intake alpha",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    serve = subparsers.add_parser("serve", help="Start the local server and canonical UI")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=7432)
    serve.add_argument("--root", help="Wallet storage root for this server process (sets ITERATION_WALLET_ROOT)")
    serve.set_defaults(func=cmd_serve)

    subparsers.add_parser("status", help="Show canonical runtime status").set_defaults(func=cmd_status)
    doctor = subparsers.add_parser("doctor", help="Verify installed package ownership and BlackBox compatibility")
    doctor.add_argument("--json", action="store_true")
    doctor.set_defaults(func=cmd_doctor)

    open_cmd = subparsers.add_parser("open", help="Start a local Vault session")
    open_cmd.add_argument("--confirm")
    open_cmd.add_argument("--actor-id", default="cli-user")
    open_cmd.add_argument("--session-id", default="")
    open_cmd.add_argument("--ttl-minutes", type=int, default=480)
    open_cmd.add_argument("--hardware-gate-token", default=None)
    open_cmd.set_defaults(func=cmd_open)

    lock_cmd = subparsers.add_parser("lock", help="Lock the Vault and revoke active ceremony tokens")
    lock_cmd.add_argument("--actor-id", default="cli-user")
    lock_cmd.add_argument("--session-id", default="")
    lock_cmd.add_argument("--ttl-minutes", type=int, default=480)
    lock_cmd.set_defaults(func=cmd_lock)

    project = subparsers.add_parser("create-project", help="Create a project")
    project.add_argument("name")
    project.add_argument("--path", default="")
    project.set_defaults(func=cmd_create_project)

    section = subparsers.add_parser("create-section", help="Create a section inside a project")
    section.add_argument("project_id")
    section.add_argument("name")
    section.add_argument("--description", default="")
    section.set_defaults(func=cmd_create_section)

    listing = subparsers.add_parser("ls", help="List projects, sections, and generations")
    listing.add_argument("--project", default="")
    listing.add_argument("--section", default="")
    listing.set_defaults(func=cmd_ls)

    for name, handler, label in (
        ("add-candidate", cmd_add_candidate, "Add a Candidate copy to custody"),
        ("add-raw-source", cmd_add_raw_source, "Add a Raw Source copy to custody"),
    ):
        add = subparsers.add_parser(name, help=label)
        add.add_argument("project_id")
        add.add_argument("section_id")
        add.add_argument("file")
        add.add_argument("--notes", default="")
        add.set_defaults(func=handler)

    identity = subparsers.add_parser("start-session", help="Create a local human identity-continuity session")
    identity.add_argument("actor_id")
    identity.add_argument("--ttl-minutes", type=int, default=480)
    identity.add_argument("--confirm")
    identity.set_defaults(func=cmd_start_session)

    promote = subparsers.add_parser("promote", help="Perform the canonical Candidate → Prime ceremony")
    promote.add_argument("project_id")
    promote.add_argument("section_id")
    promote.add_argument("candidate_id")
    promote.add_argument("--actor-id", required=True)
    promote.add_argument("--session-id")
    promote.add_argument("--reason", default="")
    promote.add_argument("--confirm")
    promote.add_argument("--open-confirm")
    promote.add_argument("--hardware-gate-token", default=None)
    promote.add_argument("--ttl-minutes", type=int, default=480)
    promote.add_argument("--token-ttl-seconds", type=int, default=300)
    promote.set_defaults(func=cmd_promote)


    # Oubliette commands were intentionally retired from the active product CLI.
    # The backend compatibility routes remain hidden for existing alpha data,
    # while all supported external work uses LabCopy.

    lab_export = subparsers.add_parser("labcopy-export", help="Export an HMAC-authenticated LabCopy")
    lab_export.add_argument("project_id")
    lab_export.add_argument("section_id")
    lab_export.add_argument("object_id")
    lab_export.add_argument("output_dir")
    lab_export.add_argument("--lab-policy", default="manual external work")
    lab_export.add_argument("--requested-label")
    lab_export.add_argument("--actor-id", required=True)
    lab_export.add_argument("--session-id")
    lab_export.add_argument("--reason", default="")
    lab_export.add_argument("--confirm")
    lab_export.add_argument("--open-confirm")
    lab_export.add_argument("--ttl-minutes", type=int, default=480)
    lab_export.add_argument("--token-ttl-seconds", type=int, default=300)
    lab_export.set_defaults(func=cmd_labcopy_export)

    lab_reenter = subparsers.add_parser("labcopy-reenter", help="Re-enter LabCopy output under the narrow linked/Raw Source/no-op rules")
    lab_reenter.add_argument("project_id")
    lab_reenter.add_argument("section_id")
    lab_reenter.add_argument("result_file")
    lab_reenter.add_argument("--manifest")
    lab_reenter.add_argument("--allowed-root")
    lab_reenter.add_argument("--source-label")
    lab_reenter.add_argument("--actor-id", required=True)
    lab_reenter.add_argument("--session-id")
    lab_reenter.add_argument("--reason", default="")
    lab_reenter.add_argument("--confirm")
    lab_reenter.add_argument("--open-confirm")
    lab_reenter.add_argument("--ttl-minutes", type=int, default=480)
    lab_reenter.add_argument("--token-ttl-seconds", type=int, default=300)
    lab_reenter.set_defaults(func=cmd_labcopy_reenter)

    receipts = subparsers.add_parser("receipts", help="List Human Intent receipts")
    receipts.add_argument("--json", action="store_true")
    receipts.set_defaults(func=cmd_receipts)

    receipt = subparsers.add_parser("receipt", help="Show one Human Intent receipt")
    receipt.add_argument("receipt_id")
    receipt.set_defaults(func=cmd_receipt)

    subparsers.add_parser("chain", help="Verify the canonical evidence chain").set_defaults(func=cmd_chain)
    subparsers.add_parser("custody", help="Verify current custody integrity").set_defaults(func=cmd_custody)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        args.func(args)
    except KeyboardInterrupt:
        print("\nInterrupted; no success is implied.", file=sys.stderr)
        return 130
    except CLIError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
