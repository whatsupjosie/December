# PubCast AI — avatar_likeness/motion.py
# Copyright © 2024–2026 Josie Curtsey Cobbley (Joshua Cobbley)
# Rearview Foresight LLC — All Rights Reserved
# Feic Mo Chroí — See My Heart
"""Motion for a freshly built avatar: the Idle and Walk clips the Studio player looks for, and a retargeter that
carries a recorded clip from another rig onto this one.

Why it is here and not a separate file of canned keyframes: every number depends on the avatar. A toddler's legs
are 0.23 m long and an adult's 0.75 m, so the cadence, the knee bend and the bob scale with the skeleton the picture
produced. The clips are plain rotations on the canonical joints (rest = T-pose, identity rotations), so they play on
any avatar from this package and on the Xbot-style mannequin names the mocap code already uses.

Clip names are the ones ``static/world_walk_glb.js`` matches: /walk/i and /idle|stand|breath/i.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

FPS = 24
Quat = np.ndarray  # (4,) x, y, z, w


def q_axis(axis: Tuple[float, float, float], deg: float) -> Quat:
    a = np.asarray(axis, float)
    a = a / np.linalg.norm(a)
    h = math.radians(deg) / 2.0
    return np.array([*(a * math.sin(h)), math.cos(h)])


def q_mul(a: Quat, b: Quat) -> Quat:
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return np.array([aw * bx + ax * bw + ay * bz - az * by, aw * by - ax * bz + ay * bw + az * bx,
                     aw * bz + ax * by - ay * bx + az * bw, aw * bw - ax * bx - ay * by - az * bz])


X, Y, Z = (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)
ARM_DOWN_DEG = 78.0           # arms hang a little away from the body so they clear the torso shell


@dataclass
class Clip:
    name: str
    duration: float
    times: np.ndarray                                   # (T,) seconds
    rotations: Dict[str, np.ndarray] = field(default_factory=dict)      # joint -> (T, 4)
    translations: Dict[str, np.ndarray] = field(default_factory=dict)   # joint -> (T, 3), absolute local translation


def q_from_matrix(m: np.ndarray) -> Quat:
    t = float(np.trace(m))
    if t > 0:
        r = math.sqrt(1.0 + t) * 2
        q = np.array([(m[2, 1] - m[1, 2]) / r, (m[0, 2] - m[2, 0]) / r, (m[1, 0] - m[0, 1]) / r, 0.25 * r])
    else:
        i = int(np.argmax(np.diag(m)))
        j, k = (i + 1) % 3, (i + 2) % 3
        r = math.sqrt(1.0 + m[i, i] - m[j, j] - m[k, k]) * 2
        q = np.zeros(4)
        q[i], q[3] = 0.25 * r, (m[k, j] - m[j, k]) / r
        q[j], q[k] = (m[j, i] + m[i, j]) / r, (m[k, i] + m[i, k]) / r
    return q / np.linalg.norm(q)


def _rest_pose_rotations(joints: List[str], drawn: Optional[Dict[str, Quat]] = None) -> Dict[str, Quat]:
    """The pose clips start from. ``drawn`` is the pose in the picture (so the avatar at rest looks like the artwork);
    without it the arms hang by the sides, which is what a character drawn in a T-pose wants."""
    base = {j: np.array([0.0, 0.0, 0.0, 1.0]) for j in joints}
    if drawn is not None:
        for j, q in drawn.items():
            if j in base:
                base[j] = np.asarray(q, float)
        return base
    base["UpperArm_L"] = q_axis(Z, -ARM_DOWN_DEG)        # +X toward -Y
    base["UpperArm_R"] = q_axis(Z, +ARM_DOWN_DEG)        # -X toward -Y
    return base


def leg_length(rest: Dict[str, np.ndarray]) -> float:
    return float(np.linalg.norm(rest["Thigh_L"] - rest["Calf_L"]) + np.linalg.norm(rest["Calf_L"] - rest["Foot_L"]))


def make_walk(rest: Dict[str, np.ndarray], local: Dict[str, np.ndarray], joints: List[str], drawn: Optional[Dict[str, Quat]] = None) -> Clip:
    leg = leg_length(rest)
    period = float(np.clip(1.05 * math.sqrt(leg / 0.75), 0.6, 1.3))
    n = int(round(period * FPS))
    times = np.arange(n + 1) / FPS * (period / (n / FPS))
    base = _rest_pose_rotations(joints, drawn)
    rot = {j: np.tile(base[j], (n + 1, 1)) for j in joints}
    pelvis_rest = local["Pelvis"].copy()
    trans = {"Pelvis": np.tile(pelvis_rest, (n + 1, 1))}
    for k in range(n + 1):
        t = k / n
        ph = 2 * math.pi * t
        for side, phi in (("L", 0.0), ("R", math.pi)):
            fwd = math.sin(ph + phi)                       # +1 = leg furthest forward
            th = -28.0 * fwd                               # forward swing is a negative turn about X
            knee = 4.0 + 38.0 * max(0.0, math.cos(ph + phi))
            rot[f"Thigh_{side}"][k] = q_mul(q_axis(X, th), base[f"Thigh_{side}"])
            rot[f"Calf_{side}"][k] = q_mul(q_axis(X, knee), base[f"Calf_{side}"])
            rot[f"Foot_{side}"][k] = q_axis(X, -0.6 * (th + knee))
            # a hanging arm swings back (positive turn about X) when the leg on its own side is forward
            rot[f"UpperArm_{side}"][k] = q_mul(q_axis(X, 18.0 * fwd), base[f"UpperArm_{side}"])
            # the elbow bends the forearm forward (+Z): about the bone-local Y, with the sign set by which way the bone points
            bend = 14.0 + 12.0 * max(0.0, -fwd)
            rot[f"LowerArm_{side}"][k] = q_mul(q_axis(Y, -bend if side == "L" else bend), base[f"LowerArm_{side}"])
        rot["Pelvis"][k] = q_mul(q_axis(Y, 5.0 * math.sin(ph)), q_axis(Z, 2.5 * math.sin(ph)))
        rot["Spine_02"][k] = q_axis(Y, -4.0 * math.sin(ph))
        rot["Head"][k] = q_axis(Y, 3.0 * math.sin(ph))
        trans["Pelvis"][k] = pelvis_rest + np.array([0.012 * leg * math.sin(ph), -0.035 * leg * (0.5 + 0.5 * math.cos(2 * ph)), 0.0])
    # the loop closes: last key equals the first
    for j in rot:
        rot[j][-1] = rot[j][0]
    trans["Pelvis"][-1] = trans["Pelvis"][0]
    return Clip("Walk", float(times[-1]), times, rot, trans)


def make_idle(rest: Dict[str, np.ndarray], local: Dict[str, np.ndarray], joints: List[str], drawn: Optional[Dict[str, Quat]] = None) -> Clip:
    period = 4.0
    n = int(period * 12)
    times = np.arange(n + 1) / 12.0
    base = _rest_pose_rotations(joints, drawn)
    rot = {j: np.tile(base[j], (n + 1, 1)) for j in joints}
    for k in range(n + 1):
        ph = 2 * math.pi * k / n
        rot["Spine_03"][k] = q_axis(X, -1.2 * math.sin(ph))
        rot["Spine_01"][k] = q_axis(X, 0.5 * math.sin(ph))
        rot["Head"][k] = q_mul(q_axis(Y, 2.0 * math.sin(ph * 0.5)), q_axis(X, 0.8 * math.sin(ph + 0.6)))
        for side in ("L", "R"):
            rot[f"UpperArm_{side}"][k] = q_mul(q_axis(X, 0.8 * math.sin(ph + 0.4)), base[f"UpperArm_{side}"])
            rot[f"LowerArm_{side}"][k] = q_mul(q_axis(Y, -6.0 if side == "L" else 6.0), base[f"LowerArm_{side}"])
    for j in rot:
        rot[j][-1] = rot[j][0]
    return Clip("Idle", float(times[-1]), times, rot, {})


def default_clips(rest: Dict[str, np.ndarray], local: Dict[str, np.ndarray], joints: List[str], drawn: Optional[Dict[str, Quat]] = None) -> List[Clip]:
    return [make_idle(rest, local, joints, drawn), make_walk(rest, local, joints, drawn)]
