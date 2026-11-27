# PubCast AI — avatar_likeness/retarget.py
# Copyright © 2024–2026 Josie Curtsey Cobbley (Joshua Cobbley)
# Rearview Foresight LLC — All Rights Reserved
# Feic Mo Chroí — See My Heart
"""Carry a recorded clip from another humanoid onto an avatar built here.

Method: world-orientation transfer. Both rigs rest in a T-pose whose bones are aligned with the world axes, so a
bone's orientation change from rest ("how far is this bone turned from where it sits in the T-pose, in world space")
means the same thing on both. The target joint takes the source bone's world orientation change and is expressed in
its own parent's frame. Rotation is what moves; limb lengths belong to the target, so a 0.9 m child does not stretch
to a 1.8 m mannequin's reach. Hip height is the one translation carried over, scaled by the ratio of pelvis heights;
sideways and forward travel are dropped because the Studio moves the avatar across the floor itself.

Source rig: any glTF whose skin uses Mixamo names (``mixamorig:Hips`` ...) with a world-aligned rest, such as the
repository's ``static/world/test_avatars/Xbot.glb``. ``MIXAMO_MAP`` is the only table to extend for another naming.

Limits stated plainly: no foot planting (feet can slide when proportions differ), no collision between limbs and the
body shell, and finger motion is not carried because the avatar has no finger bones.
"""
from __future__ import annotations

import math
from typing import Dict, List, Optional, Tuple

import numpy as np

from . import gltf_io
from .motion import Clip, FPS, q_mul
from .skeleton import BONES, NAMES, PARENT

MIXAMO_MAP: Dict[str, str] = {
    "Pelvis": "Hips", "Spine_01": "Spine", "Spine_02": "Spine1", "Spine_03": "Spine2", "Neck_01": "Neck", "Head": "Head",
    "Clavicle_L": "LeftShoulder", "UpperArm_L": "LeftArm", "LowerArm_L": "LeftForeArm", "Hand_L": "LeftHand",
    "Clavicle_R": "RightShoulder", "UpperArm_R": "RightArm", "LowerArm_R": "RightForeArm", "Hand_R": "RightHand",
    "Thigh_L": "LeftUpLeg", "Calf_L": "LeftLeg", "Foot_L": "LeftFoot", "Ball_L": "LeftToeBase",
    "Thigh_R": "RightUpLeg", "Calf_R": "RightLeg", "Foot_R": "RightFoot", "Ball_R": "RightToeBase",
}


def q_conj(q: np.ndarray) -> np.ndarray:
    return np.array([-q[0], -q[1], -q[2], q[3]])


def slerp(a: np.ndarray, b: np.ndarray, t: float) -> np.ndarray:
    d = float(a @ b)
    if d < 0:
        b, d = -b, -d
    if d > 0.9995:
        r = a + t * (b - a)
        return r / np.linalg.norm(r)
    th = math.acos(min(1.0, d))
    return (math.sin((1 - t) * th) * a + math.sin(t * th) * b) / math.sin(th)


class SourceRig:
    """A glTF skin with its animations, evaluated by forward kinematics."""

    def __init__(self, glb: bytes, prefix: str = "mixamorig:"):
        self.doc, self.bin = gltf_io.read_glb(glb)
        self.nodes = self.doc["nodes"]
        self.by_name = {n.get("name", ""): i for i, n in enumerate(self.nodes)}
        self.prefix = prefix
        self.parent: Dict[int, int] = {}
        for i, n in enumerate(self.nodes):
            for c in n.get("children", []):
                self.parent[c] = i
        self.clips = {a["name"]: a for a in self.doc.get("animations", [])}
        self.rest_rot = {i: np.array(n.get("rotation", [0, 0, 0, 1]), float) for i, n in enumerate(self.nodes)}
        self.rest_pos = {i: np.array(n.get("translation", [0, 0, 0]), float) for i, n in enumerate(self.nodes)}

    def index(self, short: str) -> Optional[int]:
        return self.by_name.get(self.prefix + short)

    def _order(self) -> List[int]:
        out: List[int] = []
        seen = set()
        def visit(i: int) -> None:
            if i in seen:
                return
            if i in self.parent:
                visit(self.parent[i])
            seen.add(i)
            out.append(i)
        for i in range(len(self.nodes)):
            visit(i)
        return out

    def _track(self, anim: Dict, path: str) -> Dict[int, Tuple[np.ndarray, np.ndarray]]:
        tracks = {}
        for ch in anim["channels"]:
            if ch["target"]["path"] != path:
                continue
            s = anim["samplers"][ch["sampler"]]
            tracks[ch["target"]["node"]] = (gltf_io._accessor_array(self.doc, self.bin, s["input"]).astype(float),
                                            gltf_io._accessor_array(self.doc, self.bin, s["output"]).astype(float))
        return tracks

    def evaluate(self, clip: str, fps: int = FPS) -> Tuple[np.ndarray, Dict[int, np.ndarray], Dict[int, np.ndarray], Optional[np.ndarray]]:
        """(times, world rotation per node per frame, local translation of the hips per frame...)

        Returns times, {node: (T,4) world quaternions}, {node: (T,4) rest-relative world delta}, hips translation (T,3).
        """
        if clip not in self.clips:
            raise KeyError(f"the source has no clip named {clip!r}; it has {', '.join(self.clips)}")
        anim = self.clips[clip]
        rot, pos = self._track(anim, "rotation"), self._track(anim, "translation")
        dur = max(float(t.max()) for t, _ in rot.values())
        n = max(2, int(round(dur * fps)) + 1)
        times = np.linspace(0.0, dur, n)
        def sample(track: Tuple[np.ndarray, np.ndarray], t: float, quat: bool) -> np.ndarray:
            ts, vs = track
            if t <= ts[0]:
                return vs[0]
            if t >= ts[-1]:
                return vs[-1]
            k = int(np.searchsorted(ts, t) - 1)
            f = (t - ts[k]) / max(1e-9, ts[k + 1] - ts[k])
            return slerp(vs[k] / np.linalg.norm(vs[k]), vs[k + 1] / np.linalg.norm(vs[k + 1]), f) if quat else vs[k] * (1 - f) + vs[k + 1] * f
        order = self._order()
        world = {i: np.zeros((n, 4)) for i in range(len(self.nodes))}
        rest_world: Dict[int, np.ndarray] = {}
        for i in order:
            p = self.parent.get(i)
            rest_world[i] = q_mul(rest_world[p], self.rest_rot[i]) if p is not None else self.rest_rot[i]
        for k, t in enumerate(times):
            for i in order:
                q = sample(rot[i], t, True) if i in rot else self.rest_rot[i]
                p = self.parent.get(i)
                world[i][k] = q_mul(world[p][k], q) if p is not None else q
        delta = {i: np.array([q_mul(w, q_conj(rest_world[i])) for w in world[i]]) for i in range(len(self.nodes))}
        hips = self.index("Hips")
        hips_pos = np.array([sample(pos[hips], t, False) for t in times]) if hips in pos else None
        return times, world, delta, hips_pos


def retarget_clip(source: SourceRig, clip: str, rest: Dict[str, np.ndarray], local: Dict[str, np.ndarray],
                  name: Optional[str] = None, in_place: bool = True) -> Clip:
    """Retarget one source clip onto a skeleton given by its T-pose joint positions (``rig.Rigged.rest`` / ``.local``)."""
    times, _, delta, hips_pos = source.evaluate(clip)
    n = len(times)
    target_world: Dict[str, np.ndarray] = {}
    rotations: Dict[str, np.ndarray] = {}
    ident = np.tile(np.array([0.0, 0.0, 0.0, 1.0]), (n, 1))
    for joint, parent in BONES:
        src = source.index(MIXAMO_MAP[joint]) if joint in MIXAMO_MAP else None
        # a joint with no counterpart in the source (Root, Toe) keeps its parent's orientation
        w = np.array(delta[src]) if src is not None else (target_world[parent] if parent else ident)
        target_world[joint] = w
        pw = target_world.get(parent, ident) if parent else ident
        rotations[joint] = np.array([q_mul(q_conj(pw[k]), w[k]) for k in range(n)])
        rotations[joint] /= np.linalg.norm(rotations[joint], axis=1, keepdims=True)
    translations: Dict[str, np.ndarray] = {}
    hips = source.index("Hips")
    if hips_pos is not None:
        ratio = float(rest["Pelvis"][1]) / max(1e-6, float(source.rest_pos[hips][1]))
        base = local["Pelvis"].copy()
        d = (hips_pos - hips_pos[0]) * ratio
        if in_place:
            d[:, 0] = 0.0
            d[:, 2] = 0.0
        translations["Pelvis"] = base[None, :] + d
    rotations = {j: q for j, q in rotations.items() if j != "Root"}
    return Clip(name or f"Retarget_{clip}", float(times[-1]), times, rotations, translations)
