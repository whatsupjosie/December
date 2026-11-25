"""Transport-neutral client contract for the canonical BlackBox recorder.

The first implementation is deliberately local and in-process.  Hosts depend on
this contract rather than recorder storage internals, so a future loopback socket
or named-pipe transport can be added without moving policy into BlackBox.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Protocol, runtime_checkable

from .models import AppendReceipt, EvidenceEvent
from .service import BlackBoxPlugin

CLIENT_SCHEMA_VERSION = "bbx1-client/1"


class BlackBoxClientError(RuntimeError):
    """Base error for client-contract failures."""


@dataclass(frozen=True, slots=True)
class BlackBoxCapabilities:
    schema_version: str
    transport: str
    operation_id_idempotency: bool
    durable_append: bool
    receipt_verification: bool
    closed_views: bool
    sealing: bool
    direct_storage_access: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "transport": self.transport,
            "operation_id_idempotency": self.operation_id_idempotency,
            "durable_append": self.durable_append,
            "receipt_verification": self.receipt_verification,
            "closed_views": self.closed_views,
            "sealing": self.sealing,
            "direct_storage_access": self.direct_storage_access,
        }


@dataclass(frozen=True, slots=True)
class ReceiptVerification:
    ok: bool
    record_id: str
    reason: str
    record: Mapping[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "record_id": self.record_id,
            "reason": self.reason,
            "record": None if self.record is None else dict(self.record),
        }


@runtime_checkable
class BlackBoxClient(Protocol):
    """Minimal host-facing BlackBox contract.

    A client validates and records evidence.  It does not decide whether the
    originating program may perform an action.
    """

    def capabilities(self) -> BlackBoxCapabilities: ...

    def submit(
        self,
        event: EvidenceEvent,
        *,
        expected_previous_hash: str | None = None,
    ) -> AppendReceipt: ...

    def status(self) -> Mapping[str, Any]: ...

    def verify_receipt(self, receipt: AppendReceipt | Mapping[str, Any]) -> ReceiptVerification: ...

    def verify(self) -> Mapping[str, Any]: ...

    def iter_records(self) -> Iterable[Mapping[str, Any]]: ...


class LocalBlackBoxClient:
    """Real local client over one standalone :class:`BlackBoxPlugin` instance."""

    def __init__(self, plugin: BlackBoxPlugin) -> None:
        if not isinstance(plugin, BlackBoxPlugin):
            raise TypeError("LocalBlackBoxClient requires a BlackBoxPlugin")
        self.plugin = plugin

    @classmethod
    def open(cls, storage_root: str | Any, session_id: str, **recorder_options: Any) -> "LocalBlackBoxClient":
        return cls(BlackBoxPlugin(storage_root, session_id, **recorder_options))

    def capabilities(self) -> BlackBoxCapabilities:
        return BlackBoxCapabilities(
            schema_version=CLIENT_SCHEMA_VERSION,
            transport="local-in-process",
            operation_id_idempotency=True,
            durable_append=True,
            receipt_verification=True,
            closed_views=True,
            sealing=True,
            direct_storage_access=False,
        )

    def submit(
        self,
        event: EvidenceEvent,
        *,
        expected_previous_hash: str | None = None,
    ) -> AppendReceipt:
        return self.plugin.append_event(event, expected_previous_hash=expected_previous_hash)

    def status(self) -> Mapping[str, Any]:
        health = dict(self.plugin.health())
        verification = dict(self.plugin.verify())
        return {
            "available": True,
            "capabilities": self.capabilities().to_dict(),
            "health": health,
            "verification": verification,
        }

    def verify(self) -> Mapping[str, Any]:
        return self.plugin.verify()

    def iter_records(self) -> Iterable[Mapping[str, Any]]:
        return self.plugin.recorder.iter_records()

    @staticmethod
    def _receipt_fields(receipt: AppendReceipt | Mapping[str, Any]) -> tuple[str, str, int]:
        if isinstance(receipt, AppendReceipt):
            return receipt.record_id, receipt.event_hash, receipt.sequence
        try:
            return str(receipt["record_id"]), str(receipt["event_hash"]), int(receipt["sequence"])
        except (KeyError, TypeError, ValueError) as exc:
            raise BlackBoxClientError(f"invalid receipt material: {exc}") from exc

    def verify_receipt(self, receipt: AppendReceipt | Mapping[str, Any]) -> ReceiptVerification:
        record_id, event_hash, sequence = self._receipt_fields(receipt)
        chain = self.plugin.verify()
        if not chain.get("ok"):
            return ReceiptVerification(False, record_id, "canonical chain verification failed")
        for record in self.plugin.recorder.iter_records():
            if record.get("record_id") != record_id:
                continue
            if record.get("hash") != event_hash:
                return ReceiptVerification(False, record_id, "receipt hash does not match canonical record")
            if int(record.get("seq", -1)) != sequence:
                return ReceiptVerification(False, record_id, "receipt sequence does not match canonical record")
            return ReceiptVerification(True, record_id, "receipt matches verified canonical record", record)
        return ReceiptVerification(False, record_id, "receipt record is absent from canonical BlackBox")
