# Big Zip inventory against the studio line

Nov 24, 2026 · @Josie

## The short version

Most of Big Zip is older than the studio line. For nearly every code file, the studio line (pre-dec, branch claude/studio-assembly-2026-11-23, head 2541c09, checked again today and unchanged) holds the same file or a newer one that keeps every function and class. Six things in Big Zip are real gaps, listed under "What's missing from the studio line". Three large zips could not be opened at all.

Nothing was changed in any repo or in Drive, nothing was deleted, and no tests were run.

## How each entry was judged

- Every file was hashed the way git hashes it, both as-is and with Windows line endings changed to Unix ones, and checked against the studio line, the studio line's history, and every other pre-dec branch.
- Where a file differed, its functions, classes and routes were listed and checked against the studio copy. "All defs present" means the studio copy has every one of them.
- Newer or older was judged by dates, size and what each copy contains, never by names like "final" or "best".
- Wiring status comes from the Nov 23 loose-parts inventory: wired in (the app imports it), tests only, tools only, or unplugged (nothing imports it).
- READ means I opened the files and compared them. LISTED means I only saw names and sizes. NOT OPENED means I couldn't get the files at all.

## Entry by entry

| Big Zip entry | What it is | Studio line has | Wiring | Status |
| --- | --- | --- | --- | --- |
| Loose .py files at the root (meaning\_maker, wired\_orchestrator, conversation\_state, response\_composer, director, pubcast\_runtime, eq\_adaptor, gpt\_adapter, wired\_server, orchestrator\_wired) and PubWorld.jsx | Companion and wired-runtime modules | Same-name files in modules/wired. Two identical in size, seven within 10 bytes, orchestrator\_wired bigger on studio (16,632 vs 14,942 bytes). PubWorld.jsx identical to run5\_pubworld\_camera/PubWorld.jsx | conversation\_state, director, eq\_adaptor, meaning\_maker, orchestrator\_wired, pubcast\_runtime, response\_composer: tests only. gpt\_adapter, wired\_server: unplugged | LISTED (sizes). The friday repo copies of the same files were READ and all defs are on studio |
| codex\_current\_wiring\_file\_copies\_20260615 and codex\_ready\_wiring\_file\_copies\_20260615\_133303 | June 15 snapshots of wiring files and handoff notes | Every file at equal or larger size; studio changes dated Nov 1 to Nov 22. The 6.9 MB main.py is an old backup; studio main.py is a 230 KB refactor | Matches the studio wiring | LISTED (sizes); handoff docs listed only |
| codex\_file\_copies\_20260615\_125529.zip (34 files) | June 15 code copies | 18 identical, 10 were in studio history (studio newer). pub\_partner\_chat, ai\_runtime, menu\_coverage and main are older versions | Wired in where studio has them | READ |
| companion core.zip.zip | Companion engine pieces | acceptance\_engine and conversation\_pacing identical in companion\_support. companion\_runner differs but all defs present | Wired in | READ |
| companion core parroting moduels.zip | Anti-parroting pieces | 4 files identical (known\_vs\_novel, safeguards, anti\_parroting, meaning\_maker). companion\_core: all defs present, studio slightly longer | Wired in / tests only | READ |
| Pub moduals not all.zip.zip and files (41).zip (identical to each other) | Websocket hardening stack | rate\_limiter identical. hardened\_websocket, test\_hardening, orchestrator\_hardening: all defs present. schemas.py: NOT on studio (see gaps) | hardened\_websocket unplugged | READ |
| files (51).zip | Reasoning modules | contradiction\_engine, response\_execution\_layer, theory\_graph identical in modules/ | Wired in | READ |
| files (49).zip | Predictive insight engine (40 KB) plus integration, example, README | On no pre-dec branch | Missing | READ |
| files (39) - Copy.zip | EQ and streaming tests plus a roadmap note | Both tests older; studio has all defs plus 4 more EQ tests. Roadmap note not in pre-dec | Tests | READ |
| pubcast\_camera\_engine\_\_1\_.zip | Rust camera engine | Source files identical in experiments/prime\_rust\_recovery/src; only Cargo.toml differs | Tools only | READ |
| codex\_autonomous\_session\_planning\_20260614 (zip and folder, 17 files) | Planning and handoff documents, no product code | None of the documents are in pre-dec | Not code | READ |
| visual\_patch\_kit\_for\_big\_zip\_20260611 (zip and folder, 80 files) | Spine visual-patch modules plus voxel reference files | All 12 spine modules on studio. The 15 voxel reference files that differ all have their defs on studio (studio newer). stage.html lacks buildCompositeCanvas and mirrorFrame, which the harvest judged June placeholders. Five docs not in pre-dec | Wired in | READ |
| Slightly older still good. use for referene parts and ideas.zip (May 30, 81 files) | Older full build, labeled by you as reference parts and ideas | Build files older and covered, except security.py in one copy has check\_not\_spam and sanitize\_text. Its nested pubcast\_evo\_FINAL.zip holds code on no pre-dec branch (see gaps) | Missing for the evo pieces | READ |
| .git folder | A clone of your Saturday repo, head 813e925 (Jun 17, "Add PubCast event architecture core package") | Saturday's visual patch kit is covered as above. pubcast\_event\_core contracts and runtime are on no pre-dec branch (see gaps) | Missing | READ (git metadata, plus the Saturday repo itself) |
| friday-Lunch (1).zip and friday-whatsupjosie-further-better.zip | By name, downloads of your friday repo's Lunch branch (Jun 10) and whatsupjosie-further-better branch (May 29) | Read from the friday repo itself. Of about 75 project files per branch (the rest is a bundled Python environment): every companion and wired .py has all defs on studio, except schemas.py and the old main.py. Nested zips opened too (next rows) | See rows below | READ through the repo; the zips themselves NOT OPENED, so a match to the repo is by name, not proven |
| friday: little buddy zips (2) | Early small companion server and core stubs | Older; wired\_system identical on studio, others covered | Superseded | READ |
| friday: Pub eq files runtime parts\_runtime\_handoff\_bundle.zip (19.6 MB) | Another friday-main copy plus core\_integration.zip and two notes | friday-main covered as above. core\_integration: hub.py and orchestrator.py covered; pubcast\_integration.py and main\_pubcast\_complete.py partly missing (see gaps) | Missing for those two | READ |
| friday: claude new choreography runtime 5-21-26.zip | Choreography fixes and tests | 16 of 23 names defined on studio; easing helpers, MockAvatar, get\_active\_steps, get\_completed\_ratio, import\_json are not | Partly missing | READ |
| friday: friend\_core\_package.zip | Eight files, each an empty class with a one-line description | Nothing to keep beyond the idea list | Not code yet | READ |
| friday: podcast\_engine\_voxel\_integration.zip | Engine code plus a memory-layer spec | character\_engine, voxel\_renderer, prosody\_engine, lighting\_engine: all defs on studio. distributed\_engine\_node\_real.py partly missing (see gaps) | Partly missing | READ |
| friday: pages and scripts (avatar\_ui\_1920s\_opulent.html, avatar\_unified\_system.js, station\_audio (1).html, PubWorld (1).jsx, main (12).py) | Avatar UI, audio mixer page, a PubWorld variant, an old rooms server | Mostly not on studio (see gaps) | Missing | READ |
| friday: models (Superhero\_Female\_A.blend, manny.glb, sheila.glb) | 3D files | Not compared | Unknown | LISTED |
| codex\_construction\_pubcast\_20260614\_pubblocks (folder) | Same project layout plus pubblocks notes and a 148 KB main.py | Covered by the June canon comparison | Wired in where kept | LISTED (top level only) |
| pubcast\_complete\_debugged\_2026-05-08 and codex\_construction\_pubcast\_20260614 (folders) | May and June full builds | Already compared by the Nov 22 harvest (429 and 446 files) | As the harvest says | Covered by the harvest, not re-listed |
| PUBCAST\_FIRST\_PRIME\_UPLOAD\_PACKAGE (69 MB) | June canon | Read through The-Prime's first commit. 255 files identical at the same path, 24 identical elsewhere, 205 differ (166 with all defs present), 166 absent (mostly runtime data, logs and backups) | See gaps for the real ones | READ through The-Prime |
| rubbish and duplicates folders | A non-destructive readme; older copies of conversation\_state, main (12), eq\_adaptor and a debugged build folder | Older | Not needed | LISTED |
| Ring Me Jeeves Parts 61126-526 PM.zip (134.9 MB), pucastpy and pub.zip (38.2 MB), codex\_construction\_pubcast\_20260614\_beefed.zip | Unknown contents | Unknown | Unknown | NOT OPENED |

## What's missing from the studio line

1. **Predictive insight engine** (files (49).zip). Not on any pre-dec branch. The harvest already listed this as your open call: wanted or not.
2. **Full websocket message schemas** (schemas.py in files (41), Pub moduals and the friday repo). Studio's modules/schemas.py is a small shim. The full version adds ChatMessage, RoomJoinMessage, PersonaSelectionMessage, CorrectionMessage, FeedbackMessage, PingMessage, the stream and complete responses, and the text sanitizers. The hardened websocket stack it belongs to is on studio but unplugged.
3. **pubcast\_evo\_FINAL pieces** (inside the "reference parts and ideas" zip, and in the friday repo). LLMBridge, RecordingEVOBridge, the vision diagnostics and auto-fixer, the PubWorld engine server, atomics, hub\_evo, the fuller evo event bus (366 lines vs studio's 146), the SQLite version of universal memory, and the about, neodeco and control pages. Your own label calls this zip reference parts and ideas.
4. **Saturday's event core** (contracts.py and runtime.py). Premiere and concert modes, room isolation, red-carpet admission and Pete, producer and owner control. Only in the Saturday repo. Its **init** imports both files, so the package is only usable from Saturday.
5. **friday-era code with no studio copy:**
   - distributed\_engine\_node\_real.py: real VideoEncoder (ffmpeg and a numpy DCT fallback), AudioProcessor, MeshGenerator and VoxelRenderer (15 names missing out of 72).
   - pubcast\_integration.py and main\_pubcast\_complete.py from core\_integration (PubCastIntegration, add\_ai\_agent, the control interface, user profile saving).
   - The choreography easing helpers and step-progress functions.
   - station\_audio (1).html, the audio mixer page (faders, knobs).
   - avatar\_unified\_system.js (UnifiedAvatarSystem) and one function of the 1920s avatar UI.
   - PubWorld (1).jsx, a variant with greedy meshing.
   - main (12).py and the friday main.py: an old rooms server with sign-in tokens. Studio's main.py replaced it; this is most likely not wanted, but it's listed so you can say so.
6. **Gaps already found by the Nov 22 harvest, still open:**
   - The dressing room's room-code lock (on an unpushed harvest branch only).
   - The launch page's goLive and its camera, recording-session and preflight calls.
   - The ported branches from the harvest (airlock, PEQ engine, PubPartner base link, recorded takes, bridge heartbeat, recording fidelity lock, shot smoothing, dressing room lock, spine consolidation) never reached pre-dec. modules/airlock.py is on no branch.
   - The studio line lacks the last 7 commits of codex/studio-integration, and the route fix sits on top of those.

## The lost Airlock result

The combined test run of the route fix (first run 124 passed and 2 failed, focused rerun 27 passed, final result lost) was not rerun, as you said. It only matters if you want the route fix and those 7 commits on the studio line; until then the studio line doesn't depend on it.

## What the earlier handoffs already covered

- **Big Zip harvest (Nov 22):** the May and June full builds, the three identical wired files, the predictive insight question, the port branches and the found-not-fixed list (The-Prime is public and holds a key file and private drafts; a sign-in redirect loop; 114 broken static API references; room-code server issues; a test run writes into data/).
- **Loose-parts inventory (Nov 23):** what on the studio line is wired in, tests only, tools only or unplugged. This inventory reuses it.
- **Nov 1 tracked-file inventory** (PRIME\_AND\_BIG\_ZIP\_TRACKED\_FILE\_INVENTORY.md): The-Prime's and Saturday's tracked files with hashes. It says it never opened the zips. This inventory is the first to open them.
- **New here:** the twelve small zips, the .git folder being Saturday, the event core gap, the friday repo and its nested zips, and the evo pieces.
- **One correction:** the harvest names a Saturday commit d0f47aa. It doesn't exist in Saturday, which has only two commits (813e925 and c004228).

## What couldn't be opened, and why

- **Ring Me Jeeves Parts 61126-526 PM.zip** (134.9 MB), **pucastpy and pub.zip** (38.2 MB) and **codex\_construction\_pubcast\_20260614\_beefed.zip**: Drive won't hand over files above 10 MB through the connection I have, and no unzipped copies turned up in Drive or in your GitHub repos.
- The two **friday zips** were read through your friday repo instead. That only works if they really are branch downloads of it, which their names suggest but which I couldn't prove.
- To finish these, you could unzip the three into a Drive folder, or push them to a GitHub repo, and I'd compare them the same way.
