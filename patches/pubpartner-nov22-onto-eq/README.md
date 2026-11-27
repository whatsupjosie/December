# PubPartner Nov 22 commits, rebuilt on the EQ foundations branch (Nov 27, 2026)

## What was asked

Josie said yes on Nov 27 to bringing "the last two Nov 22 commits onto the EQ foundations branch" (her reply: "Well that's definitely do number three now"). This folder parks the result in parts-assembly. It is parking, not integration: nothing here is installed into main or main-assembly.

## Where it lives

- pre-dec branch `claude/pubpartner-nov22-onto-eq-2026-11-27`, tip `04c8774`, started from pre-dec `claude/eq-foundations-2026-11-23` at `5ef002f`.
- Commit `cf722dc` is Beyond-October `6cba39b` (cartridge, avatar, guidance and resumed-session provider wiring).
- Commit `04c8774` is Beyond-October `7fd1fea` (the owner's cartridge memories in hosted private turns).
- Both were committed as Claude. Each message records the original commit id and how its clash was resolved.

## Why this base

- The EQ foundations branch sits on pre-dec `claude/studio-assembly-2026-11-23`, which already carries the third Nov 22 commit, calibration (Beyond-October `0dab95f`), as pre-dec `11ed0f2`. That copy leaves out Beyond-October's GitHub Actions file, `.github/workflows/pubpartner-calibration.yml`. That file is still not brought in.
- On this base only `modules/pubpartner_core.py` clashed, in two places. On pre-dec main all three commits would be needed, and they clash in three files.
- The EQ branch itself is not merged into pre-dec main.

## How the two clashes were resolved

1. `run_turn`, provider dispatch. The EQ branch records a Blackbox witness event when a turn starts, and another if dispatch fails. Beyond-October looks up a resumed session's saved provider settings when the turn sends none. Both were kept. The lookup now runs inside the witnessed block, so a resumed session uses its saved provider, and a failure during the lookup is still recorded as a failed turn.
2. `build_turn_packet`. The project notes block (saved notes only, private turns only) and the owner's cartridge memory recall were both added at the same spot. Both were kept unchanged, notes first. Cartridge memories go ahead of the other recalled memories, within the same `max_memories` limit.

## What is in this folder

- `0001-...patch` and `0002-...patch`: the two commits in `git format-patch` form, to apply with `git am` on top of pre-dec `5ef002f`.
- `files/`: the six changed files exactly as they stand at `04c8774`. These are whole files from the EQ-branch tree, not drop-in replacements for main-assembly.

## Checked (on a cloud sandbox, never GitHub Actions)

- VERIFIED: `modules/pubpartner_core.py` compiles. The tests for these pieces pass: project notes, existing wiring, cartridge memory wiring, calibration and calibration static (40 passed).
- VERIFIED: all PubPartner, Alex and EQ test files on the branch (25 files and folders): 425 passed, 5 skipped, 5 failed. All five failures are in `tests/test_pubpartner_connections.py`, and they fail the same way on the unchanged EQ branch (`5ef002f`), because those tests need a real Chromium browser and this sandbox cannot launch one.
- NOT CHECKED: a real browser, a live model reply, or Windows.

## Still open, hers to decide

- Two cartridge-memory paths exist side by side: this one (Beyond-October `7fd1fea`), and pre-dec's own `feat/pubpartner-cartridge-context-2026-11-22`, parked as `patches/pubpartner-cartridge-context/` (PARTS.md item 14). Only one should be integrated.
- Where this belongs once it is in shape: her rule is that persistent memory belongs to PubPartner, so its likely home is December's `pubpartner` branch.
- Whether the EQ foundations branch this sits on is itself the right base for integration.

## Raw sources already parked

The unresolved Nov 22 originals are in `patches/pubpartner-nov22/` (`existing-wiring/` and `cartridge-memory-wiring/`). Nothing there was changed.
