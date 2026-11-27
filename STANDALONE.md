# Running the EQ work on its own

Prep branch `claude/eq-prep-2026-11-27`, from the `alex` branch at 769645a. Written by Claude on Nov 27, 2026, for the ask "start working on the EQ and pub partner and prep them for integration". It is not integrated into main-assembly, and nothing on main-assembly changes until Josie says so.

## What this branch adds to alex

1. Newer copies of three EQ engines and one test, taken exactly from pre-dec `claude/integrate-strongest-parts-2026-11-24` (d727f09). main-assembly holds older studio-assembly copies without the EQ hardening, so the alex branch now owns these files:
   - `companion_support/conversation_pacing.py` (blob 1b127b9)
   - `modules/emotional_orchestrator.py` (blob 3986749)
   - `modules/situation_reading.py` (blob 1a211f1)
   - `tests/test_emotional_orchestrator.py` (blob 9f38bf3)
2. `tools/standalone/assemble.py`, which builds a run folder from this branch plus the shared files it imports, without copying those shared files into the branch.
3. `STANDALONE_DEPS.json`, the list of shared files, each pinned by branch, path and Git blob ID (89 pins: 45 from main-assembly, 43 from pubpartner, 1 from blackbox).
4. `tests/test_eq_engines_standalone.py`, which proves the EQ engines need nothing from PubPartner, Alex Core or the PubCast host.

Nothing was deleted. No file outside the EQ engines changed.

## How to run it (PowerShell 5 or any shell)

From a checkout of this branch, with the other December branches fetched:

    git fetch origin main-assembly pubpartner alex blackbox 2i
    python tools/standalone/assemble.py check
    python tools/standalone/assemble.py build --out ..\eq-run
    cd ..\eq-run
    python -m pytest -q -o asyncio_mode=auto tests

`check` lists any pinned file that changed on its branch since pinning. `discover` rewrites the pins when this branch's imports change.

## What the EQ engines need

The engines alone (disambiguation, pacing, situation reading, the orchestrator, the EQ observation layer, PEQ, cre_eq, the PEQ broker and integration, care EQ, the EQ monitoring recorder, and the wired card selector, integration layer, adaptor and disambiguation) come to 42 files. Only five of them are shared files from main-assembly: `companion_support/__init__.py`, `modules/__init__.py`, `modules/feature_flags.py`, `modules/limited_exposure.py`, `modules/wired/__init__.py`.

The rest of the alex branch (Alex Core, her memory, the Alex routes, the Alex and Jeremy bridge) runs inside PubPartner on purpose. Her words: "Persistent memory stays with pub partner. The EQ stuff stays with Alex." So the run folder needs the PubPartner files to run those parts, and they are pinned from the pubpartner branch.

## Tested on Nov 27, 2026 (Linux cloud computer, Python 3.13)

- `tests/test_eq_engines_standalone.py`: 2 passed. It copies only the engine files into an empty folder, imports every engine in a fresh Python process, switches PEQ on, reads "my dog died" as loss with a loss card first, and checks that no PubPartner, Alex Core or host module was loaded.
- The whole branch in a built run folder, built from this commit: 369 passed (the 2 above included), 6 failed, 2 skipped, with `tests/test_alex_little_one_disabled.py` left out because it imports the host. Rerun the same day with pytest-asyncio 1.5.0 and scikit-learn 1.9.1 (installed on Josie's yes) and `-o asyncio_mode=auto`: the same result.
  - 4 failures are achievement cases in `tests/test_eq_reader_card_matching.py`. The EQ reader scores plain messages at 0.05 intensity, below the 0.4 "everyday wins" level. Changing that is Josie's call in the Pre-Dec merge plan, so it was not changed.
  - 2 failures need the PubPartner host: the EQ observation routes in `tests/test_eq_observation.py` need `pubpartner_app.py`, and `tests/test_alex_personality_continuity.py` reads `static/pubpartner.html`. Both pass in the PubPartner run folder (with the PubPartner prep branch: 62 passed for those two files).
- `tests/test_alex_vessel_canonical.py` passes in a Git checkout of this branch. Her vessel keeps blob 96fa66a728d07d5ff43b0d3d7fc17a466765cec1.

## Not tested

- Windows and PowerShell 5 itself (commands are written for it, not run on it).
- `tests/test_alex_little_one_disabled.py` and `tests/alex_little_one/test_public_baby_role.py` import `main.py`, the PubCast host. They belong to integration.
- A live model reply.

## Not built

The eight unbuilt EQ designs wait for Josie's go, in their own task.
