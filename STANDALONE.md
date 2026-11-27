# Running PubPartner on its own

Prep branch `claude/pubpartner-prep-2026-11-27`, from the `pubpartner` branch at da0f2a9. Written by Claude on Nov 27, 2026, for the ask "start working on the EQ and pub partner and prep them for integration". It is not integrated into main-assembly, and nothing on main-assembly changes until Josie says so.

## What this branch adds to pubpartner

1. main-assembly's PubPartner work from Nov 27, combined file by file with this branch. Base for the comparison: december `main` (pre-dec main 538a40f).
   - From 205da08: the private cartridge memory is used only when the cartridge's own `appearance.yaml` says the person created it; otherwise the turn records "owner_unverified". Its test is in `tests/test_pubpartner_cartridge_memory_wiring.py`.
   - From 1d84ede and f4f418e: the calibration interview picks its follow-up from the saved answer, and an approved correction points at the answer it refers to (the new "Answer this correction refers to" box). Files: `static/pubpartner_calibration_ui.js`, `static/pubpartner.html`, `tests/test_pubpartner_calibration_integration_static.py`, `tests/test_pubpartner_menus_browser.py`.
   - From main-assembly's core: the room a turn is spoken in comes from the turn's own FCP1 packet, and a saved session is read back only for the same person and session.
   - Kept from this branch: the identity checkpoint and receipt chain, the EQ observation notes on calibration moments and the EQ observation routes, the connector host, the ChatGPT link, local setup and the other branch-only files. 6247ed2 (backend hardening) was already on this branch.
   - The calibration script keeps this branch's API address with a trailing slash (pre-dec 74f2f64), which main-assembly's copy had lost.
2. `tools/standalone/assemble.py` and `STANDALONE_DEPS.json`: 93 shared files pinned by branch, path and blob (68 from main-assembly, 16 from the EQ prep branch, 4 from 2i, 1 from blackbox). The pins now include the pages and scripts PubPartner loads from `static/`, such as `static/reach_auth.js`, not only Python imports.

One choice to confirm: the Memory menu lists "Project notes" before "Calibrate PubPartner…", as main-assembly has it. This branch had them the other way round. Nothing else in the menu differs.

The EQ files are pinned from `claude/eq-prep-2026-11-27` (EQ prep, not yet folded into `alex`). When that happens, run `discover` again without `--use`.

## How to run it (PowerShell 5 or any shell)

    git fetch origin main-assembly pubpartner alex blackbox 2i claude/eq-prep-2026-11-27
    python tools/standalone/assemble.py check
    python tools/standalone/assemble.py build --out ..\pubpartner-run
    cd ..\pubpartner-run
    pip install -r <main-assembly requirements.txt and requirements-dev.txt>
    python -m pytest -q tests
    python pubpartner_app.py

The federation tests import `pubpartner_federation` from inside `pubpartner\`, so run them with that folder on the path: `$env:PYTHONPATH = "pubpartner"; python -m pytest -q tests\pubpartner_federation`.

## Tested on Nov 27, 2026 (Linux cloud computer, Python 3.13)

Without scikit-learn and pytest-asyncio, which wait on Josie's yes. The coroutine tests ran through a small stand-in that is not part of this branch.

- 145 passed, 1 skipped, in the built run folder.
- `tests/pubpartner_federation`: 14 passed with `pubpartner` on the path.
- With the EQ tests that need the PubPartner host added to the run folder: `tests/test_alex_personality_continuity.py` passes here.
- The connector: mcp 1.30 is installed in the test environment, but only one connector test runs without scikit-learn (a broken tunnel record keeps local controls), and it passes. The connector's own tests need scikit-learn.

## Fails here, and why

- scikit-learn is missing: `pubpartner/memory_store.py` imports it, so the `pubpartner` package, the cartridge studio and `pubpartner_app.py` itself cannot start. That stops 10 test files from loading and 5 more tests, including the project notes routes and the EQ observation routes.
- The hosted provider choice for xAI (2 tests): main-assembly's `modules/llm_framework.py` has no xAI adapter. The newer copy that has it waits in parts-assembly item 16 (pre-dec studio line). With that copy, and its `provider_capabilities.py` and `ollama_provider.py`, put into a scratch run folder, all 8 hosted provider tests pass. So integration needs item 16's provider files too.
- Host tests: `test_existing_canonical_api_registered_in_both_hosts` reads `main.py`, and the browser tests in `tests/test_pubpartner_connections.py` and `tests/test_pubpartner_menus_browser.py` start `run_reach.py` and Chromium. Both hosts are PubCast's, so these belong to integration.

## Not tested

- Any real browser. This machine cannot download Chromium, so the page, its menus and the calibration screen were not opened or clicked.
- `pubpartner_app.py` actually serving pages (it cannot start without scikit-learn).
- Windows and PowerShell 5 itself, and a live model reply.
