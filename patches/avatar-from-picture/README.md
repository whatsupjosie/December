# Avatar from a picture (Nov 27, 2026), parked

Not installed. Parked here Nov 27, 2026 because it is in progress and not in main-assembly.

Source: December branch `claude/avatar-from-image-2026-11-27`, tip fc91915a3a831e3037c269e8f5255b74cc909576. It was made from main-assembly at 722b3e8be676c65c7924ff4d2d2bc882708d8721 (that commit is in main-assembly) and adds 7 commits by Claude, all dated Nov 27. The branch itself is still there, untouched.

What it is, in short (READ from its own handoff, `files/handoffs/AVATAR_FROM_PICTURE_2026-11-27.md`, which has the full results): a builder that turns one character picture into a rigged 3D avatar, an editor page at `/avatar-from-picture`, and a way to put recorded motion on it. Its handoff says the front comes out close to the picture, but the side and back can't, because one picture doesn't show them. Live capture was not tried.

## How it is laid out here

- `files/<path>`: the 77 files the branch adds, each at its main-assembly path under `files/`, exact copies (same Git blobs). This includes the test pictures, the evidence folder (models, renders, videos) and its handoff.
- `changes-to-existing-files.diff`: the branch's changes to three files main-assembly already has: `STATUS.md`, `main.py` (mounts the routes, 8 lines) and `static/avatar_foundry.html` (one card). Made with `git diff 722b3e8 fc91915` on those three files.

To install later (only when she says): copy `files/` over main-assembly and apply the diff. Main-assembly has moved on since 722b3e8, but those three files were unchanged there when checked on Nov 27; check again before applying.

## Its own flags for whoever integrates (READ from its handoff)

- The repo's motion consumer clamps each bone to ±35°, which can't carry full-body capture; this branch doesn't use that path.
- Pete's and Repeat's heights in the repo (68 in and 70 in) differ from what Josie said (5'7" and 5'9").
- The back view is a guess from the front's colours, and the back flattening it adds is called out there as her decision.

Nothing was run for this copy.

## Commits

| Commit | Message |
| --- | --- |
| c8a4d2a | Add Humphrey likeness benchmark pair as fixtures (evaluation reference only) |
| 226b94d | avatar_likeness: image to rigged avatar pipeline (intake, landmarks, skeleton, parts, shape, rig, texture, motion, glTF, viewer) |
| 8e11513 | avatar_likeness: retargeting from recorded clips, midline leg cut, deterministic builds, lossless rebuild, tests |
| 9b8d501 | avatar_likeness: draft/edit/undo/mocap/save routes, mounted beside the avatar import routes |
| a99d832 | avatar_from_picture page: build from a picture, drag joints, thickness/back/hair/height edits, versions, recorded motion, save to library |
| d15caaf | avatar_likeness: measure T-pose arms from the cut-out, art-analysis checks, old-workflow baseline recorder |
| fc91915 | avatar_likeness: generated back drops front-only prints, comparison and mocap evidence tools, handoff |
