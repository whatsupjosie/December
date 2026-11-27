# PubPartner persistent-memory tune-up, 2026-11-27

Branch: `claude/pubpartner-memory-tuneup-2026-11-27`, built on `claude/pubpartner-prep-2026-11-27` (188a367).
Her request (Nov 27, scoped to persistent memory first; EQ later): persistent memory "set up and ready to go", know
where memories are saved and how to reach them, save/commit/recall "automatic ... that we don't have to fuck with or
even really think about", "It needs to start on its own", "I want that working."

Everything below says whether it was **run** or only **read**. Linux sandbox only: nothing here was run on Windows.

## 1. Where every memory lives

All paths are inside the data folder (the launcher's `--data-dir`, default `data` next to the app).

| What | Path | Comes back into a reply? |
| --- | --- | --- |
| Her exact words (byte for byte, hash-chained) | `pubpartner/verbatim/<user>/<session>/` | Not searched; each message is also copied into Jeremy, and that copy is recalled |
| Conversation log | `pubpartner/sessions/<user>_<session>_turns.jsonl` | Last four exchanges of the SAME session only |
| Receipts (proof) | `pubpartner/receipts/` | No |
| Lessons she taught ("always...") and encounters | `pubpartner/relationship/<user>/<friend>/` | Yes: confirmed lessons come back as guidance, also in a new session |
| Alex's vessel (memory file) | `pubpartner/vessels/alex.pubpartner` | Confirmed/corroborated claims, events by word overlap. Learns only from explicit lessons |
| Jeremy | `jeremy/<friend>.db` | Yes, ranked by word overlap (see section 5, item 1) |
| Alex's own memory files | `alex/<user>/<month>/mem_*.json` | Yes, offered with Jeremy's |
| Searchable archive (her words and the replies) | `conversation_archive/pubpartner_light.sqlite3` | No (search routes only) |
| Work notes | `pubpartner/work_notes/` | Yes: notes saved for the current project, private turns only. Some can be left out for length; the reply is told how many (`not_shown`) |
| Cartridges | `pubpartner/cartridges/<id>/` | For the person who created the cartridge only; read, not added to |
| Backups | `pubpartner/backups/` (zips on request) and `pubpartner/backups/vessel/` (automatic) | No. Nothing deletes them |

"Cartridge loaded": Alex has no cartridge to load. Her memory is the vessel, which the app mounts (and creates if missing)
at every start. A custom friend's cartridge is read automatically on each private turn for its creator (existing tests
`tests/test_pubpartner_cartridge_memory_wiring.py`, run and passing).

**Alex's real vessel is not in this branch.** The canonical file is `data/pubpartner/vessels/alex.pubpartner` on the `alex`
branch (blob 96fa66a7...). If it is not in the data folder before the first start, the app creates a NEW empty one with
default identity. Read-only look at the canonical file (counts only): 10 identity records, 0 memory events, 0 claims.
See `docs/ALEX_VESSEL_PROTECTION.md` on the `alex` branch.

## 2. How to look (PowerShell 5, from the app folder)

    .\.venv\Scripts\python.exe -m modules.pubpartner_memory_map --data-dir data --verify all

Add `--json` for JSON. Without `--verify` it only counts. It is read-only (see the module's own note: SQLite may create or
touch `-wal`/`-shm` helper files next to a database). Also: `GET /api/pubpartner/memory?verify=all` (owner only), and the
file `pubpartner/memory_status.json`, rewritten at every start.

## 3. What now happens by itself

Start the launcher. Then, with nothing for her to do: dependencies checked; preflight; app starts; Jeremy opens; the vessel is
opened (created if missing); **the vessel is backed up if its state is new** (start and stop; named
`alex-<UTC time>-<state hash prefix>.pubpartner`, same state is never saved twice, nothing is ever deleted); the memory map is
written to `memory_status.json` and logged (problems at ERROR level, including "Jeremy did not open, running WITHOUT it").
Closing the console window kills the app without the stop-time backup; the start-time backup then catches that state.

To restore a vessel: stop the app, keep the current file aside, then copy a backup over it.

    Copy-Item data\pubpartner\vessels\alex.pubpartner data\pubpartner\vessels\alex.before-restore.pubpartner
    Copy-Item data\pubpartner\backups\vessel\<chosen file> data\pubpartner\vessels\alex.pubpartner -Force

## 4. What changed (files)

- `pubpartner_app.py`: 2i folder no longer required to import (it crashed the whole app when absent); start-up backup and
  memory map; stop-time backup.
- `modules/pubpartner_preflight.py`: PubCast `main.py` not required when `PUBPARTNER_ONLY=1` (the launcher sets it).
- `STANDALONE_DEPS.json`, `tools/standalone/assemble.py`: the launchers call `scripts/bootstrap_dependencies.py` and read
  `requirements.txt`; neither existed in a standalone build. Now pinned from `main-assembly` (not copied into this branch),
  and `discover` keeps them.
- `modules/pubpartner_core.py`: a failed receipt, encounter or turn-log write no longer throws away the reply; it is returned
  in `save_errors` and logged. The turn log tolerates a value JSON cannot encode.
- `modules/pubpartner_memory_map.py` (new), `modules/pubpartner_vessel_backup.py` (new), route `GET /api/pubpartner/memory`.
- `tests/test_pubpartner_memory_tuneup.py` (17 tests, one deliberate xfail), `scripts/pubpartner_memory_probe.py`.
- `.gitignore`: two lines (private vessel backups and the memory status file).

## 5. Findings NOT changed, for her decision (both sides)

1. **Recall can lose an early, specific fact.** Jeremy scores a memory by how many words of the message appear in its text
   AND tags (substring match), plus importance, recency and a use-count boost. Every memory is tagged with the project id and
   user id, so a question naming the project ("Orchid") gets no help from that word; "port/database/its" then decide.
   Run through the real spine with 1-second timer off: fact recalled after 90 later similar messages, NOT after 110 or 200;
   with the project named `p` it was still recalled at 200. My filler messages were deliberately similar, so real chats
   will degrade slower; the mechanism is real. The words are still saved exactly. Pinned as an xfail test.
   *For changing it:* the question that matters most to her ("what did we decide about X") is the one that fails.
   *Against:* Jeremy's scoring is her written design ("popular memories surface more"), is a shared file used by Alex Core,
   and ranking changes alter every reply. Options: (A) fix scoring (whole words, rarity weighting, ignore tags/boilerplate,
   cap the use boost); (B) additionally search the archive's full-text index, which ranked this fact first in a test, as a
   second recall channel; (C) leave it. Jeremy lives on another branch, so (A) is a change there, not here.
2. The vessel learns only from explicit lessons; ordinary facts reach Jeremy and the exact-words store, not the vessel.
3. A new session starts with no chat history (by design: history is per session).
4. The current message is stored in Jeremy before recall, so it is recalled as its own memory and uses one of the six slots.
5. `save_errors` is returned and logged but the page does not show it. A banner would need a change to `static/pubpartner.js`.
6. Starting the app on the canonical vessel adds search-index pages (36 to 47) and changes its Git blob; contents unchanged
   (identity 10, events 0, claims 0, audit 11 before and after). The ORIGINAL code does this too (checked), so the commit
   guard in `ALEX_VESSEL_PROTECTION.md` will flag it. Her open question there (separate live and canonical paths) is still open.
7. Automatic backups sit in `data/pubpartner/backups/vessel/`; there is no pruning, so they grow with each new state.
   They are copies of her private vessel, so this branch's `.gitignore` now lists `data/pubpartner/backups/vessel/` and
   `data/pubpartner/memory_status.json` (checked with `git check-ignore`). That covers this program branch only; it does not
   change the `alex` branch or the canonical vessel file.

## 6. Other things noticed, not touched

- `run_pubpartner_windows.ps1` sets `$ErrorActionPreference = "Stop"` and pipes native programs with `2>&1`. In Windows
  PowerShell 5.1 that turns the first line a program writes to stderr (uvicorn logs there) into an error. From knowledge of
  PS 5.1, NOT tested: no PowerShell could be run here. `RUN_PUBPARTNER_WINDOWS.bat` has no such issue (read). Left as is.
- PyJWT is imported by `modules/pubpartner_chatgpt_link.py` (account link only) and is in no requirements file.
- A turn-log row is about 45 KB (13.5 MB after 300 turns); `receipts.append` does not fsync.
- Every third reply pauses one second on purpose (identity checkpoint), not a fault.

## 7. Verification (all run in the Linux sandbox, nothing on GitHub Actions)

Run from a fresh `python tools/standalone/assemble.py build --out <folder>` of the committed tree (167 program files, 95 pinned
shared files, no `2i/` folder):

- Main suite (`python -m pytest tests -q --ignore=tests/pubpartner_federation`): 231 passed, 4 skipped, 1 xfailed, 1 failed.
  The federation tests need `pubpartner/` on the path (`PYTHONPATH=pubpartner python -m pytest tests/pubpartner_federation -q`
  in bash; in PowerShell 5 set `$env:PYTHONPATH = "pubpartner"` first): 14 passed. Together 245 passed.
  The 1 failure is `test_existing_canonical_api_registered_in_both_hosts`, which reads PubCast's `main.py`; it failed the same
  way before any change (baseline 229 passed, 4 skipped, 1 failed).
- `scripts/pubpartner_restart_probe.py` (real launcher, two boots): could not start before (exit 2); passes now.
- `scripts/pubpartner_memory_probe.py` (real launcher, two boots on one data folder, then a new session): 17 of 17 checks pass.
- Memory map against a copy of the canonical vessel: file byte-identical afterwards (the app itself does change it, item 6 above).
- Not run: Windows, PowerShell, a real provider (mock only), a vessel much larger than 200 KB.

Run it yourself (app folder, venv active): `python -m pytest tests -q --ignore=tests\pubpartner_federation` and
`python scripts\pubpartner_memory_probe.py`.
