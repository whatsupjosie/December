"""Persistent-memory tune-up regressions (2026-11-27).

Deterministic mock provider, temporary storage, no network, no CI service.
Covers: the reply surviving a failed save, the read-only memory map, the automatic
vessel backup, the standalone start-up fixes, and the recall scenario that failed on
2026-11-27 (an early specific fact lost after many similar messages). That scenario was a
strict xfail until stepping stones (2026-11-28, modules/pubpartner_stones.py) fixed it; it is
now an ordinary test.
"""
from __future__ import annotations

import json
import random
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import modules.pubpartner_core as core
from modules.pubpartner_core import PubPartnerSpine
from modules.pubpartner_memory_map import build_memory_map, human_summary, main as memory_map_main
from modules.pubpartner_preflight import run_preflight
from modules.pubpartner_vessel import PubPartnerVesselRuntime
from modules.pubpartner_vessel_backup import backup_vessel_if_changed

ROOT = Path(__file__).resolve().parents[1]
BASE = dict(user_id="u", friend="alex", provider={"provider": "mock"}, project_id="p", room_id="phone")
STORE_IDS = ["exact_words", "turn_log", "receipts", "relationship", "vessel", "jeremy", "stones",
             "alex_core", "archive", "work_notes", "cartridges", "backups"]


@pytest.fixture(autouse=True)
def no_identity_pause(monkeypatch):
    """The identity checkpoint deliberately pauses a second on every third reply; tests skip the wait."""
    real = core.identity_checkpoint
    monkeypatch.setattr(core, "identity_checkpoint", lambda turn, number, **kw: real(turn, number, minimum_seconds=0.0))


async def one_turn(spine, text="Hello there.", session="s"):
    return await spine.run_turn(session_id=session, message=text, **BASE)


def snapshot(root: Path):
    """Files (size, mtime) and folders, ignoring SQLite's own -wal/-shm helper files, which a reader may create or touch."""
    files = {str(p.relative_to(root)): (p.stat().st_size, p.stat().st_mtime_ns)
             for p in root.rglob("*") if p.is_file() and not p.name.endswith(("-shm", "-wal"))}
    dirs = {str(p.relative_to(root)) for p in root.rglob("*") if p.is_dir()}
    return files, dirs


# ── the reply survives a failed save ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_clean_turn_reports_no_save_errors(tmp_path):
    result = await one_turn(PubPartnerSpine(tmp_path))
    assert result["save_errors"] == []
    assert result["receipt_chain"]["ok"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize("target, stage", [
    ("receipts.append", "receipt"),
    ("relationship.record_encounter", "relationship_encounter"),
    ("_append_turn", "turn_log"),
])
async def test_failed_save_keeps_the_reply(tmp_path, monkeypatch, target, stage):
    spine = PubPartnerSpine(tmp_path)
    owner, _, name = target.rpartition(".")
    obj = getattr(spine, owner) if owner else spine

    def boom(*args, **kwargs):
        raise OSError("disk full (test)")

    monkeypatch.setattr(obj, name, boom)
    result = await one_turn(spine)
    assert result["friend_response"], "the paid-for reply must still be returned"
    assert [e["stage"] for e in result["save_errors"]] == [stage]
    assert "disk full" in result["save_errors"][0]["error"]
    if stage == "receipt":
        assert result["receipt_chain"]["ok"] is False
    logs = list(tmp_path.glob("pubpartner/sessions/*_turns.jsonl"))
    if stage == "turn_log":
        assert not logs or logs[0].read_text(encoding="utf-8") == ""
    else:
        assert len(logs) == 1 and len(logs[0].read_text(encoding="utf-8").splitlines()) == 1
    # The exact words were stored before the reply was generated, whatever failed afterwards.
    assert len(list(tmp_path.glob("pubpartner/verbatim/*/*/*.utf8"))) == 1


def test_turn_log_row_survives_a_value_json_cannot_encode(tmp_path):
    spine = PubPartnerSpine(tmp_path)
    spine._append_turn("u", "s", {"turn_id": "t1", "odd": Path("x"), "fcp1": {}})
    rows = next(tmp_path.glob("pubpartner/sessions/*_turns.jsonl")).read_text(encoding="utf-8").splitlines()
    assert json.loads(rows[0])["turn_id"] == "t1"


# ── the memory map ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_memory_map_lists_every_store_counts_and_verifies_chains(tmp_path):
    await one_turn(PubPartnerSpine(tmp_path), "Remember that the Orchid project uses port 4417.")
    report = build_memory_map(tmp_path, verify="all")
    assert [s["id"] for s in report["stores"]] == STORE_IDS
    by = {s["id"]: s for s in report["stores"]}
    assert by["exact_words"]["counts"]["messages"] == 1
    assert by["turn_log"]["counts"]["turns"] == 1
    assert by["receipts"]["counts"]["receipts"] == 1
    assert report["chains"]["receipts"] == {"ok": True, "sessions_checked": 1, "failures": []}
    assert report["chains"]["verbatim"] == {"ok": True, "sessions_checked": 1, "failures": []}
    assert report["ok"], report["warnings"]
    assert "Your exact words" in human_summary(report)


@pytest.mark.asyncio
async def test_memory_map_is_read_only(tmp_path):
    await one_turn(PubPartnerSpine(tmp_path))
    before = snapshot(tmp_path)
    build_memory_map(tmp_path, verify="all")
    assert snapshot(tmp_path) == before


@pytest.mark.asyncio
async def test_memory_map_catches_a_tampered_receipt(tmp_path, capsys):
    await one_turn(PubPartnerSpine(tmp_path))
    path = next(tmp_path.glob("pubpartner/receipts/*.jsonl"))
    row = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    row["ts"] = 1.0
    path.write_text(json.dumps(row) + "\n", encoding="utf-8")
    report = build_memory_map(tmp_path, verify="receipts")
    assert report["chains"]["receipts"]["ok"] is False and report["ok"] is False
    assert memory_map_main(["--data-dir", str(tmp_path), "--verify", "receipts"]) == 2


def test_memory_map_cli_ok_and_missing_folder(tmp_path, capsys):
    assert memory_map_main(["--data-dir", str(tmp_path)]) == 0
    assert "PubPartner Memory Map" in capsys.readouterr().out
    assert memory_map_main(["--data-dir", str(tmp_path / "nope")]) == 2
    with pytest.raises(ValueError):
        build_memory_map(tmp_path, verify=["bogus"])


def test_memory_map_reports_a_jeremy_that_did_not_open_and_a_missing_vessel(tmp_path):
    report = build_memory_map(tmp_path, runtime={"jeremy_open": False, "vessel_mounted": True})
    by = {s["id"]: s for s in report["stores"]}
    assert by["jeremy"]["ok"] is False and any("WITHOUT" in p for p in by["jeremy"]["problems"])
    assert by["vessel"]["ok"] is False
    assert report["ok"] is False


def test_memory_map_reads_and_verifies_the_vessel_and_flags_damage(tmp_path):
    path = tmp_path / "pubpartner" / "vessels" / "alex.pubpartner"
    PubPartnerVesselRuntime.open_or_create(path)
    report = build_memory_map(tmp_path, verify="vessel", runtime={"vessel_mounted": True})
    vessel = {s["id"]: s for s in report["stores"]}["vessel"]
    assert vessel["verified"]["ok"] is True and vessel["counts"]["identity_records"] > 0
    assert report["ok"], report["warnings"]
    path.write_bytes(path.read_bytes()[:100])
    damaged = build_memory_map(tmp_path, verify="vessel", runtime={"vessel_mounted": True})
    assert damaged["ok"] is False


# ── automatic vessel backup ─────────────────────────────────────────────────────

def test_vessel_backup_only_when_changed_and_never_deletes(tmp_path):
    runtime = PubPartnerVesselRuntime.open_or_create(tmp_path / "alex.pubpartner")
    folder = tmp_path / "backups"
    first = backup_vessel_if_changed(runtime.store, folder, reason="t1")
    assert first["ok"] and first["changed"] is True and Path(first["path"]).is_file()
    again = backup_vessel_if_changed(runtime.store, folder, reason="t2")
    assert again["ok"] and again["changed"] is False
    assert len(list(folder.glob("*.pubpartner"))) == 1
    runtime.store.set_identity("tune_up_test_key", "changed")
    third = backup_vessel_if_changed(runtime.store, folder, reason="t3")
    assert third["ok"] and third["changed"] is True
    kept = sorted(folder.glob("*.pubpartner"))
    assert len(kept) == 2 and Path(first["path"]) in kept, "an earlier copy must stay"


def test_vessel_backup_failure_is_reported_not_raised(tmp_path):
    class Broken:
        def validate(self):
            raise RuntimeError("cannot read vessel (test)")

    result = backup_vessel_if_changed(Broken(), tmp_path / "backups", reason="t")
    assert result["ok"] is False and "cannot read vessel" in result["error"]


# ── standalone start-up ─────────────────────────────────────────────────────────

def test_preflight_does_not_require_pubcast_main_in_a_pubpartner_only_run(tmp_path, monkeypatch):
    def main_check():
        report = run_preflight(data_dir=tmp_path / "data", app_root=tmp_path / "empty-app")
        return next(c for c in report["checks"] if c["name"] == "file:main.py")

    monkeypatch.setenv("PUBPARTNER_ONLY", "1")
    assert main_check()["ok"] is True
    monkeypatch.delenv("PUBPARTNER_ONLY", raising=False)
    assert main_check()["ok"] is False


def test_launchers_only_call_scripts_that_exist_or_are_pinned():
    manifest = json.loads((ROOT / "STANDALONE_DEPS.json").read_text(encoding="utf-8"))
    pinned = {p["path"] for p in manifest["pins"]}
    called = set()
    for name in ("RUN_PUBPARTNER_WINDOWS.bat", "run_pubpartner_windows.ps1", "run_pubpartner_mac_linux.sh"):
        for match in re.findall(r"scripts[\\/]+([A-Za-z0-9_]+\.py)", (ROOT / name).read_text(encoding="utf-8")):
            called.add("scripts/" + match)
    assert called, "launchers should call at least the dependency bootstrap"
    for path in sorted(called | {"requirements.txt"}):
        assert (ROOT / path).is_file() or path in pinned, f"{path} is neither in the folder nor pinned"


def test_app_starts_without_2i_writes_memory_status_and_backs_up_once(tmp_path, monkeypatch):
    import pubpartner_app

    monkeypatch.setattr(pubpartner_app, "DATA_DIR", tmp_path)
    monkeypatch.setattr(pubpartner_app, "TWOI_DIR", tmp_path / "no-2i")
    monkeypatch.setenv("PUBCAST_ENFORCE_AUTH", "0")
    headers = {"X-Client-Id": "owner"}
    copies = lambda: sorted((tmp_path / "pubpartner" / "backups" / "vessel").glob("alex-*.pubpartner"))  # noqa: E731
    with TestClient(pubpartner_app.app) as client:
        assert client.get("/2i", headers=headers).status_code == 404
        status = json.loads((tmp_path / "pubpartner" / "memory_status.json").read_text(encoding="utf-8"))
        assert status["format"] == "PubPartnerMemoryMap.v1" and status["ok"], status["warnings"]
        assert len(copies()) == 1
        response = client.get("/api/pubpartner/memory", params={"verify": "all"}, headers=headers)
        assert response.status_code == 200 and response.json()["ok"] is True
        assert client.get("/api/pubpartner/memory", params={"verify": "bogus"}, headers=headers).status_code == 400
    with TestClient(pubpartner_app.app):
        pass
    assert len(copies()) == 1, "a restart with nothing new must not make another copy"


# ── known problem waiting for the owner's decision ──────────────────────────────

@pytest.mark.asyncio
async def test_early_specific_fact_is_still_recalled_after_many_similar_messages(tmp_path):
    from modules.jeremy_cricket import CricketKeeper

    keeper = CricketKeeper(data_dir=tmp_path / "jeremy")
    await keeper.init()
    try:
        spine = PubPartnerSpine(tmp_path, cricket_keeper=keeper)
        base = {**BASE, "project_id": "orchid"}  # a project named for its subject, as in real use

        async def say(text, session):
            return await spine.run_turn(session_id=session, message=text, **base)

        await say("The Orchid project uses port 4417 for its database.", "s1")
        rng = random.Random(7)
        projects = ["Magnolia", "Juniper", "Saffron", "Cobalt", "Willow", "Harbor", "Lantern", "Pebble"]
        things = ["database", "cache", "queue", "dashboard", "scheduler", "gateway"]
        verbs = ["uses port", "listens on port", "is deployed on port", "runs behind port"]
        for i in range(1, 121):
            await say(f"The {rng.choice(projects)} project {rng.choice(verbs)} {rng.randint(1000, 9999)} "
                      f"for its {rng.choice(things)}. Note {i}.", "s3")
        packet = await spine.build_turn_packet(session_id="s4", message="What port does Orchid use for its database?", **base)
        offered = [m.get("txt", "") for m in (packet.get("fcp1") or {}).get("m") or []]
        assert any("4417" in text for text in offered)
    finally:
        await keeper.close_all()
