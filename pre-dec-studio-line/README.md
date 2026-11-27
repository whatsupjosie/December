# pre-dec studio line, parked (Nov 27, 2026)

A collection, not an installable part. Nothing here is wired into main-assembly or switched on. It was parked here because Josie asked on Nov 27: "Can you please push everything that is waiting or in progress to December, the repo, December parts assembly?" She has also said there is no integration until she says, so nothing here goes into main-assembly from this copy.

Every file is an exact copy (same Git blob) of a file at the tip of a branch of github.com/whatsupjosie/pre-dec. Each file keeps its original path under `repos/pre-dec/<branch folder>/`. SOURCES.md lists every file with its blob, mode, branch, commit and original path.

## What was left out, and why

- A file is copied only if its exact content is in no December branch yet (checked against every branch of December, main included, on Nov 27). Files already in December are listed with where they are in `ALREADY_IN_DECEMBER.tsv`, so the branch can still be rebuilt from this folder plus December.
- The branch folders are layered so the same file is not stored five times. A folder holds only the files that differ from the folders it was built on (listed below). If a path is missing from a folder, look in its parent folders first, then in `ALREADY_IN_DECEMBER.tsv`.

## The branches (tips read Nov 27, 2026)

| Folder | pre-dec branch | Tip commit | Last commit | Built on (parent folders) | Files here |
| --- | --- | --- | --- | --- | --- |
| claude-studio-line-missing-fixes-2026-11-24 | claude/studio-line-missing-fixes-2026-11-24 | a4fafd1cf611cc1c77aad38c013c35a4f5e5ed35 | 2026-11-25, Claude | none | 142 |
| claude-eq-foundations-2026-11-23 | claude/eq-foundations-2026-11-23 | 5ef002fcd959779e6c45ce28b3a9128142d0e8ae | 2026-11-23, Claude | studio-line-missing-fixes | 17 |
| claude-find-what-we-made-2026-11-25 | claude/find-what-we-made-2026-11-25 | b02994cb4514ad11a46797828772fda356586659 | 2026-11-25, Claude | none | 5 |
| claude-integrate-strongest-parts-2026-11-24 | claude/integrate-strongest-parts-2026-11-24 | ec7895a3c08cde769d2d3997c8bc8fe3d042e637 | 2026-11-25, Claude | studio-line-missing-fixes, eq-foundations, find-what-we-made | 596 |
| finish-control-room-engine | finish/control-room-engine | 24bac65bbc3af209efd43328c36e5b5772d922c3 | 2026-11-27, Claude | integrate-strongest-parts and its parents | 148 |
| finish-control-room-operator | finish/control-room-operator | b4ac093a003e267f49ab30451944279bddc6cd4e | 2026-11-26, whatsupjosie account | studio-line-missing-fixes | 3 |

All six branches start from pre-dec main 538a40f. The counts in the last column can be lower in SOURCES.md if a file was already added to parts-assembly by someone else before this push; SOURCES.md is the exact list.

## What each one is (READ from the branches' own handoffs and commit messages, not run)

- **studio-line-missing-fixes:** the studio line (studio-assembly, Nov 23) plus the fixes its Nov 24 handoff says were missing. Its own handoff is `handoffs/STUDIO_LINE_MISSING_FIXES_2026-11-24.md`.
- **eq-foundations:** the EQ observation layer in shadow mode, crisis presence only, reader fixes. Her words: "The EQ stuff stays with Alex." The alex branch of December already holds PEQ, cre_eq, eq_observation and the EQ foundations handoff. These 17 files are the versions on this pre-dec branch that are not in December yet; they are parked here because she asked for everything, and their home is still the alex branch.
- **find-what-we-made:** `handoffs/WHAT_WE_ALREADY_MADE_2026-11-25.md` and a Drive recovery folder with a 2i copy.
- **integrate-strongest-parts:** the branch PARTS.md items 1 to 13 were copied from (at d727f09). Its tip ec7895a has more since then.
- **finish/control-room-engine:** 20 commits on top of integrate-strongest-parts, made Nov 25 to 27 by Claude: program audio, capture timing, guest audio, intercom, recording preflight, faults mid-take, a 30-minute endurance run, and a parts index of every file in every zip and branch (`handoffs/parts_index/`). Its handoff is `handoffs/CONTROL_ROOM_ENGINE_COMPLETION.md`. This work was still going on Nov 27; this is a snapshot of the tip at the time of the push.
- **finish/control-room-operator:** 17 commits on top of studio-line-missing-fixes, committed under the whatsupjosie account (who made them is not recorded in the commits): recording ownership, switcher hardening, timeline transport, confidence monitors, release gates. Only 3 of its files were not already in December; the rest are listed in `ALREADY_IN_DECEMBER.tsv`.

The commit lists for each branch are in SOURCES.md.

## Not checked

No tests were run for this copy (her words: "Stop the fucking tests"). Whether any of this works was not checked here; only the branches' own handoffs say what was run, and those are their claims.
