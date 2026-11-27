"""Persistent-memory debugging-pass regressions (2026-11-27, second pass).

Every test here pins a defect that was reproduced first and then fixed. Deterministic, temporary
storage, no network, no CI service.

Windows behaviour is EMULATED on Linux (the emulation is from documented Windows behaviour, it is
not a Windows run): a file opened read-only cannot be flushed, and a directory cannot be opened
with os.open.
"""
from __future__ import annotations

import errno
import json
import os
from pathlib import Path

import pytest

from modules import pubpartner_memory_map as memory_map
from modules.pubpartner_vessel import PubPartnerVesselRuntime, VesselStore
from modules.pubpartner_vessel import store as vessel_store_module
from modules.pubpartner_vessel.errors import VesselIntegrityError
from modules.pubpartner_vessel_backup import backup_vessel_if_changed


@pytest.fixture
def emulated_windows(monkeypatch):
    """Make the file calls behave the way Windows does for the two things this code does (Linux/macOS only)."""
    fcntl = pytest.importorskip("fcntl")
    real_fsync, real_open = os.fsync, os.open

    def fsync(fd):
        if (fcntl.fcntl(fd, fcntl.F_GETFL) & os.O_ACCMODE) == os.O_RDONLY:
            raise OSError(errno.EBADF, "Bad file descriptor (emulated Windows read-only flush)")
        return real_fsync(fd)

    def open_(path, flags, *args, **kwargs):
        if os.path.isdir(path):
            raise PermissionError(errno.EACCES, "Permission denied (emulated Windows directory open)", str(path))
        return real_open(path, flags, *args, **kwargs)

    class NtOs:
        name = "nt"

        def __getattr__(self, attribute):
            return getattr(os, attribute)

    monkeypatch.setattr(os, "fsync", fsync)
    monkeypatch.setattr(os, "open", open_)
    monkeypatch.setattr(vessel_store_module, "os", NtOs())


def make_vessel(tmp_path):
    return PubPartnerVesselRuntime.open_or_create(tmp_path / "alex.pubpartner")


# ── a copy is proven sound before it gets its real name ─────────────────────────

def test_a_copy_that_fails_its_check_never_takes_the_real_name_and_does_not_block_the_next_backup(tmp_path, monkeypatch):
    runtime = make_vessel(tmp_path)
    folder = tmp_path / "backups"
    real_validate = VesselStore.validate
    state = {"failed": False}

    def damaged_once(self):
        if self.path.parent == folder and not state["failed"]:
            state["failed"] = True
            raise VesselIntegrityError("simulated damage found in the copy")
        return real_validate(self)

    monkeypatch.setattr(VesselStore, "validate", damaged_once)
    first = backup_vessel_if_changed(runtime.store, folder, reason="t1")
    assert first["ok"] is False and "simulated damage" in first["error"]
    assert list(folder.iterdir()) == [], "a damaged copy must leave nothing behind, not even a temporary file"
    second = backup_vessel_if_changed(runtime.store, folder, reason="t2")
    assert second["ok"] is True and second["changed"] is True, "the next start must try again"
    assert len(list(folder.glob("*.pubpartner"))) == 1


def test_the_file_name_carries_the_state_the_copy_really_holds(tmp_path, monkeypatch):
    """If the vessel changes between the check and the copy, the name must say so, or the next start saves it twice."""
    runtime = make_vessel(tmp_path)
    folder = tmp_path / "backups"
    real_backup_to = VesselStore.backup_to

    def change_then_copy(self, destination):
        self.set_identity("changed_during_backup", "yes")
        return real_backup_to(self, destination)

    monkeypatch.setattr(VesselStore, "backup_to", change_then_copy)
    first = backup_vessel_if_changed(runtime.store, folder, reason="t1")
    monkeypatch.setattr(VesselStore, "backup_to", real_backup_to)
    assert first["ok"] and first["changed"]
    live_hash = runtime.store.validate()["state_integrity"]["state_hash"]
    assert first["state_hash"] == live_hash
    assert Path(first["path"]).name.endswith(f"-{live_hash[:16]}.pubpartner")
    again = backup_vessel_if_changed(runtime.store, folder, reason="t2")
    assert again["changed"] is False, "the same state must not be saved a second time"
    assert len(list(folder.glob("*.pubpartner"))) == 1


# ── Windows file behaviour (emulated) ───────────────────────────────────────────

def test_vessel_backup_works_when_windows_cannot_flush_a_read_only_handle_or_open_a_directory(tmp_path, emulated_windows):
    runtime = make_vessel(tmp_path)
    result = backup_vessel_if_changed(runtime.store, tmp_path / "backups", reason="emulated windows")
    assert result["ok"] is True, result
    assert Path(result["path"]).is_file()
    assert VesselStore.open(result["path"], read_only=True).validate()["state_integrity"]["state_hash"] == result["state_hash"]


def test_memory_status_file_is_written_when_windows_cannot_flush_a_read_only_handle(tmp_path, emulated_windows):
    written = memory_map.write_status(tmp_path, {"ok": True})
    assert written.is_file() and written.read_text(encoding="utf-8").strip().startswith("{")


def test_memory_status_file_swap_survives_a_moment_of_windows_file_locking(tmp_path, monkeypatch):
    real_replace = os.replace
    calls = {"n": 0}

    def locked_twice(source, destination):
        calls["n"] += 1
        if calls["n"] <= 2:
            raise PermissionError(errno.EACCES, "the file is in use by another process (emulated)")
        return real_replace(source, destination)

    monkeypatch.setattr(os, "replace", locked_twice)
    monkeypatch.setattr(memory_map, "REPLACE_WAIT_SECONDS", 0.0)
    written = memory_map.write_status(tmp_path, {"ok": True})
    assert written.is_file() and calls["n"] == 3


def test_memory_status_file_leaves_no_temporary_file_when_the_swap_finally_fails(tmp_path, monkeypatch):
    def always_locked(source, destination):
        raise PermissionError(errno.EACCES, "locked (emulated)")

    monkeypatch.setattr(os, "replace", always_locked)
    monkeypatch.setattr(memory_map, "REPLACE_WAIT_SECONDS", 0.0)
    with pytest.raises(PermissionError):
        memory_map.write_status(tmp_path, {"ok": True})
    assert [p.name for p in (tmp_path / "pubpartner").iterdir()] == []


# ── the report must print on a console that cannot show every character ─────────

@pytest.mark.parametrize("flags", [[], ["--json"]])
def test_memory_map_cli_prints_when_the_data_folder_name_has_characters_the_console_cannot_show(tmp_path, flags):
    import subprocess
    import sys

    folder = tmp_path / "dé→ta"
    (folder / "pubpartner").mkdir(parents=True)
    root = Path(__file__).resolve().parents[1]
    done = subprocess.run([sys.executable, "-m", "modules.pubpartner_memory_map", "--data-dir", str(folder), *flags],
                          cwd=root, capture_output=True, env={**os.environ, "PYTHONIOENCODING": "cp437"})
    assert done.returncode == 0, done.stderr.decode("utf-8", "replace")[-400:]
    assert b"Traceback" not in done.stderr
    assert done.stdout.strip()


# ── a memory store that stops working must not fail silently ────────────────────

@pytest.fixture
def no_identity_pause(monkeypatch):
    import modules.pubpartner_core as core
    real = core.identity_checkpoint
    monkeypatch.setattr(core, "identity_checkpoint", lambda turn, number, **kw: real(turn, number, minimum_seconds=0.0))


async def spine_with_jeremy(root):
    """The app wires Jeremy in at start-up; a bare spine has none, so build it the way the app does."""
    from modules.jeremy_cricket import CricketKeeper
    from modules.pubpartner_core import PubPartnerSpine

    cricket = CricketKeeper(data_dir=root / "jeremy")
    await cricket.init()
    spine = PubPartnerSpine(root, cricket_keeper=cricket)
    assert spine.cricket_keeper is not None
    return spine


@pytest.mark.asyncio
async def test_a_broken_jeremy_is_logged_and_reported_with_the_reply_not_swallowed(tmp_path, monkeypatch, caplog, no_identity_pause):
    spine = await spine_with_jeremy(tmp_path)

    async def broken(*args, **kwargs):
        raise RuntimeError("database is locked (test)")

    monkeypatch.setattr(spine.cricket_keeper, "get", broken)
    base = dict(user_id="u", friend="alex", provider={"provider": "mock"}, project_id="p", room_id="phone")
    with caplog.at_level("ERROR"):
        result = await spine.run_turn(session_id="s", message="Remember that the port is 4417.", **base)
    assert result["friend_response"], "the reply must still come back"
    stages = [(e["stage"], e["error"]) for e in result["save_errors"]]
    assert any(stage == "jeremy" and error.startswith("remember:") and "database is locked" in error for stage, error in stages), stages
    assert any(stage == "jeremy" and error.startswith("recall:") for stage, error in stages), stages
    assert "Jeremy could not save a memory" in caplog.text and "Jeremy could not recall memories" in caplog.text


@pytest.mark.asyncio
async def test_a_working_jeremy_reports_no_problems(tmp_path, no_identity_pause):
    spine = await spine_with_jeremy(tmp_path)
    result = await spine.run_turn(
        session_id="s", message="Hello.", user_id="u", friend="alex", provider={"provider": "mock"}, project_id="p", room_id="phone")
    assert result["save_errors"] == []
    assert result["jeremy_status"] == {"configured": True, "problems": []}


# ── a vessel that will not open: refuse to start, say how to recover ─────────────

def test_unopenable_vessel_note_points_at_the_newest_sound_backup_and_changes_nothing(tmp_path):
    import hashlib
    import shutil
    from modules.pubpartner_vessel_backup import explain_unopenable_vessel

    runtime = make_vessel(tmp_path)
    folder = tmp_path / "backups"
    folder.mkdir()
    sound = folder / "alex-20250101T000000Z-aaaaaaaaaaaaaaaa.pubpartner"
    shutil.copyfile(runtime.store.path, sound)
    unsound = folder / "alex-20260101T000000Z-bbbbbbbbbbbbbbbb.pubpartner"
    unsound.write_bytes(b"not a database " * 50)
    damaged = tmp_path / "damaged.pubpartner"
    damaged.write_bytes(b"also not a database " * 40)
    before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (sound, unsound, damaged)}

    note = explain_unopenable_vessel(damaged, folder, RuntimeError("database disk image is malformed"))

    assert str(sound) in note and str(unsound) not in note, "must skip a newer copy that does not open"
    assert "Copy-Item" in note and "-Force" in note and ".damaged" in note
    assert "database disk image is malformed" in note and "did NOT start" in note
    assert before == {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (sound, unsound, damaged)}, "the note must change nothing"
    assert not (tmp_path / "damaged.pubpartner.damaged").exists()


def test_unopenable_vessel_note_without_any_backup_says_so_and_never_raises(tmp_path):
    from modules.pubpartner_vessel_backup import explain_unopenable_vessel

    note = explain_unopenable_vessel(tmp_path / "alex.pubpartner", tmp_path / "no-such-folder", ValueError("x"))
    assert "No backup that opens was found" in note
    assert "'" in explain_unopenable_vessel(tmp_path / "it's here" / "alex.pubpartner", tmp_path, ValueError("x"))


# ── a crash or power cut in the middle of a write ────────────────────────────────

def test_append_row_starts_a_fresh_line_after_a_torn_row_and_changes_nothing_else(tmp_path):
    from modules.pubpartner_durable import append_row

    log = tmp_path / "log.jsonl"
    append_row(log, '{"n":1}\n')
    log.write_bytes(log.read_bytes() + b'{"n":2,"cut sh')            # power cut: the row was cut short, no newline
    append_row(log, '{"n":3}\n')
    rows = log.read_text(encoding="utf-8").splitlines()
    assert rows[0] == '{"n":1}' and rows[1] == '{"n":2,"cut sh' and rows[2] == '{"n":3}', rows
    append_row(log, '{"n":4}\n')                                      # a clean file gets no extra blank line
    assert log.read_text(encoding="utf-8").splitlines()[-2:] == ['{"n":3}', '{"n":4}']


def test_append_row_works_on_a_new_file_and_an_empty_file(tmp_path):
    from modules.pubpartner_durable import append_row

    append_row(tmp_path / "a.jsonl", "x\n")
    (tmp_path / "b.jsonl").write_bytes(b"")
    append_row(tmp_path / "b.jsonl", "y\n")
    assert (tmp_path / "a.jsonl").read_text() == "x\n" and (tmp_path / "b.jsonl").read_text() == "y\n"


@pytest.mark.asyncio
async def test_the_turn_after_a_torn_turn_log_row_is_not_lost(tmp_path, no_identity_pause):
    from modules.pubpartner_core import PubPartnerSpine

    base = dict(user_id="u", friend="alex", provider={"provider": "mock"}, project_id="p", room_id="phone")
    spine = PubPartnerSpine(tmp_path)
    for i in range(3):
        await spine.run_turn(session_id="s", message=f"before the crash {i}", **base)
    log = next((tmp_path / "pubpartner" / "sessions").glob("*_turns.jsonl"))
    log.write_bytes(log.read_bytes()[:-37])                              # the last row is cut short
    await PubPartnerSpine(tmp_path).run_turn(session_id="s", message="after the crash", **base)

    def readable(line):
        try:
            json.loads(line)
            return True
        except ValueError:
            return False

    rows = [l for l in log.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert sum(readable(r) for r in rows) == 3, "two intact old rows plus the new one"
    assert sum(not readable(r) for r in rows) == 1, "only the torn row stays unreadable"
    assert "after the crash" in rows[-1]


@pytest.mark.asyncio
async def test_each_memory_file_is_flushed_to_disk_before_the_turn_returns(tmp_path, monkeypatch, no_identity_pause):
    """Exact words, their audit row, the receipt and the turn log must all be flushed, not left in the OS cache."""
    from modules import pubpartner_durable
    from modules.pubpartner_core import PubPartnerSpine

    if not Path("/proc/self/fd").exists():
        pytest.skip("needs /proc to name the flushed files")
    flushed = []
    real = os.fsync

    def recording(fd):
        flushed.append(Path(os.readlink(f"/proc/self/fd/{fd}")).name)
        return real(fd)

    monkeypatch.setattr(pubpartner_durable.os, "fsync", recording)
    await PubPartnerSpine(tmp_path).run_turn(
        session_id="s", message="Flush me.", user_id="u", friend="alex", provider={"provider": "mock"}, project_id="p", room_id="phone")
    joined = " ".join(flushed)
    assert ".utf8.tmp" in joined, flushed
    assert ".json.tmp" in joined, flushed
    assert "audit_hash_chain.jsonl" in flushed, flushed
    assert "u_s.jsonl" in flushed, flushed
    assert any(name.endswith("_turns.jsonl") for name in flushed), flushed


def test_a_vessel_that_is_only_locked_is_never_described_as_damaged(tmp_path):
    """Advice to copy a backup over a healthy file that is merely in use by a second window would destroy newer memories."""
    import shutil
    import sqlite3
    from modules.pubpartner_vessel_backup import explain_unopenable_vessel

    runtime = make_vessel(tmp_path)
    folder = tmp_path / "backups"
    folder.mkdir()
    shutil.copyfile(runtime.store.path, folder / "alex-20250101T000000Z-aaaaaaaaaaaaaaaa.pubpartner")
    for error in (sqlite3.OperationalError("database is locked"), PermissionError(13, "Permission denied"),
                  sqlite3.OperationalError("unable to open database file")):
        note = explain_unopenable_vessel(runtime.store.path, folder, error)
        assert "NOT a sign the file is damaged" in note, note
        assert "Copy-Item" not in note and "-Force" not in note, "no restore command for a file that is only in use"
    damaged = explain_unopenable_vessel(runtime.store.path, folder, sqlite3.DatabaseError("database disk image is malformed"))
    assert "Copy-Item" in damaged, "real damage still gets the recovery steps"


# ── characters json.dumps leaves unescaped must not tear a log row ───────────────

SEPARATORS = [" ", " ", "\x85", "\x0b", "\x0c", "\x1c", "\x1d", "\x1e"]


@pytest.mark.asyncio
@pytest.mark.parametrize("separator", SEPARATORS, ids=[f"U+{ord(c):04X}" for c in SEPARATORS])
async def test_a_message_holding_a_line_separator_character_keeps_every_log_whole(tmp_path, separator, no_identity_pause):
    """str.splitlines() cuts at these characters, tearing a row whose text holds one into pieces that were reported as unreadable."""
    from modules.pubpartner_backup import create_friend_backup
    from modules.pubpartner_core import PubPartnerSpine

    base = dict(user_id="u", friend="alex", provider={"provider": "mock"}, project_id="p", room_id="phone")
    spine = PubPartnerSpine(tmp_path)
    await spine.create_session(user_id="u", session_id="s", project_id="p", room_id="phone", friend={"id": "alex"}, provider={"provider": "mock"})
    await spine.run_turn(session_id="s", message=f"copied from a web page{separator}with a hidden separator", **base)
    await spine.run_turn(session_id="s", message="a plain follow-up", **base)

    turns = spine.list_turns(user_id="u", session_id="s", limit=50)["turns"]
    assert len(turns) == 2 and not [t for t in turns if set(t) == {"error"}], turns
    assert spine.verify_receipts(user_id="u", session_id="s")["ok"] is True
    assert spine.relationship.verify_encounters(user_id="u", friend_id="alex")["ok"] is True
    encounters = spine.relationship.list_encounters(user_id="u", friend_id="alex")["encounters"]
    assert not [e for e in encounters if set(e) == {"error"}], encounters
    assert spine.vault.verify_session_audit(user_id="u", session_id="s")["ok"] is True
    backup = create_friend_backup(tmp_path, user_id="u", friend_id="alex")
    assert backup["ok"]
    import zipfile
    names = zipfile.ZipFile(backup["path"]).namelist()
    assert any(name.endswith("u_s_turns.jsonl") for name in names), "the session's turn log must be in the friend backup"


# ── a long session must not make every turn slower ───────────────────────────────

def test_tail_lines_matches_reading_the_whole_file(tmp_path):
    """Compared against the old way (read everything, split on newline, drop blanks, keep the last few) on awkward files."""
    import random
    from modules.pubpartner_durable import tail_lines

    rng = random.Random(7)
    for trial in range(60):
        rows = []
        for i in range(rng.randint(0, 120)):
            kind = rng.random()
            if kind < 0.1:
                rows.append("")                                              # a blank line
            elif kind < 0.2:
                rows.append("{\"torn\": \"" + "é" * rng.randint(1, 30))         # a row cut short, with multi-byte text
            else:
                rows.append(json.dumps({"i": i, "t": "x" * rng.randint(0, 400) + " é💥"}, ensure_ascii=False))
        text = "\n".join(rows) + ("\n" if rng.random() < 0.7 else "")
        path = tmp_path / f"t{trial}.jsonl"
        path.write_bytes(text.encode("utf-8"))
        for count in (1, 3, 40, 500):
            expected = [line for line in text.split("\n") if line.strip()][-count:]
            assert tail_lines(path, count, block_size=rng.choice((16, 100, 4096))) == expected, (trial, count)


@pytest.mark.asyncio
async def test_listing_the_last_turns_does_not_parse_the_whole_log(tmp_path, monkeypatch, no_identity_pause):
    from modules.pubpartner_core import PubPartnerSpine

    base = dict(user_id="u", friend="alex", provider={"provider": "mock"}, project_id="p", room_id="phone")
    spine = PubPartnerSpine(tmp_path)
    for i in range(60):
        await spine.run_turn(session_id="s", message=f"message {i}", **base)
    parsed = {"n": 0}
    real_loads = json.loads

    def counting(text, *args, **kwargs):
        parsed["n"] += 1
        return real_loads(text, *args, **kwargs)

    monkeypatch.setattr(json, "loads", counting)
    turns = spine.list_turns(user_id="u", session_id="s", limit=5)["turns"]
    assert len(turns) == 5 and turns[-1]["source"]["id"]
    assert parsed["n"] == 5, f"only the 5 rows asked for may be parsed, not all 60 (parsed {parsed['n']})"
