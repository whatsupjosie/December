"""Evidence for one character: the picture, what the old workflow gave, what the new workflow gives, at rest and in motion.

    python tools/avatar_likeness/compare.py --name pete --image PICTURE.png --height-in 67 --old OLD_DIR --out OUT_DIR
        [--video RUNWAY.mp4 --video-frames 1,56,67,89,111] [--models MODELS_DIR] [--back-mode plain]

Writes into OUT_DIR:  NAME.glb  NAME_angles.png  NAME_walk_turn.mp4  NAME_metrics.json  NAME_metrics.md  [NAME_reference_views.png]
OLD_DIR is the folder tools/avatar_likeness/baseline_old_workflow.py wrote for the same picture.
Needs Playwright with Chromium (software WebGL), ffmpeg on PATH, and the packages in requirements-avatar.txt.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from modules.avatar_likeness import analysis, intake, matte, pipeline  # noqa: E402
from tools.avatar_likeness.render import Studio, over  # noqa: E402

ANGLES = (0, 45, 90, 135, 180)
FPS = 24
TILE_W, TILE_H = 440, 440            # one view in the angle sheet; square because a T-pose is about as wide as it is tall
RENDER = dict(w=660, h=660, halfH=0.58)
OLD_STUDIO_CROP = (330, 280, 610, 725)       # the flat figure in the Studio screenshot baseline_old_workflow.py takes (1280x900)


def font(size: int):
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def captioned(img: Image.Image, text: str, bg=(24, 22, 19), fg=(232, 223, 207)) -> Image.Image:
    bar = 34
    out = Image.new("RGB", (img.width, img.height + bar), bg)
    out.paste(img.convert("RGB"), (0, bar))
    ImageDraw.Draw(out).text((8, 6), text, fill=fg, font=font(18))
    return out


def fit(img: Image.Image, w: int, h: int, bg=(255, 255, 255)) -> Image.Image:
    img = over(img, bg) if img.mode == "RGBA" else img.convert("RGB")
    s = min(w / img.width, h / img.height)
    r = img.resize((max(1, int(img.width * s)), max(1, int(img.height * s))), Image.LANCZOS)
    out = Image.new("RGB", (w, h), bg)
    out.paste(r, ((w - r.width) // 2, (h - r.height) // 2))
    return out


def walk_turn_script(n: int) -> List[Dict[str, Any]]:
    """Toward the camera, turn right, walk away, turn left, back toward the camera: front, side, back, side, front."""
    legs = [(0, 1), (1, 0), (0, -1), (-1, 0), (0, 1)]
    per, extra = divmod(n, len(legs))
    out: List[Dict[str, Any]] = []
    for i, (vx, vy) in enumerate(legs):
        out += [dict(vx=vx, vy=vy, moving=True, dt=1 / FPS)] * (per + (1 if i < extra else 0))
    return out


def run_ffmpeg(frames: List[Image.Image], out: Path) -> None:
    tmp = Path(tempfile.mkdtemp(prefix="cmp_frames_"))
    try:
        for i, f in enumerate(frames):
            f.save(tmp / f"f_{i:04d}.png")
        w, h = frames[0].size
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(FPS), "-i", str(tmp / "f_%04d.png"),
                        "-vf", f"scale={w // 2 * 2}:{h // 2 * 2}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", str(out)], check=True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def video_frames(path: Path, indexes: List[int]) -> Dict[int, Image.Image]:
    tmp = Path(tempfile.mkdtemp(prefix="ref_frames_"))
    try:
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(path), str(tmp / "v_%03d.png")], check=True)
        return {i: Image.open(tmp / f"v_{i:03d}.png").convert("RGB").copy() for i in indexes}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def head_region(rgba: np.ndarray, hat_widths: float = 1.45) -> np.ndarray:
    """From the top of the figure down ``hat_widths`` times the widest row in its top fifth (a hat brim, hair or the head)."""
    m = rgba[..., 3] > 127
    ys, xs = np.nonzero(m)
    y0, y1 = ys.min(), ys.max() + 1
    top = m[y0:y0 + max(2, (y1 - y0) // 5)]
    cols = np.nonzero(top.any(axis=0))[0]
    width = cols[-1] - cols[0] + 1
    return rgba[y0:min(rgba.shape[0], y0 + int(hat_widths * width))]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True)
    ap.add_argument("--image", required=True, type=Path)
    ap.add_argument("--height-in", required=True, type=float)
    ap.add_argument("--old", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--video", type=Path)
    ap.add_argument("--video-frames", default="")
    ap.add_argument("--video-yaws", default="", help="degrees the character is turned in each --video-frames frame, chosen by eye (the better of +/- each is used)")
    ap.add_argument("--joints", type=Path, help="JSON {joint name: [x, y]} in cut-out pixels, as the editor would send (a person's dragged joints)")
    ap.add_argument("--suffix", default="", help="added to every output name, for a variant of the same character")
    ap.add_argument("--models", type=Path, help="folder holding isnetis.onnx and pose_landmarker_heavy.task")
    ap.add_argument("--use-pose", action="store_true", help="use the pose detector when --models has one")
    ap.add_argument("--back-mode", default="plain")
    a = ap.parse_args()
    out, name = a.out, a.name + a.suffix
    out.mkdir(parents=True, exist_ok=True)

    matte_path = pose = None
    if a.models:
        m = a.models / "isnetis.onnx"
        p = a.models / "pose_landmarker_heavy.task"
        matte_path = str(m) if m.is_file() else None
        pose = str(p) if (a.use_pose and p.is_file()) else None
    image = a.image.read_bytes()
    built = pipeline.build(image, pipeline.Settings(name=name, height_m=a.height_in * 0.0254, back_mode=a.back_mode,
                                                   joints={k: tuple(v) for k, v in json.loads(a.joints.read_text(encoding="utf-8")).items()} if a.joints else {}),
                           matte_path=matte_path, pose_model=pose, data_dir=str(a.models) if a.models else None)
    glb_path = out / f"{name}.glb"
    glb_path.write_bytes(built.glb)
    metrics: Dict[str, Any] = {"name": name, "glb": glb_path.name, "fingerprint": pipeline.fingerprint(built.glb)[:16],
                               "models_used": {"cutout_network": bool(matte_path), "pose_detector": bool(pose)}, "report": built.report}

    original = Image.open(a.image).convert("RGBA")
    old_still = Image.open(a.old / "old_studio_after.png").convert("RGB").crop(OLD_STUDIO_CROP)
    old_record = json.loads((a.old / "old_workflow_record.json").read_text(encoding="utf-8"))
    metrics["old_workflow"] = {"page_said": old_record["bake_status_text_on_the_page"], "skin_color": old_record["bake_api_body"]["bake"]["skin_color"],
                               "voxel_count": old_record["bake_api_body"]["bake"]["voxel_count"], "face_detected": old_record["bake_api_body"]["bake"]["face_detected"],
                               "preset_after": old_record["api_avatars_me"]["preset_id"], "studio": "flat figure; nothing from the picture reaches Studio"}

    with Studio("tools/avatar_likeness/viewer.html") as v:
        v.viewer_load(glb_path)
        cam = RENDER
        tpose = built.report["pose_in_picture"] == "tpose"
        shown_clip = None if tpose else "Idle"                                                   # the pose the picture is drawn in: the bind pose for a T-pose picture, else the clips' first frame
        rest = [v.viewer_frame(yaw=y, clip=None, **cam) for y in ANGLES]
        idle = [v.viewer_frame(yaw=y, clip="Idle", t=0.0, **cam) for y in ANGLES]
        drawn = rest if tpose else idle
        dense = {y: v.viewer_frame(yaw=y, clip=shown_clip, t=0.0, **cam) for y in range(0, 360, 15)}
        turn_ys = [int(x) for x in a.video_yaws.split(",")] if a.video_yaws else []
        extra = {y % 360: v.viewer_frame(yaw=y % 360, clip=shown_clip, t=0.0, **cam) for y in turn_ys + [-y for y in turn_ys]}
    arr = lambda im: np.asarray(im.convert("RGBA"))
    orig_arr = arr(original)
    if orig_arr[..., 3].min() == 255:                                                            # a picture with a backdrop: compare against the builder's own cut-out
        orig_arr = built.cutout.rgba
        original = Image.fromarray(orig_arr)
    metrics["pose_compared"] = "bind pose (the picture is a T-pose)" if tpose else "first frame of the Idle clip (the picture is not a T-pose, so its drawn pose is what to compare)"
    metrics["front_rest_vs_picture"] = analysis.compare_views(orig_arr, arr(drawn[0]))
    metrics["mesh_stretch"] = {c: analysis.mesh_stretch(built.glb, c, samples=24) for c in ("Idle", "Walk")}
    metrics["front_picture_use_by_yaw"] = [analysis.texture_stretch(built.glb, y) for y in (0, 30, 60, 90, 120, 180)]
    metrics["turntable_stability_rest_pose"] = analysis.turn_stability([arr(dense[y]) for y in sorted(dense)])

    grey = (238, 238, 238)
    top = [captioned(fit(original, TILE_W, TILE_H), "the picture"), captioned(fit(old_still, TILE_W, TILE_H, (20, 20, 20)), "old workflow: flat figure in Studio")]
    top += [captioned(fit(r, TILE_W, TILE_H, grey), f"new, rest pose, {y} deg") for r, y in zip(rest, ANGLES)]
    bottom = [captioned(fit(r, TILE_W, TILE_H, grey), f"new, Idle clip, {y} deg") for r, y in zip(idle, ANGLES)]
    pitch = TILE_W + 6
    angles = Image.new("RGB", (len(top) * pitch, 2 * (TILE_H + 34) + 6), (20, 18, 16))
    for i, t in enumerate(top):
        angles.paste(t, (i * pitch, 0))
    for i, t in enumerate(bottom):
        angles.paste(t, ((i + 2) * pitch, TILE_H + 34 + 6))
    angles.save(out / f"{name}_angles.png")

    # a matching-view comparison against the reference clip, head and upper body only (the clip is a close-up)
    ref_frames: Dict[int, Image.Image] = {}
    if a.video and a.video_frames:
        idx = [int(x) for x in a.video_frames.split(",")]
        yaws = turn_ys if turn_ys else [0] * len(idx)
        ref_frames = video_frames(a.video, idx)
        net = matte.load(matte_path, None) if matte_path else None
        rows, refmetrics = [], []
        import io as _io
        for i, nominal in zip(idx, yaws):
            buf = _io.BytesIO()
            ref_frames[i].save(buf, "PNG")
            cutref = intake.prepare(buf.getvalue(), matte=net, prefer_matte=net is not None)
            ref_head = head_region(cutref.rgba)
            cands = {nominal % 360: extra[nominal % 360], (-nominal) % 360: extra[(-nominal) % 360]}
            scored = [(analysis.silhouette(ref_head, head_region(arr(img)))["iou"], y) for y, img in cands.items()]
            iou, y = max(scored)
            r_head = head_region(arr(cands[y]))
            cmp = analysis.compare_views(ref_head, r_head)
            refmetrics.append({"video_frame": i, "nominal_yaw_deg": nominal, "yaw_used_deg": y, "silhouette_iou_head_and_upper_body": round(iou, 3),
                               "palette_mean_delta_e": cmp["palette"]["mean_delta_e"], "findings": cmp["findings"]})
            rows += [Image.fromarray(ref_head).convert("RGBA"), Image.fromarray(r_head).convert("RGBA")]
        metrics["against_reference_clip"] = {"note": "head and upper body only (the clip is a close-up). The turn angle of each clip frame was judged by eye; the render is at that angle or its mirror, whichever overlaps better, and the pose is the picture's drawn pose.",
                                              "views": refmetrics}
        tiles = [captioned(fit(r, 300, 330, (60, 52, 44) if k % 2 == 0 else (238, 238, 238)),
                           ("clip frame %d" % idx[k // 2]) if k % 2 == 0 else ("new at %d deg" % refmetrics[k // 2]["yaw_used_deg"])) for k, r in enumerate(rows)]
        ref_sheet = Image.new("RGB", (len(tiles) * 306, tiles[0].height), (20, 18, 16))
        for i, t in enumerate(tiles):
            ref_sheet.paste(t, (i * 306, 0))
        ref_sheet.save(out / f"{name}_reference_views.png")

    # the walk and turn in the real Studio player
    n = 121 if a.video else 108
    with Studio("static/world_walk.html") as s:
        info = s.studio_load(glb_path, name)
        frames = s.studio_frames(name, walk_turn_script(n), H=560, size=(520, 660))
    metrics["studio_player"] = {k: info.get(k) for k in ("hasWalk", "hasIdle", "skinned", "bones", "nativeHeight")}
    metrics["walk_turn_stability"] = analysis.turn_stability([np.asarray(f) for f in frames])

    ref_all = None
    if a.video:
        tmp = Path(tempfile.mkdtemp(prefix="ref_all_"))
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(a.video), str(tmp / "v_%03d.png")], check=True)
        ref_all = [Image.open(tmp / f"v_{i + 1:03d}.png").convert("RGB").copy() for i in range(min(n, len(list(tmp.glob("v_*.png")))))]
        shutil.rmtree(tmp, ignore_errors=True)
    panels: List[Image.Image] = []
    for i, f in enumerate(frames):
        tiles = [captioned(fit(original, 520, 660), "the picture"), captioned(fit(old_still, 520, 660, (20, 20, 20)), "old workflow, in Studio"),
                 captioned(fit(f, 520, 660, (205, 192, 168)), "new workflow, walking and turning in Studio")]
        if ref_all is not None:
            tiles.append(captioned(fit(ref_all[min(i, len(ref_all) - 1)], 1173, 660, (20, 20, 20)), "reference: Runway clip"))
        row = Image.new("RGB", (sum(t.width for t in tiles) + 6 * (len(tiles) - 1), tiles[0].height), (12, 11, 10))
        x = 0
        for t in tiles:
            row.paste(t, (x, 0))
            x += t.width + 6
        panels.append(row)
    run_ffmpeg(panels, out / f"{name}_walk_turn.mp4")

    (out / f"{name}_metrics.json").write_text(json.dumps(metrics, indent=1, default=lambda o: o.item() if hasattr(o, "item") else str(o)), encoding="utf-8")
    write_markdown(out / f"{name}_metrics.md", metrics)
    print(json.dumps({k: metrics[k] for k in ("name", "fingerprint", "models_used")}))
    return 0


def write_markdown(path: Path, m: Dict[str, Any]) -> None:
    rep, cmp = m["report"], m["front_rest_vs_picture"]
    L = [f"# {m['name']}: picture to avatar, measured", "",
         f"Built file {m['glb']} (fingerprint {m['fingerprint']}); cut-out network used: {m['models_used']['cutout_network']}; pose detector used: {m['models_used']['pose_detector']}.", "",
         f"Height {rep['height_m'] / 0.0254:.1f} in = {rep['height_pub_blocks']:.2f} pub blocks; build {rep['build']}; {rep['vertices']:,} vertices, {rep['triangles']:,} triangles, {rep['bones']} bones.", "",
         "## Old workflow (real Dressing Room bake)", f"The page said: {m['old_workflow']['page_said']}. Host returned skin colour {m['old_workflow']['skin_color']}, voxel count {m['old_workflow']['voxel_count']}, face detected {m['old_workflow']['face_detected']}. Studio: {m['old_workflow']['studio']}.", "",
         f"## New workflow, front view, against the picture ({m['pose_compared']})",
         f"Silhouette overlap {cmp['silhouette']['iou']:.3f} (bands {cmp['silhouette']['iou_bands']}); colour distance {cmp['palette']['mean_delta_e']:.1f}; ink outline loss {cmp['ink_outline_loss']:.2f}.",
         "Findings: " + ("; ".join(cmp["findings"]) if cmp["findings"] else "none above the thresholds"), "",
         "## Deformation in motion (CPU skinning against the bind pose)"]
    for c, r in m["mesh_stretch"].items():
        L.append(f"- {c}: {r['triangles_ever_stretched_or_collapsed'] * 100:.2f}% of triangles ever grow or shrink by more than 2.5x; worst single triangle {r['worst_area_ratio']}x; by part {r['share_by_part']}")
    L += ["", "## How much of the picture is used at each view angle (front picture only)"]
    for r in m["front_picture_use_by_yaw"]:
        L.append(f"- {r['yaw_deg']:>3} deg: used well {r['seen_well'] * 100:.0f}%, smeared {r['edge_on'] * 100:.0f}%, hidden {r['hidden'] * 100:.0f}%; {r['visible_from_generated_back'] * 100:.0f}% of what is on screen is the generated back")
    t, w = m["turntable_stability_rest_pose"], m["walk_turn_stability"]
    L += ["", "## Turn stability", f"Turntable (rest pose): height drift {t['height_drift'] * 100:.1f}%, lowest frame-to-frame overlap {t['min_consecutive_iou']:.3f}. " + "; ".join(t["findings"]),
          f"Studio walk and turn: height drift {w['height_drift'] * 100:.1f}%, lowest frame-to-frame overlap {w['min_consecutive_iou']:.3f}. " + "; ".join(w["findings"])]
    if "against_reference_clip" in m:
        L += ["", "## Against the Runway clip", m["against_reference_clip"]["note"]]
        for v in m["against_reference_clip"]["views"]:
            L.append(f"- clip frame {v['video_frame']}: turned about {v['nominal_yaw_deg']} deg (by eye), render at {v['yaw_used_deg']} deg, silhouette overlap {v['silhouette_iou_head_and_upper_body']:.2f}, colour distance {v['palette_mean_delta_e']:.1f}")
            L += [f"    - {f}" for f in v["findings"]]
    L += ["", "## Warnings the builder gave the user", *[f"- {w}" for w in rep["warnings"]], "", "## Not in the picture", *[f"- {w}" for w in rep["not_in_the_picture"]]]
    path.write_text("\n".join(L) + "\n", encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
