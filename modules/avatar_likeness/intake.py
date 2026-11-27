# PubCast AI — avatar_likeness/intake.py
# Copyright © 2024–2026 Josie Curtsey Cobbley (Joshua Cobbley)
# Rearview Foresight LLC — All Rights Reserved
# Feic Mo Chroí — See My Heart
"""Intake: one character illustration in, a clean cut-out and an honest quality report out.

Nothing here guesses silently. Every decision that could cost likeness (the picture is cropped at the feet, the
background was not plain, the figure touches the frame) is returned in ``IntakeReport.warnings`` so the Foundry
can show it to the person and the pipeline can store it in the avatar's recipe.

Offline by design: classical segmentation only (background colour model + GrabCut). A matting network can be
supplied through ``segment(..., matte=callable)`` and is never downloaded here.
"""
from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np

from . import deps

MAX_SIDE = 2048
MIN_SIDE = 128


class IntakeError(ValueError):
    """The upload cannot become an avatar; the message says why in plain words."""


@dataclass
class IntakeReport:
    sha256: str
    source_size: Tuple[int, int]
    working_size: Tuple[int, int]
    background: str                       # "alpha" | "plain-light" | "plain-dark" | "plain-colour" | "textured"
    bg_rgb: Tuple[int, int, int]
    method: str
    foreground_fraction: float
    touches: Dict[str, bool]              # which frame edges the figure touches
    bbox: Tuple[int, int, int, int]       # x0, y0, x1, y1 of the figure in working pixels
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "sha256": self.sha256, "source_size": list(self.source_size), "working_size": list(self.working_size),
            "background": self.background, "bg_rgb": list(self.bg_rgb), "method": self.method,
            "foreground_fraction": round(self.foreground_fraction, 4), "touches": self.touches,
            "bbox": list(self.bbox), "warnings": list(self.warnings),
        }


@dataclass
class Cutout:
    rgb: np.ndarray            # HxWx3 uint8, background colour kept (used for edge-bleed removal)
    alpha: np.ndarray          # HxW float32 0..1
    report: IntakeReport

    @property
    def rgba(self) -> np.ndarray:
        return np.dstack([self.rgb, np.round(self.alpha * 255).astype(np.uint8)])


def decode(data: bytes) -> Tuple[np.ndarray, Optional[np.ndarray], str]:
    """Decode PNG/JPEG/WebP bytes to RGB (+ alpha if it carries any). Returns (rgb, alpha|None, sha256)."""
    Image = deps.require("PIL.Image", "Pillow")
    ImageOps = deps.require("PIL.ImageOps", "Pillow")
    if not data or len(data) < 16:
        raise IntakeError("the upload is empty")
    if len(data) > 40 * 1024 * 1024:
        raise IntakeError("the image is larger than 40 MB")
    digest = hashlib.sha256(data).hexdigest()
    try:
        im = Image.open(io.BytesIO(data))
        im.load()
    except Exception as exc:  # PIL raises a zoo of types for bad files
        raise IntakeError(f"that file is not an image I can read ({type(exc).__name__})") from None
    im = ImageOps.exif_transpose(im)
    if min(im.size) < MIN_SIDE:
        raise IntakeError(f"the image is only {im.size[0]}x{im.size[1]}; at least {MIN_SIDE} pixels on the short side is needed")
    alpha = None
    if im.mode in ("RGBA", "LA", "PA") or (im.mode == "P" and "transparency" in im.info):
        rgba = np.asarray(im.convert("RGBA"))
        a = rgba[..., 3]
        if a.min() < 250 and (a < 250).mean() > 0.01:
            alpha = a.astype(np.float32) / 255.0
        rgb = rgba[..., :3].copy()
    else:
        rgb = np.asarray(im.convert("RGB")).copy()
    return rgb, alpha, digest


def _resize(rgb: np.ndarray, alpha: Optional[np.ndarray]) -> Tuple[np.ndarray, Optional[np.ndarray]]:
    h, w = rgb.shape[:2]
    scale = MAX_SIDE / max(h, w)
    if scale >= 1.0:
        return rgb, alpha
    cv2 = deps.optional("cv2")
    size = (max(1, round(w * scale)), max(1, round(h * scale)))
    if cv2 is not None:
        rgb = cv2.resize(rgb, size, interpolation=cv2.INTER_AREA)
        alpha = cv2.resize(alpha, size, interpolation=cv2.INTER_AREA) if alpha is not None else None
    else:
        Image = deps.require("PIL.Image", "Pillow")
        rgb = np.asarray(Image.fromarray(rgb).resize(size, Image.LANCZOS))
        alpha = np.asarray(Image.fromarray((alpha * 255).astype(np.uint8)).resize(size, Image.LANCZOS)).astype(np.float32) / 255 if alpha is not None else None
    return rgb, alpha


def _border_ring(h: int, w: int, t: int) -> np.ndarray:
    ring = np.zeros((h, w), bool)
    ring[:t, :] = ring[-t:, :] = True
    ring[:, :t] = ring[:, -t:] = True
    return ring


def _to_lab(rgb: np.ndarray) -> np.ndarray:
    cv2 = deps.optional("cv2")
    if cv2 is not None:
        return cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB).astype(np.float32)
    ski = deps.require("skimage.color", "scikit-image")
    lab = ski.rgb2lab(rgb.astype(np.float32) / 255.0)
    lab[..., 0] *= 255 / 100
    lab[..., 1:] += 128
    return lab.astype(np.float32)


def _background_kind(rgb: np.ndarray) -> Tuple[str, Tuple[int, int, int], float]:
    """Classify the border ring: (kind, median rgb, spread). Spread is the mean Lab distance to the nearest of 3 clusters."""
    cv2 = deps.require("cv2", "opencv-python-headless")
    h, w = rgb.shape[:2]
    ring = _border_ring(h, w, max(4, int(0.02 * min(h, w))))
    bg_rgb = tuple(int(v) for v in np.median(rgb[ring], axis=0))
    ring_px = _to_lab(rgb)[ring].astype(np.float32)
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 20, 0.5)
    _, labels, centers = cv2.kmeans(ring_px, 3, None, criteria, 3, cv2.KMEANS_PP_CENTERS)
    spread = float(np.mean(np.linalg.norm(ring_px - centers[labels.ravel()], axis=1)))
    luma = float(np.mean(bg_rgb))
    kind = "plain-light" if luma > 200 else "plain-dark" if luma < 70 else "plain-colour"
    if spread > 28:
        kind = "textured"
    return kind, bg_rgb, spread


def _largest_components(mask: np.ndarray, keep_fraction: float = 0.02) -> np.ndarray:
    """Keep the biggest blob plus any blob that is large or touches it after a small closing (a held prop)."""
    cv2 = deps.require("cv2", "opencv-python-headless")
    n, lab, stats, _ = cv2.connectedComponentsWithStats(mask.astype(np.uint8), connectivity=8)
    if n <= 1:
        return mask
    areas = stats[1:, cv2.CC_STAT_AREA]
    main = 1 + int(np.argmax(areas))
    keep = {main}
    near = cv2.dilate((lab == main).astype(np.uint8), np.ones((15, 15), np.uint8)) > 0
    for i in range(1, n):
        if i == main:
            continue
        if areas[i - 1] >= keep_fraction * areas.max() and (near & (lab == i)).any():
            keep.add(i)
    return np.isin(lab, list(keep))


def segment(rgb: np.ndarray, alpha_in: Optional[np.ndarray] = None,
            matte: Optional[Callable[[np.ndarray], np.ndarray]] = None) -> Tuple[np.ndarray, str, str, Tuple[int, int, int]]:
    """Return (alpha, method, background_kind, bg_rgb)."""
    cv2 = deps.require("cv2", "opencv-python-headless")
    h, w = rgb.shape[:2]
    t = max(4, int(0.02 * min(h, w)))
    ring = _border_ring(h, w, t)
    bg_rgb = tuple(int(v) for v in np.median(rgb[ring], axis=0))
    if alpha_in is not None:
        a = alpha_in.astype(np.float32)
        return a, "embedded-alpha", "alpha", bg_rgb
    if matte is not None:
        a = np.clip(matte(rgb).astype(np.float32), 0, 1)
        kind, bg_rgb, _ = _background_kind(rgb)
        return a, "matting-network", kind, bg_rgb
    lab = _to_lab(rgb)
    ring_px = lab[ring]
    # background colour model: up to 3 clusters of the border ring (vignettes and floors are not one colour)
    k = 3
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 20, 0.5)
    _, labels, centers = cv2.kmeans(ring_px.astype(np.float32), k, None, criteria, 3, cv2.KMEANS_PP_CENTERS)
    spread = float(np.mean(np.linalg.norm(ring_px - centers[labels.ravel()], axis=1)))
    dist = np.min(np.stack([np.linalg.norm(lab - c, axis=2) for c in centers]), axis=0)
    luma = float(np.mean([bg_rgb]))
    kind = "plain-light" if luma > 200 else "plain-dark" if luma < 70 else "plain-colour"
    if spread > 14:
        kind = "textured" if spread > 28 else kind
    # seed: confident background = close to a border cluster AND connected to the border; confident foreground = far
    thr_bg = max(6.0, spread * 1.6)
    thr_fg = max(22.0, spread * 4.0)
    sure_bg_raw = dist < thr_bg
    n, comp = cv2.connectedComponents(sure_bg_raw.astype(np.uint8), connectivity=4)
    border_ids = np.unique(comp[ring & sure_bg_raw])
    sure_bg = np.isin(comp, border_ids[border_ids > 0])
    sure_fg = (dist > thr_fg) & ~sure_bg
    sure_fg = cv2.erode(sure_fg.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0
    gc = np.full((h, w), cv2.GC_PR_BGD, np.uint8)
    gc[~sure_bg & ~sure_fg] = cv2.GC_PR_FGD
    gc[sure_bg] = cv2.GC_BGD
    gc[sure_fg] = cv2.GC_FGD
    gc[ring] = cv2.GC_BGD
    if (gc == cv2.GC_FGD).sum() < 50:
        raise IntakeError("I cannot find a character against this background; try an image with a plainer backdrop")
    bgd, fgd = np.zeros((1, 65), np.float64), np.zeros((1, 65), np.float64)
    try:
        cv2.grabCut(cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR), gc, None, bgd, fgd, 5, cv2.GC_INIT_WITH_MASK)
    except cv2.error as exc:
        raise IntakeError(f"segmentation failed: {exc}") from None
    fg = (gc == cv2.GC_FGD) | (gc == cv2.GC_PR_FGD)
    fg = _largest_components(fg)
    # holes: fill interior holes (the gap between an arm and the body is NOT a hole; it connects to the border)
    fg = _fill_holes(fg)
    fg = cv2.morphologyEx(fg.astype(np.uint8), cv2.MORPH_OPEN, np.ones((3, 3), np.uint8)) > 0
    a = cv2.GaussianBlur(fg.astype(np.float32), (0, 0), 0.8)
    a = np.clip((a - 0.15) / 0.7, 0, 1)
    return a, "background-model+grabcut", kind, bg_rgb


def _fill_holes(mask: np.ndarray) -> np.ndarray:
    cv2 = deps.require("cv2", "opencv-python-headless")
    h, w = mask.shape
    inv = (~mask).astype(np.uint8)
    n, lab = cv2.connectedComponents(inv, connectivity=4)
    border_ids = set(np.unique(np.concatenate([lab[0], lab[-1], lab[:, 0], lab[:, -1]])).tolist())
    holes = ~np.isin(lab, list(border_ids)) & ~mask
    return mask | holes


def _dark_backdrop(kind: str, bg_rgb: Tuple[int, int, int]) -> bool:
    """A dark or mid-tone backdrop is where classical cut-outs eat dark hair, hat bands, trousers and shoes."""
    return kind in ("plain-dark", "plain-colour", "textured") and float(np.mean(bg_rgb)) < 110


def prepare(data: bytes, matte: Optional[Callable[[np.ndarray], np.ndarray]] = None, prefer_matte: bool = False) -> Cutout:
    """bytes of an image -> Cutout. Raises IntakeError with a plain-language reason.

    ``matte`` is an optional network (see ``matte.load``). With ``prefer_matte`` it is always used; otherwise it is
    used only when the picture has no transparency and the backdrop is dark, because that is where the classical
    cut-out fails. Without a matte the dark-backdrop case is not hidden: it is returned as a warning.
    """
    rgb, alpha, digest = decode(data)
    src_size = (rgb.shape[1], rgb.shape[0])
    rgb, alpha = _resize(rgb, alpha)
    risk_note = None
    use_matte = None
    if alpha is None and matte is not None:
        kind0, bg0, _ = _background_kind(rgb)
        if prefer_matte or _dark_backdrop(kind0, bg0):
            use_matte = matte
    a, method, kind, bg_rgb = segment(rgb, alpha, use_matte)
    if alpha is None and use_matte is None and _dark_backdrop(kind, bg_rgb):
        risk_note = ("The backdrop is dark. Dark hair, hat bands, trousers or shoes can be cut away by a colour-based "
                     "cut-out. Check the outline, or add the optional matting model (avatar_likeness/matte.py) and rebuild.")
    h, w = a.shape
    solid = a > 0.5
    frac = float(solid.mean())
    if frac < 0.03:
        raise IntakeError("the character fills too little of the picture to model; crop closer and try again")
    if frac > 0.92:
        raise IntakeError("the character fills the whole frame; I cannot tell where it ends. Use a plainer background")
    ys, xs = np.where(solid)
    bbox = (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1)
    margin = max(3, int(0.006 * max(h, w)))
    touches = {"left": bbox[0] <= margin, "right": bbox[2] >= w - margin, "top": bbox[1] <= margin, "bottom": bbox[3] >= h - margin}
    warnings: List[str] = []
    if touches["bottom"]:
        warnings.append("The picture is cropped at the feet. The legs will end where the picture ends and the shoes are closed off; "
                        "set the floor line yourself if the shoes are visible.")
    if touches["top"]:
        warnings.append("The head touches the top of the picture; the top of the head or hat may be cut off.")
    if touches["left"] or touches["right"]:
        warnings.append("The figure touches the side of the picture; an arm or prop may be cut off.")
    if risk_note:
        warnings.append(risk_note)
    if kind == "textured":
        warnings.append("The background is not plain, so the cut-out edge may be rough. Check the outline before building.")
    if method == "embedded-alpha":
        warnings.append("Using the transparency already in the file.")
    rep = IntakeReport(sha256=digest, source_size=src_size, working_size=(w, h), background=kind, bg_rgb=bg_rgb,
                       method=method, foreground_fraction=frac, touches=touches, bbox=bbox, warnings=warnings)
    return Cutout(rgb=rgb, alpha=a.astype(np.float32), report=rep)
