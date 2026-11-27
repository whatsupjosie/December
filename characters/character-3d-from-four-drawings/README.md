# 3D character from her four drawings, unrigged v1 (Nov 19, 2026)

Parked here Nov 27, 2026 because the work is waiting on her. Not installed anywhere.

## Where it stands

- Built Nov 19 directly from her four drawings (front, back, two sides), not by an AI 3D generator. How, and its known gaps, are in NOTES.md (copied unchanged).
- Josie's verdict on Nov 19: "hideous". So nothing was rigged.
- Waiting on her: whether to try TRELLIS (a Hugging Face image-to-3D tool) on her own Hugging Face account, or stop. Nothing has been run on her account.
- Which character this is was never confirmed. NOTES.md guesses Pete from where similar sheets sit in Beyond-October.

## Files and where they came from

| Here | Copied from (unchanged) |
| --- | --- |
| NOTES.md, character-unrigged-v1.glb, comparison-sheet-v1.png, three-quarter-views-v1.png, reference/ (her 7 drawing files), renders/ (6 renders of the GLB) | project folder `character-3d/` (files dated Nov 19) |
| build/src/*.py (align, build, check_shape, export, rast, render, texture) and build/*.npz (aligned, masks, uvmesh) | the build scripts and data saved by the Nov 19 session that made it |

The build scripts read and write temporary folders of that session (`/tmp/claude-0/w/` and `/tmp/claude-0/src`), so they will not run as they are; they are here so the method is kept. Their imports: numpy, trimesh, fast_simplification, xatlas, numba, scipy, scikit-image and Pillow. That session's own working notes were not copied.

A newer avatar-from-a-picture builder (Nov 27) is parked in `patches/avatar-from-picture/`.

Nothing was run for this copy.
