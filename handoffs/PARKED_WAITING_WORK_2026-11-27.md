# Handoff: waiting and in-progress work parked in parts-assembly (Nov 27, 2026)

## What was asked

Josie, Nov 27, 2026: "Can you please push everything that is waiting or in progress to December, the repo, December parts assembly?"

This is parking, not integration. She has said there is no integration until she says. Nothing in this push touches main or main-assembly, nothing was deleted anywhere, and no files already in parts-assembly were changed, except PARTS.md, which only had items added at the end. No tests were run (her words: "Stop the fucking tests"). Committed as Claude.

## What went in

| Folder in parts-assembly | What it is | Came from | Files |
| --- | --- | --- | --- |
| pre-dec-studio-line/ | Six pre-dec branches that were never merged: the studio line with its missing fixes, EQ foundations, find-what-we-made, integrate-strongest-parts (newer than the copy PARTS.md items 1 to 13 came from), and the two control room branches still being worked on Nov 26 to 27 | pre-dec, branch tips listed in its README.md | 911 |
| studios-reference/ | The two "nearly complete" studios she said to use as the model. Which two is a guess, not confirmed | pre-dec `recovery/control-room-beyond-october-2026-11-22` (5f05314) and Beyond-October `gpt/live-studio-setup-2026-11-09` (1cfb2d2) | 148 |
| patches/slate-button-crew-only/ | Slate launcher fix, with her two picks ("Performers too", "Roll call is enough") | project folder `pubcast/slate-button/` | 5 |
| patches/avatar-from-picture/ | Today's avatar-from-a-picture builder, editor page and evidence | December branch `claude/avatar-from-image-2026-11-27` (fc91915) | 79 |
| characters/character-3d-from-four-drawings/ | The Nov 19 unrigged 3D model built from her four drawings, which she called "hideous", plus its build scripts | project folder `character-3d/` and the Nov 19 session's saved build files | 28 |
| ws-renderer-subscriber-version/ | A Rust renderer file found loose in the project folder | project folder `pubcast/ws_renderer/`; where it came from before that is unknown | 2 |
| handoffs/claude-docs/ | The Pre-Dec merge plan (Nov 24) and the Big Zip inventory, saved from Claude Docs as Markdown | Claude Docs | 3 |

Each folder has a README.md. The two collections also have SOURCES.md (every file: blob, mode, repo, branch, commit, original path, and each branch's commits) and ALREADY_IN_DECEMBER.tsv (every other file on those branches, with where its exact copy already is in December).

## How "not already in December" was decided (verified)

Every file on every branch of December (main included) was listed by its Git blob ID on Nov 27. A file from pre-dec or Beyond-October was copied only if that exact content was in none of them. Copies use the original blobs, so every copy is byte-for-byte the original and can be checked with `git ls-tree`. The new tree was checked by script before committing: no existing path was removed or changed except PARTS.md.

## Already in December, so not copied again

- PEQ, cre_eq, eq_observation and the EQ foundations handoff with its eight unbuilt designs: the alex branch. Her words: "The EQ stuff stays with Alex." The 17 EQ-branch files in pre-dec-studio-line/ that were not yet in December are parked there only because she asked for everything; their home is still the alex branch.
- PubPartner `link.py`, `companion_mode.py`, `avatar_preference.py`: the pubpartner branch.
- Code Collector: the code-collector branch. It does not go in main-assembly (her words: "Code collector does not go in main assembly at this point"), and its broken node_modules link stays (she said "Not yet" to removing it).
- Airlock, Camera Engine v2, VDI, camera pause rebuild, the PubPartner Nov 22 patches, cartridge continuity: already in parts-assembly (PARTS.md items 1 to 14 and the Nov 22 section).
- The option C engine readiness audit: its own December branch, `audit/option-c-engine-readiness-2026-11-27`.

## Verified, read, or guessed

- VERIFIED: every copied file matches its source blob; branch tips and commit IDs as listed in each README and SOURCES.md, read Nov 27.
- READ, not run: what each piece is and what was tested, taken from its own handoff or notes. Those are their claims.
- GUESS: which two studios she meant (studios-reference/). Which character the Nov 19 model is (its notes guess Pete).
- UNKNOWN: who made ws_renderer.rs and when; it matches nothing in pre-dec, Beyond-October or December.

## Not found, or not brought in

- The 0.4 "everyday wins" EQ level from the Pre-Dec merge plan: tried only in a throwaway sandbox, on no branch anywhere.
- The three large zips the Big Zip inventory could not open: still not opened.
- Snow Day: not found on any branch or on Drive (as recorded in story/SOURCES.md on Nov 25).
- Drive files over the connector's 10 MB download limit, such as Pete_Clothed_Motion_Test.glb (17.3 MB), noted in handoffs/GATHERED_STORY_CHARACTERS_AVATARS_2026-11-25.md: still not copied.
- Other sessions' private working notes in the project folder were not copied, because they are notes, not work.

## What's still waiting on her (unchanged by this push)

- Pre-Dec merge plan decisions 2 to 9 (in handoffs/claude-docs/).
- Which two studios are the model.
- The slate fix: whether to install it.
- The 3D model: try TRELLIS on her Hugging Face account, or stop.
- Open design questions on her tasks (Airlock and others) stay on those tasks.

## Next step

Nothing is installed. When she picks a part to integrate, follow the per-part workflow in WORKFLOW.md on main: fix it up, prove it in main-assembly, write the handoff, then move it to parts-live-archive.
