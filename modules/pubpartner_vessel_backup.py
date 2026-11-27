"""Automatic, change-triggered backups of the PubPartner vessel.

The vessel is a single SQLite file and the friend backup (``pubpartner_backup``) does
not include it, so without this the vessel has no copy at all. This module takes a
transaction-consistent copy with the vessel's own ``backup_to`` (which proves the copy is a
sound vessel before it is moved into place) whenever the vessel's sealed state has changed.

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
import os
import sqlite3
import time
import uuid
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
        # The copy is made under a neutral name and renamed once we know which state it really holds. The
        # vessel can change between the check above and the copy; naming it from the check would put the
        # wrong state hash in the file name and make the next start save the same state a second time.
        staging = backup_dir / f"{label}-{stamp}-incoming.pubpartner"
        result = store.backup_to(staging)
        copy_hash = str(result.get("state_hash") or state_hash)
        target = backup_dir / f"{label}-{stamp}-{copy_hash[:HASH_PREFIX_LENGTH]}.pubpartner"
        if target.exists():
            target = backup_dir / f"{label}-{stamp}-{copy_hash[:HASH_PREFIX_LENGTH]}-{uuid.uuid4().hex[:6]}.pubpartner"
        os.replace(staging, target)
        if copy_hash != state_hash:
            logger.info("vessel changed while it was being backed up; the copy holds the newer state")
        logger.info("vessel backup written: %s (%s)", target, reason or "automatic")
        return {"ok": True, "changed": True, "reason": reason, "state_hash": copy_hash,
                "path": str(target), "size_bytes": result.get("size_bytes"), "seconds": round(time.perf_counter() - started, 3)}
    except Exception as exc:  # never block startup or shutdown
        logger.error("vessel backup failed (%s): %s", reason or "automatic", exc)
        return {"ok": False, "changed": False, "reason": reason, "error": f"{type(exc).__name__}: {exc}",
                "seconds": round(time.perf_counter() - started, 3)}


def _file_is_in_use_not_damaged(error: BaseException) -> bool:
    """True when the error means 'busy / not reachable', where overwriting the file with a backup would be wrong."""
    if isinstance(error, PermissionError):
        return True
    text = str(error).lower()
    return isinstance(error, (sqlite3.OperationalError, OSError)) and any(
        word in text for word in ("locked", "busy", "unable to open", "readonly", "read-only", "permission", "in use", "being used"))


def explain_unopenable_vessel(vessel_path: Path | str, backup_dir: Path | str, error: BaseException) -> str:
    """Plain-language recovery note for a vessel that will not open. Never raises; changes nothing on disk.

    The app refuses to start in this case on purpose: starting would let it write over, or
    quietly replace, the one file that holds Alex's confirmed memories. This note says what
    happened and exactly how to put the newest sound backup in place.
    """
    try:
        from modules.pubpartner_vessel import VesselStore  # local import: keep this module importable without the vessel package

        vessel_path, backup_dir = Path(vessel_path), Path(backup_dir)
        if _file_is_in_use_not_damaged(error):
            return "\n".join([
                "PubPartner did NOT start, on purpose: Alex's memory file (the vessel) is in use or cannot be reached right now.",
                f"  File:  {vessel_path}",
                f"  Error: {type(error).__name__}: {error}",
                "  This is NOT a sign the file is damaged. Do not restore a backup over it.",
                "  Most often another PubPartner window is still open on this data folder, or antivirus / a sync tool is holding the file.",
                "  Close every PubPartner window, wait a minute, and start it again. Nothing was changed or deleted.",
            ])
        sound = None
        copies = sorted(backup_dir.glob("*.pubpartner"), reverse=True) if backup_dir.is_dir() else []
        for candidate in copies[:10]:  # newest first; stop at the first that opens and checks out
            try:
                VesselStore.open(candidate, read_only=True)
                sound = candidate
                break
            except Exception:
                continue
        quote = lambda path: "'" + str(path).replace("'", "''") + "'"
        lines = [
            "PubPartner did NOT start, on purpose: Alex's memory file (the vessel) could not be opened.",
            f"  File:  {vessel_path}",
            f"  Error: {type(error).__name__}: {error}",
            "  Nothing was changed or deleted. Starting anyway could write over the only copy of Alex's memories.",
        ]
        if sound is not None:
            lines += [
                f"  Newest backup that opens and checks out: {sound}",
                "  To recover: close PubPartner, then in PowerShell (keeps the damaged file, does not delete it):",
                f"    Copy-Item -LiteralPath {quote(vessel_path)} -Destination {quote(str(vessel_path) + '.damaged')}",
                f"    Copy-Item -LiteralPath {quote(sound)} -Destination {quote(vessel_path)} -Force",
            ]
        else:
            lines += [
                f"  No backup that opens was found in {backup_dir}.",
                "  Restore the vessel from any other copy you kept, keep the damaged file aside, and do not delete it.",
            ]
        return "\n".join(lines)
    except Exception as exc:  # the note itself must never hide the original error
        return f"PubPartner did NOT start: the vessel at {vessel_path} could not be opened ({type(error).__name__}: {error}). Recovery note failed: {exc}"


__all__ = ["backup_vessel_if_changed", "backup_dir_for", "explain_unopenable_vessel", "HASH_PREFIX_LENGTH"]
