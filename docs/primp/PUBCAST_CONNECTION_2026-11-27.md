# Primp connected to main-assembly: the PubCast avatar store

Date: 2026-11-27 (Los Angeles). Repo: `whatsupjosie/december`. Branch: `claude/primp-to-main-assembly-2026-11-27`, cut from `main-assembly` at `2cede61`. Not merged into main-assembly; that is the owner's call.

## What was already true before this change (checked, not assumed)

- Primp's 33 files were already in main-assembly (they came over with main). They are byte-identical to the newest Primp anywhere in pre-dec or Beyond-October: the latest Primp change is pre-dec `b91c3a0` (2026-11-20), and main-assembly already contains it. Nothing needed carrying over.
- Primp was already reachable in three ways: the Foresight Counter tray (`static/foresight_programs.js`, id `primp`), the Primp card in `static/avatar_foundry.html`, and the host's static mounts (`tests/test_primp_host_integration.py`).
- What was missing: Primp was an island. It could only open a GLB file picked by hand, or the two prepared bases. A finished look could only leave as a downloaded file. It never reached the user's avatars in PubCast.

## What this change does

PubCast already has an avatar store, `modules/avatar_imports.py`. Each GLB in it is measured against its canonical height, and the world lists them as the "Imported Avatars" pack in `/data/avatars/manifest.json`. Primp now uses that store at both ends:

1. **Open from PubCast.** The new header picker (`#pubcast-avatar`) lists every stored avatar with its canonical height. Choosing one opens it in the mirror.
2. **Direct link.** `/static/primp.html?avatar=<id>` opens that avatar straight away. Import Avatar's library now has an "Open in Primp" link on every avatar, and on the "Saved" report.
3. **Send to PubCast.** The new button (`#send`) exports the painted avatar (the after-state, even while Before / after is showing the before-state) and saves it to the store as a **new** avatar. The original is never replaced, edited or deleted.
   - From a PubCast avatar: same canonical height (shown read-only) and same character. `character_id` is the original's character id, or the original's own id if it had none. `source_name` is `primp:<original id>`.
   - From a file or a prepared base: the height is pre-filled with the height the avatar actually stands, to the nearest half inch, and can be edited. Primp never resizes. The server re-measures and refuses a height mismatch with its own reason, and Primp shows that reason.
4. **Looks remember where they came from.** A `.primp` look (and its local recovery) now carries an optional `origin` record (`id`, `name`, `character_id`, `canonical_height_in`). Reopening the look later still sends at the right height and character. A malformed `origin` is ignored rather than trusted; the look still opens.
5. **No surprise redirects.** The shared auth adapter sends any 401 straight to the login page, which would throw away unsaved paint. Primp's store calls use the adapter's token without that redirect, and show "Sign in to PubCast to open or send PubCast avatars. Your open work is still here."
6. **Fix on the Import Avatar page.** Avatar names in its library and its Saved report were inserted as raw HTML. They are now escaped, so a name like `<b>Tag</b>` shows as text.

## Files

- New: `static/primp/pubcast.mjs` (store client), `tests/primp/pubcast.test.mjs`, `tests/primp_chromium/test_pubcast_store.py`, this note.
- Changed (additions only, no existing wording changed): `static/primp.html` (picker, Send button, Send dialog), `static/primp/app.mjs`, `static/primp/primp.css`, `static/avatar_import.html`, `tests/primp_chromium/conftest.py` (the live-host fixture also yields its `data_dir`).
- New on-screen wording, written by Claude, the owner's to change: "PubCast avatars…", "No PubCast avatars yet", "Send to PubCast", the Send dialog's sentences, "Open in Primp", the status messages in `sendToPubcast`, and the default new-avatar name "<name> (Primp)".

## Tested (executed 2026-11-27, Linux, Node 22.23.5, Python 3.13.18, Google Chrome with SwiftShader WebGL)

- `node --test tests/primp/*.test.mjs tests/test_voxel_block_preview_client_node.js tests/test_foresight_file_close_node.js`: 43 passed, 0 failed (was 36; the 7 new ones are `pubcast.test.mjs`).
- `python -m pytest tests/primp_chromium --browser chromium` (with `PLAYWRIGHT_CHROMIUM_EXECUTABLE`, `AXE_CORE_PATH`): 19 passed. The 14 original tests passed before and after the change. The 5 new ones run against a real host and a real browser: open via link and via picker; paint; Cancel sends nothing; Send makes exactly one new avatar with the right name, character, height and provenance; the original's bytes are unchanged; the sent GLB is different and stands at the same height; the world manifest lists both; reopening the sent avatar shows the paint; a saved look reopens and still sends at the right height and character; a prepared base sends at its own standing height; a wrong height is refused with the server's reason and the work stays open; Import Avatar's link opens the avatar in Primp and shows names as text.
- `tests/test_primp_host_integration.py`, `tests/test_avatar_imports.py`, `tests/test_saves_survive_restart.py`: passed.
- `tests/test_avatar_import_browser.py`: 8 passed on this branch and 8 passed on untouched main-assembly. Its fixture looks for Playwright's bundled headless shell, so locally `PLAYWRIGHT_BROWSERS_PATH` pointed at a folder holding a link to the installed Chrome. That is a local setup step, not a repo change.
- `git diff --check`: clean.

## Not tested / still open

- The world actually drawing a Primp-sent avatar in a room. Verified only that the manifest lists it with the right character and height. The world reading that manifest is existing, separately tested code, not re-run here.
- Real Windows/phone browsers, a real pen, the native save picker, a hardware GPU.
- Whether the world should offer the made-up avatar as a "look" of the same character rather than as a separate avatar. Today the store and manifest treat it as its own entry that shares the `character_id`. Owner decision.
- Primp's own open items in `SESSION_ENDING_HANDOFF.md` and `CHROMIUM_ACCEPTANCE_2026-11-09.md` are unchanged by this work (live-face tracking, Filler Cream and Dremel inside Primp, teaching library).

## Next step

Owner reviews and decides whether to merge `claude/primp-to-main-assembly-2026-11-27` into `main-assembly`.

---

# Addendum, same evening: side button between the boudoir and the mirror and stage

The owner asked for a clearly labeled button on the side of the screen, so an avatar can be adjusted at the mirror and stage and made up in the boudoir, switching back and forth while designing it. Her words: "you need to be able to switch between the two, so you can adjust your avatar or do your avatar's makeup as you're designing them." Icons are her choice: "a makeup brush and a tailor's mannequin." She then said: "If the maker process difficult, try lipstick." Both the brush and a lipstick icon are drawn. The brush is in use until she picks one. Switching is one word: `icon: 'brush'` → `icon: 'lipstick'` in the `mount` call at the end of `static/avatar_foundry.html`.

## What is where

- `static/js/dressing_switch.js` (new): the button. The icons are drawn in it (makeup brush, lipstick, tailor's dress form), so there are no image files. The page keeps a clear strip on the right edge (`body.dsw-reserve`), so the button never covers a control. The button is vertically centered at every size, clear of the bottom corners where the production-slate button sits. It opens the other page in the same window, so a Counter tray stays a tray.
- Primp (`static/primp.html`, `static/primp/app.mjs`): the mannequin button, labeled "Mirror and Stage", goes to `/static/avatar_foundry.html`. Before leaving, the open look is written to Primp's local recovery. Coming back through the button restores it automatically, still marked unsaved if it was unsaved. If recovery fails and the look is unsaved, Primp asks before leaving.
- Avatar Foundry (`static/avatar_foundry.html`): the brush button, labeled "Boudoir", goes to `/static/primp.html`. Before leaving, it waits for the page to finish loading the saved profile, then keeps the form (form, name, glow, energy, hologram mode, visibility) as a draft in this browser tab, and puts it back on return. Leaving does not save to the server; Save Avatar still does that. Edits sit at the end of the file and merge with zero conflicts with `claude/avatar-from-image-2026-11-27` (checked with `git merge-file`).
- Which Foundry: `avatar_foundry.html`, the page Primp already linked to and the one the avatar-from-picture session extended today. Other Foundry pages exist and were not changed: `dressing_foundry.html` (not served directly), `avatar_studio_demo.html` (what the classic world's pop-up opens), and the walkable world's "Avatar Foundry" exit (`world.json` room `avatar_foundry`, no views yet).
- Labels "Mirror and Stage" and "Boudoir" and the hover titles are Claude's wording, the owner's to change.

## Problems found in the Foundry page, NOT fixed (owner decision; another session is working on this page)

1. It does not load `/static/reach_auth.js`, so with sign-in enforced its profile load and save go out without a token.
2. Picking a form never saves: the page sends `preset`, and `POST /api/avatars/me` reads only `preset_id`. Also `loadMe` merges `preset_id` but the page reads `preset`, so the highlighted form after load is always Manny.
3. `POST /api/avatars/me` does not store energy, hologram mode or visibility.
4. "✓ Saved" shows even when the save request fails (`saveAvatar` never checks the response).

## Tested (executed)

- `tests/primp_chromium/test_dressing_switch.py`, 8 passed: a painted Primp look goes to the Foundry and back pixel for pixel and still counts as unsaved; Foundry choices (name, energy, mode, glow, visibility, form) go to Primp and back; the button covers no control on Primp or the Foundry at 1440×900, 1280×720 and 390×844.
- Full set after the change: Node 43/43; `tests/primp_chromium` 27/27 (14 original + 5 store + 8 switch); `test_primp_host_integration`, `test_avatar_imports`, `test_saves_survive_restart` 39/39; `test_avatar_import_browser` 8/8; `git diff --check` clean.

## Not tested

- The button inside a Foresight Counter tray (same-window navigation is the design; the tray was not run).
- The two Foundry pages still do not share one avatar (Primp paints a stored GLB; the Foundry edits the preset profile). Open question to the owner, unanswered: should both work on the stored 3D avatar?
