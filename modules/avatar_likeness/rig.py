# PubCast AI — avatar_likeness/rig.py
# Copyright © 2024–2026 Josie Curtsey Cobbley (Joshua Cobbley)
# Rearview Foresight LLC — All Rights Reserved
# Feic Mo Chroí — See My Heart
"""Skin the shell to the canonical skeleton and carry it from the pose it was drawn in into the T-pose.

The shell is built where the picture shows the body (a hand in a pocket, arms down, a lean). The mocap contract needs
a T-pose rest. ``bake_to_rest`` moves each vertex there with the same linear blend skinning the avatar will use at
runtime: for each bone, rotate the vertex about that bone's drawn joint so the bone's drawn direction becomes its
canonical rest direction, then place it at the bone's canonical joint. For a figure already drawn in a T-pose the
rotations are close to zero and nothing moves, which the tests check.

Feet are the one exception: a foot's canonical direction is +Z (forward) but a front-view picture shows it pointing
at the camera, so feet are translated, not rotated; ``shape`` already gives the shoe its forward length.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple

import numpy as np

from .parts import PARTS, SEGMENTS, bone_radii, segment_endpoints, skin_weights
from .shape import Shell
from .skeleton import BONES, DEFORM, NAMES, REST_DIR, Fit, local_translations

NO_ROTATION = ("Foot_L", "Foot_R")


@dataclass
class Rigged:
    pos: np.ndarray                 # (N, 3) float32, T-pose metres, feet on the floor
    joints: np.ndarray              # (N, 4) uint16, indices into ``names``
    weights: np.ndarray             # (N, 4) float32
    names: List[str]                # skin joint order (= skeleton.NAMES)
    rest: Dict[str, np.ndarray]     # joint -> (3,) T-pose position, floor-corrected
    local: Dict[str, np.ndarray]    # joint -> glTF node translation
    ibm: np.ndarray                 # (J, 4, 4) float32 inverse bind matrices, row-major here (the writer transposes)
    moved_m: float                  # largest distance any vertex travelled in the bake (0 for a figure drawn in a T-pose)
    floor_shift_m: float


def _arc(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Shortest-arc rotation matrix taking unit vector a to unit vector b. Opposite vectors turn about Z."""
    a, b = a / np.linalg.norm(a), b / np.linalg.norm(b)
    v = np.cross(a, b)
    c = float(a @ b)
    if c > 1 - 1e-9:
        return np.eye(3)
    if c < -1 + 1e-9:
        return np.array([[-1.0, 0, 0], [0, -1.0, 0], [0, 0, 1.0]])      # 180 degrees about Z
    vx = np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]])
    return np.eye(3) + vx + vx @ vx * (1.0 / (1.0 + c))


def bone_rotations(fit: Fit) -> Dict[str, np.ndarray]:
    segs = segment_endpoints(fit)
    out: Dict[str, np.ndarray] = {}
    for bone in DEFORM:
        if bone in NO_ROTATION:
            out[bone] = np.eye(3)
            continue
        a, b = segs[bone]
        d = np.array([b[0] - a[0], b[1] - a[1], 0.0])
        out[bone] = np.eye(3) if np.linalg.norm(d) < 1e-9 else _arc(d, REST_DIR[bone])
    return out


def rig(shell: Shell, fit: Fit, mask: np.ndarray) -> Rigged:
    radii = bone_radii(fit, mask, fit.floor_y)
    s, cx, fy = fit.scale_m_per_px, fit.cx, fit.floor_y
    xy = np.stack([(shell.px[:, 0] - cx) * s, (fy - shell.px[:, 1]) * s], axis=1).astype(np.float32)
    dj, dw, dnames = skin_weights(xy, fit, radii)
    index = {n: i for i, n in enumerate(NAMES)}
    joints = np.vectorize(lambda i: index[dnames[i]], otypes=[np.uint16])(dj)

    rot = bone_rotations(fit)
    pos = np.zeros_like(shell.pos, dtype=np.float64)
    for k in range(4):
        for bi, bone in enumerate(dnames):
            sel = (dj[:, k] == bi) & (dw[:, k] > 0)
            if not sel.any():
                continue
            drawn_j, rest_j = fit.drawn[bone], fit.rest[bone]
            moved = rest_j + (shell.pos[sel].astype(np.float64) - drawn_j) @ rot[bone].T
            pos[sel] += dw[sel, k:k + 1] * moved
    moved_m = float(np.linalg.norm(pos - shell.pos, axis=1).max())

    # feet on the floor: lift or lower everything except the Root joint, which stays on the floor by definition
    shift = -float(pos[:, 1].min())
    pos[:, 1] += shift
    rest = {n: (v.copy() if n == "Root" else v + np.array([0.0, shift, 0.0])) for n, v in fit.rest.items()}
    ibm = np.tile(np.eye(4, dtype=np.float32), (len(NAMES), 1, 1))
    for n in NAMES:
        ibm[index[n], :3, 3] = -rest[n]
    return Rigged(pos.astype(np.float32), joints, dw, list(NAMES), rest, local_translations(rest), ibm, moved_m, shift)


def skeleton_summary(rest: Dict[str, np.ndarray]) -> Dict[str, object]:
    """Numbers the report and the tests quote: limb lengths and widths in metres."""
    d = lambda a, b: float(np.linalg.norm(rest[a] - rest[b]))
    return {
        "height_pelvis_m": float(rest["Pelvis"][1]),
        "shoulder_width_m": d("UpperArm_L", "UpperArm_R"),
        "hip_width_m": d("Thigh_L", "Thigh_R"),
        "upper_arm_m": d("UpperArm_L", "LowerArm_L"), "forearm_m": d("LowerArm_L", "Hand_L"),
        "thigh_m": d("Thigh_L", "Calf_L"), "calf_m": d("Calf_L", "Foot_L"),
        "spine_m": d("Pelvis", "Neck_01"), "neck_to_head_m": d("Neck_01", "Head"),
    }


def drawn_pose_rotations(fit: Fit) -> Dict[str, np.ndarray]:
    """Local joint rotations (quaternions x, y, z, w) that put the T-pose skeleton back into the pose the picture shows.

    The bake rotates each bone's vertices by R_b to reach the T-pose; the drawn pose is the inverse. A bone's local
    rotation is its parent's bake rotation times the transpose of its own. Playing these as the rest pose of Idle
    and Walk makes the avatar at rest match the artwork instead of standing in a T-pose.
    """
    from .motion import q_from_matrix
    R = bone_rotations(fit)
    out: Dict[str, np.ndarray] = {}
    for name, parent in BONES:
        Rp = R.get(parent, np.eye(3)) if parent else np.eye(3)
        Rb = R.get(name, np.eye(3))
        out[name] = q_from_matrix(Rp @ Rb.T)
    return out
