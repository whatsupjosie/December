# PubCast AI — avatar_likeness/skeleton.py
# Copyright © 2024–2026 Josie Curtsey Cobbley (Joshua Cobbley)
# Rearview Foresight LLC — All Rights Reserved
# Feic Mo Chroí — See My Heart
"""The canonical PubCast skeleton, fitted to a character picture.

The names, parents and rest directions here are the contract the motion-capture side already uses
(``modules/avatar_performer.py`` ``AvatarBinding.rest_directions`` and ``MocapRetargeter.BONE_LANDMARK_PAIRS``;
``tests/test_avatar_likeness_skeleton.py`` fails if they drift apart). Rest pose is a T-pose: spine, neck and head
along +Y, the character's left arm along +X and right arm along -X, legs along -Y, feet along +Z, and the character
faces +Z. Every joint has an identity rest rotation, so a joint's local translation is simply child minus parent.

Two poses are kept side by side:

  rest    the canonical T-pose, in metres, built from the picture's own limb lengths (so a chibi keeps its stubby
          legs and a tall figure keeps its long ones), which is what mocap retargeting scales against.
  drawn   where the same joints sit in the picture as drawn (a relaxed pose, a raised hand, a lean). The mesh is
          built in the drawn pose so it matches the artwork, then ``rig.bake_to_rest`` carries it into the T-pose.

World frame for both: metres, +Y up, +X = the character's left = the picture's right, +Z = the way it faces,
origin on the floor under the pelvis.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np

from .landmarks import Landmarks

# (name, parent) in an order where a parent always precedes its children.
BONES: Tuple[Tuple[str, Optional[str]], ...] = (
    ("Root", None), ("Pelvis", "Root"),
    ("Spine_01", "Pelvis"), ("Spine_02", "Spine_01"), ("Spine_03", "Spine_02"), ("Neck_01", "Spine_03"), ("Head", "Neck_01"),
    ("Clavicle_L", "Spine_03"), ("UpperArm_L", "Clavicle_L"), ("LowerArm_L", "UpperArm_L"), ("Hand_L", "LowerArm_L"),
    ("Clavicle_R", "Spine_03"), ("UpperArm_R", "Clavicle_R"), ("LowerArm_R", "UpperArm_R"), ("Hand_R", "LowerArm_R"),
    ("Thigh_L", "Pelvis"), ("Calf_L", "Thigh_L"), ("Foot_L", "Calf_L"), ("Ball_L", "Foot_L"), ("Toe_L", "Ball_L"),
    ("Thigh_R", "Pelvis"), ("Calf_R", "Thigh_R"), ("Foot_R", "Calf_R"), ("Ball_R", "Foot_R"), ("Toe_R", "Ball_R"),
)
NAMES: Tuple[str, ...] = tuple(n for n, _ in BONES)
PARENT: Dict[str, Optional[str]] = dict(BONES)
CHILDREN: Dict[str, List[str]] = {n: [c for c, p in BONES if p == n] for n in NAMES}

_X, _Y, _Z = np.array([1.0, 0, 0]), np.array([0, 1.0, 0]), np.array([0, 0, 1.0])
# Direction each bone points at rest (matches AvatarBinding.rest_directions; Ball/Toe follow Foot).
REST_DIR: Dict[str, np.ndarray] = {
    "Pelvis": _Y, "Spine_01": _Y, "Spine_02": _Y, "Spine_03": _Y, "Neck_01": _Y, "Head": _Y,
    "Clavicle_L": _X, "UpperArm_L": _X, "LowerArm_L": _X, "Hand_L": _X,
    "Clavicle_R": -_X, "UpperArm_R": -_X, "LowerArm_R": -_X, "Hand_R": -_X,
    "Thigh_L": -_Y, "Calf_L": -_Y, "Foot_L": _Z, "Ball_L": _Z, "Toe_L": _Z,
    "Thigh_R": -_Y, "Calf_R": -_Y, "Foot_R": _Z, "Ball_R": _Z, "Toe_R": _Z,
}
# The bones whose vertices move when the character moves. Root/Ball/Toe exist for the retargeter but carry no weights.
DEFORM: Tuple[str, ...] = tuple(n for n in NAMES if n not in ("Root", "Ball_L", "Ball_R", "Toe_L", "Toe_R"))
SPINE_FRACTIONS = (0.222, 0.5, 0.778)       # Spine_01..03 along pelvis -> neck base (REF_PROPORTIONS ratios 0.08/0.10/0.10/0.08)
CLAVICLE_FRACTION = 0.3                      # clavicle joint sits this far from the midline toward the shoulder


@dataclass
class Fit:
    scale_m_per_px: float
    height_m: float
    cx: float                                # picture x of the pelvis (the midline)
    floor_y: float                           # picture y of the floor
    rest: Dict[str, np.ndarray]              # joint -> (3,) metres, T-pose
    drawn: Dict[str, np.ndarray]             # joint -> (3,) metres, as drawn
    lengths: Dict[str, float]                # bone -> length to its main child, metres
    foot_length_m: float
    ends: Dict[str, np.ndarray]              # drawn-pose end point of the bones that have no child bone (Head, Hands, Feet)

    def to_dict(self) -> Dict[str, object]:
        return {"scale_m_per_px": self.scale_m_per_px, "height_m": self.height_m, "cx": self.cx, "floor_y": self.floor_y,
                "foot_length_m": round(self.foot_length_m, 4),
                "rest": {k: [round(float(x), 5) for x in v] for k, v in self.rest.items()},
                "drawn": {k: [round(float(x), 5) for x in v] for k, v in self.drawn.items()},
                "lengths": {k: round(v, 5) for k, v in self.lengths.items()},
                "ends": {k: [round(float(x), 5) for x in v] for k, v in self.ends.items()}}


def _norm(v: np.ndarray) -> float:
    return float(np.linalg.norm(v))


def fit(lm: Landmarks, bbox: Tuple[int, int, int, int], height_m: float, foot_fraction: float) -> Fit:
    """Place the canonical skeleton on the picture. ``foot_fraction`` is the build's foot length as a fraction of height."""
    P = {k: np.array(v, float) for k, v in lm.points.items()}
    x0, y0, x1, y1 = bbox
    floor_y = float(y1)
    H_px = max(1.0, floor_y - float(P["head_top"][1]))
    s = height_m / H_px
    cx = float(P["pelvis"][0])

    def W(pt: np.ndarray) -> np.ndarray:                       # picture px -> drawn world metres
        return np.array([(pt[0] - cx) * s, (floor_y - pt[1]) * s, 0.0])

    D: Dict[str, np.ndarray] = {"Root": np.array([0.0, 0.0, 0.0]), "Pelvis": W(P["pelvis"])}
    neck_w, pel_w = W(P["neck"]), D["Pelvis"]
    for name, f in zip(("Spine_01", "Spine_02", "Spine_03"), SPINE_FRACTIONS):
        D[name] = pel_w + (neck_w - pel_w) * f
    D["Neck_01"] = neck_w
    D["Head"] = W(P["chin"]) if P["chin"][1] < P["neck"][1] else neck_w + np.array([0.0, 0.02 * height_m, 0.0])
    head_end = W(P["head_top"])
    for side in ("L", "R"):
        sh = W(P[f"shoulder_{side}"])
        D[f"Clavicle_{side}"] = np.array([CLAVICLE_FRACTION * sh[0], sh[1], 0.0])
        D[f"UpperArm_{side}"], D[f"LowerArm_{side}"] = sh, W(P[f"elbow_{side}"])
        D[f"Hand_{side}"] = W(P[f"wrist_{side}"])
        D[f"Thigh_{side}"] = W(P[f"hip_{side}"])
        D[f"Calf_{side}"], D[f"Foot_{side}"] = W(P[f"knee_{side}"]), W(P[f"ankle_{side}"])
    foot_len = max(0.03, foot_fraction * height_m)
    for side in ("L", "R"):
        f = D[f"Foot_{side}"]
        D[f"Ball_{side}"], D[f"Toe_{side}"] = f + np.array([0, 0, 0.6 * foot_len]), f + np.array([0, 0, foot_len])

    # lengths of each bone to its main child, from the drawn pose
    end = {"Head": head_end, "Hand_L": W(P["hand_tip_L"]), "Hand_R": W(P["hand_tip_R"])}
    ends = dict(end)
    for side in ("L", "R"):
        ends[f"Foot_{side}"] = W(P[f"toe_{side}"])
    main_child = {"Pelvis": "Spine_01", "Spine_01": "Spine_02", "Spine_02": "Spine_03", "Spine_03": "Neck_01", "Neck_01": "Head",
                  "Clavicle_L": "UpperArm_L", "UpperArm_L": "LowerArm_L", "LowerArm_L": "Hand_L",
                  "Clavicle_R": "UpperArm_R", "UpperArm_R": "LowerArm_R", "LowerArm_R": "Hand_R",
                  "Thigh_L": "Calf_L", "Calf_L": "Foot_L", "Thigh_R": "Calf_R", "Calf_R": "Foot_R"}
    L: Dict[str, float] = {}
    for b, c in main_child.items():
        L[b] = max(0.005, _norm(D[c] - D[b]))
    for b, e in end.items():
        L[b] = max(0.005, _norm(e - D[b]))
    for side in ("L", "R"):
        L[f"Foot_{side}"], L[f"Ball_{side}"] = 0.6 * foot_len, 0.4 * foot_len
    # the spine chain is one straight line at rest, so its pieces share the pelvis->neck length
    spine_total = _norm(D["Neck_01"] - D["Pelvis"])
    for b, f0, f1 in (("Pelvis", 0.0, SPINE_FRACTIONS[0]), ("Spine_01", SPINE_FRACTIONS[0], SPINE_FRACTIONS[1]),
                      ("Spine_02", SPINE_FRACTIONS[1], SPINE_FRACTIONS[2]), ("Spine_03", SPINE_FRACTIONS[2], 1.0)):
        L[b] = max(0.005, spine_total * (f1 - f0))

    # rest pose: walk the hierarchy, each child sits parent + length * rest direction (the contract's straight bones)
    R: Dict[str, np.ndarray] = {"Root": np.zeros(3), "Pelvis": np.array([0.0, D["Pelvis"][1], 0.0])}
    for name, parent in BONES:
        if parent is None or name == "Pelvis":
            continue
        if name in ("Spine_01", "Spine_02", "Spine_03", "Neck_01"):
            R[name] = R[parent] + _Y * L[parent]
        elif name == "Head":
            R[name] = R[parent] + _Y * _norm(D["Head"] - D["Neck_01"])
        elif name.startswith("Clavicle"):
            sgn = 1.0 if name.endswith("_L") else -1.0
            R[name] = np.array([sgn * abs(D[name][0]), D["UpperArm_" + name[-1]][1] - 0.0, 0.0])
        elif name.startswith("Thigh"):
            sgn = 1.0 if name.endswith("_L") else -1.0
            R[name] = np.array([sgn * abs(D[name][0]), R["Pelvis"][1], 0.0])
        elif name.startswith("UpperArm"):
            sgn = 1.0 if name.endswith("_L") else -1.0
            R[name] = np.array([sgn * abs(D[name][0]), R["Clavicle_" + name[-1]][1], 0.0])
        else:
            R[name] = R[parent] + REST_DIR[parent] * L[parent]
    return Fit(s, height_m, cx, floor_y, R, D, L, foot_len, ends)


def local_translations(rest: Dict[str, np.ndarray]) -> Dict[str, np.ndarray]:
    """glTF node translation for each joint: its rest position minus its parent's (rotations are identity at rest)."""
    return {n: (rest[n] - rest[p]) if p else rest[n].copy() for n, p in BONES}


def parity_with_mocap_contract() -> List[str]:
    """Differences against ``avatar_performer.AvatarBinding`` (empty list = same). Needs that module's imports."""
    from modules import avatar_performer as ap       # noqa: WPS433 - deliberate late import, the module pulls in websockets
    bind = ap.AvatarBinding.create("MANNY")
    problems: List[str] = []
    for name, vec in bind.rest_directions.items():
        mine = REST_DIR.get(name)
        if mine is None:
            problems.append(f"{name}: in the mocap contract but not in this skeleton")
        elif not np.allclose(mine, vec):
            problems.append(f"{name}: rest direction {mine.tolist()} != contract {np.asarray(vec).tolist()}")
    for child, (parent, _) in ((k, v) for k, v in ap.MocapRetargeter.BONE_LANDMARK_PAIRS.items()):
        if child not in PARENT:
            problems.append(f"{child}: used by the retargeter but not in this skeleton")
    return problems
