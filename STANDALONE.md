# Running PubPartner on its own

Prep branch `claude/pubpartner-prep-2026-11-27`, from the `pubpartner` branch at da0f2a9. Written by Claude on Nov 27, 2026, for the ask "start working on the EQ and pub partner and prep them for integration". It is not integrated into main-assembly, and nothing on main-assembly changes until Josie says so.

## What this branch adds to pubpartner

1. main-assembly's PubPartner work from Nov 27, combined file by file with this branch. Base for the comparison: december `main` (pre-dec main 538a40f).
   - From 205da08: the private cartridge memory is used only when the cartridge's own `appearance.yaml` says the person created it; otherwise the turn records "owner_unverified". Its test is in `tests/test_pubpartner_cartridge_memory_wiring.py`.
   - From 1d84ede and f4f418e: the calibration interview picks its follow-up from the saved answer, and an approved correction points at the answer it refers to (the new "Answer this correction refers to" box). Files: `static/pubpartner_calibration_ui.js`, `static/pubpartner.html`, `tests/test_pubpartner_calibration_integration_static.py`, `tests/test_pubpartner_menus_browser.py`.
   - From main-assembly's core: the room a turn is spoken in comes from the turn's own FCP1 packet, and a saved session is read back only for the same person and session.
   - Kept from this branch: the identity checkpoint and receipt chain, the EQ observation notes on calibration moments and the EQ observation routes, the connector host, the ChatGPT link, local setup and the other branch-only files. 6247ed2 (backend hardening) was already on this branch.
   - The calibration script keeps this branch's API address with a trailing slash (pre-dec 74f2f64), which main-assembly's copy had lost.
2. `tools/standalone/assemble.py` and `STANDALONE_DEPS.json`: 181 shared files pinned by branch, path and blob (91 from 2i, 73 from main-assembly, 16 from the EQ prep branch, 1 from blackbox). The pins include the pages and scripts PubPartner loads from `static/`, such as `static/reach_auth.js`, and two things it reaches by path: the `2i/2i-assets` folder the host mounts, and the test model `static/world/test_avatars/Xbot.glb` (listed under "includes").

One choice to confirm: the Memory menu lists "Project notes" before "Calibrate PubPartner…", as main-assembly has it. This branch had them the other way round. Nothing else in the menu differs.

The EQ files are pinned from `claude/eq-prep-2026-11-27` (EQ prep, not yet folded into `alex`). When that happens, run `discover` again without `--use`.

## How to run it (PowerShell 5 or any shell)

    git fetch origin main-assembly pubpartner alex blackbox 2i claude/eq-prep-2026-11-27
    python tools/standalone/assemble.py check
    python tools/standalone/assemble.py build --out ..\pubpartner-run
    cd ..\pubpartner-run
    pip install -r <main-assembly requirements.txt and requirements-dev.txt>
    python -m pytest -q -o asyncio_mode=auto tests
    python pubpartner_app.py

The federation tests import `pubpartner_federation` from inside `pubpartner\`, so run them with that folder on the path: `$env:PYTHONPATH = "pubpartner"; python -m pytest -q tests\pubpartner_federation`.

## Tested on Nov 27, 2026 (Linux cloud computer, Python 3.13)

With scikit-learn 1.9.1 and pytest-asyncio 1.5.0 installed on Josie's yes, and mcp 1.30.0 for the connector. Run with `-o asyncio_mode=auto`, as main-assembly's pytest.ini sets it.

- 246 passed, 1 skipped, in the built run folder.
- `tests/pubpartner_federation`: 14 passed with `pubpartner` on the path.
- The EQ tests that need the PubPartner host (`tests/test_eq_observation.py`, `tests/test_alex_personality_continuity.py`, from the EQ prep branch): 62 passed here.
- `pubpartner_app.py` started on its own (uvicorn, empty data folder). `/pubpartner`, its script, style sheet, calibration script and `reach_auth.js`, `/2i/chat`, `/2i/chat/archive` and the avatar import page all answered 200, and every script and style sheet those pages name answered 200, including the three.js files the avatar import loads. With no account set up yet, the host reports itself in relaxed development mode, as its first-run setup is designed.

## Fails here, and why

- The hosted provider choice for xAI (2 tests): main-assembly's `modules/llm_framework.py` has no xAI adapter. The newer copy that has it waits in parts-assembly item 16 (pre-dec studio line). With that copy, and its `provider_capabilities.py` and `ollama_provider.py`, put into a scratch run folder, all 8 hosted provider tests pass. So integration needs item 16's provider files too.
- Host tests (10): `test_existing_canonical_api_registered_in_both_hosts` reads `main.py`; the browser tests in `tests/test_pubpartner_connections.py`, `tests/test_pubpartner_menus_browser.py` and the cartridge restart test in `tests/test_pubpartner_cartridges.py` start `run_reach.py` and Chromium. Both hosts are PubCast's, so these belong to integration.

## Not tested

- Any real browser. This machine cannot download Chromium, so the page, its menus and the calibration screen were served but not opened or clicked.
- Windows and PowerShell 5 itself, and a live model reply.
