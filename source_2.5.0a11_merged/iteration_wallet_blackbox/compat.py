"""Compatibility surface for the current Iteration Wallet VaultEngine.

This adapter exposes the small method set the existing VaultEngine already calls,
while all durable evidence is owned by the standalone BlackBox plugin.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import uuid4

from blackbox_plugin import BlackBoxClient, BlackBoxPlugin, Coverage, LocalBlackBoxClient, ObservationMode
from .connector import WalletBlackBoxConnector, WitnessDelivery
from .models import WalletFact
from .outbox import DurableOutbox


class WalletBlackBoxCompat:
    def __init__(self, client: BlackBoxClient | BlackBoxPlugin, outbox_path: Path | str) -> None:
        self.client = LocalBlackBoxClient(client) if isinstance(client, BlackBoxPlugin) else client
        self.connector = WalletBlackBoxConnector(DurableOutbox(outbox_path), self.client)

    @staticmethod
    def _subject(extra: dict[str, Any]) -> str:
        return str(extra.get("file_id") or extra.get("object_id") or extra.get("section_id") or extra.get("project_id") or "wallet:system")

    def write_event(self, event_type: str, summary: str, **extra: Any) -> dict[str, Any]:
        operation_id = str(extra.pop("operation_id", None) or uuid4().hex)
        fact = WalletFact(
            event_type=event_type,
            actor=str(extra.pop("actor", "system:iteration_wallet")),
            object_id=self._subject(extra),
            project_id=str(extra.get("project_id") or "project:system"),
            section_id=extra.get("section_id"),
            operation_id=operation_id,
            session_id=str(self.client.status().get("health", {}).get("session_id") or "wallet-main"),
            observation_mode=ObservationMode.DIRECT,
            coverage=Coverage.FULL,
            payload={"summary": summary, **extra},
        )
        status, receipt = self.connector.submit(fact, require_ack=True)
        if status is not WitnessDelivery.ACKNOWLEDGED or receipt is None:
            raise RuntimeError(
                "BlackBox require-ack contract returned without a durable acknowledgement"
            )
        return {
            "event_id": receipt.record_id,
            "event_hash": receipt.event_hash,
            "previous_event_hash": receipt.previous_hash,
            "chain_index": receipt.sequence + 1,
            "event_type": event_type,
            "summary": summary,
            "operation_id": operation_id,
        }

    def issue_human_intent_receipt(self, **kwargs: Any) -> dict[str, Any]:
        """Refuse authority fabrication at the compatibility boundary.

        Human Intent receipts are Wallet-owned artifacts requiring a real
        identity session, Gatekeeper decision, scoped one-time ceremony record,
        completed custody result, and canonical receipt graph. This neutral
        event adapter cannot prove those facts and therefore fails closed.
        """
        raise PermissionError(
            "Non-authoritative compatibility adapters cannot mint Human Intent receipts; "
            "use the Wallet-owned canonical promotion protocol."
        )

    def current_chain_head(self) -> str:
        health = self.client.status().get("health", {})
        return str(health.get("last_record_hash") or "GENESIS")

    def verify_chain(self) -> dict[str, Any]:
        result = dict(self.client.verify())
        return {
            "ok": result["ok"],
            "event_count": result["checked"],
            "reason": "; ".join(result.get("errors") or []),
            "sealed": result["sealed"],
        }

    def verify_receipts(self) -> dict[str, Any]:
        receipts = [item for item in self.client.iter_records() if item.get("event_type") == "HUMAN_INTENT_RECEIPT_ISSUED"]
        return {"ok": bool(self.client.verify()["ok"]), "receipt_count": len(receipts)}

    def closed_summary(self) -> dict[str, Any]:
        plugin = getattr(self.client, "plugin", None)
        if plugin is None:
            summary = {"chain_verified": bool(self.client.verify().get("ok")), "transport": self.client.capabilities().transport}
        else:
            summary = plugin.closed_summary()
        summary["wallet_outbox"] = self.connector.outbox.closed_status()
        return summary


def attach_to_wallet(vault_engine: Any, client: BlackBoxClient | BlackBoxPlugin, *, outbox_path: Path | str | None = None) -> WalletBlackBoxCompat:
    """Attach without replacing Wallet custody policy or state ownership."""
    if outbox_path is None:
        plugin = client if isinstance(client, BlackBoxPlugin) else getattr(client, "plugin", None)
        fallback_root = plugin.session_dir.parent if plugin is not None else Path.cwd()
        root = Path(getattr(vault_engine, "vault_root", fallback_root))
        outbox_path = root / "blackbox_outbox" / "wallet_facts.jsonl"
    adapter = WalletBlackBoxCompat(client, outbox_path)
    vault_engine.blackbox = adapter
    return adapter
