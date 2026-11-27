# PubCast AI — avatar_likeness/pipeline.py
# Copyright © 2024–2026 Josie Curtsey Cobbley (Joshua Cobbley)
# Rearview Foresight LLC — All Rights Reserved
# Feic Mo Chroí — See My Heart
"""One character picture in, one rigged glTF avatar out, and a way to rebuild it after the person edits it.

    intake -> landmarks -> skeleton fit -> parts -> shape -> rig (bake to T-pose) -> texture atlas -> motion -> .glb

``build`` runs the whole chain from image bytes. ``rebuild`` runs it from a GLB this package wrote: the artwork comes
from the atlas inside the file, the recipe supplies everything else, and ``edits`` change what the person changed
(moved joints, depth, back view, height, name). Both return the same ``Built`` so the host, the tests and the
command-line tool share one path.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from . import deps, gltf_io, intake, landmarks as lmk, matte as matte_mod, motion, parts, rig, shape, skeleton, texture
from .skeleton import NAMES

VERSION = "1"
PUB_BLOCK_M = 0.254          # modules/voxel_set_contract.PUB_BLOCK_METERS; repeated here so the package imports alone, a test pins them equal
MIN_HEIGHT_M, MAX_HEIGHT_M = 0.15, 3.5

UNSEEN = [
    "The back and the sides of the character are not in the picture. They are generated from the front's colours (back view setting) and a rounded body shape inferred from the outline.",
    "Depth is inferred. Parts are given rounded cross-sections sized from their own width; use the depth sliders where the character is flatter or deeper than that.",
    "Shoes are given a sole length from the build; the picture shows them head-on.",
]


@dataclass
class Settings:
    name: str = "avatar"
    height_m: float = 1.7
    build: Optional[str] = None                      # adult | child | toddler; chosen from the height when None
    pose_hint: Optional[str] = None                  # tpose | relaxed for the template fallback
    depth: Dict[str, float] = field(default_factory=dict)
    back_mode: str = "plain"
    hair_rgb: Optional[Tuple[int, int, int]] = None
    unlit: bool = True
    joints: Dict[str, Sequence[float]] = field(default_factory=dict)       # the person's dragged joints, picture pixels
    floor_y: Optional[float] = None                  # the person's floor line in picture pixels (feet cut off by the frame)

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "height_m": round(self.height_m, 5), "build": self.build, "pose_hint": self.pose_hint,
                "depth": {k: float(v) for k, v in self.depth.items()}, "back_mode": self.back_mode,
                "hair_rgb": list(self.hair_rgb) if self.hair_rgb else None, "unlit": self.unlit,
                "joints": {k: [float(v[0]), float(v[1])] for k, v in self.joints.items()}, "floor_y": self.floor_y}

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "Settings":
        return Settings(name=str(d.get("name", "avatar")), height_m=float(d["height_m"]), build=d.get("build"), pose_hint=d.get("pose_hint"),
                        depth={k: float(v) for k, v in (d.get("depth") or {}).items()}, back_mode=d.get("back_mode", "plain"),
                        hair_rgb=tuple(d["hair_rgb"]) if d.get("hair_rgb") else None, unlit=bool(d.get("unlit", True)),
                        joints={k: tuple(v) for k, v in (d.get("joints") or {}).items()}, floor_y=d.get("floor_y"))


@dataclass
class Built:
    glb: bytes
    recipe: Dict[str, Any]
    report: Dict[str, Any]
    cutout: intake.Cutout
    landmarks: lmk.Landmarks
    fit: skeleton.Fit
    labels: np.ndarray
    shell: shape.Shell
    rigged: rig.Rigged
    atlas: np.ndarray


def validate(settings: Settings) -> None:
    if not (MIN_HEIGHT_M <= settings.height_m <= MAX_HEIGHT_M):
        raise intake.IntakeError(f"height must be between {MIN_HEIGHT_M} and {MAX_HEIGHT_M} metres (got {settings.height_m:g})")
    if settings.build and settings.build not in lmk.BUILDS:
        raise intake.IntakeError(f"build must be one of {', '.join(lmk.BUILDS)}")
    bad = [k for k in settings.depth if k not in parts.PARTS]
    if bad:
        raise intake.IntakeError(f"unknown part(s) in depth: {', '.join(bad)}; parts are {', '.join(parts.PARTS)}")
    for k, v in settings.depth.items():
        if not (0.05 <= float(v) <= 2.5):
            raise intake.IntakeError(f"depth for {k} must be between 0.05 and 2.5 (got {v})")
    if settings.back_mode not in texture.BACK_MODES:
        raise intake.IntakeError(f"back view must be one of {', '.join(texture.BACK_MODES)}")


def _assemble(cut: intake.Cutout, settings: Settings, source: Dict[str, Any], custom_back: Optional[np.ndarray],
              pose_model: Optional[str], data_dir: Optional[str]) -> Built:
    validate(settings)
    rep = cut.report
    bbox = rep.bbox
    if settings.floor_y is not None:
        bbox = (bbox[0], bbox[1], bbox[2], int(round(settings.floor_y)))
    feet_cropped = rep.touches["bottom"] and settings.floor_y is None
    lm = lmk.find(cut.rgb, cut.alpha, bbox, settings.height_m, build=settings.build, pose_hint=settings.pose_hint,
                  feet_cropped=feet_cropped, model_path=pose_model, data_dir=data_dir, user_edits=settings.joints or None)
    fit = skeleton.fit(lm, bbox, settings.height_m, lmk.BUILDS[lm.build]["foot"])
    mask = cut.alpha > 0.5
    labels = parts.label_parts(mask.shape, mask, fit)
    sh = shape.build_shell(cut, labels, fit, settings.depth)
    rg = rig.rig(sh, fit, mask)
    atlas, atlas_info = texture.build_atlas(cut, labels, sh.crop, settings.back_mode, custom_back, settings.hair_rgb)
    drawn_base = None if lm.pose_kind == "tpose" else rig.drawn_pose_rotations(fit)
    clips = motion.default_clips(rg.rest, rg.local, list(NAMES), drawn_base)

    measures = rig.skeleton_summary(rg.rest)
    height = float(rg.pos[:, 1].max() - rg.pos[:, 1].min())
    warnings = list(rep.warnings) + list(lm.warnings)
    if rg.moved_m > 0.35 * settings.height_m:
        warnings.append("The pose in the picture is far from a T-pose, so the arms were swung a long way into the rest pose. "
                        "Check the shoulders and elbows in the editor.")
    report = {
        "height_m": round(height, 4), "height_requested_m": round(settings.height_m, 4), "height_pub_blocks": round(height / PUB_BLOCK_M, 3),
        "build": lm.build, "pose_in_picture": lm.pose_kind, "pose_detector_used": lm.detector_used,
        "cutout_method": rep.method, "background": rep.background, "vertices": int(len(rg.pos)), "triangles": int(len(sh.faces)),
        "bones": len(NAMES), "atlas": atlas_info, "atlas_size": [int(atlas.shape[1]), int(atlas.shape[0])],
        "bake_max_move_m": round(rg.moved_m, 4), "measures_m": {k: round(v, 4) for k, v in measures.items()},
        "joint_sources": {s: sum(1 for v in lm.source.values() if v == s) for s in sorted(set(lm.source.values()))},
        "warnings": warnings, "not_in_the_picture": list(UNSEEN),
    }
    recipe = {"version": VERSION, "source": source, "settings": settings.to_dict(), "intake": rep.to_dict(), "landmarks": lm.to_dict(),
              "fit": {"scale_m_per_px": fit.scale_m_per_px, "cx": fit.cx, "floor_y": fit.floor_y, "foot_length_m": fit.foot_length_m},
              "crop": list(sh.crop), "report": report}
    glb = gltf_io.write_glb(rg.pos, sh.uv, sh.faces, rg.joints, rg.weights, rg.local, rg.ibm, atlas, clips, recipe, settings.name, settings.unlit)
    return Built(glb, recipe, report, cut, lm, fit, labels, sh, rg, atlas)


def build(image: bytes, settings: Settings, *, matte_path: Optional[str] = None, pose_model: Optional[str] = None,
          data_dir: Optional[str] = None, custom_back: Optional[np.ndarray] = None, prefer_matte: bool = False) -> Built:
    validate(settings)
    matte = matte_mod.load(matte_path, data_dir)
    cut = intake.prepare(image, matte=matte, prefer_matte=prefer_matte)
    source = {"sha256": cut.report.sha256, "source_size": list(cut.report.source_size)}
    return _assemble(cut, settings, source, custom_back, pose_model, data_dir)


def rebuild(glb: bytes, edits: Optional[Dict[str, Any]] = None, *, pose_model: Optional[str] = None, data_dir: Optional[str] = None,
            custom_back: Optional[np.ndarray] = None) -> Built:
    """Rebuild from a GLB written by ``build``. ``edits`` may hold any Settings field; ``joints`` merges into the person's earlier joints."""
    recipe = gltf_io.read_recipe(glb)
    if recipe is None:
        raise intake.IntakeError("this file was not made by the avatar builder, so it has no recipe to rebuild from. Import it as a plain avatar instead.")
    s = Settings.from_dict(recipe["settings"])
    edits = dict(edits or {})
    joints = {**s.joints, **{k: tuple(v) for k, v in (edits.pop("joints", None) or {}).items()}}
    changed_back = ("back_mode" in edits and edits["back_mode"] != s.back_mode) or ("hair_rgb" in edits and edits["hair_rgb"] != (list(s.hair_rgb) if s.hair_rgb else None))
    depth = {**s.depth, **{k: float(v) for k, v in (edits.pop("depth", None) or {}).items()}}
    for k, v in edits.items():
        if not hasattr(s, k):
            raise intake.IntakeError(f"unknown setting: {k}")
        setattr(s, k, tuple(v) if k == "hair_rgb" and v is not None else v)
    s.joints, s.depth = joints, depth
    atlas = gltf_io.read_atlas(glb)
    front, back = texture.split_atlas(atlas)
    crop = tuple(recipe["crop"])
    wh = tuple(recipe["intake"]["working_size"])
    x0, y0, w, h = crop
    cv2 = deps.require("cv2", "opencv-python-headless")
    canvas = np.zeros((wh[1], wh[0], 4), np.uint8)
    canvas[y0:y0 + h, x0:x0 + w] = cv2.resize(front, (w, h), interpolation=cv2.INTER_LINEAR if front.shape[1] < w else cv2.INTER_AREA)
    ri = recipe["intake"]
    report = intake.IntakeReport(sha256=ri["sha256"], source_size=tuple(ri["source_size"]), working_size=wh, background=ri["background"],
                                 bg_rgb=tuple(ri["bg_rgb"]), method=ri["method"], foreground_fraction=ri["foreground_fraction"],
                                 touches=ri["touches"], bbox=tuple(ri["bbox"]), warnings=list(ri["warnings"]))
    cut = intake.Cutout(rgb=canvas[..., :3].copy(), alpha=canvas[..., 3].astype(np.float32) / 255.0, report=report)
    keep_back = None
    if not changed_back and custom_back is None and s.back_mode != "custom":
        keep_back = back[..., :3]                   # the file's own back, already as seen from behind, which is what 'custom' takes
    use_custom = custom_back if custom_back is not None else keep_back
    back_mode = "custom" if (use_custom is not None and s.back_mode != "custom") else s.back_mode
    s_build = Settings.from_dict({**s.to_dict(), "back_mode": back_mode}) if back_mode != s.back_mode else s
    built = _assemble(cut, s_build, recipe["source"], use_custom, pose_model, data_dir)
    if back_mode != s.back_mode:      # the recipe keeps the person's choice, not the mechanism used to preserve the file's own back
        built.recipe["settings"]["back_mode"] = s.back_mode
        built.recipe["report"]["atlas"]["back_mode"] = s.back_mode
        drawn_base = None if built.landmarks.pose_kind == "tpose" else rig.drawn_pose_rotations(built.fit)
        built.glb = gltf_io.write_glb(built.rigged.pos, built.shell.uv, built.shell.faces, built.rigged.joints, built.rigged.weights,
                                      built.rigged.local, built.rigged.ibm, built.atlas,
                                      motion.default_clips(built.rigged.rest, built.rigged.local, list(NAMES), drawn_base),
                                      built.recipe, s.name, s.unlit)
    return built


def fingerprint(glb: bytes) -> str:
    return hashlib.sha256(glb).hexdigest()
