# PubCast AI — avatar_likeness/texture.py
# Copyright © 2024–2026 Josie Curtsey Cobbley (Joshua Cobbley)
# Rearview Foresight LLC — All Rights Reserved
# Feic Mo Chroí — See My Heart
"""The texture atlas: the supplied artwork on the front, and a back the picture never showed.

Atlas layout: left half = the front exactly as supplied (cut-out, colours untouched); right half = the back, seen from
behind (so a vertex at picture x samples the back image at 1 - x). Both halves share the crop of ``shape.Shell.crop``.

The front is not repainted, resampled beyond a straight resize, or colour-corrected: the front of the character is
the artwork. The back is a guess and is labelled as one. Modes, chosen by the person in the editor:

  plain    the outfit as flat painted colour (no invented detail), and the head as the front's own hair or hat with the
           face painted out in the hair colour around it. Matches the front's palette and style without inventing.
  mirror   the front reflected through the body. Keeps every detail, including the face on the back of the head, so
           it is offered for props and flat designs, not as a default.
  custom   a picture the person supplies (a painted back view), fitted to the same crop.
"""
from __future__ import annotations

from typing import Dict, Optional, Tuple

import numpy as np

from . import deps
from .intake import SEED, Cutout
from .parts import PARTS

MAX_HALF = 1024
BACK_MODES = ("plain", "mirror", "custom")
BACK_PALETTE = 7             # colours the back of the outfit is reduced to before small patches are merged; 0 turns the whole step off
BACK_FOOTWEAR = 0.14         # the bottom of the figure (shoes, boot shafts) is not flattened
BACK_PATCH_OF_PART = 0.25    # a colour patch smaller than this share of the body part it sits on is a print, pocket or strap, not a garment


def _bleed(rgb: np.ndarray, alpha: np.ndarray) -> np.ndarray:
    """Push the figure's edge colours outward into the transparent area so filtering never pulls in the backdrop colour."""
    from scipy import ndimage
    inside = alpha > 0.5
    idx = ndimage.distance_transform_edt(~inside, return_distances=False, return_indices=True)
    return rgb[idx[0], idx[1]]


def _crop(cut: Cutout, crop: Tuple[int, int, int, int]) -> Tuple[np.ndarray, np.ndarray]:
    x0, y0, w, h = crop
    return cut.rgb[y0:y0 + h, x0:x0 + w], cut.alpha[y0:y0 + h, x0:x0 + w]


def _hair_colour(rgb: np.ndarray, alpha: np.ndarray, labels: np.ndarray, crop: Tuple[int, int, int, int]) -> np.ndarray:
    """Median colour of the top third of the head pixels: hair or hat, whatever is on top."""
    x0, y0, w, h = crop
    lab = labels[y0:y0 + h, x0:x0 + w] == PARTS.index("head")
    ys = np.nonzero(lab.any(axis=1))[0]
    if len(ys) == 0:
        return np.array([60, 50, 45], np.uint8)
    cut = ys[0] + max(1, int(0.33 * (ys[-1] - ys[0] + 1)))
    sel = lab.copy()
    sel[cut:] = False
    sel &= alpha > 0.9
    px = rgb[sel]
    return np.median(px, axis=0).astype(np.uint8) if len(px) else np.array([60, 50, 45], np.uint8)


def _face(rgb: np.ndarray, head: np.ndarray) -> np.ndarray:
    """Mask of the face inside the head region: skin-coloured pixels closed over the eyes and mouth. Empty if none found."""
    cv2 = deps.require("cv2", "opencv-python-headless")
    ycc = cv2.cvtColor(rgb, cv2.COLOR_RGB2YCrCb)
    skin = (ycc[..., 1] >= 133) & (ycc[..., 1] <= 178) & (ycc[..., 2] >= 80) & (ycc[..., 2] <= 132) & (ycc[..., 0] > 70) & head
    ys = np.nonzero(head.any(axis=1))[0]
    if len(ys) == 0 or skin.sum() < 40:
        return np.zeros_like(head)
    hh = ys[-1] - ys[0] + 1
    k = max(3, int(0.09 * hh)) | 1
    closed = cv2.morphologyEx(skin.astype(np.uint8), cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
    n, lab, stats, _ = cv2.connectedComponentsWithStats(closed, connectivity=8)
    if n <= 1:
        return np.zeros_like(head)
    face = lab == 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    face = cv2.dilate(face.astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (max(3, k // 2) | 1,) * 2)) > 0
    return face & head


def _hair_around(rgb: np.ndarray, head: np.ndarray, face: np.ndarray, top: Optional[np.ndarray] = None) -> Optional[np.ndarray]:
    """Colour of what surrounds the face (hair beside the cheeks and ears), ignoring skin, ink and, when ``top`` is the
    colour of the crown (a hat), anything that is just more of the hat."""
    cv2 = deps.require("cv2", "opencv-python-headless")
    if not face.any():
        return None
    ys = np.nonzero(face.any(axis=1))[0]
    ring = cv2.dilate(face.astype(np.uint8), np.ones((max(3, int(0.12 * (ys[-1] - ys[0])) | 1),) * 2, np.uint8)) > 0
    ycc = cv2.cvtColor(rgb, cv2.COLOR_RGB2YCrCb)
    notskin = ~((ycc[..., 1] >= 133) & (ycc[..., 1] <= 178) & (ycc[..., 2] >= 80) & (ycc[..., 2] <= 132))
    sel = ring & ~face & head & notskin & (ycc[..., 0] > 45)
    if top is not None:
        sel &= np.linalg.norm(rgb.astype(np.float32) - top[None, None, :], axis=2) > 45
    sel[: ys[0] + int(0.3 * (ys[-1] - ys[0]))] = False          # beside and below the brow line, where hair, not a hat, is
    px = rgb[sel]
    return np.median(px, axis=0) if len(px) >= 30 else None


def _flatten_regions(rgb: np.ndarray, area: np.ndarray, part_label: np.ndarray) -> np.ndarray:
    """Reduce ``rgb`` inside ``area`` to a few flat colours and merge every patch that is small for the body part it sits on.

    A print, a pocket, a lapel or a strap is a small patch of another colour on a big garment; a boot, a sleeve, a pair of
    jeans or a hat band is not small for the part it is on. Small patches take the colour of what surrounds them, so the
    front's details do not show through on the back, while garment boundaries and shoes survive.
    """
    cv2 = deps.require("cv2", "opencv-python-headless")
    from scipy import ndimage
    if BACK_PALETTE <= 0 or area.sum() < 400:
        return rgb
    rows = np.nonzero(area.any(axis=1))[0]
    area = area.copy()
    area[rows[-1] - int(BACK_FOOTWEAR * (rows[-1] - rows[0])):] = False      # shoes and boots keep the front's colours, as before
    pts = np.argwhere(area)
    if len(pts) < 400:
        return rgb
    cv2.setRNGSeed(SEED)
    lab = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB).astype(np.float32)
    pick = pts[np.linspace(0, len(pts) - 1, min(len(pts), 30000)).astype(int)]
    sample = lab[pick[:, 0], pick[:, 1]]
    k = int(min(BACK_PALETTE, max(2, len(np.unique(np.round(sample / 8).astype(int), axis=0)))))
    _, _, centres = cv2.kmeans(sample, k, None, (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 40, 0.5), 3, cv2.KMEANS_PP_CENTERS)
    ys, xs = np.nonzero(area)
    d = ((lab[ys, xs][:, None, :] - centres[None, :, :]) ** 2).sum(axis=2)
    lab_idx = np.full(area.shape, -1, np.int32)
    lab_idx[ys, xs] = d.argmin(axis=1)
    part_area = {int(p): int(((part_label == p) & area).sum()) for p in np.unique(part_label[area])}
    for _round in range(3):
        small = np.zeros(area.shape, bool)
        for c in range(k):
            n, cc, stats, _centroids = cv2.connectedComponentsWithStats(((lab_idx == c) & area).astype(np.uint8), connectivity=4)
            for j in range(1, n):
                x, y, bw, bh, count = (int(v) for v in stats[j])
                m = cc[y:y + bh, x:x + bw] == j
                part = int(np.bincount(part_label[y:y + bh, x:x + bw][m].clip(0)).argmax())
                if count < BACK_PATCH_OF_PART * part_area.get(part, 0):
                    small[y:y + bh, x:x + bw] |= m
        if not small.any():
            break
        keep = area & ~small
        if not keep.any():
            break
        near = ndimage.distance_transform_edt(~keep, return_distances=False, return_indices=True)
        lab_idx = np.where(small, lab_idx[near[0], near[1]], lab_idx)
    out = rgb.copy()
    for c in range(k):                                           # each remaining patch gets the colour it actually has, not its cluster's
        n, cc, stats, _centroids = cv2.connectedComponentsWithStats(((lab_idx == c) & area).astype(np.uint8), connectivity=4)
        for j in range(1, n):
            x, y, bw, bh, _count = (int(v) for v in stats[j])
            m = cc[y:y + bh, x:x + bw] == j
            out[y:y + bh, x:x + bw][m] = np.median(rgb[y:y + bh, x:x + bw][m], axis=0).astype(np.uint8)
    return out


def _plain_back(rgb: np.ndarray, alpha: np.ndarray, labels: np.ndarray, crop: Tuple[int, int, int, int],
                hair_override: Optional[Tuple[int, int, int]] = None) -> np.ndarray:
    """The back of the outfit as flat painted colour, and the back of the head as the front's hair or hat with the face painted out."""
    cv2 = deps.require("cv2", "opencv-python-headless")
    x0, y0, w, h = crop
    solid = alpha > 0.5
    # Flat painted regions: edge-preserving smoothing, then a median wide enough to erase prints, pockets, buttons and
    # straps (details that belong to the front) while keeping the big garment boundaries (jacket against jeans).
    k = max(5, int(0.045 * h)) | 1
    flat = cv2.medianBlur(cv2.pyrMeanShiftFiltering(rgb, sp=max(6, int(0.012 * h)), sr=26, maxLevel=2), min(k, 255))
    part_label = labels[y0:y0 + h, x0:x0 + w]
    head = (part_label == PARTS.index("head")) & solid
    hands = np.isin(part_label, [PARTS.index("hand_L"), PARTS.index("hand_R")])
    flat = _flatten_regions(flat, solid & ~head & ~hands, part_label)
    face = _face(rgb, head)
    crown = _hair_colour(rgb, alpha, labels, crop).astype(np.float32)
    hair = np.array(hair_override, np.float32) if hair_override is not None else _hair_around(rgb, head, face, crown)
    if hair is None:
        hair = crown
    out = flat.copy()
    back_head = rgb.copy()
    if face.any():
        ys = np.nonzero(face.any(axis=1))[0]
        t = ((np.arange(h)[:, None] - ys[0]) / max(1, ys[-1] - ys[0])).clip(0, 1)
        fill = np.broadcast_to(hair[None, None, :] * (1.0 - 0.12 * t[..., None]), rgb.shape)
        soft = cv2.GaussianBlur(face.astype(np.float32), (0, 0), max(1.5, 0.01 * h))[..., None]
        back_head = (rgb.astype(np.float32) * (1 - soft) + fill * soft).astype(np.uint8)
    out[head] = back_head[head]
    return out


def build_atlas(cut: Cutout, labels: np.ndarray, crop: Tuple[int, int, int, int], back_mode: str = "plain",
                custom_back: Optional[np.ndarray] = None, hair_override: Optional[Tuple[int, int, int]] = None) -> Tuple[np.ndarray, Dict[str, object]]:
    """Return (RGBA uint8 atlas, info). The atlas is 2*tw x th with tw,th <= MAX_HALF."""
    cv2 = deps.require("cv2", "opencv-python-headless")
    if back_mode not in BACK_MODES:
        raise ValueError(f"back_mode must be one of {', '.join(BACK_MODES)}")
    rgb, alpha = _crop(cut, crop)
    h, w = alpha.shape
    f = min(1.0, MAX_HALF / max(h, w))
    tw, th = max(2, int(round(w * f))), max(2, int(round(h * f)))
    front_rgb = _bleed(rgb, alpha)
    if back_mode == "plain":
        back_rgb = _plain_back(front_rgb, alpha, labels, crop, hair_override)
    elif back_mode == "mirror":
        back_rgb = front_rgb
    else:
        if custom_back is None:
            raise ValueError("back_mode 'custom' needs a back picture")
        back_rgb = cv2.resize(custom_back[..., :3], (w, h), interpolation=cv2.INTER_AREA)
    # The back, seen from behind, is the front's silhouette mirrored; its alpha is the same cut-out, mirrored.
    a_front = alpha
    a_back = alpha[:, ::-1]
    back_img = back_rgb[:, ::-1]                 # seen from behind
    if back_mode == "custom":
        back_img = back_rgb                      # the person painted it as seen from behind already
    def pack(img, a):
        img = cv2.resize(img, (tw, th), interpolation=cv2.INTER_AREA if f < 1 else cv2.INTER_LINEAR)
        a = cv2.resize(a.astype(np.float32), (tw, th), interpolation=cv2.INTER_AREA if f < 1 else cv2.INTER_LINEAR)
        return np.dstack([img, np.round(np.clip(a, 0, 1) * 255).astype(np.uint8)])
    atlas = np.concatenate([pack(front_rgb, a_front), pack(back_img, a_back)], axis=1)
    return atlas, {"back_mode": back_mode, "half_size": [tw, th], "scale": round(f, 4),
                   "hair_rgb": [int(v) for v in (hair_override or _hair_colour(rgb, alpha, labels, crop))]}


def split_atlas(atlas: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    half = atlas.shape[1] // 2
    return atlas[:, :half], atlas[:, half:]
