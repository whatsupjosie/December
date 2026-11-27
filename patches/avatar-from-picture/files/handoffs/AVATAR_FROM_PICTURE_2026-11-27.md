# Avatar from a picture — 2026-11-27

Branch: `claude/avatar-from-image-2026-11-27`, made from `main-assembly` (base commit `c8a4d2a`). `main` is untouched. Nothing was deleted.
Evidence folder: `handoffs/avatar_from_picture_2026-11-27/`. Everything in it was produced by the code on this branch; the two fresh characters
are the pictures already in `tests/fixtures/avatar_likeness/fresh/`, and Humphrey is the benchmark pair in `tests/fixtures/avatar_likeness/humphrey/`.

## What Josie asked for

In her words: "I want them to look like the same fucking character. So far, I don't think we can do that. I know we can't do that."
And: "Look at a reference image and create a very, very extremely similar 3D mesh rigged version that we can use in our motion capture
software, so we can accurately capture its movements and translate a real person's physical performance onto that avatar."
Heights she gave: Humphrey "just under 3 feet tall, the baby", Pete 5'7", Repeat 5'9". A pub block is 10 in. The builder takes the height
as an input and reports it in pub blocks (Humphrey was built at 35 in = 3.52 blocks; Pete 67 in = 6.70; Repeat 69 in = 6.91).

## Short answer (read this first)

- **Front view: yes, close.** Built from one picture, with no model files for Pete and Repeat, the front of the avatar overlaps its own
  picture at 0.926 (Pete) and 0.932 (Repeat); Humphrey, whose picture is not a T-pose, overlaps his drawn pose at 0.922. Colours are the artwork.
- **Side and back: no.** One picture does not contain them. The side is the front picture smeared over a thin shell; the back is a guess painted
  from the front's colours. Against the one real back reference we have (Humphrey's Runway clip) the back is about 19–22 Lab units away in
  average colour. This is the gap that decides "the same character", and nothing on this branch closes it.
- **Motion: yes, for Pete and Repeat.** A recorded performance (the bundled mannequin's run, walk, agree, sneak clips) retargets onto them
  and reads as the same movement. For Humphrey it moves, but his arms stretch badly (see gaps).
- **Control:** the editor page lets a person drag joints, change thickness per part, height, hair colour and the back view, undo, keep every version, and save
  to the avatar library. A moved joint and a thickness change survive export and reimport (tested).
- **Live capture was not tried.** No camera or landmark stream exists in the sandbox.

## What the old workflow does (RAN, same three pictures, real host, real login)

Dressing Room "Bake" on each picture: the page says "Portrait baked — skin: auto, face detected: no". The host returns a skin colour taken
from the picture's grey background (Pete `#a4a29f`, Repeat `#9d9790`, Humphrey `#6a543f`) and a voxel count of 3. Studio then shows the same
generic 5'8" green flat figure for every character, Humphrey included. Nothing from the picture reaches Studio. Screenshots and the raw
records: `old_workflow/<name>_old_*.png`, `old_workflow/<name>_old_workflow_record.json`. Recorder: `tools/avatar_likeness/baseline_old_workflow.py`.

## What was built (exact paths)

| Piece | Path |
| --- | --- |
| Image → rigged avatar pipeline: intake/cut-out, landmarks, skeleton fit, parts and skin weights, shell, rig bake to T-pose, texture atlas, clips, glTF with the recipe in `asset.extras.pubcast_likeness` | `modules/avatar_likeness/` (`intake, matte, landmarks, skeleton, parts, shape, rig, texture, motion, gltf_io, pipeline, retarget, analysis, routes`) |
| Routes under `/api/avatars/likeness/…` (status, drafts, edit, select version, recorded motion, save to library, delete) | `modules/avatar_likeness/routes.py` |
| The editor page at `/avatar-from-picture` and a card on the Foundry page that links to it | `static/avatar_from_picture.html`, `static/avatar_foundry.html` |
| Art-analysis checks: proportion, silhouette overlap, palette, ink-outline loss, turn stability, per-triangle stretch in a clip, how much of the picture is used at each view angle | `modules/avatar_likeness/analysis.py` |
| Evidence tools | `tools/avatar_likeness/compare.py` (picture / old / new, angles, walk-and-turn in Studio), `mocap_demo.py` (recorded performance on each avatar), `ab_back.py` (old vs current back against the clip), `baseline_old_workflow.py`, `render.py`, `viewer.html` |
| Tests | `tests/test_avatar_likeness.py`, `…_analysis.py`, `…_routes.py`, `tests/test_avatar_from_picture_browser.py` |
| Optional extras list | `requirements-avatar.txt` (nothing is installed or downloaded at startup) |

### Changes outside this department — flag for whoever owns integration

1. `main.py`: the likeness router is mounted after the avatar-import router; route `/avatar-from-picture`; a 64 MB body limit for `/api/avatars/likeness/`. Eight inserted lines.
2. `static/avatar_foundry.html`: one added card linking to the new page. The Photo Portrait card is untouched.
3. Not changed, but found (please decide): the repo's motion consumer clamps each bone's Euler angle to ±35°, which cannot carry full-body capture on a T-pose rig; the
   retarget path on this branch (world-orientation transfer from a Mixamo-style GLB) does not use it. Pete's height is 68 in in the repo's `DEFAULT_HEIGHTS` and
   `data/avatars/canonical_heights.json` (RePete 70) and the Studio list shows Pete 5'8", RePete 5'10"; Josie said 5'7" and 5'9", and says "Repeat". See `tests/fixtures/avatar_likeness/CAST_HEIGHTS.md`.
4. Pre-existing, not caused here: six host tests fail identically on base commit `722b3e8`, and a TestClient teardown error. The sandbox had a FastAPI/Starlette mismatch against the repo's pins; installing the pinned versions fixed that.

## How Josie repeats it herself (PowerShell 5)

Install the extras once, on purpose: `python -m pip install -r requirements-avatar.txt`
Optional, better results, only if the files are placed by hand: `$env:PUBCAST_AVATAR_MATTE_ONNX = "C:\models\isnetis.onnx"` (cut-outs on dark or busy backgrounds; Humphrey needs it) and `$env:PUBCAST_AVATAR_POSE_TASK = "C:\models\pose_landmarker_heavy.task"` (joint detection on adult T-pose photos).
Start PubCast the usual way (`python run_reach.py`), sign in, open Avatar Foundry, choose "Avatar from a picture" (or go to `/avatar-from-picture`).
1. Drop the character picture in, type the name, set the height in feet and inches (the page shows pub blocks), pick the build, and choose Build.
2. Read the warnings and "what a single picture cannot show". Drag any joint that sits off the body (gold = yours, blue = measured from the cut-out, green = detected, grey = template). Apply.
3. Use the thickness sliders for parts that are flatter or deeper than a rounded body. Use the back-view setting for the back (`custom` takes a painted back picture; that is the real fix for a wrong back).
4. Turn the figure with Front / Side / Back / Turn; play Idle and Walk. "Recorded motion" puts a recorded clip (or your own Mixamo-rigged GLB) on it.
5. Save to library. It re-measures the height and feet before accepting.
Every Apply makes a new version; nothing is deleted; Undo and the version buttons go back.

The evidence for any picture, from the repository folder: `python tools\avatar_likeness\baseline_old_workflow.py PICTURE.png OLD_DIR` then `python tools\avatar_likeness\compare.py --name NAME --image PICTURE.png --height-in 67 --old OLD_DIR --out OUT_DIR` then `python tools\avatar_likeness\mocap_demo.py --out OUT_DIR --avatar NAME=OUT_DIR\NAME.glb`.
These need Playwright with Chromium and `ffmpeg` on the PATH; they run with software graphics.

## Evidence (all RAN on this branch, 2026-11-27)

| | Humphrey (35 in) | Pete (67 in) | Repeat (69 in) |
| --- | --- | --- | --- |
| Picture pose | relaxed, not a T-pose | T-pose | T-pose |
| Cut-out network used | yes (classic cut-out fails on his dark background) | no | no |
| Joints | all 20 from the template (detector found no person in the cartoon) | 8 measured from the silhouette, 12 template | same |
| Front vs own picture, silhouette overlap | 0.922 (middle third 0.917) | 0.926 (lower third 0.858) | 0.932 (lower third 0.873) |
| Triangles that ever grow or shrink > 2.5x vs the bind pose, Idle / Walk | 7.2% / 9.6%, worst 662x / 1249x, arms 36–43% | 0.04% / 0.11%, worst 3.1x / 5.0x | 0.06% / 0.86%, worst 3.6x / 10.7x |
| Picture used well at 90° / smeared / hidden | 32% / 19% / 49% | 31% / 18% / 50% | 29% / 20% / 50% |
| Share of what is on screen that is the generated back, at 90° / 180° | 47% / 96% | 46% / 100% | 46% / 100% |
| Studio walk and turn: height drift; lowest frame-to-frame overlap | 5.4%; 0.81 | 6.9%; 0.45 | 7.1%; 0.28 |

Files per character in the folder: `NAME.glb` (the rigged asset, 25 bones, Idle and Walk), `NAME_angles.png` (picture | old workflow | new at 0/45/90/135/180°, rest pose and Idle),
`NAME_walk_turn.mp4` (picture | old workflow | new walking and turning in the real Studio player, plus the Runway clip for Humphrey), `NAME_metrics.md` / `.json`,
`NAME_angles_before_back_change.png` and `NAME_metrics_before_back_change.md` (the same before the back change below). Humphrey also has `humphrey_reference_views.png` (clip frames beside the new avatar at the same turn).
Mocap: `mocap_run.mp4`, `mocap_{run,walk,agree,sneak_pose}_sheet.png`, `mocap_report.json` — the recorded performer next to all three avatars at the same instants.
Back A/B against the clip: `ab_back.json`, `ab_back.png`.

### Mocap result

The recorded run, walk, agree and sneak clips were retargeted onto all three avatars with the editor's own code and written into the files as `Mocap_<clip>`. In the run clip, which I looked at frame by frame, Pete and Repeat follow the performer's
legs, hips and arms recognisably. The walk, agree and sneak sheets are in the folder; I did not review them frame by frame. Humphrey moves but is a bust: his picture ends at the shoes, his coat covers his short legs, and his arms stretch into flat brown shapes when they swing.
The clips are recorded, not live.

### The back change made in this session (a judgement call — Josie, your decision)

The generated back used to carry blurred copies of front-only details: Repeat's shirt print, Pete's neckline. `texture._flatten_regions` now reduces the back of the outfit to a few colours and merges any
colour patch smaller than a quarter of the body part it sits on (not the head, not the hands, not the bottom 14% of the figure, so boots keep their colours). Pete's and Repeat's backs are visibly cleaner
(`*_angles.png` against `*_angles_before_back_change.png`; 2 tests). **Against the only real back reference, Humphrey's clip, it did not help:** mean-colour distance for the two back-turned frames went from 18.6 to 19.9 and 21.1 to 22.0 Lab units (the side frame at 80° went from 4.4 to 3.9);
outlines overlap identically (`ab_back.json`). If a real back has a print, flattening it away is wrong too. To turn it off: set `BACK_PALETTE = 0` in `modules/avatar_likeness/texture.py`. The `mirror` back keeps every front detail; `custom` takes a real back picture.

## Quality gaps still visible (specific)

1. **Sides.** A thin slab with the front picture smeared over it and a dotted line down the middle where the front and back halves meet. At 90° only about 31% of the picture is used at full sharpness. Depth is a rounded-body prior (Pete's torso is 0.126 of her height deep); it is not read from the picture.
2. **Backs.** Guessed from the front's colours. Humphrey's from behind is a brown patchwork where the clip shows a cream coat and a hat with a brim; its colour is ~20 Lab units off (above).
3. **Humphrey's arms.** His picture is relaxed, the joints are template, and baking his drawn pose to a T-pose swings the arms a long way: the coat grows "wings" in the T-pose and arm triangles stretch up to 1249x when the arms move (NAME_angles.png, rest row). The page warns "Check the shoulders and elbows in the editor." Dragging the joints is the intended fix; I did not hand-place his joints to show it. His arm joints cannot be measured from the silhouette the way a T-pose's can (arms overlap the coat).
4. **Humphrey's legs and shoes.** The benchmark picture is cropped at his shoes, so the avatar's legs end where the picture ends and the shoes are closed off. This is the input's limit.
5. **Hands and feet.** In motion the hands are thin flat strips. Ball and Toe joints control no vertices, so toes do not bend (feet are flat pads). The side-hem of Repeat's jeans tears at the thigh in one run frame (his Walk: 0.86% stretched triangles, worst 10.7x).
6. **Ink outlines.** Humphrey's outline along the edge is 15% weaker than in his picture; from the side there is no outline mesh, so inked silhouettes do not read as inked.
7. **Studio walk-and-turn jumps.** The lowest frame-to-frame overlap (0.28 Repeat, 0.45 Pete) is at the instants the walking direction flips, and also mid-stride in the side view where crossing legs change a thin silhouette quickly. I did not separate how much is the Studio player's turn and how much is the avatar. UNKNOWN.
8. **Relaxed or A-pose pictures** other than Humphrey's were not tried; their arm joints come from the template only.

## What I tried that failed or was wrong (so nobody repeats it)

- Classic cut-out on Humphrey's dark picture: failed (cut the figure with the background); the cut-out network (`isnetis.onnx`) fixed it. Offline, with no model, a dark picture will warn or fail in plain words.
- Template arms for the fresh T-pose characters missed the drawn arms; Hand joints had no skin. Fixed by measuring the arms from the cut-out (`landmarks._tpose_arms`) and by a test that every bone that can move has skin.
- The pose detector (MediaPipe) on Humphrey: ran, found no person in the cartoon baby; joints stayed template. It is used on T-pose adults and refused on toddlers (test).
- My first comparison tool compared Humphrey's T-pose bind pose to his relaxed picture (overlap 0.82, "57% too wide") — wrong comparison, fixed to use his drawn pose (0.92). My first clip comparison searched every turn angle for the best silhouette overlap and picked a side view for a front frame — dropped for stated nominal angles judged by eye.
- The palette distance in `NAME_metrics.md` comes from k-means and moved from 4.7 to 1.3 on a front frame that did not change between two runs; UNEXPLAINED. Use the mean-colour numbers in `ab_back.json`, the silhouette overlaps, and your eyes.
- First back flattening turned Pete's boots teal and one of Repeat's boots olive; fixed by excluding the bottom of the figure and colouring each patch by its own median.

## Ledger

RAN (this session, Linux sandbox, Python 3.13, software WebGL):
- `tests/test_avatar_likeness.py`, `…_analysis.py`, `…_routes.py`, `tests/test_avatar_from_picture_browser.py`: see the result line at the end of this file.
- The two tests that need optional model files, with the files present: cut-out network rescues a dark background; pose detector is used on a T-pose adult and refused on a toddler: 2 passed.
- The browser test runs the real host (`run_reach.py`) on a throwaway data folder: build from a picture, edit, quit, restart, reopen the draft, save to the library.
- Edit survives export and reimport: `test_a_moved_joint_and_a_depth_change_survive_export_and_reimport` (Pete) and the browser test.
- Recorded clips survive a rebuild; rebuild refuses a file that was not made here; a failed write leaves the previous version in place (route tests).
- Old workflow baseline on all three pictures; comparison, walk-and-turn in Studio, mocap transfer, back A/B.

WROTE, NOT RUN: nothing known.

NOT RUN / UNKNOWN:
- Live capture (webcam or landmark stream) into the avatars, and the repo's live path `avatar_performer.MocapRetargeter` → Studio (±35° consumer).
- Windows / PowerShell 5 on Josie's laptop; native file chooser; real GPU speed. The tools and page ran on Linux with software graphics only.
- Hosted or local generative view synthesis (Qwen-Image-Edit, Hunyuan3D, TripoSR) for real side and back views: not run (no access from the sandbox). This is the most likely route to the side and back; `custom` back is where its output would go.
- Relaxed-pose pictures other than Humphrey; characters that are not humanoid; pictures with two characters.
- The Counter commissioning goal in `CLAUDE.md` (this branch does not touch the Counter).
- A full-suite run of the repository. Only the avatar tests and the neighbours listed below were run.

## Test results at the end of this session (2026-11-27)

- Avatar tests, final code: `python -m pytest tests/test_avatar_likeness.py tests/test_avatar_likeness_analysis.py tests/test_avatar_likeness_routes.py tests/test_avatar_from_picture_browser.py` → 70 passed, 2 skipped in 165 s. The 2 skipped need the optional model files; run with `PUBCAST_AVATAR_MATTE_ONNX` and `PUBCAST_AVATAR_POSE_TASK` set, `-k "cutout_network or pose_detector"` → 2 passed.
- Neighbouring tests (selected with `-k "avatar or foundry or import or host or main"`, avatar files excluded; 3,020 tests deselected, so this is not the full suite): 321 passed, 5 skipped, 33 failed, 4 errors in 565 s. The same 37 tests (in `test_hosted_adapters_audit.py`, `test_evo_host_backend.py`, `test_evo_semantic_prosody_tick.py`, `test_alex_keyword_matching.py`, `test_post_baseline_integration.py`, `test_pubpartner_cartridge_memory_wiring.py`, `primp_chromium/test_mirror.py`) fail identically on a clean checkout of the branch's base commit `c8a4d2a`. None is in avatar code. I did not investigate why they fail.
- Not run: the full repository suite.
