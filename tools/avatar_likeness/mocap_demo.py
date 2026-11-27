"""Carry one recorded performance onto avatars built from pictures, and show it beside the performer.

    python tools/avatar_likeness/mocap_demo.py --out OUT_DIR --avatar humphrey=humphrey.glb --avatar pete=pete.glb ...
        [--clips run,walk,agree,sneak_pose] [--samples 6] [--yaw 30]

The performer is the bundled Mixamo-rigged mannequin (static/world/test_avatars/Xbot.glb) playing its recorded clips. Each clip is
retargeted onto each avatar by the same code the editor's "recorded motion" button uses (modules/avatar_likeness/retarget.py) and
written into a copy of the avatar's GLB as Mocap_<clip>. Everything is rendered by the same three.js build the Studio uses.
This is a RECORDED clip. It is not live capture: no camera or live landmark stream is involved.

Writes OUT_DIR/mocap_<clip>_sheet.png for each clip, OUT_DIR/mocap_<clip>.mp4 for the first clip, and OUT_DIR/mocap_report.json.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Dict, List

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from modules.avatar_likeness import pipeline, retarget  # noqa: E402
from tools.avatar_likeness.compare import captioned, fit  # noqa: E402
from tools.avatar_likeness.render import Studio  # noqa: E402

XBOT = ROOT / "static" / "world" / "test_avatars" / "Xbot.glb"
TILE = (300, 420)
CAM = dict(w=520, h=700, halfH=0.58)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--avatar", action="append", required=True, help="name=path.glb (repeatable)")
    ap.add_argument("--clips", default="run,walk,agree,sneak_pose")
    ap.add_argument("--samples", type=int, default=6)
    ap.add_argument("--yaw", type=float, default=30.0)
    ap.add_argument("--video-frames", type=int, default=48)
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    clips = [c for c in a.clips.split(",") if c]
    src = retarget.SourceRig(XBOT.read_bytes())
    tmp = Path(tempfile.mkdtemp(prefix="mocap_demo_"))
    files: Dict[str, Path] = {}
    report: Dict[str, object] = {"performer": "Xbot.glb (bundled Mixamo mannequin), recorded clips", "live_input": "not used", "avatars": {}}
    for item in a.avatar:
        name, path = item.split("=", 1)
        built = pipeline.rebuild(Path(path).read_bytes(), {})
        extra = [retarget.retarget_clip(src, c, built.rigged.rest, built.rigged.local, name=f"Mocap_{c}") for c in clips]
        glb = pipeline.add_clips(built, extra)
        files[name] = tmp / f"{name}.glb"
        files[name].write_bytes(glb)
        report["avatars"][name] = {"clips_written": [e.name for e in extra], "durations_s": {e.name: round(float(e.duration), 3) for e in extra}}

    renders: Dict[str, Dict[str, List[Image.Image]]] = {c: {} for c in clips}
    video: List[Image.Image] = []
    with Studio("tools/avatar_likeness/viewer.html") as v:
        info = v.viewer_load(XBOT)
        dur = {c["name"]: c["duration"] for c in info["clips"]}
        for c in clips:
            ts = np.linspace(0, dur[c], a.samples, endpoint=False)
            renders[c]["performer"] = [v.viewer_frame(yaw=a.yaw, clip=c, t=float(t), **CAM) for t in ts]
        v_ts = np.linspace(0, dur[clips[0]], a.video_frames, endpoint=False)
        perf_video = [v.viewer_frame(yaw=a.yaw, clip=clips[0], t=float(t), **CAM) for t in v_ts]
        video_cols = {"performer": perf_video}
        for name, f in files.items():
            v.viewer_load(f)
            for c in clips:
                ts = np.linspace(0, dur[c], a.samples, endpoint=False)
                renders[c][name] = [v.viewer_frame(yaw=a.yaw, clip=f"Mocap_{c}", t=float(t), **CAM) for t in ts]
            video_cols[name] = [v.viewer_frame(yaw=a.yaw, clip=f"Mocap_{clips[0]}", t=float(t), **CAM) for t in v_ts]

    order = ["performer"] + list(files)
    for c in clips:
        W, H = TILE
        sheet = Image.new("RGB", (len(order) * (W + 6), a.samples * (H + 34 + 6)), (20, 18, 16))
        for ci, who in enumerate(order):
            for ri, img in enumerate(renders[c][who]):
                label = ("recorded performer (Xbot)" if who == "performer" else f"{who} (from a picture)") + f", {c}, {ri + 1}/{a.samples}"
                sheet.paste(captioned(fit(img, W, H, (238, 238, 238)), label), (ci * (W + 6), ri * (H + 34 + 6)))
        sheet.save(a.out / f"mocap_{c}_sheet.png")
    frames = []
    for i in range(a.video_frames):
        row = Image.new("RGB", (len(order) * (TILE[0] + 6), TILE[1] + 34), (20, 18, 16))
        for ci, who in enumerate(order):
            row.paste(captioned(fit(video_cols[who][i], *TILE, (238, 238, 238)), "recorded performer (Xbot)" if who == "performer" else f"{who}, from a picture"), (ci * (TILE[0] + 6), 0))
        frames.append(row)
    loops = 3
    seq = frames * loops
    t2 = Path(tempfile.mkdtemp(prefix="mocap_vid_"))
    try:
        for i, f in enumerate(seq):
            f.save(t2 / f"f_{i:04d}.png")
        w, h = seq[0].size
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", "24", "-i", str(t2 / "f_%04d.png"), "-vf", f"scale={w // 2 * 2}:{h // 2 * 2}",
                        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", str(a.out / f"mocap_{clips[0]}.mp4")], check=True)
    finally:
        shutil.rmtree(t2, ignore_errors=True)
        shutil.rmtree(tmp, ignore_errors=True)
    (a.out / "mocap_report.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(json.dumps(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
