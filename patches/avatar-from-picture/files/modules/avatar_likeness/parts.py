# PubCast AI — avatar_likeness/parts.py
# Copyright © 2024–2026 Josie Curtsey Cobbley (Joshua Cobbley)
# Rearview Foresight LLC — All Rights Reserved
# Feic Mo Chroí — See My Heart
"""Which part of the body each picture pixel belongs to, and how strongly each bone pulls on it.

Everything is measured in the drawn pose (see ``skeleton``), in metres, in the picture's x/y plane. Bones are line
segments; a pixel belongs to the nearest one. The same distances give skin weights: close to one bone's segment and
far from the others means weight 1 on that bone, near a joint the two neighbouring bones share it. The width of that
blend is each bone's own radius, measured from the cut-out (a chibi's thick arm blends over a wider band than a
finger does).
"""
from __future__ import annotations

from typing import Dict, List, Tuple

import numpy as np

from . import deps
from .skeleton import DEFORM, Fit

# bone -> (start joint, end joint or end-key). End points of bones with no child bone live in ``Fit.ends``.
SEGMENTS: Dict[str, Tuple[str, str]] = {
    "Pelvis": ("Pelvis", "Spine_01"), "Spine_01": ("Spine_01", "Spine_02"), "Spine_02": ("Spine_02", "Spine_03"),
    "Spine_03": ("Spine_03", "Neck_01"), "Neck_01": ("Neck_01", "Head"), "Head": ("Head", "@Head"),
    "Clavicle_L": ("Clavicle_L", "UpperArm_L"), "UpperArm_L": ("UpperArm_L", "LowerArm_L"),
    "LowerArm_L": ("LowerArm_L", "Hand_L"), "Hand_L": ("Hand_L", "@Hand_L"),
    "Clavicle_R": ("Clavicle_R", "UpperArm_R"), "UpperArm_R": ("UpperArm_R", "LowerArm_R"),
    "LowerArm_R": ("LowerArm_R", "Hand_R"), "Hand_R": ("Hand_R", "@Hand_R"),
    "Thigh_L": ("Thigh_L", "Calf_L"), "Calf_L": ("Calf_L", "Foot_L"), "Foot_L": ("Foot_L", "@Foot_L"),
    "Thigh_R": ("Thigh_R", "Calf_R"), "Calf_R": ("Calf_R", "Foot_R"), "Foot_R": ("Foot_R", "@Foot_R"),
}
GROUP: Dict[str, str] = {
    "Pelvis": "torso", "Spine_01": "torso", "Spine_02": "torso", "Spine_03": "torso", "Clavicle_L": "torso", "Clavicle_R": "torso",
    "Neck_01": "head", "Head": "head",
    "UpperArm_L": "arm_L", "LowerArm_L": "arm_L", "Hand_L": "hand_L", "UpperArm_R": "arm_R", "LowerArm_R": "arm_R", "Hand_R": "hand_R",
    "Thigh_L": "leg_L", "Calf_L": "leg_L", "Foot_L": "foot_L", "Thigh_R": "leg_R", "Calf_R": "leg_R", "Foot_R": "foot_R",
}
PARTS: Tuple[str, ...] = ("head", "torso", "arm_L", "arm_R", "hand_L", "hand_R", "leg_L", "leg_R", "foot_L", "foot_R")
assert set(SEGMENTS) == set(DEFORM) == set(GROUP)


def segment_endpoints(fit: Fit) -> Dict[str, Tuple[np.ndarray, np.ndarray]]:
    """bone -> (start, end) as drawn, x/y only (metres)."""
    out = {}
    for bone, (a, b) in SEGMENTS.items():
        end = fit.ends[b[1:]] if b.startswith("@") else fit.drawn[b]
        out[bone] = (fit.drawn[a][:2].copy(), end[:2].copy())
    return out


def _dist_to_segments(xy: np.ndarray, segs: Dict[str, Tuple[np.ndarray, np.ndarray]], names: List[str]) -> np.ndarray:
    """(N, B) distances from each point to each bone's segment."""
    d = np.empty((len(xy), len(names)), np.float32)
    for j, n in enumerate(names):
        a, b = segs[n]
        ab = b - a
        L2 = float(ab @ ab)
        t = np.zeros(len(xy), np.float32) if L2 < 1e-12 else np.clip(((xy - a) @ ab) / L2, 0.0, 1.0)
        d[:, j] = np.linalg.norm(xy - (a + t[:, None] * ab), axis=1)
    return d


def bone_radii(fit: Fit, mask: np.ndarray, floor_y: float) -> Dict[str, float]:
    """Half-width of the cut-out around each bone in metres (median distance-transform value along the segment)."""
    cv2 = deps.require("cv2", "opencv-python-headless")
    dt = cv2.distanceTransform(mask.astype(np.uint8), cv2.DIST_L2, 5)
    s, cx = fit.scale_m_per_px, fit.cx
    floor_m = 0.012 * fit.height_m
    segs = segment_endpoints(fit)
    radii: Dict[str, float] = {}
    h, w = mask.shape
    for bone, (a, b) in segs.items():
        ts = np.linspace(0.1, 0.9, 9)
        pts = a[None] + ts[:, None] * (b - a)[None]
        px = np.clip(np.round(pts[:, 0] / s + cx).astype(int), 0, w - 1)
        py = np.clip(np.round(floor_y - pts[:, 1] / s).astype(int), 0, h - 1)
        vals = dt[py, px] * s
        vals = vals[vals > 0]
        radii[bone] = float(max(floor_m, np.median(vals))) if len(vals) else floor_m
    return radii


def skin_weights(xy: np.ndarray, fit: Fit, radii: Dict[str, float], max_influences: int = 4) -> Tuple[np.ndarray, np.ndarray, List[str]]:
    """(joints (N,4) indices into the returned bone list, weights (N,4) summing to 1, bone list)."""
    segs = segment_endpoints(fit)
    names = list(DEFORM)
    d = _dist_to_segments(xy, segs, names)
    r = np.array([max(radii[n], 0.02 * fit.height_m) for n in names], np.float32)[None]
    w = np.exp(-1.6 * (d / r) ** 2)
    # nothing close to any bone (a prop far from the skeleton): give it to the nearest bone outright
    far = w.max(axis=1) < 1e-4
    if far.any():
        w[far] = 0.0
        w[far, np.argmin(d[far], axis=1)] = 1.0
    idx = np.argsort(-w, axis=1)[:, :max_influences]
    top = np.take_along_axis(w, idx, axis=1)
    top = top / np.maximum(top.sum(axis=1, keepdims=True), 1e-9)
    # drop negligible influences so the glTF stays light
    top[top < 0.02] = 0.0
    top = top / np.maximum(top.sum(axis=1, keepdims=True), 1e-9)
    return idx.astype(np.uint16), top.astype(np.float32), names


def label_parts(shape_hw: Tuple[int, int], mask: np.ndarray, fit: Fit) -> np.ndarray:
    """(H, W) int8 label per picture pixel: index into ``PARTS``, or -1 outside the figure."""
    h, w = shape_hw
    ys, xs = np.nonzero(mask)
    s, cx, fy = fit.scale_m_per_px, fit.cx, fit.floor_y
    xy = np.stack([(xs - cx) * s, (fy - ys) * s], axis=1).astype(np.float32)
    segs = segment_endpoints(fit)
    names = list(DEFORM)
    d = _dist_to_segments(xy, segs, names)
    part_of = np.array([PARTS.index(GROUP[n]) for n in names], np.int8)
    lab = part_of[np.argmin(d, axis=1)]
    # a hat, hair or a big head: everything above the chin line is head (an arm cannot be above the chin in a standing figure)
    chin_y = fit.drawn["Head"][1]
    above = xy[:, 1] > chin_y
    lab[above] = PARTS.index("head")
    # shoes: everything below the ankle line is the foot on its side of the midline
    ankle_y = max(fit.drawn["Foot_L"][1], fit.drawn["Foot_R"][1]) + 0.012 * fit.height_m
    below = (xy[:, 1] < ankle_y) & (xy[:, 1] < fit.drawn["Calf_L"][1] * 0.6)
    lab[below & (xy[:, 0] >= 0)] = PARTS.index("foot_L")
    lab[below & (xy[:, 0] < 0)] = PARTS.index("foot_R")
    out = np.full((h, w), -1, np.int8)
    out[ys, xs] = lab
    return out
