# Handoff: EQ and PubPartner prepped for integration (Nov 27, 2026)

Her ask (Nov 27, her words): "Well once you get them out of the repo I want you to start working on the EQ and pub partner and prep them for integration". Then: "I don't know what you're waiting for. Go."

Done by Claude in the December repo. Nothing went into main-assembly or main. Nothing was deleted. Integration waits for her go.

## Where the work is

| Program | Prep branch | Starts from | Tip |
|---|---|---|---|
| EQ (Alex) | `claude/eq-prep-2026-11-27` | `alex` 769645a | 41ccde7 |
| PubPartner | `claude/pubpartner-prep-2026-11-27` | `pubpartner` da0f2a9 | 6eb64c1 |

Each branch has a `STANDALONE.md` that says what changed, how to build and run it on its own (PowerShell 5 commands), what each test run proved, and what was not tested. The program branches `alex` and `pubpartner` are unchanged; folding each prep branch into its program branch is her call.

## Checked before building

- The Nov 22 Beyond-October PubPartner commits (6cba39b, 7fd1fea) are already in `pubpartner`: every added line is there and both tests are byte-identical. PARTS item 23 is superseded.
- No newer EQ or PubPartner code exists on later pre-dec or Beyond-October branches than pre-dec `claude/integrate-strongest-parts-2026-11-24` (d727f09), which `alex` and `pubpartner` were copied from.
- main-assembly got PubPartner work on Nov 27 (205da08, 1d84ede, f4f418e, and 6247ed2, which `pubpartner` already had). The PubPartner prep branch combines it.
- main-assembly's `conversation_pacing.py`, `emotional_orchestrator.py` and `situation_reading.py` are older than pre-dec d727f09 (they lack the EQ foundations and the Nov 23 face rule). The EQ prep branch holds the newer copies.

## Standalone without copying shared files

`tools/standalone/assemble.py` (same file on both prep branches) builds a run folder from the branch plus the shared files it imports or loads from `static/`, each pinned by branch, path and Git blob in `STANDALONE_DEPS.json`. Nothing shared is duplicated into a program branch. `check` reports pinned files that changed since.

## Proven (Linux cloud computer, Python 3.13)

scikit-learn 1.9.1 and pytest-asyncio 1.5.0 were installed on her yes ("Install them", Nov 27 23:01 UTC), with mcp 1.30.0 for the connector.

- EQ engines need nothing from PubPartner, Alex Core or a host: `tests/test_eq_engines_standalone.py`, 2 passed, from a branch checkout and from a run folder.
- EQ branch in a run folder: 369 passed, 6 failed, 2 skipped. 4 failures are the "everyday wins" achievement cases (her decision). The other 2 need the PubPartner host, and pass in the PubPartner run folder.
- PubPartner run folder: 246 passed, 1 skipped; federation 14 passed. Still failing: 2 xAI tests (need item 16's provider files) and 10 tests that need PubCast's `main.py` or `run_reach.py` with Chromium.
- `pubpartner_app.py` started on its own and served `/pubpartner`, the 2i chat pages and the avatar import page, with every script and style sheet they name.

## Her calls

1. Done on her yes: scikit-learn and pytest-asyncio installed for testing.
2. "Everyday wins" level (0.4) for plain achievement messages, from the Pre-Dec merge plan. Not changed.
3. PubPartner Memory menu order: now "Project notes" then "Calibrate PubPartner…", as main-assembly has it. The pubpartner branch had them reversed.
4. Fold each prep branch into `alex` and `pubpartner`.
5. Which cartridge memory path to keep (PARTS item 14, asked on the PubPartner memory choices task). The PubPartner prep branch carries Beyond-October 7fd1fea's `_owned_cartridge_memories` in `pubpartner_core.py`, plus main-assembly's creator check. It has none of pre-dec `feat/pubpartner-cartridge-context-2026-11-22` (`modules/pubpartner_cartridge_context.py` is not on it). Integration waits for this answer too.
6. Integration into main-assembly. That also needs the newer shared provider files in PARTS item 16 (`llm_framework.py`, `provider_capabilities.py`, `ollama_provider.py`), without which PubPartner's xAI choice fails. With them, all 8 hosted provider tests pass.

## Not tested

Any real browser (this machine cannot download Chromium, so pages were served but never opened or clicked), Windows, a live model reply, and the tests that need the PubCast host (`main.py`, `run_reach.py`).

## Noticed, not changed

- On `pubpartner`, the saved provider lookup in `run_turn` sits just before the Blackbox-witnessed `try`, so a failure reading saved session state is not witnessed. The superseded pre-dec rebuild (item 23) had it inside. Left as the branch has it.
- `alex/BRANCH.md` points to `handoffs/DECEMBER_PLUG_POINTS_2026-11-25.md`, which is on no branch.
