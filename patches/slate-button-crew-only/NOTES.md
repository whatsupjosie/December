# Slate launcher button: finding and proposed fix (Nov 26, 2026)

## Her decision (Nov 26, 04:21 UTC)

Both fixes, and performers too. Her words, answering the question "should performers who aren't crew ever see the slate": "Performers too". That was a pick on a chip, not a yes to commit, push or install.

Performers in the code (READ): sign-in has no performer or cast role. The account roles are modules/chat_rooms.py ROLE_RANK (guest, friend, crew, security, mod, owner) and modules/auth.py ROLE_ORDER (guest, viewer, mod, admin, owner). "cast", "actor" and "performer" appear only as end-credit line types in modules/credits_export.py and as avatar or character performers, never as a login role. The slate's "Actors" field is free text (names), not account IDs. So no role was invented. Performers get the button the way the slate already names people: the director lists them on the roll call (departments, "Cast = account ID"), and fix 1 already gives the button to anyone on the roll call while a production is open. With no production open the button can only open a new production, which only mod, admin or owner may do, so a performer would only get a refusal there.

Her follow-up pick (Nov 26, 04:41 UTC), answering whether the roll call is enough for performers: "Roll call is enough". No performer role added; the patches stand as they are.

Changed for this: the floor_crew() docstring says this, and the fix-1 test now also checks a viewer-role performer listed as "Cast". fix-2 is unchanged.

Proposal only. Nothing was committed, pushed or opened as a PR. Every file here is a patch waiting for Josie's okay.

## What was read

- Repo whatsupjosie/pre-dec, branch claude/studio-assembly-2026-11-23, commit 2541c0936155f1ff6158d3cf816e6b208c5caabe (READ).
- Same files compared on claude/studio-wire-avatars-2026-11-23, claude/eq-foundations-2026-11-23, claude/studio-line-missing-fixes-2026-11-24 and claude/integrate-strongest-parts-2026-11-24: static/studio_slate.js and static/studio_slate.css are byte-identical (md5) to the Nov 23 branch, so the issue is unchanged there (VERIFIED by checksum).
- pre-dec main (538a40f) and December main and main-assembly have no studio_slate.js at all (VERIFIED). That is why the eight checks pass on main: there is no slate overlay there.
- The branch's own handoff, handoffs/STUDIO_ASSEMBLY_2026-11-23.md, "Known and not fixed", first bullet, already records this regression and the three options. It says it was READ and RAN there.

## The finding (verified by reading; the browser tests were NOT run here)

1. modules/studio_slate.py, SlateOverlayMiddleware (near the end of the file): injects studio_slate.js and studio_slate.css into every HTML page except the Foresight Counter (SLATE_EXEMPT_PATHS).
2. static/studio_slate.js line 130 (inside render()): `launcher.hidden=false;` runs for every signed-in caller whose GET /api/studio/slate succeeds, slate or no slate. With no production open the button reads "Open production slate".
3. static/studio_slate.css: `#pubcast-slate-open{position:fixed;right:14px;bottom:14px;z-index:2147482999;...}`.
4. static/human_profile.html line 10: `.profile-actions{position:fixed;z-index:20;bottom:0;left:0;right:0;...}`, line 28: Save then "Skip optional details". On a 390 px phone, Skip is the right-hand button in that bar, so the launcher sits over it (GEOMETRY REASONED from the CSS, not measured).
5. The eight failing checks (tests/test_human_profile_onboarding_browser.py, 6, and tests/test_human_profiles_browser.py, 2) all run on /static/human_profile.html, signed in as the first-setup account. modules/auth_routes.py line 150 gives that account role "owner" (VERIFIED).

So the claim is true, with one correction that matters: a crew-only launcher does not fix those eight checks, because the account they sign in as is the owner, and the owner is crew.

## How the code tells crew from members (existing, nothing invented)

- modules/chat_rooms.py ROLE_RANK: guest 0, friend 1, crew 2, security 3, mod 4, owner 5. The studio, control room, director and teleprompter rooms require "crew".
- modules/route_security.py require_role("crew") uses that table.
- modules/auth.py ROLE_ORDER is the older table (guest, viewer, mod, admin, owner). The slate's own "create" rule uses it: role_gte(role, 'mod').
- The slate also names people regardless of role: director_id, editors (delegated assistants; tests/test_studio_slate.py line 40 has a viewer-role editor) and departments (assigned check-ins, viewer role in the tests).

## The two patches

- fix-1-crew-only-launcher.diff (what the task asked): new floor_crew() in modules/studio_slate.py; GET/POST /api/studio/slate now also return floor_crew; studio_slate.js line 130 becomes `launcher.hidden=!snapshot.floor_crew;`. True for crew and up (ROLE_RANK), anyone who may open a production (mod, admin, owner), and, while a production is open, its director, editors and department assignees, so a cast member assigned a station can still reopen the board to check in. Members otherwise still see the floor whenever the director shows it on every screen; only the button changes. The in-page "Production slate" buttons on crew pages keep working (they call PubCastSlate.open()). Adds one test.
- fix-2-exempt-sign-in-and-profile-pages.diff (the part that fixes the eight checks): adds /login, /static/login.html and /static/human_profile.html to SLATE_EXEMPT_PATHS, the same way the Counter is exempt. Cost: a director's "show on every screen" roll call will not appear on those three pages. Adds one test.
- combined-both-fixes.diff: both together. The two single patches each apply alone but not one after the other (both append to the end of the test file), so use the combined one for both.

## Why not "move the button"

The profile action bar spans the full width of the bottom of the screen, so the bottom-left corner covers Save instead of Skip, and any other fixed spot covers something on some page. Moving it cannot promise it never covers a control.

## Tested / untested ledger

- RAN after her yes to install (Nov 26, ~04:45 to 05:00 UTC), in a throwaway Python environment in this sandbox only, with fastapi 0.115.14 (starlette 0.46.2), httpx 0.28.1 and playwright 1.56.0:
  - tests/test_studio_slate.py with the combined patch: 10 of 10 passed (the eight that were there plus the two new ones), in the runs that finished.
  - The two new tests on the unpatched branch: both FAIL (no floor_crew in the answer; the overlay is still added to /login, /static/login.html and /static/human_profile.html). So they test the fix, not nothing.
  - One older test, test_live_voice_only_verified_director_can_transmit, sometimes hangs. Run alone five times WITHOUT the patch it hung 5 of 5; with the patch it hung 4 of 5. So the patch did not cause it. GUESS, not diagnosed: this sandbox's library versions or timing (its send step drops a listener after 0.25 s, and the test then waits forever). The handler it exercises does not call anything the patch changed.
  - NOT RUN: the eight browser checks and tests/test_recorded_sync_browser.py. Chromium could not be installed: this sandbox points Playwright's browser download at a dead address on purpose, and its preinstalled browser folder is empty. I did not go around that block.
- RAN again after her pick: floor_crew() against the real tables: guest, viewer, friend, and the made-up role names performer and cast (to prove no such role sneaks in) get no button with no production open; crew, security, mod, admin, owner do. With a production open: editor, Camera assignee, Cast (performer) assignee and director yes; an unlisted viewer no. After end: the assignees no.
- RAN: python py_compile on the changed Python files, node --check on studio_slate.js; floor_crew() run against the repo's real ROLE_RANK and ROLE_ORDER tables: guest, viewer, friend and no role get no button; crew, security, mod, admin and owner do; with a production open, a viewer-role editor and a viewer-role department assignee do, an unrelated viewer does not; after "end", the assignee does not.
- (Superseded by the run above.) Before her yes, nothing needing fastapi, playwright or Chromium had run.

## To try it on her laptop (PowerShell 5), from the pre-dec folder

git checkout claude/studio-assembly-2026-11-23
git apply --check C:\path\to\combined-both-fixes.diff
git apply C:\path\to\combined-both-fixes.diff
python -m pytest tests/test_studio_slate.py tests/test_human_profile_onboarding_browser.py tests/test_human_profiles_browser.py tests/test_recorded_sync_browser.py

To undo before committing: git checkout -- modules/studio_slate.py static/studio_slate.js tests/test_studio_slate.py
