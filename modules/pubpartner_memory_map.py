"""PubPartner memory map: where every kind of memory lives, and whether it is healthy.

This answers three plain questions: where is each memory saved, how many are
there, and is the store readable. It is read-only: files are opened for reading,
SQLite files are opened with ``mode=ro``, and nothing is created, repaired, moved
or deleted. The one visible side effect is SQLite's own: reading a database that is
in WAL mode can create or touch its small ``-wal`` and ``-shm`` helper files next to
it (they hold no data of their own and SQLite reuses them). Data files are not changed.
(``write_status`` is the only function that writes, and only ``memory_status.json``.)

Use it three ways:

* from the app folder, with no server running:
      python -m modules.pubpartner_memory_map --data-dir data
  Add ``--verify all`` to also re-check every hash chain and the vessel, and
  ``--json`` for machine-readable output.
* from a running app: ``GET /api/pubpartner/memory`` (owner only).
* as a file: the app rewrites ``<data dir>/pubpartner/memory_status.json`` at every start.

Counts come from the stores themselves. ``recalled`` describes, in words, how each
store reaches a reply today; it was checked against the code and a real two-session
test, and it states limits rather than hiding them.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Set, Tuple

FORMAT = "PubPartnerMemoryMap.v1"
STATUS_FILENAME = "memory_status.json"
REPLACE_ATTEMPTS = 6
REPLACE_WAIT_SECONDS = 0.1
VERIFY_CHOICES = ("vessel", "receipts", "verbatim")

# Jeremy memories below this importance are never offered to a reply
# (PubPartnerSpine._jeremy_memories passes min_importance=3).
JEREMY_MIN_IMPORTANCE = 3

VESSEL_TABLES = (
    "identity_records", "entities", "relationships", "memory_events", "memory_claims",
    "memory_evidence", "memory_corrections", "assets", "audit_events",
)


def _utc(ts: Optional[float]) -> Optional[str]:
    if not ts:
        return None
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))


def _rel(data_dir: Path, path: Path) -> str:
    try:
        return path.relative_to(data_dir).as_posix()
    except ValueError:
        return str(path)


def _scan(root: Path, *, suffix: Optional[str] = None, prefix: Optional[str] = None) -> Tuple[int, int, float]:
    """(files, bytes, newest mtime) under root. Symlinks are not followed."""
    files = size = 0
    newest = 0.0
    if not root.is_dir():
        return 0, 0, 0.0
    for base, _dirs, names in os.walk(root):
        for name in names:
            if suffix and not name.endswith(suffix):
                continue
            if prefix and not name.startswith(prefix):
                continue
            try:
                st = os.stat(os.path.join(base, name))
            except OSError:
                continue
            files += 1
            size += st.st_size
            newest = max(newest, st.st_mtime)
    return files, size, newest


def _count_lines(path: Path) -> int:
    rows = 0
    with path.open("rb") as handle:
        for line in handle:
            if line.strip():
                rows += 1
    return rows


def _ro(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=2.0)
    connection.execute("PRAGMA query_only = ON")
    return connection


def _table_counts(path: Path, tables: Iterable[str], problems: List[str]) -> Dict[str, Optional[int]]:
    counts: Dict[str, Optional[int]] = {}
    try:
        connection = _ro(path)
    except sqlite3.Error as exc:
        problems.append(f"cannot open {path.name}: {exc}")
        return {t: None for t in tables}
    try:
        for table in tables:
            try:
                counts[table] = int(connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
            except sqlite3.Error as exc:
                counts[table] = None
                problems.append(f"{path.name}: table {table} unreadable: {exc}")
    finally:
        connection.close()
    return counts


def _grouped(path: Path, table: str, column: str, problems: List[str]) -> Dict[str, int]:
    try:
        connection = _ro(path)
    except sqlite3.Error as exc:
        problems.append(f"cannot open {path.name}: {exc}")
        return {}
    try:
        rows = connection.execute(f'SELECT "{column}", COUNT(*) FROM "{table}" GROUP BY "{column}"').fetchall()
        return {str(k): int(v) for k, v in rows}
    except sqlite3.Error as exc:
        problems.append(f"{path.name}: {table}.{column} unreadable: {exc}")
        return {}
    finally:
        connection.close()


def _entry(store_id: str, label: str, holds: str, recalled: str, path: Path, data_dir: Path) -> Dict[str, Any]:
    return {
        "id": store_id, "label": label, "holds": holds, "recalled": recalled,
        "path": _rel(data_dir, path), "exists": path.exists(),
        "files": 0, "bytes": 0, "last_write": None, "counts": {}, "ok": True, "problems": [],
    }


def _fill_scan(entry: Dict[str, Any], files: int, size: int, newest: float) -> None:
    entry["files"], entry["bytes"], entry["last_write"] = files, size, _utc(newest)


# --------------------------------------------------------------------------- stores

def _exact_words(data_dir: Path, ctx: Dict[str, Any]) -> Dict[str, Any]:
    root = data_dir / "pubpartner" / "verbatim"
    e = _entry("exact_words", "Your exact words", "Every message you send, saved byte for byte with a hash-chained audit row.",
               "Not searched directly. Each message is also written into Jeremy's memory as an event; that copy is what gets recalled.",
               root, data_dir)
    _fill_scan(e, *_scan(root, suffix=".utf8"))
    sessions = sum(1 for _ in root.glob("*/*/audit_hash_chain.jsonl")) if root.is_dir() else 0
    e["counts"] = {"messages": e["files"], "sessions": sessions}
    return e


def _turn_log(data_dir: Path, ctx: Dict[str, Any]) -> Dict[str, Any]:
    root = data_dir / "pubpartner" / "sessions"
    e = _entry("turn_log", "Conversation log", "Every turn with the reply, one file per session (turns are appended and flushed to disk).",
               "The last four exchanges of the SAME session come back as short history. A new session starts with no history; "
               "cross-session recall comes from the other stores.", root, data_dir)
    _fill_scan(e, *_scan(root))
    turns = 0
    if root.is_dir():
        for path in root.glob("*_turns.jsonl"):
            try:
                turns += _count_lines(path)
            except OSError as exc:
                e["problems"].append(f"{path.name}: {exc}")
    e["counts"] = {"sessions": sum(1 for p in root.glob("*.json")) if root.is_dir() else 0, "turns": turns}
    return e


def _receipts(data_dir: Path, ctx: Dict[str, Any]) -> Dict[str, Any]:
    root = data_dir / "pubpartner" / "receipts"
    e = _entry("receipts", "Receipts", "A hash-chained receipt for every reply, as proof of what was said and when.",
               "Proof only. Not recalled.", root, data_dir)
    _fill_scan(e, *_scan(root, suffix=".jsonl"))
    rows = 0
    if root.is_dir():
        for path in root.glob("*.jsonl"):
            try:
                rows += _count_lines(path)
            except OSError as exc:
                e["problems"].append(f"{path.name}: {exc}")
    e["counts"] = {"receipts": rows}
    return e


def _relationship(data_dir: Path, ctx: Dict[str, Any]) -> Dict[str, Any]:
    root = data_dir / "pubpartner" / "relationship"
    e = _entry("relationship", "Lessons and encounters", "What you have explicitly taught a friend (\"always...\", \"from now on...\") plus an encounter log.",
               "Confirmed lessons come back as guidance on every turn, including in a new session (verified for the same project).",
               root, data_dir)
    _fill_scan(e, *_scan(root))
    lessons = encounters = 0
    if root.is_dir():
        for path in root.glob("*/*/lessons.json"):
            try:
                lessons += len(json.loads(path.read_text(encoding="utf-8")).get("lessons") or [])
            except (OSError, ValueError, AttributeError) as exc:
                e["problems"].append(f"{_rel(data_dir, path)}: {exc}")
        for path in root.glob("*/*/encounters.jsonl"):
            try:
                encounters += _count_lines(path)
            except OSError as exc:
                e["problems"].append(f"{_rel(data_dir, path)}: {exc}")
    e["counts"] = {"lessons": lessons, "encounters": encounters}
    return e


def _vessel(data_dir: Path, ctx: Dict[str, Any]) -> Dict[str, Any]:
    path = data_dir / "pubpartner" / "vessels" / "alex.pubpartner"
    e = _entry("vessel", "Alex's vessel (the memory file)", "One SQLite file: identity, people, memory events, claims with evidence and corrections, sealed and audited.",
               "Only claims marked confirmed or corroborated (or approved for proactive use) are recalled; events come back by word overlap. "
               "It learns from explicit lessons, not from ordinary chat.", path, data_dir)
    if not path.is_file():
        # Before the first start there is nothing to report. Once the app says it mounted the vessel, a missing file is a real problem.
        if ctx.get("runtime", {}).get("vessel_mounted"):
            e["problems"].append("the app reports the vessel mounted, but the file does not exist")
        else:
            e["ok"] = None
        return e
    st = path.stat()
    _fill_scan(e, 1, st.st_size, st.st_mtime)
    counts = _table_counts(path, VESSEL_TABLES, e["problems"])
    by_status = _grouped(path, "memory_claims", "status", e["problems"])
    e["counts"] = {**{k: v for k, v in counts.items() if v is not None}, "claims_by_status": by_status}
    if "vessel" in ctx["verify"]:
        try:
            from .pubpartner_vessel.store import VesselStore

            check = VesselStore.open(path, read_only=True).validate()
            e["verified"] = {"ok": True, "audit_entries": check["audit"].get("entries"),
                             "state_hash": check["state_integrity"].get("state_hash"), "schema_version": check["schema_version"]}
        except Exception as exc:  # any failure here is the answer, not a crash
            e["verified"] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
            e["problems"].append(f"vessel failed verification: {exc}")
    return e


def _jeremy(data_dir: Path, ctx: Dict[str, Any]) -> Dict[str, Any]:
    root = data_dir / "jeremy"
    e = _entry("jeremy", "Jeremy's memory", "Short memories per friend (one database file each), including a copy of every message you send.",
               "Ranked by word overlap, importance, recency and how often a memory was used; only importance 3 or higher is offered, "
               "and about six memories per turn are shared across Jeremy, Alex and any cartridge. See the notes at the end: "
               "with many similar memories an early, specific one can stop coming back.", root, data_dir)
    _fill_scan(e, *_scan(root, suffix=".db"))
    per_friend: Dict[str, Dict[str, int]] = {}
    if root.is_dir():
        for db in sorted(root.glob("*.db")):
            counts = _table_counts(db, ("memories",), e["problems"])
            recallable = 0
            try:
                connection = _ro(db)
                try:
                    recallable = int(connection.execute(
                        "SELECT COUNT(*) FROM memories WHERE importance >= ?", (JEREMY_MIN_IMPORTANCE,)).fetchone()[0])
                finally:
                    connection.close()
            except sqlite3.Error as exc:
                e["problems"].append(f"{db.name}: {exc}")
            per_friend[db.stem] = {"memories": counts.get("memories") or 0, "recallable": recallable}
    e["counts"] = {"friends": per_friend}
    if ctx.get("runtime", {}).get("jeremy_open") is False:
        e["ok"] = False
        e["problems"].append("Jeremy memory did not open at startup; the app is running WITHOUT it")
    return e


def _alex_core(data_dir: Path, ctx: Dict[str, Any]) -> Dict[str, Any]:
    root = data_dir / "alex"
    e = _entry("alex_core", "Alex's own memory files", "One small file per remembered moment, grouped by person and month.",
               "Offered to the reply alongside Jeremy's memories (word overlap).", root, data_dir)
    _fill_scan(e, *_scan(root, prefix="mem_", suffix=".json"))
    e["counts"] = {"memories": e["files"]}
    return e


def _archive(data_dir: Path, ctx: Dict[str, Any]) -> Dict[str, Any]:
    path = data_dir / "conversation_archive" / "pubpartner_light.sqlite3"
    e = _entry("archive", "Searchable conversation archive", "Every exchange (your words and the reply) in a full-text searchable database.",
               "Searchable by you through its routes; NOT fed into replies automatically.", path, data_dir)
    if not path.is_file():
        e["ok"] = None
        return e
    st = path.stat()
    _fill_scan(e, 1, st.st_size, st.st_mtime)
    counts = _table_counts(path, ("conversations", "messages"), e["problems"])
    e["counts"] = {k: v for k, v in counts.items() if v is not None}
    return e


def _stones(data_dir: Path, ctx: Dict[str, Any]) -> Dict[str, Any]:
    root = data_dir / "pubpartner" / "stones"
    e = _entry("stones", "Stepping stones (sentence memories)",
               "Each sentence you said in private chat, with who, what, where, when, why and how filled in only from your exact words "
               "(unknown otherwise), plus whether it was said as a fact, a question or a guess, and whether it is lasting or about one day.",
               "Recalled by overlap of words, names, roles and places, rarest overlaps first; each one comes back with a short reason. "
               "Merged with Jeremy's list. Private chats only. Rebuilt from your exact words if this folder is deleted.", root, data_dir)
    if not root.is_dir():
        e["ok"] = None
        return e
    files = sorted(root.glob("*/*.sqlite3"))
    _fill_scan(e, *_scan(root))
    totals: Dict[str, Any] = {"stores": len(files), "sources": 0, "stones": 0, "names": 0}
    for path in files:
        counts = _table_counts(path, ("sources", "stones", "names"), e["problems"])
        for key in ("sources", "stones", "names"):
            totals[key] += counts.get(key) or 0
    sync = ctx["runtime"].get("stones_sync")
    if isinstance(sync, dict):
        totals["start_sync"] = {k: sync[k] for k in ("status", "complete", "ingested", "unverified", "not_private") if k in sync}
    e["counts"] = totals
    return e


def _work_notes(data_dir: Path, ctx: Dict[str, Any]) -> Dict[str, Any]:
    root = data_dir / "pubpartner" / "work_notes"
    e = _entry("work_notes", "Work notes", "Decisions and to-dos caught from conversation. Drafts autosave for a week; saved notes stay.",
               "Offered to the reply when relevant to the project.", root, data_dir)
    _fill_scan(e, *_scan(root, suffix=".sqlite3"))
    by_status: Dict[str, int] = {}
    if root.is_dir():
        for db in sorted(root.glob("*.sqlite3")):
            for status, n in _grouped(db, "notes", "status", e["problems"]).items():
                by_status[status] = by_status.get(status, 0) + n
    e["counts"] = {"notes_by_status": by_status}
    return e


def _cartridges(data_dir: Path, ctx: Dict[str, Any]) -> Dict[str, Any]:
    root = data_dir / "pubpartner" / "cartridges"
    e = _entry("cartridges", "Cartridges", "Characters you made: voice, appearance and seed memories (memories.jsonl) in a portable folder.",
               "A cartridge's memories are offered only to the person who created it (appearance.yaml created_by). "
               "In the app they are read, not added to; new conversation facts go to the other stores.", root, data_dir)
    _fill_scan(e, *_scan(root))
    found: Dict[str, Dict[str, Any]] = {}
    if root.is_dir():
        for folder in sorted(p for p in root.iterdir() if p.is_dir() and not p.name.startswith(".")):
            info: Dict[str, Any] = {"character_yaml": (folder / "character.yaml").is_file()}
            seed = folder / "memories.jsonl"
            try:
                info["seed_memories"] = _count_lines(seed) if seed.is_file() else 0
            except OSError as exc:
                e["problems"].append(f"{_rel(data_dir, seed)}: {exc}")
            db = folder / "memories.db"
            info["memories_db"] = db.is_file()
            if db.is_file():
                info["db_memories"] = _table_counts(db, ("memories",), e["problems"]).get("memories")
            if not info["character_yaml"]:
                e["problems"].append(f"cartridge {folder.name} has no character.yaml")
            found[folder.name] = info
    e["counts"] = {"cartridges": found}
    return e


def _backups(data_dir: Path, ctx: Dict[str, Any]) -> Dict[str, Any]:
    root = data_dir / "pubpartner" / "backups"
    e = _entry("backups", "Backups", "Friend backups (zip, made on request) and automatic vessel backups (made at start and stop when the vessel changed).",
               "Never recalled. Kept for restore. Nothing deletes them.", root, data_dir)
    zips, zip_bytes, zip_new = _scan(root, suffix=".zip") if root.is_dir() else (0, 0, 0.0)
    vessel_dir = root / "vessel"
    vf, vb, vn = _scan(vessel_dir, suffix=".pubpartner")
    e["files"], e["bytes"], e["last_write"] = zips + vf, zip_bytes + vb, _utc(max(zip_new, vn))
    e["counts"] = {"friend_backups": zips, "vessel_backups": vf, "latest_vessel_backup": _utc(vn)}
    return e


COLLECTORS: Tuple[Callable[[Path, Dict[str, Any]], Dict[str, Any]], ...] = (
    _exact_words, _turn_log, _receipts, _relationship, _vessel, _jeremy, _stones, _alex_core, _archive, _work_notes, _cartridges, _backups,
)

NOTES = (
    "Recall limit seen in testing: Jeremy scores a memory by how many words of your message appear in its text and tags. Every memory is "
    "tagged with the project id and your user id, so a question that names your project gets no help from that word; ordinary words "
    "(port, database, its) then decide, and busy memories get a use-count boost. In one test an early fact came back after 90 later "
    "similar messages but not after 110. The fact itself is still saved exactly (exact_words, conversation log, archive).",
    "Since 2026-11-28 a second recall path runs beside Jeremy: stepping stones (sentence memories, recalled by rarity-weighted overlap, "
    "with a reason per memory). Both lists are merged for the reply. Jeremy is unchanged; its limit above still applies to Jeremy's own list.",
)


# --------------------------------------------------------------------------- verification

def _first_row(path: Path) -> Optional[Dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                return json.loads(line)
    return None


def _verify_chains(data_dir: Path, verify: Set[str]) -> Dict[str, Any]:
    """Re-check the receipt and verbatim hash chains of every session on disk. Reads only.

    Sessions are found from the files themselves (each receipt row names its user and
    session; each verbatim folder is one session), so a session that was never
    registered through the session API is still checked.
    """
    result: Dict[str, Any] = {}
    if "receipts" in verify:
        from .pubpartner_receipts import PubPartnerReceiptStore

        root = data_dir / "pubpartner" / "receipts"
        bad: List[Dict[str, Any]] = []
        checked = 0
        if root.is_dir():
            store = PubPartnerReceiptStore(data_dir)
            for path in sorted(root.glob("*.jsonl")):
                try:
                    first = _first_row(path)
                    if first is None:
                        continue
                    user_id, session_id = str(first["user_id"]), str(first["session_id"])
                except (OSError, ValueError, KeyError, TypeError) as exc:
                    checked += 1
                    bad.append({"file": path.name, "error": f"first row unreadable: {type(exc).__name__}: {exc}"})
                    continue
                check = store.verify(user_id=user_id, session_id=session_id)
                checked += 1
                if not check.get("ok"):
                    bad.append({"file": path.name, "error": check.get("error"), "line": check.get("line")})
        result["receipts"] = {"ok": not bad, "sessions_checked": checked, "failures": bad}
    if "verbatim" in verify:
        from .pubpartner_core import VerbatimVault

        vault_root = data_dir / "pubpartner" / "verbatim"
        bad = []
        checked = 0
        if vault_root.is_dir():
            vault = VerbatimVault(data_dir)
            for audit in sorted(vault_root.glob("*/*/audit_hash_chain.jsonl")):
                session_dir = audit.parent
                # Folder names are already safe slugs, so they map back to themselves; this never creates a folder.
                check = vault.verify_session_audit(user_id=session_dir.parent.name, session_id=session_dir.name)
                checked += 1
                if not check.get("ok"):
                    bad.append({"folder": _rel(data_dir, session_dir), "error": check.get("error"), "line": check.get("line")})
        result["verbatim"] = {"ok": not bad, "sessions_checked": checked, "failures": bad}
    return result


# --------------------------------------------------------------------------- public API

def build_memory_map(
    data_dir: Path | str,
    *,
    runtime: Optional[Dict[str, Any]] = None,
    verify: Iterable[str] = (),
) -> Dict[str, Any]:
    """Describe every memory store under ``data_dir``. Read-only; never raises for a bad store."""
    data_dir = Path(data_dir).expanduser().resolve()
    wanted = {verify} if isinstance(verify, str) else set(verify)
    if "all" in wanted:
        wanted = set(VERIFY_CHOICES)
    unknown = wanted - set(VERIFY_CHOICES)
    if unknown:
        raise ValueError(f"unknown verify target(s): {sorted(unknown)}; choose from {list(VERIFY_CHOICES)} or 'all'")
    ctx: Dict[str, Any] = {"runtime": dict(runtime or {}), "verify": wanted}
    stores: List[Dict[str, Any]] = []
    for collect in COLLECTORS:
        try:
            entry = collect(data_dir, ctx)
        except Exception as exc:  # one broken store must not hide the others
            entry = {"id": collect.__name__.lstrip("_"), "label": collect.__name__.lstrip("_"), "ok": False,
                     "problems": [f"could not be read: {type(exc).__name__}: {exc}"], "counts": {}}
        entry["ok"] = False if entry.get("problems") and entry.get("ok") is not None else entry.get("ok")
        stores.append(entry)
    chains: Dict[str, Any] = {}
    try:
        chains = _verify_chains(data_dir, wanted)
    except Exception as exc:
        chains = {"error": f"{type(exc).__name__}: {exc}"}
    warnings: List[str] = []
    for key, text in chains.items():
        if key == "error" or not (isinstance(text, dict) and text.get("ok")):
            warnings.append(f"hash-chain check '{key}' did not pass: {text}")
    state = ctx["runtime"]
    if state.get("vessel_mounted") is False:
        warnings.append("the vessel is not mounted")
    for store in stores:
        for problem in store.get("problems", []):
            warnings.append(f"{store['id']}: {problem}")
    return {
        "format": FORMAT,
        "generated_at": _utc(time.time()),
        "data_dir": str(data_dir),
        "ok": not warnings,
        "verified": sorted(wanted),
        "runtime": state,
        "stores": stores,
        "chains": chains,
        "warnings": warnings,
        "notes": list(NOTES),
        "how_to_access": {
            "command": "python -m modules.pubpartner_memory_map --data-dir <your data folder> --verify all",
            "route": "GET /api/pubpartner/memory?verify=vessel (owner only)",
            "file": "pubpartner/memory_status.json inside the data folder (rewritten at every start)",
        },
    }


def write_status(data_dir: Path | str, report: Dict[str, Any]) -> Path:
    """Atomically write the report next to the data it describes. This is the only write this module makes."""
    target = Path(data_dir).expanduser().resolve() / "pubpartner" / STATUS_FILENAME
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    try:
        # Flush through the handle that wrote it: Windows refuses to flush a handle that cannot write.
        with temporary.open("w", encoding="utf-8") as handle:
            handle.write(json.dumps(report, ensure_ascii=False, indent=2))
            handle.flush()
            os.fsync(handle.fileno())
        # On Windows a reader (antivirus, an editor, Explorer) holding the old file open makes the swap fail for a moment.
        for attempt in range(REPLACE_ATTEMPTS):
            try:
                os.replace(temporary, target)
                break
            except PermissionError:
                if attempt == REPLACE_ATTEMPTS - 1:
                    raise
                time.sleep(REPLACE_WAIT_SECONDS)
    except BaseException:
        try:
            temporary.unlink()
        except OSError:
            pass
        raise
    return target


def _size(n: int) -> str:
    value = float(n)
    for unit in ("bytes", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{int(value)} bytes" if unit == "bytes" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{n} bytes"


def human_summary(report: Dict[str, Any]) -> str:
    lines = [
        "PubPartner Memory Map",
        "=====================",
        f"Overall: {'OK' if report.get('ok') else 'NEEDS ATTENTION'}",
        f"Data folder: {report.get('data_dir')}",
        f"Checked at: {report.get('generated_at')}   Deep checks run: {', '.join(report.get('verified') or []) or 'none (add --verify all)'}",
        "",
    ]
    for store in report.get("stores", []):
        tag = "OK" if store.get("ok") else ("--" if store.get("ok") is None else "PROBLEM")
        where = store.get("path")
        lines.append(f"[{tag}] {store.get('label')}")
        lines.append(f"      where: {where}{'' if store.get('exists', True) else '  (not created yet)'}")
        lines.append(f"      size: {_size(store.get('bytes', 0))} in {store.get('files', 0)} file(s); last written: {store.get('last_write') or 'never'}")
        if store.get("counts"):
            lines.append(f"      counts: {json.dumps(store['counts'], sort_keys=True)}")
        if store.get("verified"):
            lines.append(f"      deep check: {json.dumps(store['verified'], sort_keys=True)}")
        if store.get("recalled"):
            lines.append(f"      how it comes back: {store['recalled']}")
        for problem in store.get("problems", []):
            lines.append(f"      PROBLEM: {problem}")
    for key, value in (report.get("chains") or {}).items():
        lines.append(f"[{'OK' if isinstance(value, dict) and value.get('ok') else 'PROBLEM'}] hash chain check: {key}: {json.dumps(value, sort_keys=True)}")
    if report.get("notes"):
        lines.append("")
        lines.extend(f"NOTE: {n}" for n in report["notes"])
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Show where PubPartner keeps its memories and whether they are healthy (read-only).")
    parser.add_argument("--data-dir", default=os.environ.get("PUBPARTNER_DATA_DIR", "data"))
    parser.add_argument("--verify", action="append", default=[], choices=[*VERIFY_CHOICES, "all"],
                        help="also re-check hash chains / the vessel; repeat or use 'all'")
    parser.add_argument("--json", action="store_true", help="print JSON instead of text")
    parser.add_argument("--write", action="store_true", help="also write pubpartner/memory_status.json")
    args = parser.parse_args(argv)
    _console_never_crashes()
    data_dir = Path(args.data_dir).expanduser()
    if not data_dir.is_dir():
        print(f"No data folder at {data_dir.resolve()}. Pass --data-dir with the folder PubPartner uses.", file=sys.stderr)
        return 2
    report = build_memory_map(data_dir, verify=args.verify)
    if args.write:
        try:
            write_status(data_dir, report)
        except OSError as exc:
            print(f"Could not write the status file: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 2
    # ensure_ascii for the console: a legacy Windows code page cannot show every character in a folder or user name.
    print(json.dumps(report, ensure_ascii=True, indent=2) if args.json else human_summary(report))
    return 0 if report["ok"] else 2


def _console_never_crashes() -> None:
    """A path or name the console's code page cannot show must print as an escape, not stop the report with a traceback."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(errors="backslashreplace")
            except (OSError, ValueError):
                pass


__all__ = ["build_memory_map", "write_status", "human_summary", "main", "FORMAT", "STATUS_FILENAME", "VERIFY_CHOICES"]

if __name__ == "__main__":
    raise SystemExit(main())
