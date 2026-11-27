# Handoff: EQ and PubPartner prepped for integration (Nov 27, 2026)

Her ask (Nov 27, her words): "Well once you get them out of the repo I want you to start working on the EQ and pub partner and prep them for integration". Then: "I don't know what you're waiting for. Go."

Done by Claude in the December repo. Nothing went into main-assembly or main. Nothing was deleted. Integration waits for her go.

## Where the work is

| Program | Prep branch | Starts from | Tip |
|---|---|---|---|
| EQ (Alex) | `claude/eq-prep-2026-11-27` | `alex` 769645a | 6e88969 |
| PubPartner | `claude/pubpartner-prep-2026-11-27` | `pubpartner` da0f2a9 | 188a367 |

Each branch has a `STANDALONE.md` that says what changed, how to build and run it on its own (PowerShell 5 commands), what each test run proved, and what was not tested. The program branches `alex` and `pubpartner` are unchanged; folding each prep branch into its program branch is her call.

## Checked before building

- The Nov 22 Beyond-October PubPartner commits (6cba39b, 7fd1fea) are already in `pubpartner`: every added line is there and both tests are byte-identical. PARTS item 23 is superseded.
- No newer EQ or PubPartner code exists on later pre-dec or Beyond-October branches than pre-dec `claude/integrate-strongest-parts-2026-11-24` (d727f09), which `alex` and `pubpartner` were copied from.
- main-assembly got PubPartner work on Nov 27 (205da08, 1d84ede, f4f418e, and 6247ed2, which `pubpartner` already had). The PubPartner prep branch combines it.
- main-assembly's `conversation_pacing.py`, `emotional_orchestrator.py` and `situation_reading.py` are older than pre-dec d727f09 (they lack the EQ foundations and the Nov 23 face rule). The EQ prep branch holds the newer copies.

## Standalone without copying shared files

`tools/standalone/assemble.py` (same file on both prep branches) builds a run folder from the branch plus the shared files it imports or loads from `static/`, each pinned by branch, path and Git blob in `STANDALONE_DEPS.json`. Nothing shared is duplicated into a program branch. `check` reports pinned files that changed since.

## Proven (Linux cloud computer, Python 3.13, no scikit-learn or pytest-asyncio)

- EQ engines need nothing from PubPartner, Alex Core or a host: `tests/test_eq_engines_standalone.py`, 2 passed, from a branch checkout and from a run folder.
- EQ branch in a run folder: 369 passed, 6 failed, 2 skipped. 4 failures are the "everyday wins" achievement cases (her decision); 2 need the PubPartner host and pass there except the one that needs scikit-learn.
- PubPartner run folder: 145 passed, 1 skipped; federation 14 passed.

## Her calls

1. Install scikit-learn and pytest-asyncio on the cloud computer for testing. Both are in the project's own requirements. Without scikit-learn, `pubpartner_app.py` and the cartridge studio cannot start, so most PubPartner tests cannot run.
2. "Everyday wins" level (0.4) for plain achievement messages, from the Pre-Dec merge plan. Not changed.
3. PubPartner Memory menu order: now "Project notes" then "Calibrate PubPartner…", as main-assembly has it. The pubpartner branch had them reversed.
4. Fold each prep branch into `alex` and `pubpartner`.
5. Integration into main-assembly. That also needs the newer shared provider files in PARTS item 16 (`llm_framework.py`, `provider_capabilities.py`, `ollama_provider.py`), without which PubPartner's xAI choice fails. With them, all 8 hosted provider tests pass.

## Not tested

Any real browser (this machine cannot download Chromium), PubPartner serving its pages, Windows, a live model reply, and the tests that need the PubCast host (`main.py`, `run_reach.py`).

## Noticed, not changed

- On `pubpartner`, the saved provider lookup in `run_turn` sits just before the Blackbox-witnessed `try`, so a failure reading saved session state is not witnessed. The superseded pre-dec rebuild (item 23) had it inside. Left as the branch has it.
- `alex/BRANCH.md` points to `handoffs/DECEMBER_PLUG_POINTS_2026-11-25.md`, which is on no branch.
