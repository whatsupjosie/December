# PubCast AI — avatar_likeness/shape.py
# Copyright © 2024–2026 Josie Curtsey Cobbley (Joshua Cobbley)
# Rearview Foresight LLC — All Rights Reserved
# Feic Mo Chroí — See My Heart
"""Body shape from one picture: a closed, part-aware shell that follows the character's own outline.

What this is, and what it is not. The cut-out gives the exact silhouette from the front. Depth is not in the picture,
so it is inferred from the outline: each part gets a rounded cross-section whose size comes from that part's own width
(a chibi head is deep, a thin arm is thin), with the torso flatter than the limbs and the shoes extended forward so
they have a sole to walk on. This is a prior, not a reconstruction, and the report says so. The ``depth`` controls
(one multiplier per part) are how a person corrects what a single view cannot show; a learned shape model can replace
``build_shell``'s depth field later without touching the rig, texture or export stages.

Front vertices carry the original artwork's coordinates, so the front of the character IS the supplied picture.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Tuple

import numpy as np

from . import deps
from .intake import Cutout
from .parts import PARTS
from .skeleton import Fit

# cross-section depth as a fraction of the part's half-width: torso flatter than limbs; head deep enough to read as a head
DEFAULT_DEPTH: Dict[str, float] = {"head": 1.15, "torso": 0.85, "arm_L": 1.0, "arm_R": 1.0, "hand_L": 0.8, "hand_R": 0.8,
                                   "leg_L": 1.05, "leg_R": 1.05, "foot_L": 0.8, "foot_R": 0.8}
BACK_RATIO = 0.9            # the back is a little shallower than the front: backs are flatter than fronts
TARGET_ROWS = 200           # grid rows from head to floor; ~40k triangles for a full figure
PAD_FRACTION = 0.02


@dataclass
class Shell:
    pos: np.ndarray             # (N, 3) float32, drawn-pose world metres; front vertices first, then back
    uv: np.ndarray              # (N, 2) float32, glTF convention (v down) into the front|back atlas
    faces: np.ndarray           # (M, 3) uint32
    px: np.ndarray              # (N, 2) float32, picture coordinates of each vertex
    part: np.ndarray            # (N,) int8 index into PARTS
    side: np.ndarray            # (N,) int8, 0 front 1 back
    crop: Tuple[int, int, int, int]   # x0, y0, w, h of the picture region the atlas covers

    @property
    def n_front(self) -> int:
        return int((self.side == 0).sum())


def _field(mask: np.ndarray, labels: np.ndarray, fit: Fit, depth: Dict[str, float]) -> Tuple[np.ndarray, np.ndarray]:
    """Per-pixel half-depth in pixels for the front and for the back."""
    cv2 = deps.require("cv2", "opencv-python-headless")
    dt = cv2.distanceTransform(mask.astype(np.uint8), cv2.DIST_L2, 5)
    hw = np.zeros_like(dt)
    k = np.zeros_like(dt)
    for i, name in enumerate(PARTS):
        sel = labels == i
        if not sel.any():
            continue
        hw[sel] = max(2.0, float(np.percentile(dt[sel], 92)))
        k[sel] = depth.get(name, DEFAULT_DEPTH[name])
    sig = max(1.5, 0.02 * (mask.shape[0]))
    # blur across part boundaries so a shoulder does not step; only inside the figure
    m = mask.astype(np.float32)
    hw = cv2.GaussianBlur(hw * m, (0, 0), sig) / np.maximum(cv2.GaussianBlur(m, (0, 0), sig), 1e-3)
    k = cv2.GaussianBlur(k * m, (0, 0), sig) / np.maximum(cv2.GaussianBlur(m, (0, 0), sig), 1e-3)
    d = np.minimum(dt, hw)
    prof = k * (2.0 * d - d * d / np.maximum(hw, 1e-3))          # parabolic, 0 at the edge, k*hw at the middle
    prof[~mask] = 0.0
    front, back = prof.copy(), prof * BACK_RATIO
    # shoes get a sole: their front reaches forward by the foot length while the heel stays put
    foot_px = fit.foot_length_m / fit.scale_m_per_px
    for name in ("foot_L", "foot_R"):
        sel = labels == PARTS.index(name)
        if sel.any():
            reach = foot_px * np.sqrt(np.clip(dt / np.maximum(hw, 1e-3), 0, 1))
            front[sel] = np.maximum(front[sel], reach[sel] * 0.8)
            back[sel] = prof[sel] * 0.4
    return front, back


def build_shell(cut: Cutout, labels: np.ndarray, fit: Fit, depth: Optional[Dict[str, float]] = None,
                rows: int = TARGET_ROWS) -> Shell:
    cv2 = deps.require("cv2", "opencv-python-headless")
    depth = {**DEFAULT_DEPTH, **(depth or {})}
    mask = cut.alpha > 0.5
    h, w = mask.shape
    x0b, y0b, x1b, y1b = cut.report.bbox
    pad = max(2, int(PAD_FRACTION * max(x1b - x0b, y1b - y0b)))
    cx0, cy0 = max(0, x0b - pad), max(0, y0b - pad)
    cx1, cy1 = min(w, x1b + pad), min(h, y1b + pad)
    crop = (cx0, cy0, cx1 - cx0, cy1 - cy0)

    front_px, back_px = _field(mask, labels, fit, depth)
    step = max(1, int(round((y1b - y0b) / rows)))
    gw, gh = int(np.ceil((cx1 - cx0) / step)), int(np.ceil((cy1 - cy0) / step))
    region = np.zeros((gh * step, gw * step), np.float32)
    region[: cy1 - cy0, : cx1 - cx0] = mask[cy0:cy1, cx0:cx1]
    active = cv2.resize(region, (gw, gh), interpolation=cv2.INTER_AREA) > 0.2      # (gh, gw) cells, a little generous at the rim
    # nodes are the cells' corners, (gh+1, gw+1). A node is on the rim when some, but not all, of its four cells are active.
    pa = np.pad(active, 1, constant_values=False)
    nb = [pa[0:gh + 1, 0:gw + 1], pa[0:gh + 1, 1:gw + 2], pa[1:gh + 2, 0:gw + 1], pa[1:gh + 2, 1:gw + 2]]
    node_active = nb[0] | nb[1] | nb[2] | nb[3]
    edge = node_active & ~(nb[0] & nb[1] & nb[2] & nb[3])
    ii, jj = np.nonzero(node_active)
    nx = np.clip(cx0 + jj * step, 0, w - 1)
    ny = np.clip(cy0 + ii * step, 0, h - 1)
    zf = front_px[ny, nx].astype(np.float32)
    zb = back_px[ny, nx].astype(np.float32)
    rim = edge[ii, jj]
    zf[rim] = 0.0
    zb[rim] = 0.0
    nid = -np.ones((gh + 1, gw + 1), np.int64)
    nid[ii, jj] = np.arange(len(ii))
    n = len(ii)
    s, cx, fy = fit.scale_m_per_px, fit.cx, fit.floor_y
    X = (cx0 + jj * step - cx) * s
    Y = (fy - (cy0 + ii * step)) * s
    pos = np.concatenate([np.stack([X, Y, zf * s], 1), np.stack([X, Y, -zb * s], 1)]).astype(np.float32)
    pxy = np.stack([cx0 + jj * step, cy0 + ii * step], 1).astype(np.float32)
    px = np.concatenate([pxy, pxy])
    u = (pxy[:, 0] - cx0) / crop[2]
    v = (pxy[:, 1] - cy0) / crop[3]
    uv = np.concatenate([np.stack([0.5 * u, v], 1), np.stack([0.5 + 0.5 * (1.0 - u), v], 1)]).astype(np.float32)
    ci, cj = np.nonzero(active)
    a, b, c, d = nid[ci, cj], nid[ci, cj + 1], nid[ci + 1, cj + 1], nid[ci + 1, cj]
    front = np.concatenate([np.stack([a, d, c], 1), np.stack([a, c, b], 1)])
    back = n + np.concatenate([np.stack([a, c, d], 1), np.stack([a, b, c], 1)])
    faces = np.concatenate([front, back]).astype(np.uint32)
    lab = labels[np.clip(pxy[:, 1].astype(int), 0, h - 1), np.clip(pxy[:, 0].astype(int), 0, w - 1)]
    # rim nodes can sit just outside the figure (label -1): borrow the nearest inside label
    if (lab < 0).any():
        from scipy import ndimage
        ind = ndimage.distance_transform_edt(labels < 0, return_distances=False, return_indices=True)
        yy, xx = ind[0][np.clip(pxy[:, 1].astype(int), 0, h - 1), np.clip(pxy[:, 0].astype(int), 0, w - 1)], \
                 ind[1][np.clip(pxy[:, 1].astype(int), 0, h - 1), np.clip(pxy[:, 0].astype(int), 0, w - 1)]
        lab = np.where(lab < 0, labels[yy, xx], lab)
    part = np.concatenate([lab, lab]).astype(np.int8)
    side = np.concatenate([np.zeros(n), np.ones(n)]).astype(np.int8)
    return Shell(pos, uv, faces, px, part, side, crop)
