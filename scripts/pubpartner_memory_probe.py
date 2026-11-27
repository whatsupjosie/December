"""Persistent-memory restart probe for the packaged application.

Starts the real launcher (``run_pubpartner.py``) twice against one temporary data
folder, the same way a person does, and proves what survives a restart:

  boot 1  save three messages (a fact, an explicit "always..." lesson, a decision),
          check the memory map and the start-up files, then stop the app
  boot 2  open a NEW session and ask about the fact; check that the fact comes back
          into the reply's memories, the lesson comes back as guidance, the vessel
          still holds the lesson as a confirmed claim, no store lost anything, and
          the automatic vessel backups exist and open

It uses the deterministic mock provider (no network, no cost) and a throw-away data
folder, so it never touches your real memories. Run it from the app folder:

    python scripts/pubpartner_memory_probe.py

Exit code 0 means every check passed; each check is printed by name either way.
Reuses the helpers of ``pubpartner_restart_probe.py`` (ports, requests, start/stop).
"""
from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _load_restart_helpers():
    spec = importlib.util.spec_from_file_location("pubpartner_restart_probe", ROOT / "scripts" / "pubpartner_restart_probe.py")
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


helpers = _load_restart_helpers()
FACT = "The Orchid project uses port 4417 for its database."
LESSON = "Always keep answers in plain text from now on."
DECISION = "We decided to use SQLite for Orchid."
QUESTION = "What port does Orchid use for its database?"
PROJECT = "orchid"


def _turn(base: str, token: str, session: str, text: str) -> tuple[int, Dict[str, Any]]:
    return helpers._request(base, "/api/pubpartner/turns/live", method="POST", token=token, payload={
        "user_id": "owner", "session_id": session, "message": text, "provider": {"provider": "mock"},
        "project_id": PROJECT, "room_id": "phone"})


def _store(report: Dict[str, Any], store_id: str) -> Dict[str, Any]:
    return next(s for s in report["stores"] if s["id"] == store_id)


def _backup_claims(path: Path) -> int:
    connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        return int(connection.execute("SELECT COUNT(*) FROM memory_claims").fetchone()[0])
    finally:
        connection.close()


def main() -> int:
    checks: Dict[str, Any] = {}

    def check(name: str, passed: bool, detail: Any = "") -> None:
        checks[name] = {"ok": bool(passed), "detail": detail}

    with tempfile.TemporaryDirectory(prefix="pubpartner_memory_") as tmp:
        data_dir = Path(tmp) / "data"
        log_path = Path(tmp) / "server.log"
        port = helpers._free_port()
        base = f"http://127.0.0.1:{port}"
        password = "Lantern!River9Stone"

        # ── boot 1: save ────────────────────────────────────────────────────────
        first = helpers._start(port, data_dir, log_path)
        try:
            helpers._wait(base, first)
            status, setup = helpers._request(base, "/api/auth/setup", method="POST", payload={
                "username": "owner", "password": password, "confirm_password": password})
            token = str(setup.get("access_token") or "")
            check("boot1_owner_setup", status == 201 and bool(token), status)
            helpers._request(base, "/api/pubpartner/sessions", method="POST", token=token, payload={
                "user_id": "owner", "session_id": "mem-1", "friend": "alex", "provider": "mock",
                "project_id": PROJECT, "room_id": "phone"})
            statuses = [_turn(base, token, "mem-1", text)[0] for text in (FACT, LESSON, DECISION)]
            check("boot1_three_turns_saved", statuses == [200, 200, 200], statuses)
            check("boot1_start_up_status_file", (data_dir / "pubpartner" / "memory_status.json").is_file())
            _, report1 = helpers._request(base, "/api/pubpartner/memory?verify=all", token=token)
            check("boot1_memory_map_ok", report1.get("ok") is True, report1.get("warnings"))
            claims1 = _store(report1, "vessel")["counts"].get("memory_claims", 0)
            jeremy1 = _store(report1, "jeremy")["counts"]["friends"].get("alex", {}).get("memories", 0)
            check("boot1_exact_words_saved", _store(report1, "exact_words")["counts"]["messages"] == 3)
            check("boot1_lesson_became_vessel_claim", claims1 >= 1, claims1)
            check("boot1_jeremy_has_the_messages", jeremy1 >= 3, jeremy1)
        finally:
            helpers._stop(first)

        # ── boot 2: new process, new session ────────────────────────────────────
        second = helpers._start(port, data_dir, log_path)
        try:
            helpers._wait(base, second)
            _, login = helpers._request(base, "/api/auth/login", method="POST", payload={"username": "owner", "password": password})
            token = str(login.get("access_token") or "")
            check("boot2_login", bool(token))
            helpers._request(base, "/api/pubpartner/sessions", method="POST", token=token, payload={
                "user_id": "owner", "session_id": "mem-2", "friend": "alex", "provider": "mock",
                "project_id": PROJECT, "room_id": "phone"})
            status, packet = helpers._request(base, "/api/pubpartner/turns", method="POST", token=token, payload={
                "user_id": "owner", "session_id": "mem-2", "message": QUESTION, "provider": {"provider": "mock"},
                "project_id": PROJECT, "room_id": "phone"})
            fcp = packet.get("fcp1") or {}
            offered = [str(m.get("txt", "")) for m in fcp.get("m") or []]
            guide = [str(g.get("text", "")) for g in fcp.get("guide") or []]
            check("boot2_fact_comes_back_in_new_session", status == 200 and any("4417" in t for t in offered), offered[:3])
            check("boot2_lesson_comes_back_as_guidance", any("plain text" in t for t in guide), guide[:3])
            check("boot2_new_session_has_no_chat_history", fcp.get("history") == [], "expected: history is per session")
            _, claims = helpers._request(base, "/api/pubpartner/vessel/memory/claims?status=all", token=token)
            rows = claims.get("claims") or []
            check("boot2_vessel_claim_survived", any(r.get("status") == "confirmed" for r in rows), len(rows))
            _, report2 = helpers._request(base, "/api/pubpartner/memory?verify=all", token=token)
            check("boot2_memory_map_ok", report2.get("ok") is True, report2.get("warnings"))
            check("boot2_nothing_lost",
                  _store(report2, "vessel")["counts"].get("memory_claims", 0) >= claims1
                  and _store(report2, "exact_words")["counts"]["messages"] >= 3
                  and _store(report2, "jeremy")["counts"]["friends"].get("alex", {}).get("memories", 0) >= jeremy1)
        finally:
            helpers._stop(second)

        # ── backups ─────────────────────────────────────────────────────────────
        copies = sorted((data_dir / "pubpartner" / "backups" / "vessel").glob("alex-*.pubpartner"))
        check("vessel_backups_exist", len(copies) >= 2, [c.name for c in copies])
        if copies:
            from modules.pubpartner_vessel.store import VesselStore

            newest_with_claim = [c for c in copies if _backup_claims(c) >= 1]
            check("a_vessel_backup_holds_the_lesson", bool(newest_with_claim))
            for copy in copies:
                try:
                    VesselStore.open(copy, read_only=True).validate()
                except Exception as exc:  # report, do not crash the probe
                    check(f"backup_opens:{copy.name}", False, str(exc))
                    break
            else:
                check("every_vessel_backup_opens_and_validates", True, len(copies))

        ok = all(item["ok"] for item in checks.values())
        print(json.dumps({"ok": ok, "checks": checks, "data_dir": str(data_dir)}, indent=2))
        if not ok:
            print(log_path.read_text(encoding="utf-8", errors="replace")[-12000:], file=sys.stderr)
        return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
