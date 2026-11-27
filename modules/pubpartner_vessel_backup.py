"""Automatic, change-triggered backups of the PubPartner vessel.

The vessel is a single SQLite file and the friend backup (``pubpartner_backup``) does
not include it, so without this the vessel has no copy at all. This module takes a
transaction-consistent copy with the vessel's own ``backup_to`` (which validates the
copy before it is moved into place) whenever the vessel's sealed state has changed.

Rules it keeps:

* A copy is made only when the vessel's state hash is new. The first 16 hex digits of
  that hash are in the file name, so "have I already saved this state?" is answered
  by looking at the folder. A clean stop followed by a start makes one copy, not two.
* Nothing is ever deleted, overwritten or pruned. Old copies stay until you remove them.
* It never raises. A failed backup is reported in the returned dict and the caller
  logs it; it must not stop the app from starting or from shutting down.

Copies live in ``<data dir>/pubpartner/backups/vessel/`` and are named
``<label>-<UTC time>-<state hash prefix>.pubpartner``. A copy is a complete vessel:
to restore, stop the app and copy it over ``pubpartner/vessels/alex.pubpartner``.
"""
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Dict

logger = logging.getLogger("pubpartner.vessel_backup")

HASH_PREFIX_LENGTH = 16


def backup_dir_for(data_dir: Path | str) -> Path:
    return Path(data_dir) / "pubpartner" / "backups" / "vessel"


def backup_vessel_if_changed(store: Any, backup_dir: Path | str, *, label: str = "alex", reason: str = "") -> Dict[str, Any]:
    """Back up ``store`` (a ``VesselStore``) into ``backup_dir`` if its state is not already saved there."""
    started = time.perf_counter()
    try:
        backup_dir = Path(backup_dir)
        check = store.validate()
        state_hash = str(check["state_integrity"]["state_hash"])
        short = state_hash[:HASH_PREFIX_LENGTH]
        existing = sorted(backup_dir.glob(f"{label}-*-{short}.pubpartner")) if backup_dir.is_dir() else []
        if existing:
            return {"ok": True, "changed": False, "reason": reason, "state_hash": state_hash,
                    "latest": str(existing[-1]), "seconds": round(time.perf_counter() - started, 3)}
        stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        target = backup_dir / f"{label}-{stamp}-{short}.pubpartner"
        result = store.backup_to(target)
        if result.get("state_hash") != state_hash:
            # The vessel changed between the check and the copy. The copy is still a valid, newer state; say so.
            logger.info("vessel changed while it was being backed up; the copy holds the newer state")
        logger.info("vessel backup written: %s (%s)", target, reason or "automatic")
        return {"ok": True, "changed": True, "reason": reason, "state_hash": result.get("state_hash", state_hash),
                "path": str(target), "size_bytes": result.get("size_bytes"), "seconds": round(time.perf_counter() - started, 3)}
    except Exception as exc:  # never block startup or shutdown
        logger.error("vessel backup failed (%s): %s", reason or "automatic", exc)
        return {"ok": False, "changed": False, "reason": reason, "error": f"{type(exc).__name__}: {exc}",
                "seconds": round(time.perf_counter() - started, 3)}


__all__ = ["backup_vessel_if_changed", "backup_dir_for", "HASH_PREFIX_LENGTH"]
