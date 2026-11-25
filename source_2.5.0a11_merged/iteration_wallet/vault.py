"""Retired pre-v2.1 Vault engine compatibility boundary.

The original broad v2 engine is preserved verbatim under ``historical_sources``.
It is not an active custody authority because it bypasses scoped Human Intent,
the canonical transaction journal, and BBX1 evidence.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

VAULT_ROOT = Path.home() / ".iteration_wallet"
PRESERVATION_RULE = "Once material is admitted, its protected content remains preserved."
NO_EXECUTE_RULE = "Iteration Wallet never executes user-custodied material."


class VaultError(RuntimeError):
    """Raised when active code attempts to use the retired v2 engine."""


class VaultEngine:
    """Fail-closed tombstone for the retired broad-mutation engine."""

    def __init__(self, *_: Any, **__: Any) -> None:
        raise VaultError(
            "The pre-v2.1 Vault engine is retired because it bypasses the "
            "canonical Wallet/BlackBox transaction protocol. Use "
            "iteration_wallet.vault_v21.VaultEngine through the canonical server runtime."
        )


__all__ = ["VAULT_ROOT", "PRESERVATION_RULE", "NO_EXECUTE_RULE", "VaultError", "VaultEngine"]
