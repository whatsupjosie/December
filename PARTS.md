# parts-assembly

Her words for this branch: "where we put all the parts that we haven't integrated yet... to get the parts in shape and make sure they work". And: "For now, parts assembly is filled with the parts we are still building."

This branch starts fresh. It holds only the parts below, at the paths they will have in main-assembly, so a part can be installed by copying it by path (`git checkout parts-assembly -- <path>`). Never `git merge` this branch into main-assembly: it holds a different set of files on purpose.

Every file here is copied exactly from pre-dec branch `claude/integrate-strongest-parts-2026-11-24` at d727f09, unless the part says otherwise. Nothing was deleted from pre-dec or Beyond-October.

## The parts

1. **Airlock (October 28 engine):** modules/airlock.py, modules/airlock_routes.py, tests/test_airlock.py, handoffs/AIRLOCK_2026-10-28.md. Added to pre-dec in commit 2f96a96 and never switched on (not mounted in main.py). Waiting on her: whether to switch it on.
2. **Camera Engine v2:** modules/camera_engine.py. Added in pre-dec commit 613792a, not wired to anything. Waiting on her: whether it replaces the current capture path.
3. **VDI engine:** modules/vdi_engine.py. Same commit 613792a, not wired. Waiting on her: which API it exposes.
4. **Renderer crates, vendored:** rust_crate/vendor/ (95 Rust crates). From pre-dec branch `claude/renderer-crates-vendored-2026-11-24`. Vendored, not built. Note: pre-dec's assembly ledger says ws_renderer was rebuilt offline from these crates; the instruction for December is that they are vendored and not built, so they wait here.
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
