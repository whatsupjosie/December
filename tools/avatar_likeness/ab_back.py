"""A/B the generated back against real back views: old back (no patch merging) versus the current back.

    python tools/avatar_likeness/ab_back.py --image PICTURE.png --height-in 35 --video CLIP.mp4 --frames 89,111 --yaws 140,170 --models MODELS --out OUT_DIR

Both avatars are built from the same picture; only ``texture._flatten_regions`` differs. Each is rendered in the picture's drawn pose at the stated
turn angle (or its mirror, whichever overlaps the clip frame better) and compared with the clip frame's head-and-upper-body cut-out by:
  mean_colour_delta_e   distance between the two figures' average colours in Lab (no clustering, so it does not jump with a few pixels)
  silhouette_iou        overlap of the two outlines
Writes OUT_DIR/ab_back.json and OUT_DIR/ab_back.png (clip | old back | current back for each frame).
"""
from __future__ import annotations

import argparse
import io
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from modules.avatar_likeness import analysis, intake, matte, pipeline, texture  # noqa: E402
from tools.avatar_likeness.compare import captioned, fit, head_region, video_frames  # noqa: E402
from tools.avatar_likeness.render import Studio  # noqa: E402


def mean_lab(rgba: np.ndarray) -> np.ndarray:
    px = analysis._lab_pixels(rgba)
    return px.mean(axis=0)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", required=True, type=Path)
    ap.add_argument("--height-in", required=True, type=float)
    ap.add_argument("--video", required=True, type=Path)
    ap.add_argument("--frames", required=True)
    ap.add_argument("--yaws", required=True)
    ap.add_argument("--models", type=Path)
    ap.add_argument("--out", required=True, type=Path)
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    frames = [int(x) for x in a.frames.split(",")]
    yaws = [int(x) for x in a.yaws.split(",")]
    onnx = a.models / "isnetis.onnx" if a.models else None
    net_path = str(onnx) if onnx and onnx.is_file() else None
    net = matte.load(net_path, None) if net_path else None
    data = a.image.read_bytes()
    settings = pipeline.Settings(name="ab", height_m=a.height_in * 0.0254)
    original = texture._flatten_regions
    texture._flatten_regions = lambda rgb, area, part_label: rgb                         # the back as it was before patch merging
    old = pipeline.build(data, settings, matte_path=net_path, data_dir=str(a.models) if a.models else None)
    texture._flatten_regions = original
    new = pipeline.build(data, settings, matte_path=net_path, data_dir=str(a.models) if a.models else None)
    refs = video_frames(a.video, frames)
    result, tiles = [], []
    with Studio("tools/avatar_likeness/viewer.html") as v:
        shots = {}
        for label, built in (("old", old), ("new", new)):
            p = a.out / f"_ab_{label}.glb"
            p.write_bytes(built.glb)
            v.viewer_load(p)
            shots[label] = {y % 360: v.viewer_frame(yaw=y % 360, clip="Idle", t=0.0, w=660, h=660, halfH=0.58) for y in yaws + [-y for y in yaws]}
            p.unlink()
    for f, nominal in zip(frames, yaws):
        buf = io.BytesIO()
        refs[f].save(buf, "PNG")
        ref = head_region(intake.prepare(buf.getvalue(), matte=net, prefer_matte=net is not None).rgba)
        row = {"clip_frame": f, "nominal_yaw_deg": nominal}
        pair = []
        for label in ("old", "new"):
            best = max(((analysis.silhouette(ref, head_region(np.asarray(img.convert("RGBA"))))["iou"], y) for y, img in
                        ((nominal % 360, shots[label][nominal % 360]), ((-nominal) % 360, shots[label][(-nominal) % 360]))))
            iou, y = best
            r = head_region(np.asarray(shots[label][y].convert("RGBA")))
            de = float(np.linalg.norm(mean_lab(ref) - mean_lab(r)))
            row[label] = {"yaw_used_deg": y, "silhouette_iou": round(float(iou), 3), "mean_colour_delta_e": round(de, 1)}
            pair.append(Image.fromarray(r).convert("RGBA"))
        result.append(row)
        tiles += [captioned(fit(Image.fromarray(ref).convert("RGBA"), 300, 330, (60, 52, 44)), f"clip frame {f}"),
                  captioned(fit(pair[0], 300, 330, (238, 238, 238)), f"old back, {row['old']['yaw_used_deg']} deg"),
                  captioned(fit(pair[1], 300, 330, (238, 238, 238)), f"current back, {row['new']['yaw_used_deg']} deg")]
    sheet = Image.new("RGB", (len(tiles) * 306, tiles[0].height), (20, 18, 16))
    for i, t in enumerate(tiles):
        sheet.paste(t, (i * 306, 0))
    sheet.save(a.out / "ab_back.png")
    (a.out / "ab_back.json").write_text(json.dumps({"note": "head and upper body only; turn angles judged by eye; Humphrey's back is the only real back reference available", "views": result}, indent=1), encoding="utf-8")
    print(json.dumps(result, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
