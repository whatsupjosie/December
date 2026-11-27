# Slate launcher button: crew only, and off the sign-in and profile pages (patch)

A patch, not installed. Parked here Nov 27, 2026 because it was waiting.

The problem (READ in NOTES.md): the "Open production slate" button floats over onboarding's "Skip optional details" on a phone, and 8 browser checks fail on the studio line.

Her picks on Nov 26 (in NOTES.md, her words on chips): "Performers too" and "Roll call is enough". Those were picks, not a yes to commit or install.

## Files

- NOTES.md: the finding, her picks, what was read, what was and wasn't run. Copied unchanged.
- fix-1-crew-only-launcher.diff: shows the button only to crew and to people on the roll call.
- fix-2-exempt-sign-in-and-profile-pages.diff: keeps the slate off sign-in and profile pages.
- combined-both-fixes.diff: both together.

All four were copied unchanged from the project folder `pubcast/slate-button/` (dated Nov 26).

## Where it applies

The patches are written against pre-dec branch `claude/studio-assembly-2026-11-23` at 2541c0936155f1ff6158d3cf816e6b208c5caabe. December main-assembly's `modules/studio_slate.py` does not have this fix (it has no `floor_crew`, checked Nov 27). Whether the patches apply cleanly to main-assembly was not tried.

## Tested and not tested

- Ran earlier (Nov 26, per NOTES.md): tests/test_studio_slate.py, 10 of 10 passed with the combined patch, "in the runs that finished". One older test there sometimes hangs with or without the patch; NOTES.md has the counts.
- Not run: the eight browser checks, because Chromium could not be installed in that session.
- Nothing was run for this copy.
