"""Retired Wallet-native BlackBox compatibility boundary.

The writable implementation that formerly lived here created a second evidence
chain.  It is preserved verbatim under ``historical_sources`` for legacy audit
and migration work, but it is not an active product authority.

New code must use :class:`iteration_wallet.canonical_evidence.CanonicalEvidenceAdapter`.
This module intentionally fails closed rather than offering a compatibility
writer that could silently recreate the retired chain.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any


class LegacyBlackBoxRetiredError(RuntimeError):
    """Raised when active code attempts to instantiate the retired writer."""


class BlackBox:
    """Fail-closed tombstone for the retired writable Wallet-native recorder."""

    def __init__(self, vault_root: Path | str, *_: Any, **__: Any) -> None:
        raise LegacyBlackBoxRetiredError(
            "The writable Wallet-native BlackBox has been retired because it "
            "created a second canonical evidence chain. Use "
            "CanonicalEvidenceAdapter for active evidence, or inspect the "
            "preserved historical source with explicit read-only migration tooling."
        )


__all__ = ["BlackBox", "LegacyBlackBoxRetiredError"]
