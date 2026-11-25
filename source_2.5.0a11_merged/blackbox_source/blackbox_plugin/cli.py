"""Command-line interface for the standalone BBX1 plugin."""
from __future__ import annotations

import argparse
import json
from typing import Any

from .discovery import closed_discovery_summary, discover_ai_profiles
from .client import LocalBlackBoxClient, BlackBoxClientError
from .errors import BlackBoxError
from .models import Coverage, ObservationMode
from .sentinel import IntegritySentinel
from .service import BlackBoxPlugin


def _plugin(args: argparse.Namespace) -> BlackBoxPlugin:
    return BlackBoxPlugin(args.storage, args.session)


def _json(value: str) -> dict[str, Any]:
    parsed = json.loads(value)
    if not isinstance(parsed, dict):
        raise argparse.ArgumentTypeError("payload must be a JSON object")
    return parsed


class CLIError(RuntimeError):
    """Controlled user-facing CLI failure."""


def _human_actor(value: str) -> str:
    actor = str(value or "").strip()
    if not actor:
        raise CLIError("--human-actor is required")
    return actor if actor.startswith("human:") else f"human:{actor}"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="bbx1", description="Standalone tamper-evident flight recorder for AI agents and local software")
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="initialize an empty session")
    init.add_argument("--storage", required=True)
    init.add_argument("--session", required=True)

    capabilities = sub.add_parser("capabilities", help="show the public local client contract")
    capabilities.add_argument("--storage", required=True)
    capabilities.add_argument("--session", required=True)

    status = sub.add_parser("status", help="show recorder health, verification, and capabilities")
    status.add_argument("--storage", required=True)
    status.add_argument("--session", required=True)

    receipt = sub.add_parser("verify-receipt", help="verify one append receipt against the canonical chain")
    receipt.add_argument("--storage", required=True)
    receipt.add_argument("--session", required=True)
    receipt.add_argument("--record-id", required=True)
    receipt.add_argument("--event-hash", required=True)
    receipt.add_argument("--sequence", required=True, type=int)

    record = sub.add_parser("record", help="append one host-supplied fact")
    record.add_argument("--storage", required=True)
    record.add_argument("--session", required=True)
    record.add_argument("--event-type", required=True)
    record.add_argument("--source", required=True)
    record.add_argument("--actor", required=True)
    record.add_argument("--subject", required=True)
    record.add_argument("--operation-id")
    record.add_argument("--source-sequence", type=int)
    record.add_argument("--channel", default="GEN")
    record.add_argument("--event-code", default="OBS")
    record.add_argument("--coverage", choices=[item.value for item in Coverage], default=Coverage.FULL.value)
    record.add_argument("--observation-mode", choices=[item.value for item in ObservationMode], default=ObservationMode.DIRECT.value)
    record.add_argument("--payload", type=_json, default={})

    for name in ("verify", "summary", "report", "seal"):
        cmd = sub.add_parser(name)
        cmd.add_argument("--storage", required=True)
        cmd.add_argument("--session", required=True)
        if name == "seal":
            cmd.add_argument("--reason", default="manual")
    history = sub.add_parser("history")
    history.add_argument("--storage", required=True)
    history.add_argument("--session", required=True)
    history.add_argument("--subject", required=True)

    discover = sub.add_parser("discover-ai", help="read only explicitly supplied AI runtime configs")
    discover.add_argument("config", nargs="+")

    commission = sub.add_parser("sentinel-commission", help="commission a local read-only reference manifest")
    commission.add_argument("--target", required=True)
    commission.add_argument("--manifest", required=True)
    commission.add_argument("--human-actor", required=True)
    commission.add_argument("--confirm-human", action="store_true")
    commission.add_argument("--label", default="Golden Build")

    sentinel_verify = sub.add_parser("sentinel-verify")
    sentinel_verify.add_argument("--target", required=True)
    sentinel_verify.add_argument("--manifest", required=True)

    return parser


def _main_impl(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "init":
        plugin = _plugin(args)
        print(json.dumps({"ok": True, "session_dir": str(plugin.session_dir), "health": plugin.health()}, indent=2))
        return 0
    if args.command == "capabilities":
        client = LocalBlackBoxClient(_plugin(args))
        print(json.dumps(client.capabilities().to_dict(), indent=2))
        return 0
    if args.command == "status":
        client = LocalBlackBoxClient(_plugin(args))
        print(json.dumps(dict(client.status()), indent=2))
        return 0 if client.verify()["ok"] else 2
    if args.command == "verify-receipt":
        client = LocalBlackBoxClient(_plugin(args))
        result = client.verify_receipt({
            "record_id": args.record_id,
            "event_hash": args.event_hash,
            "sequence": args.sequence,
        })
        print(json.dumps(result.to_dict(), indent=2))
        return 0 if result.ok else 2
    if args.command == "record":
        receipt = _plugin(args).record(
            event_type=args.event_type,
            source=args.source,
            actor=args.actor,
            subject_id=args.subject,
            operation_id=args.operation_id,
            source_sequence=args.source_sequence,
            coverage=Coverage(args.coverage),
            observation_mode=ObservationMode(args.observation_mode),
            payload=args.payload,
            channel=args.channel,
            event_code=args.event_code,
        )
        print(json.dumps(receipt.to_dict(), indent=2))
        return 0
    if args.command == "verify":
        result = _plugin(args).verify()
        print(json.dumps(result, indent=2))
        return 0 if result["ok"] else 2
    if args.command == "summary":
        print(json.dumps(_plugin(args).closed_summary(), indent=2))
        return 0
    if args.command == "history":
        print(json.dumps(_plugin(args).object_history(args.subject), indent=2))
        return 0
    if args.command == "report":
        print(_plugin(args).known_record_report(), end="")
        return 0
    if args.command == "seal":
        path = _plugin(args).seal(args.reason)
        print(json.dumps({"ok": True, "seal": str(path)}, indent=2))
        return 0
    if args.command == "discover-ai":
        print(json.dumps(closed_discovery_summary(discover_ai_profiles(args.config)), indent=2))
        return 0
    if args.command == "sentinel-commission":
        path = IntegritySentinel().commission_reference(
            args.target,
            args.manifest,
            actor_id=_human_actor(args.human_actor),
            human_authorized=args.confirm_human,
            label=args.label,
        )
        print(json.dumps({"ok": True, "manifest": str(path), "trusted_by_human_ceremony": True}, indent=2))
        return 0
    if args.command == "sentinel-verify":
        result = IntegritySentinel().verify_target(args.target, args.manifest)
        print(json.dumps(result, indent=2))
        return 0 if result["ok"] else 2
    raise AssertionError(args.command)


def main(argv: list[str] | None = None) -> int:
    try:
        return _main_impl(argv)
    except KeyboardInterrupt:
        print("Interrupted; no success is implied.")
        return 130
    except (CLIError, BlackBoxError, BlackBoxClientError, PermissionError, FileExistsError, ValueError, OSError) as exc:
        print(f"Error: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
