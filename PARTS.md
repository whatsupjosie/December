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

PEQ and cre_eq are EQ work, so they are in the alex branch, not here.

## What these parts still need from other branches

Found by reading the import lines of the Python files here (read by script, not run):

- From blackbox: `blackbox_event_language/schema.py`, `blackbox_recorder/__init__.py`
- From main-assembly: `modules/__init__.py`, `modules/auth.py`, `modules/avatar_imports.py`, `modules/governance.py`, `modules/route_security.py`
