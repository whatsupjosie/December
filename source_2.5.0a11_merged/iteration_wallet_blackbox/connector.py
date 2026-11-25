"""Seamless but non-owning Iteration Wallet / BlackBox connector."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from blackbox_plugin import (AppendReceipt, BlackBoxClient, LocalBlackBoxClient, BlackBoxPlugin,
    RecorderIntegrityError, RecorderSealedError, RecordValidationError, WitnessUnavailableError)
from .event_map import wallet_fact_to_event
from .models import WalletFact
from .outbox import DurableOutbox


class WitnessDelivery(str, Enum):
    ACKNOWLEDGED = "acknowledged"
    PENDING = "pending"
    REJECTED = "rejected"
    NOT_CONFIGURED = "not_configured"


class WitnessRejectedError(RuntimeError):
    """The canonical recorder rejected a validly delivered evidence fact."""


class WitnessAcknowledgementPersistenceError(OSError):
    """BlackBox accepted the fact but the adapter could not persist its acknowledgement."""

    def __init__(self, receipt: AppendReceipt, cause: BaseException) -> None:
        super().__init__(
            f"BlackBox accepted record {receipt.record_id}, but local acknowledgement persistence failed: "
            f"{type(cause).__name__}: {cause}"
        )
        self.receipt = receipt


@dataclass(slots=True)
class WalletBlackBoxConnector:
    outbox: DurableOutbox
    sink: BlackBoxClient | BlackBoxPlugin | None = None

    def __post_init__(self) -> None:
        if isinstance(self.sink, BlackBoxPlugin):
            self.sink = LocalBlackBoxClient(self.sink)

    def submit(self, fact: WalletFact, *, require_ack: bool = False) -> tuple[WitnessDelivery, AppendReceipt | None]:
        self.outbox.enqueue(fact)
        if self.sink is None:
            if require_ack:
                raise WitnessUnavailableError("BlackBox acknowledgement is required but no sink is configured")
            return WitnessDelivery.NOT_CONFIGURED, None
        try:
            receipt = self.sink.submit(wallet_fact_to_event(fact))
        except (RecordValidationError, RecorderIntegrityError, RecorderSealedError) as exc:
            self.outbox.reject(fact.operation_id, f"{type(exc).__name__}: {exc}")
            if require_ack:
                raise WitnessRejectedError("BlackBox rejected the Wallet fact") from exc
            return WitnessDelivery.REJECTED, None
        except Exception as exc:
            self.outbox.fail(fact.operation_id, f"{type(exc).__name__}: {exc}")
            if require_ack:
                raise WitnessUnavailableError("BlackBox did not acknowledge the Wallet fact") from exc
            return WitnessDelivery.PENDING, None
        try:
            self.outbox.acknowledge(fact.operation_id, receipt.record_id)
        except Exception as exc:
            raise WitnessAcknowledgementPersistenceError(receipt, exc) from exc
        return WitnessDelivery.ACKNOWLEDGED, receipt

    def flush(self) -> int:
        if self.sink is None:
            return 0
        delivered = 0
        for item in tuple(self.outbox.pending()):
            try:
                receipt = self.sink.submit(wallet_fact_to_event(item.fact))
            except (RecordValidationError, RecorderIntegrityError, RecorderSealedError) as exc:
                self.outbox.reject(item.fact.operation_id, f"{type(exc).__name__}: {exc}")
                continue
            except Exception as exc:
                self.outbox.fail(item.fact.operation_id, f"{type(exc).__name__}: {exc}")
                continue
            try:
                self.outbox.acknowledge(item.fact.operation_id, receipt.record_id)
            except Exception as exc:
                raise WitnessAcknowledgementPersistenceError(receipt, exc) from exc
            delivered += 1
        return delivered
