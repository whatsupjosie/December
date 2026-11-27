# PubCast AI — avatar_likeness/landmarks.py
# Copyright © 2024–2026 Josie Curtsey Cobbley (Joshua Cobbley)
# Rearview Foresight LLC — All Rights Reserved
# Feic Mo Chroí — See My Heart
"""Body landmarks from a character illustration: where the joints are in the picture.

Three sources, always labelled per joint so the person editing them can see which ones to check:

  detector  MediaPipe Pose, opt-in, from a model file already on disk (never downloaded here). Trusted only after
            ``plausible`` passes. It was trained on photographs; it is reliable on adult T-pose illustrations and
            unreliable on chibi proportions and relaxed poses (Humphrey's shoulders, hips and feet came back wrong).
  template  proportions for the declared build (adult, child, toddler), fitted to the cut-out's silhouette. The real
            height the person states picks the build when none is given, so a figure "just under three feet" is
            built as a toddler and a 5'7" figure as an adult.
  (head_top comes from the cut-out's top edge and the neck from the shoulders and chin: "silhouette" / "derived".)
  user      points the person dragged. They always win and are never overwritten by a later run.

Image coordinates: x to the right, y down, in the working-picture pixels. The character's LEFT is the picture's
RIGHT (the character faces the viewer), which is +X in the PubCast rig.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from . import deps

POSE_ENV_VAR = "PUBCAST_AVATAR_POSE_TASK"
POSE_FILE = "pose_landmarker_heavy.task"

JOINTS: Tuple[str, ...] = (
    "head_top", "chin", "neck",
    "shoulder_L", "shoulder_R", "elbow_L", "elbow_R", "wrist_L", "wrist_R", "hand_tip_L", "hand_tip_R",
    "pelvis", "hip_L", "hip_R", "knee_L", "knee_R", "ankle_L", "ankle_R", "toe_L", "toe_R",
)

# build -> proportions as fractions of figure height measured from the top of the head/hat (y down).
# adult: 7.5 heads. child: ~5.5 heads. toddler: ~3.3 heads (large head, short legs).
BUILDS: Dict[str, Dict[str, float]] = {
    "adult":   {"chin": 0.135, "neck": 0.165, "shoulder": 0.195, "elbow": 0.37, "wrist": 0.46, "hip": 0.53, "knee": 0.735, "ankle": 0.955,
                "shoulder_half": 0.115, "hip_half": 0.055, "arm": 0.37, "foot": 0.06},
    "child":   {"chin": 0.185, "neck": 0.215, "shoulder": 0.25, "elbow": 0.42, "wrist": 0.52, "hip": 0.56, "knee": 0.76, "ankle": 0.955,
                "shoulder_half": 0.15, "hip_half": 0.07, "arm": 0.34, "foot": 0.08},
    "toddler": {"chin": 0.36, "neck": 0.385, "shoulder": 0.43, "elbow": 0.58, "wrist": 0.68, "hip": 0.70, "knee": 0.84, "ankle": 0.955,
                "shoulder_half": 0.17, "hip_half": 0.09, "arm": 0.30, "foot": 0.10},
}


def build_for_height(height_m: float) -> str:
    """Pick the build from the real standing height. Under 1.15 m is a toddler build; under 1.45 m a child."""
    return "toddler" if height_m < 1.15 else "child" if height_m < 1.45 else "adult"


@dataclass
class Landmarks:
    points: Dict[str, Tuple[float, float]]
    source: Dict[str, str]                      # joint -> "detector" | "template" | "user"
    confidence: Dict[str, float]                # joint -> 0..1
    pose_kind: str                              # "tpose" | "apose" | "relaxed"
    build: str
    detector_used: bool
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {"points": {k: [round(v[0], 2), round(v[1], 2)] for k, v in self.points.items()}, "source": dict(self.source),
                "confidence": {k: round(v, 3) for k, v in self.confidence.items()}, "pose_kind": self.pose_kind,
                "build": self.build, "detector_used": self.detector_used, "warnings": list(self.warnings)}

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "Landmarks":
        pts = {k: (float(v[0]), float(v[1])) for k, v in d["points"].items()}
        return Landmarks(pts, dict(d["source"]), {k: float(v) for k, v in d["confidence"].items()}, d["pose_kind"], d["build"],
                         bool(d.get("detector_used")), list(d.get("warnings", [])))

    def apply_user_edits(self, edits: Dict[str, Sequence[float]]) -> "Landmarks":
        """Return a copy with the person's dragged points applied. Unknown joint names are an error, not ignored."""
        bad = [k for k in edits if k not in JOINTS]
        if bad:
            raise KeyError(f"unknown joint(s): {', '.join(sorted(bad))}")
        pts, src, conf = dict(self.points), dict(self.source), dict(self.confidence)
        for k, v in edits.items():
            pts[k] = (float(v[0]), float(v[1])); src[k] = "user"; conf[k] = 1.0
        out = Landmarks(pts, src, conf, self.pose_kind, self.build, self.detector_used, list(self.warnings))
        out.pose_kind = classify_pose(out.points)
        return out


# ── detector (optional) ────────────────────────────────────────────────────────────────────────────────────────

def locate_pose_model(path: Optional[os.PathLike] = None, data_dir: Optional[os.PathLike] = None) -> Optional[Path]:
    cands = [Path(path)] if path else []
    if os.environ.get(POSE_ENV_VAR):
        cands.append(Path(os.environ[POSE_ENV_VAR]))
    if data_dir:
        cands.append(Path(data_dir) / "models" / "avatar" / POSE_FILE)
    for p in cands:
        if p.is_file() and p.stat().st_size > 1_000_000:
            return p
    return None


def detect(rgb: np.ndarray, model_path: Optional[os.PathLike] = None, data_dir: Optional[os.PathLike] = None) -> Optional[np.ndarray]:
    """MediaPipe Pose on one picture -> (33, 4) array of x_px, y_px, visibility, presence; ``None`` if unavailable."""
    model = locate_pose_model(model_path, data_dir)
    mp = deps.optional("mediapipe")
    if model is None or mp is None:
        return None
    from mediapipe.tasks import python as mpp            # imported late: heavy, and only on this path
    from mediapipe.tasks.python import vision
    opts = vision.PoseLandmarkerOptions(base_options=mpp.BaseOptions(model_asset_path=str(model)), running_mode=vision.RunningMode.IMAGE,
                                        num_poses=1, min_pose_detection_confidence=0.2, min_pose_presence_confidence=0.2)
    det = vision.PoseLandmarker.create_from_options(opts)
    try:
        res = det.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb)))
    finally:
        det.close()
    if not res.pose_landmarks:
        return None
    h, w = rgb.shape[:2]
    return np.array([[l.x * w, l.y * h, l.visibility, l.presence] for l in res.pose_landmarks[0]], np.float32)


# ── geometry helpers ───────────────────────────────────────────────────────────────────────────────────────────

def classify_pose(p: Dict[str, Tuple[float, float]]) -> str:
    """tpose: both arms near horizontal. relaxed: both arms hang down. apose: in between."""
    angs = []
    for s in ("L", "R"):
        sh, wr = np.array(p[f"shoulder_{s}"]), np.array(p[f"wrist_{s}"])
        d = wr - sh
        n = np.linalg.norm(d)
        angs.append(90.0 if n < 1e-6 else float(np.degrees(np.arcsin(np.clip(abs(d[1]) / n, 0, 1)))))   # degrees below/above horizontal
    a = float(np.mean(angs))
    return "tpose" if a < 22 else "apose" if a < 60 else "relaxed"


def plausible(p: Dict[str, Tuple[float, float]], bbox: Tuple[int, int, int, int], feet_cropped: bool) -> Tuple[bool, List[str]]:
    """Reject detections that cannot be a standing figure fitted to the cut-out. Returns (ok, reasons)."""
    x0, y0, x1, y1 = bbox
    H, W = max(1, y1 - y0), max(1, x1 - x0)
    why: List[str] = []
    sh_y = (p["shoulder_L"][1] + p["shoulder_R"][1]) / 2
    hip_y = (p["hip_L"][1] + p["hip_R"][1]) / 2
    kn_y = (p["knee_L"][1] + p["knee_R"][1]) / 2
    an_y = (p["ankle_L"][1] + p["ankle_R"][1]) / 2
    if not (sh_y < hip_y < kn_y < an_y):
        why.append("joints are not in standing order (shoulders, hips, knees, ankles)")
    if (sh_y - y0) / H > 0.45:
        why.append("shoulders are below the middle of the figure")
    if (an_y - hip_y) / H < 0.30:
        why.append("legs are shorter than a third of the figure")
    if not feet_cropped and abs(y1 - an_y) / H > 0.12:
        why.append("ankles are not near the floor")
    if abs(p["shoulder_L"][0] - p["shoulder_R"][0]) / W < 0.10:
        why.append("shoulders are almost on top of each other")
    if p["shoulder_L"][0] < p["shoulder_R"][0]:
        why.append("left and right are swapped (the character faces away or the detector flipped)")
    for k, v in p.items():
        if not (x0 - 0.05 * W <= v[0] <= x1 + 0.05 * W and y0 - 0.05 * H <= v[1] <= y1 + 0.05 * H):
            why.append(f"{k} is outside the figure")
            break
    return (not why), why


def _from_detector(lm: np.ndarray, mask: np.ndarray, bbox: Tuple[int, int, int, int]) -> Tuple[Dict[str, Tuple[float, float]], Dict[str, float]]:
    def pt(i): return (float(lm[i, 0]), float(lm[i, 1]))
    def vis(*ids): return float(np.mean([lm[i, 2] for i in ids]))
    # MediaPipe "left" is the person's left, which is the picture's right, which is our _L. Same convention.
    P: Dict[str, Tuple[float, float]] = {}
    C: Dict[str, float] = {}
    for name, i in (("shoulder_L", 11), ("shoulder_R", 12), ("elbow_L", 13), ("elbow_R", 14), ("wrist_L", 15), ("wrist_R", 16),
                    ("hip_L", 23), ("hip_R", 24), ("knee_L", 25), ("knee_R", 26), ("ankle_L", 27), ("ankle_R", 28)):
        P[name], C[name] = pt(i), float(lm[i, 2])
    for s, hands, toe in (("L", (17, 19, 21), 31), ("R", (18, 20, 22), 32)):
        P[f"hand_tip_{s}"] = tuple(np.mean([lm[i, :2] for i in hands], axis=0).tolist()); C[f"hand_tip_{s}"] = vis(*hands)
        P[f"toe_{s}"], C[f"toe_{s}"] = pt(toe), float(lm[toe, 2])
    nose, mouth = (lm[0, 1], (lm[9, 1] + lm[10, 1]) / 2)
    x0, y0, x1, y1 = bbox
    cx = float(lm[0, 0])
    P["head_top"], C["head_top"] = (cx, float(y0)), 0.9
    P["chin"], C["chin"] = (cx, float(mouth + (mouth - nose) * 1.1)), vis(0, 9, 10)
    sh_mid = ((P["shoulder_L"][0] + P["shoulder_R"][0]) / 2, (P["shoulder_L"][1] + P["shoulder_R"][1]) / 2)
    P["neck"], C["neck"] = (sh_mid[0], sh_mid[1] - 0.25 * max(0.0, sh_mid[1] - P["chin"][1])), 0.8
    P["pelvis"], C["pelvis"] = (((P["hip_L"][0] + P["hip_R"][0]) / 2, (P["hip_L"][1] + P["hip_R"][1]) / 2)), vis(23, 24)
    return P, C


def _span(mask: np.ndarray, y: int, x_from: float, step: int) -> float:
    """Walk along row y from x_from in direction step until the cut-out ends; return the last inside x."""
    h, w = mask.shape
    y = int(np.clip(y, 0, h - 1))
    x = int(np.clip(x_from, 0, w - 1))
    last = x
    while 0 <= x < w and mask[y, x]:
        last = x
        x += step
    return float(last)


def _from_template(mask: np.ndarray, bbox: Tuple[int, int, int, int], build: str, pose_hint: str, feet_cropped: bool) -> Tuple[Dict[str, Tuple[float, float]], Dict[str, float]]:
    t = BUILDS[build]
    x0, y0, x1, y1 = bbox
    H = float(y1 - y0)
    def Y(f): return y0 + f * H
    # centre line: median of the figure's pixels in the torso band, so a prop or a swung arm does not drag it
    band = mask[int(Y(t["shoulder"])): int(Y(t["hip"])) + 1]
    cx = float(np.median(np.where(band)[1])) if band.any() else (x0 + x1) / 2.0
    sh_y, hip_y = Y(t["shoulder"]), Y(t["hip"])
    half_sh = t["shoulder_half"] * H
    half_hip = t["hip_half"] * H
    P: Dict[str, Tuple[float, float]] = {"head_top": (cx, float(y0)), "chin": (cx, Y(t["chin"])), "neck": (cx, Y(t["neck"])), "pelvis": (cx, hip_y)}
    for s, sign in (("L", 1.0), ("R", -1.0)):
        P[f"shoulder_{s}"] = (cx + sign * half_sh, sh_y)
        P[f"hip_{s}"] = (cx + sign * half_hip, hip_y)
        P[f"knee_{s}"] = (cx + sign * half_hip * 0.95, Y(t["knee"]))
        floor = float(y1) if feet_cropped else Y(t["ankle"] + 0.045)
        P[f"ankle_{s}"] = (cx + sign * half_hip * 0.9, min(Y(t["ankle"]), floor - 0.03 * H))
        P[f"toe_{s}"] = (cx + sign * (half_hip * 0.9 + 0.02 * H), floor)
        arm = t["arm"] * H
        if pose_hint == "tpose":     # out sideways; the cut-out's own edge sets the hand tip
            P[f"elbow_{s}"] = (P[f"shoulder_{s}"][0] + sign * arm * 0.52, sh_y)
            P[f"wrist_{s}"] = (P[f"shoulder_{s}"][0] + sign * arm * 1.0, sh_y)
            tip = _span(mask, int(sh_y), P[f"wrist_{s}"][0], int(sign))
            P[f"hand_tip_{s}"] = (tip if abs(tip - P[f"wrist_{s}"][0]) > 1 else P[f"wrist_{s}"][0] + sign * arm * 0.18, sh_y)
        else:                        # hanging at the sides, slightly out
            P[f"elbow_{s}"] = (P[f"shoulder_{s}"][0] + sign * 0.02 * H, sh_y + arm * 0.52)
            P[f"wrist_{s}"] = (P[f"shoulder_{s}"][0] + sign * 0.03 * H, sh_y + arm * 1.0)
            P[f"hand_tip_{s}"] = (P[f"wrist_{s}"][0] + sign * 0.01 * H, P[f"wrist_{s}"][1] + 0.05 * H)
    return P, {k: 0.35 for k in P}


# fraction of figure height: how long a hand is from the wrist to the fingertip, and the column height above which a column is body, not arm
HAND_LEN = {"adult": 0.10, "child": 0.115, "toddler": 0.12}
ARM_COLUMN_MAX = {"adult": 0.12, "child": 0.14, "toddler": 0.16}


def _runs(col: np.ndarray) -> List[Tuple[int, int]]:
    """(start, end exclusive) of each vertical run of True in one image column."""
    d = np.diff(np.concatenate([[0], col.astype(np.int8), [0]]))
    return list(zip(np.nonzero(d == 1)[0].tolist(), np.nonzero(d == -1)[0].tolist()))


def _tpose_arms(mask: np.ndarray, P: Dict[str, Tuple[float, float]], bbox: Tuple[int, int, int, int], build: str) -> Optional[Dict[str, Tuple[float, float]]]:
    """Arm joints measured from the cut-out for a figure drawn with its arms out sideways.

    Start at the outermost column of the arm (the fingertips) and follow the arm inward column by column, always taking the
    vertical run that overlaps the one before, until the run grows tall enough to be the torso. The arm's centre line is a
    straight line fitted through those columns, so a drooping or raised arm is followed. The wrist is where the sleeve or cuff
    ends (the run suddenly thins) when that is visible, otherwise a hand length from the tip; the shoulder keeps its template
    x and takes the line's y; the elbow is halfway. Returns None when the arm cannot be followed (the caller keeps the template).
    """
    x0, y0, x1, y1 = bbox
    H = float(y1 - y0)
    h, w = mask.shape
    cx = P["pelvis"][0]
    y_ref = P["shoulder_L"][1]
    out: Dict[str, Tuple[float, float]] = {}
    for s, sign in (("L", 1), ("R", -1)):
        top, bottom = int(max(0, y0 + 0.08 * H)), int(min(h, y0 + 0.5 * H))
        cols = [x for x in range(w) if mask[top:bottom, x].any()]
        if not cols:
            return None
        tip_x = max(cols) if sign > 0 else min(cols)
        inner = cx + sign * 0.10 * H
        track: List[Tuple[int, float, float]] = []          # (x, centre y, run length) from the tip inward
        prev_c = None
        x = tip_x
        while (x - inner) * sign > 0 and 0 <= x < w:
            runs = [(a, b) for a, b in _runs(mask[:, x]) if a < bottom and b > top]
            if not runs:
                x -= sign
                continue
            if prev_c is None:
                a, b = min(runs, key=lambda r: abs((r[0] + r[1]) / 2 - y_ref))
            else:
                hit = [r for r in runs if r[0] <= prev_c < r[1]]
                a, b = hit[0] if hit else min(runs, key=lambda r: abs((r[0] + r[1]) / 2 - prev_c))
            if (b - a) > ARM_COLUMN_MAX[build] * H:
                break                                       # this column is body
            if abs(((a + b) / 2) - (prev_c if prev_c is not None else y_ref)) > 0.06 * H:
                break                                       # jumped to something else (a hand of hair, a prop): stop following
            prev_c = (a + b) / 2
            track.append((x, prev_c, float(b - a)))
            x -= sign
        if len(track) < max(20, int(0.12 * H)):
            return None
        xs = np.array([t[0] for t in track], float)
        ys = np.array([t[1] for t in track], float)
        ls = np.array([t[2] for t in track], float)
        n = len(track)
        use = slice(int(0.12 * n), int(0.9 * n))            # skip the tapering hand and the shoulder end
        A = np.vstack([xs[use], np.ones(len(xs[use]))]).T
        slope, icpt = np.linalg.lstsq(A, ys[use], rcond=None)[0]
        line = lambda xx: float(slope * xx + icpt)
        mid = np.median(ls[int(0.3 * n):int(0.8 * n)])
        thick = np.nonzero(ls >= 0.7 * mid)[0]              # columns (from the tip inward) that are as thick as the sleeve
        wrist_x = None
        if len(thick):
            cand = float(xs[thick[0]])                      # the outermost thick column: where the cuff ends
            if 0.04 * H <= abs(tip_x - cand) <= 0.13 * H:
                wrist_x = cand
        if wrist_x is None:
            wrist_x = tip_x - sign * HAND_LEN[build] * H
        sh_x = P[f"shoulder_{s}"][0]
        out[f"hand_tip_{s}"] = (float(tip_x), line(tip_x))
        out[f"wrist_{s}"] = (float(wrist_x), line(wrist_x))
        out[f"shoulder_{s}"] = (float(sh_x), line(sh_x))
        out[f"elbow_{s}"] = ((sh_x + wrist_x) / 2.0, line((sh_x + wrist_x) / 2.0))
    return out


# ── public entry ───────────────────────────────────────────────────────────────────────────────────────────────

def find(rgb: np.ndarray, alpha: np.ndarray, bbox: Tuple[int, int, int, int], height_m: float,
         build: Optional[str] = None, pose_hint: Optional[str] = None, feet_cropped: bool = False,
         model_path: Optional[os.PathLike] = None, data_dir: Optional[os.PathLike] = None,
         user_edits: Optional[Dict[str, Sequence[float]]] = None) -> Landmarks:
    """Joint positions for one cut-out. Never silent about where a joint came from: see ``Landmarks.source``."""
    mask = alpha > 0.5
    build = build or build_for_height(height_m)
    if build not in BUILDS:
        raise ValueError(f"build must be one of {', '.join(BUILDS)}")
    warns: List[str] = []
    P: Dict[str, Tuple[float, float]] = {}
    C: Dict[str, float] = {}
    src: Dict[str, str] = {}
    used = False
    lm = detect(rgb, model_path, data_dir)
    if lm is None:
        warns.append("No pose model is installed, so joints come from the build template. Check them in the editor.")
    else:
        P, C = _from_detector(lm, mask, bbox)
        ok, why = plausible(P, bbox, feet_cropped)
        key_vis = float(np.mean([C[k] for k in ("shoulder_L", "shoulder_R", "hip_L", "hip_R", "knee_L", "knee_R")]))
        if not ok or key_vis < 0.55 or build != "adult":
            reason = ("; ".join(why) if why else f"detector confidence {key_vis:.2f}" if key_vis < 0.55 else
                      f"a {build} build is outside what the detector was trained on")
            warns.append(f"The pose detector's result was not used ({reason}); joints come from the {build} template. Check them in the editor.")
            P, C = {}, {}
        else:
            used = True
    if not used:
        hint = pose_hint or ("tpose" if _looks_tpose(mask, bbox) else "relaxed")
        P, C = _from_template(mask, bbox, build, hint, feet_cropped)
        src = {k: "template" for k in P}
        if hint == "tpose":
            arms = _tpose_arms(mask, P, bbox, build)
            if arms is None:
                warns.append("The arms could not be followed in the cut-out, so they use the template. Drag the shoulders, elbows and wrists onto the arms.")
            else:
                for k, v in arms.items():
                    P[k], C[k], src[k] = v, 0.6, "silhouette"
                warns.append("The arm joints were measured from the cut-out, not detected. Check the elbows and wrists in the editor.")
    else:
        src = {k: "detector" for k in P}
        src["head_top"], src["neck"] = "silhouette", "derived"
    lmk = Landmarks(P, src, C, classify_pose(P), build, used, warns)
    return lmk.apply_user_edits(user_edits) if user_edits else lmk


def _looks_tpose(mask: np.ndarray, bbox: Tuple[int, int, int, int]) -> bool:
    """A T-pose figure is much wider than a standing one: the shoulder-height row spans most of the figure's height."""
    x0, y0, x1, y1 = bbox
    return (x1 - x0) / max(1, (y1 - y0)) > 0.75
