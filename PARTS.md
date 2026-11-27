# parts-assembly

Her words for this branch: "where we put all the parts that we haven't integrated yet... to get the parts in shape and make sure they work". And: "For now, parts assembly is filled with the parts we are still building."

This branch starts fresh. It holds only the parts below, at the paths they will have in main-assembly, so a part can be installed by copying it by path (`git checkout parts-assembly -- <path>`). Never `git merge` this branch into main-assembly: it holds a different set of files on purpose.

Every file here is copied exactly from pre-dec branch `claude/integrate-strongest-parts-2026-11-24` at d727f09, unless the part says otherwise. Nothing was deleted from pre-dec or Beyond-October.

## The parts

1. **Airlock (October 28 engine):** modules/airlock.py, modules/airlock_routes.py, tests/test_airlock.py, handoffs/AIRLOCK_2026-10-28.md. Added to pre-dec in commit 2f96a96 and never switched on (not mounted in main.py). Waiting on her: whether to switch it on.
2. **Camera Engine v2:** modules/camera_engine.py. Added in pre-dec commit 613792a, not wired to anything. Waiting on her: whether it replaces the current capture path.
3. **VDI engine:** modules/vdi_engine.py. Same commit 613792a, not wired. Waiting on her: which API it exposes.
4. **Renderer crates, vendored:** rust_crate/vendor/ (95 Rust crates). From pre-dec branch `claude/renderer-crates-vendored-2026-11-24`. These dependencies were used for the locked offline December build at 75b2e33. The resulting Linux x86_64 executable and reconciled source are in main-assembly. The vendor tree remains here for reproducible builds. See REPOSITORY_SWEEP.md for the target, executable blob and runtime checks.
5. **Camera pause rebuild:** patches/camera-pause-rebuild/. A patch, not files; see its README. Waiting on a try on Windows.
6. **Director Dock restore and Control Room routing:** patches/director-dock/. A patch, not files; see its README. Moved back here from main-assembly on Nov 25 because it was not proven. Waiting on being used in a real browser.
7. **On-set mini console:** patches/mini-console/. A patch; see its README. Moved back here from main-assembly on Nov 25 because it was not proven. Her words: "the mini console goes in pub world. So the director can operate from inside there if they need to." Waiting on being wired into Pub World and used in a real browser.
8. **PubPartner connector baseline:** patches/pubpartner-connector-baseline/. A patch; see its README. Moved back here from main-assembly on Nov 25: its connection routes passed, but the connector itself and its screens were never run. Waiting on the MCP SDK and a real browser.
9. **Sir Purfluous:** patches/sir-purfluous/. Two patches; see its README. Her words: "Superfluous right now goes into parts assembly." His tests passed while he was installed.

The next four are collections, not installable parts. They keep each file at its original repo path under a repos/ folder (Drive files under drive/), so they are not laid out at main-assembly paths. Each has a SOURCES.md listing where every file came from. All copied on Nov 25; nothing was deleted anywhere and nothing was taken out of main-assembly.

10. **Sir Purfluous, everything else:** characters/sir-purfluous/. His files from every branch of pre-dec and Beyond-October (runtime, waiting room, character profile, cue cards, bots, salvage proposals, diagnostics, tests, recovery zips, Blender model, early nudge code) plus older versions from Drive. His monologues are in drive/BELLE_EPOQUE_CHARACTER_BIBLES/. Her words: "along with any of the other superfluous files, his monologues, the chats discussing him and his design and development. The bot, the AI instructions, whatever."
11. **Pete and RePete:** characters/pete-and-repeat/. History and monologues (Drive character bibles), bots, character data, runtimes, Pete director page, sprites, reference sheets, models and Blender builds, plus older versions from Drive. Her words: "Pete and Repeat's history and their monologues and their anything we have on their avatars or bots, their design art, their reference art."
12. **Story bible and storylines:** story/. The story bible (TikTok movie arc, Poppy), cast files, the PubCast Character Bible docx and the Belle Epoque character bibles from Drive. Snow Day was not found anywhere this session can read; see story/SOURCES.md.
13. **Avatars and motion capture:** avatars-and-mocap/. Avatar and mocap code, pages, tests, test models, and the avatar, motion capture and animation recovery folders, plus a few Drive-only files. Her words: "because avatars are going to be the next thing we work on. And motion capture with that." Many of these files are also in main-assembly (marked in its SOURCES.md); they were copied, not moved.

PEQ and cre_eq are EQ work, so they are in the alex branch, not here.

14. **PubPartner cartridge continuity:** patches/pubpartner-cartridge-context/. Five original donor blobs, source comparison patch and acceptance gates. Newly harvested from `feat/pubpartner-cartridge-context-2026-11-22`; not installed. See `PRE_DEC_HARVEST_LEDGER.md` for the branch review queue.

## What these parts still need from other branches

Found by reading the import lines of the Python files here (read by script, not run):

- From blackbox: `blackbox_event_language/schema.py`, `blackbox_recorder/__init__.py`
- From main-assembly: `modules/__init__.py`, `modules/auth.py`, `modules/avatar_imports.py`, `modules/governance.py`, `modules/route_security.py`

## Beyond-October PubPartner candidates

[November 22 source deltas](patches/pubpartner-nov22/) preserve the calibration, identity checkpoint, existing wiring, cartridge memory wiring and unification work as individual patches with provenance and remaining checks. These branches share source, and some backend paths overlap with the hardening donor. Review each patch against the current assembly before promoting individual changes.

15. **Studio long-take acceptance.** `tools/acceptance/studio_long_take.py` is the exact Beyond-October blob `45d34e44d7516cf60207ca1e8ba3596874141419`, introduced at `884c1cd` on `codex/main-debug-20261119` and retained at `eacde8753402447e3454b07622fb2fcec8dd17e7` on `integration/main-debug-union-trial-2026-11-20`. It checks uninterrupted chunk growth each minute, reopens the take, downloads it and measures decoded packet coverage. December has the short reload/playback browser test and the imported fixtures in tests/test_production25d_browser.py. This harness assumes the default Program recording path and a 1280-pixel playback width. In production proof, reconcile those assumptions against each selected mode and retain the exported WebM alongside its timing measurements. The 30-minute run is deferred.

## Primp and set-building surface tools

**Filler Cream applicator and rotary sanding.** Beyond-October `11-12-merge`, applicator proposal `daed761b2c866afd91fdcef103b62797c1b435d2` and cumulative sanding design `5b8a7203886b7cf05dfeb86db74086b95a302f57`. The complete donor sources are already byte-identical in December at [applicator](https://github.com/whatsupjosie/December/blob/4a4576ed72c8c7ebeaa9524c1ba6ca60d9337b95/docs/FILLER_CREAM_APPLICATOR_UI_SPEC.md) and [sanding](https://github.com/whatsupjosie/December/blob/4a4576ed72c8c7ebeaa9524c1ba6ca60d9337b95/docs/SANDING_TOOL_DESIGN.md). The sanding revisions specify a reusable base, variants and per-instance edits, including cut-through and crisp edges.

Primp opens a GLB and paints UV texture layers through `static/primp/app.mjs`. VoxelStudio persists selected primitive IDs and reversible cream layers through `apply_filler`, `filler_status` and `bake_object`. The missing connection is a persistent mapping from the selected rendered surface to the editable voxel object and its primitive IDs. The donor supplied design documents for the brush and cutter. First implement and exercise selection of a known primitive from a generated asset, apply and remove one named layer, then reopen the object and verify the unaffected primitives and existing paint. A paintable textured bake exists in `modules/filler_cream.py`; ordinary VoxelStudio baking goes through `FillerStore.bake`. Track paint invalidation when geometry changes before offering re-bake on a painted asset.

## Waiting and in-progress work, parked Nov 27, 2026

Her words: "Can you please push everything that is waiting or in progress to December, the repo, December parts assembly?" Parked only; nothing installed. Full account: handoffs/PARKED_WAITING_WORK_2026-11-27.md.

16. **pre-dec studio line:** pre-dec-studio-line/. A collection. Six unmerged pre-dec branches (studio-line-missing-fixes, eq-foundations, find-what-we-made, integrate-strongest-parts at ec7895a, finish/control-room-engine at 24bac65, finish/control-room-operator at b4ac093), only the files not already in December. See its README.md, SOURCES.md and ALREADY_IN_DECEMBER.tsv.
17. **Two near-complete studios, reference only:** studios-reference/. pre-dec `recovery/control-room-beyond-october-2026-11-22` and Beyond-October `gpt/live-studio-setup-2026-11-09`. Which two studios she meant is not confirmed; these are a guess.
18. **Slate launcher, crew only:** patches/slate-button-crew-only/. A patch against pre-dec studio-assembly 2541c09, with her picks "Performers too" and "Roll call is enough". Waiting on her: whether to install it.
19. **Avatar from a picture:** patches/avatar-from-picture/. The December branch `claude/avatar-from-image-2026-11-27` (fc91915): its 77 new files under files/ and a diff for the three existing files it changes.
20. **3D character from her four drawings, v1:** characters/character-3d-from-four-drawings/. Unrigged; she called it "hideous". Waiting on her: TRELLIS on her Hugging Face account, or stop.
21. **ws_renderer.rs, render-subscriber version:** ws-renderer-subscriber-version/. Where it came from is unknown. Not a drop-in: it has no camera_control, which main-assembly's version uses.
22. **Plans saved from Claude Docs:** handoffs/claude-docs/. The Pre-Dec merge plan (Nov 24, decisions 2 to 9 still hers) and the Big Zip inventory.
23. **PubPartner Nov 22 commits on the EQ foundations branch:** patches/pubpartner-nov22-onto-eq/. Beyond-October `6cba39b` and `7fd1fea` rebuilt on pre-dec `claude/eq-foundations-2026-11-23` (pre-dec branch `claude/pubpartner-nov22-onto-eq-2026-11-27`, tip `04c8774`), with the two `pubpartner_core.py` clashes resolved as its README says. Not installed. Waiting on her: which cartridge-memory path to keep (this or item 14).
    Correction (Nov 27): superseded. Both commits were already in December's `pubpartner` branch (`da0f2a9`), which is newer; see the folder README.
24. **EQ and PubPartner, prepped for integration:** December branches `claude/eq-prep-2026-11-27` and `claude/pubpartner-prep-2026-11-27`, not files here. Each runs on its own through `tools/standalone/assemble.py`, with tests; see each branch's STANDALONE.md and handoffs/EQ_PUBPARTNER_PREP_2026-11-27.md. Not installed. Waiting on her: the everyday-wins level, the Memory menu order, folding each into its program branch, and her go to integrate (which also needs item 16's provider files).

## Beyond-October archive and branch review

The [complete contents comparison](beyond-october-inventory/README.md) includes the original 2i and PubPartner regression workflows and two handoffs recovered from four donor paths with no counterpart in either assembly at inspection. Their exact source pins, destination paths and next actions are in the comparison.

**Live Primp makeup** — Beyond-October `11-12-merge`, bf073508 through 27529758. The cumulative source `docs/PRIMP_LIVE_MAKEUP_DESIGN.md` already matches main-assembly. Current Primp handles GLB texture painting and stroke undo. Camera-tracked pencil grip, virtual tip, voice engage/retreat and whole-engage undo need a live face/hand tracking session connected to the brush. First replay a known tracking sequence through a session and verify disengagement prevents further strokes.

**Alex situation reading** — Beyond-October `11-12-merge` at 6006fa8237112748b10f948b3eb006a01c3ab655. December already has the exact modules/situation_reading.py, tests/test_situation_reading.py and tools/alex_eq_testkit sources. Its unit tests exercise the real affect engine. The production turn does not import the reader. The donor plan also requires a validated form provider and owner settings for outside-model cards. First connect a private, local test turn to the existing form validator and prove that a correction survives subsequent turns without passing private memory to an outside provider.
