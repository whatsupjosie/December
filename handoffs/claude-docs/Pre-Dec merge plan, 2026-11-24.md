# Pre-Dec merge plan, 2026-11-24

Nov 24, 2026 · whatsupjosie/pre-dec · plan only: nothing pushed, merged, deleted, no pull request, no GitHub Actions

## The short version

- Eight jobs can come into main in a fixed order. I ran that whole order in a throwaway sandbox copy: every merge went through, three needed small hand fixes, and the tests I could run passed except four that also fail on the untouched branches because this sandbox lacks two libraries. (RAN)
- Code Collector comes away from Sir Purfluous cleanly. It is one commit that touches only the code\_collector/ folder, and no Purfluous commit touches that folder. (RAN)
- One line can't be merged without your decision: the Nov 19 to 20 recording line (codex/main-debug-20261119 and the two branches built on it). It clashes with the studio line in 11 files at 45 spots. It is the same recording-architecture fork the Nov 20 merge report stopped on. (RAN) You chose on Nov 24 to keep the studio line.

## How to read this

- RAN: I ran it in the sandbox and saw the result.
- READ: I opened and read it (a handoff, a commit message, code).
- GUESS: my judgment, not checked.
- Sandbox limits: the repo's requirements are not installed (fastapi, httpx and sklearn are missing). Installing what the repo lists needs your yes, so app, route, browser and full-suite tests were not run here. What I did run: the EQ and Purfluous tests, the loose-parts test, and Code Collector's Python extractor tests.
- Main is 538a40f, 2026-11-20, "Converge: merge report for integration/converge-2026-11-20". Origin has 33 branches besides main. (RAN)

## Every branch

"Inside" means the branch's whole history is already contained in the branch named, so merging that one brings it along. (RAN with git ancestry checks.) Clashes are from trial merges of each pair of branch tips. (RAN)

### Studio line (the one-source branch and what it absorbed)

| Branch | Base | What it holds (READ) | Inside | Clashes (RAN) |
| --- | --- | --- | --- | --- |
| claude/studio-assembly-2026-11-23 (2541c09) | main | The one-source branch: camera fixes, live sources, recording end to end, live avatar camera, 2i unified, Director Dock, mini console, PubPartner connector baseline, studio-integration as of Nov 22, recording modes, 2i WordPad parity, timeline repair, recording safety, loose-parts inventory, show clocks step 1. Its handoff names a known regression: the slate button covers onboarding's Skip, 8 browser tests fail. | wire-avatars, eq-foundations | Only with the recording line |
| claude/studio-wire-avatars-2026-11-23 (45de912) | studio-assembly | Show clocks drawn on the control room and three set screens, labelled IN and LEFT | tip | 1 spot in modules/studio\_slate.py with portable-2i; 11 files with the recording line |
| claude/eq-foundations-2026-11-23 (5ef002f) | studio-assembly | EQ observation layer in shadow mode, crisis presence only, reader fixes, handoff with designs not yet built | tip | 1 spot in studio\_slate.py with portable-2i; eq\_disambiguation\_engine.py with Purfluous; pubpartner\_core.py with cartridge-context; 11 files with the recording line |

Already inside the studio line, no separate merge needed: claude/camera-fixes-2026-11-21, claude/avatar-live-camera-2026-11-21, claude/recording-e2e-2026-11-21, claude/live-sources-2026-11-22, integration/2i-camera-repairs-2026-11-20, integration/2i-unified-2026-11-20, codex/pubpartner-connector-baseline, codex/live-production, codex/restore-director-dock, codex/restore-mini-console. (RAN)

### Airlock and portable 2i

| Branch | Base | What it holds (READ) | Inside | Clashes (RAN) |
| --- | --- | --- | --- | --- |
| codex/studio-integration (0d4d042) | main | Airlock, Waiting Room, Sir Purfluous greeting and FAQ, entry contract, owner-issued temporary passes. The studio line merged an earlier tip; the 7 newest commits (8630561 to 0d4d042) are not in it. | portable-2i | via portable-2i |
| gpt/pubpartner-portable-2i-2026-11-22 (a692d5b) | studio-integration | PubPartner portable opens the modern 2i editor, manuscript backend and 2i Chat; plus all of studio-integration. Committed under your account name (READ author field; GUESS it was ChatGPT or Codex). | tip | 1 spot in studio\_slate.py with the studio line; 1 spot in pubpartner\_app.py with cartridge-context; 3 files with the recording line |

### Sir Purfluous and Code Collector (today)

| Branch | Base | What it holds (READ) | Inside | Clashes (RAN) |
| --- | --- | --- | --- | --- |
| claude/purfluous-character-salvage-2026-11-24 (1d30d88) | main | Character material salvaged from the old scene-director file, for you to pick | every later Purfluous branch | none |
| claude/purfluous-ai-wiring-2026-11-24 (a9cdde5) | salvage | AI Sir Purfluous wired to his canon, paced interruptions | later ones | none |
| claude/purfluous-canon-2026-11-24 (390a88a) | ai-wiring | Owner decisions of 2026-11-24 | later ones | none |
| claude/purfluous-cue-cards-2026-11-24 (f762b3e) | canon | Cue-card deck, TikTok watch line, the EQ card-catalog reader fix (62430f9, edits eq\_disambiguation\_engine.py), Pete cuts him off | code-collector, more-cards | eq\_disambiguation\_engine.py with EQ |
| claude/code-collector-2026-11-24 (c403fe6) | 62430f9 (a Purfluous commit) | Code Collector March 23 build in code\_collector/ (48bc039), then a merge of cue-cards | more-cards | tangled with Purfluous |
| claude/purfluous-more-cards-2026-11-24 (14c2388) | code-collector | Nine more Purfluous card commits; carries Code Collector along by accident | tip | eq\_disambiguation\_engine.py with EQ |

### Recording line (held for your decision)

| Branch | Base | What it holds (READ) | Inside | For main? |
| --- | --- | --- | --- | --- |
| codex/main-debug-20261119 (d3b9db8) | an old pre-dec commit (c82069b, Nov 4), 322 commits behind main | 25 commits: camera filename reservation, FFmpeg overwrite refusal, PANIC handling, per-source failure persistence, timeline transport repair | land-clean, union-trial, studio-exact, recovery/control-room | not directly |
| integration/main-debug-union-trial-2026-11-20 (eacde87) | daa9b77 (main's parent) | Commit message: "TRIAL (not for main)" | land-clean, recovery/control-room | labelled not for main |
| recovery/beyond-october-studio-exact-2026-11-22 | same commit as union-trial (eacde87) | Same TRIAL label | as above | labelled not for main |
| integration/main-debug-land-clean-2026-11-20 (b282b2b) | main | Lands main-debug's work except static/production25d\_storage.js and static/production25d\_app.js, which stay at main's version byte for byte; landing note with test numbers | recovery/control-room | your call |
| recovery/control-room-beyond-october-2026-11-22 (5f05314) | land-clean | Ten commits under your account name: Beyond-October console donor snapshots under recovery/beyond\_october/, plus slate, voxel props and mini console at live paths. Its own manifest says it was not tested. | tip | your call |

Against the studio line, land-clean clashes in 11 files at 45 spots (main.py, cameras\_advanced.py, capture.py, evo/camera\_manager.py, production\_routes.py, recording.py with 13 spots, timeline.py, director\_switcher.html and three test files). recovery/control-room adds studio\_slate.py, studio\_slate.js and test\_studio\_slate.py as both-sides-added clashes, 14 files in all. (RAN) Its live-path files are older copies of what the studio line already has: the voxel props, mini console and slate CSS are byte-identical to the studio line, and its studio\_slate.py and studio\_slate.js match codex/studio-integration's older versions. (RAN, by comparing file hashes)

### Small, independent

| Branch | Base | What it holds (READ) | Inside | Clashes (RAN) |
| --- | --- | --- | --- | --- |
| claude/handoff-cricket-2026-11-23 (a531ff5) | main | One handoff document, section 14.6 on the Cricket, plus appendix items 22 to 25 | tip | none |
| claude/bring-in-donor-finds-2026-11-23 (c812e22) | main | Donor finds from other repos into recovery/2026-11-23 | rediscovery | none |
| claude/rediscovery-early-repos-2026-11-23 (a1b4063) | donor-finds | 861 files added under recovery/2026-11-23 plus two handoffs; nothing changed elsewhere | tip | none |

### PubPartner memory

| Branch | Base | What it holds (READ) | Inside | Clashes (RAN) |
| --- | --- | --- | --- | --- |
| feat/pubpartner-cartridge-context-2026-11-22 (7b8c7ea) | main | Puts a cartridge's identity and scoped memory into FCP1 and mounts the cartridge routes in pubpartner\_app.py. Its own document says the full app, pytest, providers and browser were not run. Committed under your account name. | tip | 1 marked spot in pubpartner\_core.py with EQ (a second nearby change merged on its own); 1 spot in pubpartner\_app.py with portable-2i |

### Old Nov 17 to 19 branches (already judged in MERGE\_REPORT\_2026-11-20.md)

| Branch | Base | What the Nov 20 report says (READ) | Clashes with main (RAN) |
| --- | --- | --- | --- |
| 2i-beta-polish (df737ca) | c82069b, 322 behind | Needs your decision: its desk layout fights your single-page notebook look | reach.css, reach.js, writers-room-v22.html, STATUS.md |
| console-touch-typewriter-keys (3ee394a) | c82069b, 322 behind | Already in main by exact port; no merge needed | STATUS.md and three typewriter files |
| codex/2i-typewriter-visual-2026-11-17 (69e1550) | 156 behind | Swaps the interactive typewriter for a static image; report recommends not merging | studio-desk.js |

## Merge order

All of this goes on one new landing branch made from main, named for the task and date. Main itself is only touched when you say so.

1. **claude/handoff-cricket-2026-11-23.** One document, no clashes. (RAN)
2. **claude/rediscovery-early-repos-2026-11-23.** Adds files under recovery/ only and brings the donor-finds branch with it. (RAN)
3. **Code Collector on its own** (see the next section). No clashes. Before it lands: decisions 2 and 3 below. Its 137 Python extractor tests passed on main alone; I didn't run its JavaScript tests. (RAN) The builder's handoff, code\_collector/HANDOFF\_2026-11-24.md, reports 179 of 180 JavaScript tests passing in its own sandbox. (READ)
4. **claude/studio-wire-avatars-2026-11-23.** Brings studio-assembly and the ten branches inside it, plus the show clocks. No clashes. Before it lands on main: decisions 4 and 5. (RAN)
5. **claude/eq-foundations-2026-11-23.** No clashes on top of step 4. Before it lands on main: decision 6. (RAN)
6. **gpt/pubpartner-portable-2i-2026-11-22.** One spot in modules/studio\_slate.py: both sides list pages the slate overlay must skip. Fix: keep both lists (the Foresight Counter pages, plus /login, /airlock, the waiting room and human visits pages). This touches decision 4. (RAN; the file compiles; slate tests need fastapi, not run)
7. **Sir Purfluous, rebuilt without Code Collector.** Two marked spots and one hidden clash in the EQ reader (see below). (RAN: 202 passed; 4 failed, and those same 4 fail on the untouched EQ and Purfluous branches for want of httpx and fastapi)
8. **feat/pubpartner-cartridge-context-2026-11-22, last.** Two spots, both "keep both lines": the EQ layer and the cartridge bridge in pubpartner\_core.py, and two import groups in pubpartner\_app.py. Only after the PubPartner memory choices (decision 7). (RAN; both files compile; its tests need sklearn and fastapi, not run)

Held back: the recording line and the three old branches.

After all eight, the trial branch differs from main by 1,271 files, every changed Python file outside recovery/ compiles, and no new GitHub workflow file comes in. (RAN)

### How this compares with the voice-call sketch

It mostly holds. Three differences:

- **EQ isn't small.** eq-foundations sits on the whole studio line, 106 commits, so it lands after the small independent branches, not among them. (RAN)
- **Merge rather than rebase for Purfluous.** Only one Purfluous commit touches the EQ reader, so one merge resolves it once and keeps the commits and hashes you've already seen. A rebase would replace 17 commits with new copies. Both work. (GUESS on which you'd prefer)
- **The sketch leaves out the recording line.** It is the hardest piece and needs your decision first.

## Separating Code Collector from Sir Purfluous

What's true (RAN):

- Code Collector is one commit, 48bc039. It changes 45 files, all inside code\_collector/.
- The merge c403fe6 only brings in one Purfluous commit (f762b3e, Pete cuts him off).
- The nine Purfluous commits after that touch no code\_collector/ file.

Steps, both tried in the sandbox (RAN):

1. New branch from main for Code Collector alone. Copy commit 48bc039 onto it (git cherry-pick -x keeps a note of the original). Result: code\_collector/ is byte-identical to the original branch.
2. New branch from claude/purfluous-cue-cards-2026-11-24 (f762b3e) for Purfluous alone. Copy the nine later commits onto it. Result: identical to purfluous-more-cards except the 45 Code Collector files.
3. Leave all original branches as they are. Nothing is deleted.

## The EQ and Purfluous clash, in plain English

Both branches fixed the same reader bugs independently.

- **Spot 1, "I hit my goal" is not violence.** Each side wrote its own list of win phrases. Fix: keep both lists. (RAN)
- **Spot 2, "I lost my keys" is not grief.** EQ's list holds every word on Purfluous's list and adds job, home, pregnancy and more. Fix: take EQ's. (RAN)
- **Hidden clash, which git doesn't mark.** EQ scores plain messages at 0.05 intensity instead of 0.5. Purfluous's celebration cards need 0.2 to 0.6, so "I got the part!" drops to the fallback listening card and 4 Purfluous tests fail. I tried an "everyday wins" level at 0.4 (got the part, nailed it, scored, hit the target), and then every EQ and Purfluous test passed. (RAN) That fix is mine, not yours, so it waits on your yes and is on no real branch. If you'd score wins differently, say so.
- Taking either side's whole file breaks the other side: EQ's file alone fails 13 Purfluous tests, Purfluous's file alone fails 5 EQ tests. (RAN)

## The recording line: three options

The studio line replaced main-debug's SessionCapture with FFmpegCaptureEngine and wrote most of main-debug's fixes in by hand. An earlier version of this plan said three main-debug fixes were not yet carried over. That was wrong. When I opened the studio line's modules/production\_routes.py, all three are already there: production pause rejects a non-yes/no value ("paused must be a boolean"), import cleans the file name, and import picks a new file name instead of overwriting an existing zip. (READ)

The three tests for those fixes are on main and on the studio line already, in a newer form than main-debug's. The studio handoff saw them fail because it ran main-debug's older copies, whose stand-in recording object is out of date, not because the code was missing. (READ)

- **A. Keep the studio line and port what's missing.** Port those three fixes with tests, and bring in only the recovery/beyond\_october/ donor snapshot folder as files. (GUESS: lowest risk)
- **B. Merge land-clean into the studio line.** Resolve the 45 spots by hand, mixing two capture designs. Biggest and riskiest.
- **C. Leave the line as history.** Nothing from it lands.

**Decided on Nov 24: A, keep the studio line.** The three fixes are already in, so that part needed no porting. The other part of A is still to do: bringing recovery/beyond\_october/ in as plain files. Those 108 files (about 6 MB, three snapshot folders) are only on recovery/control-room-beyond-october-2026-11-22, not on the studio line or main, and none of them is a workflow file. (RAN) No branch has been made or pushed for it yet. What's still open is the studio handoff's other main-debug test failures. About 15 of its 26 failures were never looked into by anyone. Checking them means running main-debug's test files against the studio line, which needs the repo's listed test packages installed in the sandbox. (READ)

Before any push, I checked the workflows. The two on the studio line run on push only to codex/2i-beta-test-gates-2026-11-17 and codex/github-browser-tests-2026-11-17, so a push to any other branch name starts no run. (READ)

Also worth knowing: land-clean swaps the bin/ws\_renderer program file from 9.7 MB to 1.8 MB. (RAN, file size only) And the Nov 20 choice between the two production25d recording designs is still open. (READ)

## Decisions only you can make

1. **Recording line:** decided Nov 24: A, keep the studio line. The three fixes needed no porting; the recovery/beyond\_october/ files are still to bring in.
2. **Code Collector's P3 test** ("strips XSS from extracted content"). The builder kept captured code exactly as written, so the test fails on purpose. Their recommendation: keep code exact, escape it only when shown, and change the test. (READ)
3. **Code Collector's broken link.** The commit stores code\_collector/node\_modules as a link to /home/claude/scratch/cc\_run/node\_modules, a folder on the builder's computer. It points nowhere on any other machine, and main has no such links today. Taking it out is a deletion, so it waits on your yes; I haven't removed it. The likely fix is to remove it and change .gitignore's "node\_modules/" to "node\_modules", which also catches links. (RAN)
4. **Slate button regression.** On the studio line, the "Open production slate" button covers onboarding's "Skip optional details", and 8 browser tests fail. The handoff's options: skip the onboarding and profile pages, show the button only to floor roles, or move it. (READ) Decide before step 4 reaches main, or land it with the known regression.
5. **Show clock labels.** IN and LEFT are the builder's words; you haven't named them. Four clock questions are also open: keep counting past the script, negative time left, 29.97 frames, and who may see the clocks. (READ)
6. **EQ observation on by default.** eq-foundations sets eq\_observation\_enabled=True. It runs in shadow mode, changes no reply, and writes per-person numbers to data/pubpartner/eq\_observation/. Is that okay on main? Its dial numbers are all marked pending you. (READ)
7. **PubPartner memory choices,** before step 8 (the open "Line up the six PubPartner memory choices" task). The cartridge branch loads identity, voice, appearance and seed memories from the cartridge's YAML; whether that fits your five-file cartridge design is part of the same call. (GUESS on fit)
8. **Sir Purfluous salvage picks.** The salvaged material waits for you to choose. It doesn't block the merge. (READ)
9. **The old branches.** 2i-beta-polish's look, and whether to drop codex/2i-typewriter-visual (the Nov 20 report recommends not merging it). console-touch-typewriter-keys is already in. (READ)

## Not done or not checked

- No app, route, browser or full-suite tests: they need the repo's requirements installed, which needs your yes.
- I didn't run Code Collector's JavaScript tests. Its builder reports 179 of 180 passing in its own sandbox. (READ)
- The studio-integration Waiting Room work and today's Purfluous canon merge with no clash, but I didn't check they agree in behaviour. (GUESS)
- The trial branches live only in this session's sandbox and are gone when it ends. The steps above are enough to redo them.
