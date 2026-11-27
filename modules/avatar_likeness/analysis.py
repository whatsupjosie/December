"""Art-analysis checks: how close is an avatar to the picture (or video frame) it came from, at rest and in motion.

Everything here measures; nothing here improves an avatar. The numbers feed the comparison sheets (tools/avatar_likeness/compare.py)
and the tests. The thresholds that turn numbers into plain-language findings are named constants at the top, they are judgement
calls made on the three pictures in tests/fixtures, and they are the first thing to revisit with a larger set.

Matching-view checks take two RGBA images of the figure (alpha = the figure) and say how they differ:
  proportions   bounding-box aspect, where the mass sits, and the width-per-row profile (head size, shoulder width, leg length)
  silhouette    intersection over union after scaling both to the same height, overall and in three height bands
  palette       how far the colours of one are from the colours of the other (CIE Lab, both directions)
  ink and flat  whether an illustrated style survived: dark outline along the edge, interior edge density, flat colour areas
Motion checks:
  turn_stability   a run of frames of a turn: does the figure keep its height, and does its silhouette jump between frames
  mesh_stretch     skin the mesh by a clip on the CPU and measure how much every triangle stretches or collapses against the bind pose
  texture_stretch  at a view angle, how much of the visible front-textured surface is seen edge-on (where a single front picture smears)
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from . import deps, gltf_io, parts

# judgement calls, in one place
IOU_LOW = 0.80                    # below this the silhouette is a different figure
BAND_IOU_LOW = 0.70
ASPECT_REL_HIGH = 0.12            # relative difference in width/height of the bounding box
PROFILE_L1_HIGH = 0.06            # mean absolute difference of the width-per-row profile (as a fraction of figure height)
PALETTE_DE_HIGH = 12.0            # mean CIE76 distance between palettes
PALETTE_MISSING_DE = 25.0         # a colour covering >= MISSING_WEIGHT of one picture with no neighbour this close in the other
MISSING_WEIGHT = 0.03
INK_DELTA_HIGH = 0.5              # relative loss of dark outline along the silhouette edge
TURN_HEIGHT_DRIFT_HIGH = 0.06     # figure height moves more than 6 % across a turn
TURN_JUMP_IOU_LOW = 0.88          # consecutive frames at small angle steps overlap less than this
STRETCH_AREA_HIGH = 2.5           # a triangle that grows or shrinks by more than this (or its inverse) against the bind pose
EDGE_ON_COS = 0.33                # |normal . view| below this counts as seen edge-on (about 71 degrees off the view axis)
CANVAS_H = 512


def _cv2():
    return deps.require("cv2", "opencv-python-headless")


def _mask(rgba: np.ndarray) -> np.ndarray:
    return rgba[..., 3] > 127


def _bbox(mask: np.ndarray) -> Tuple[int, int, int, int]:
    ys, xs = np.nonzero(mask)
    if len(xs) == 0:
        raise ValueError("the image has no figure in it (its alpha channel is empty)")
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


def normalise(rgba: np.ndarray, height: int = CANVAS_H) -> np.ndarray:
    """The figure scaled to ``height`` pixels tall, standing on the bottom of a canvas, centred on its bounding box."""
    cv2 = _cv2()
    x0, y0, x1, y1 = _bbox(_mask(rgba))
    crop = rgba[y0:y1, x0:x1]
    s = height / crop.shape[0]
    w = max(1, int(round(crop.shape[1] * s)))
    crop = cv2.resize(crop, (w, height), interpolation=cv2.INTER_AREA)
    side = int(height * 1.2)
    canvas = np.zeros((height, max(side, w + 4), 4), np.uint8)
    ox = (canvas.shape[1] - w) // 2
    canvas[:, ox:ox + w] = crop
    return canvas


def _pad_to(a: np.ndarray, b: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    w = max(a.shape[1], b.shape[1])
    def fit(x):
        if x.shape[1] == w:
            return x
        out = np.zeros((x.shape[0], w, 4), np.uint8)
        ox = (w - x.shape[1]) // 2
        out[:, ox:ox + x.shape[1]] = x
        return out
    return fit(a), fit(b)


def width_profile(rgba: np.ndarray, rows: int = 48) -> np.ndarray:
    """Width of the figure at ``rows`` evenly spaced heights, as a fraction of the figure's height."""
    m = _mask(rgba)
    x0, y0, x1, y1 = _bbox(m)
    m = m[y0:y1]
    h = m.shape[0]
    out = np.zeros(rows)
    for i in range(rows):
        band = m[int(i * h / rows): max(int(i * h / rows) + 1, int((i + 1) * h / rows))]
        cols = np.nonzero(band.any(axis=0))[0]
        out[i] = (cols[-1] - cols[0] + 1) / h if len(cols) else 0.0
    return out


def proportions(a: np.ndarray, b: np.ndarray) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for key, img in (("a", a), ("b", b)):
        x0, y0, x1, y1 = _bbox(_mask(img))
        m = _mask(img)[y0:y1, x0:x1]
        ys = np.nonzero(m)[0]
        out[key] = {"aspect_w_over_h": round((x1 - x0) / (y1 - y0), 4), "mass_centre_from_top": round(float(ys.mean() / m.shape[0]), 4)}
    pa, pb = width_profile(a), width_profile(b)
    out["aspect_relative_difference"] = round(abs(out["a"]["aspect_w_over_h"] - out["b"]["aspect_w_over_h"]) / max(1e-6, out["a"]["aspect_w_over_h"]), 4)
    out["width_profile_l1"] = round(float(np.abs(pa - pb).mean()), 4)
    out["profile_a"], out["profile_b"] = [round(float(v), 4) for v in pa], [round(float(v), 4) for v in pb]
    return out


def silhouette(a: np.ndarray, b: np.ndarray) -> Dict[str, Any]:
    na, nb = _pad_to(normalise(a), normalise(b))
    ma, mb = _mask(na), _mask(nb)
    def iou(x, y):
        u = (x | y).sum()
        return float((x & y).sum() / u) if u else 1.0
    h = ma.shape[0]
    bands = {"upper": slice(0, h // 3), "middle": slice(h // 3, 2 * h // 3), "lower": slice(2 * h // 3, h)}
    return {"iou": round(iou(ma, mb), 4), "iou_bands": {k: round(iou(ma[s], mb[s]), 4) for k, s in bands.items()}}


def _lab_pixels(rgba: np.ndarray, cap: int = 60000) -> np.ndarray:
    cv2 = _cv2()
    m = _mask(rgba)
    rgb = np.ascontiguousarray(rgba[..., :3])
    lab = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB).astype(np.float32)
    lab[..., 0] *= 100.0 / 255.0
    lab[..., 1:] -= 128.0
    px = lab[m]
    if len(px) > cap:
        px = px[np.random.RandomState(1).choice(len(px), cap, replace=False)]
    return px


def palette(rgba: np.ndarray, k: int = 8) -> Tuple[np.ndarray, np.ndarray]:
    """(centres in Lab, weights) of the figure's colours."""
    cv2 = _cv2()
    px = _lab_pixels(rgba)
    k = max(1, min(k, len(px)))
    cv2.setRNGSeed(20261127)
    _, labels, centres = cv2.kmeans(px, k, None, (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.5), 3, cv2.KMEANS_PP_CENTERS)
    w = np.bincount(labels.ravel(), minlength=k).astype(float)
    return centres, w / w.sum()


def palette_distance(a: np.ndarray, b: np.ndarray, k: int = 8) -> Dict[str, Any]:
    ca, wa = palette(a, k)
    cb, wb = palette(b, k)
    d = np.linalg.norm(ca[:, None, :] - cb[None, :, :], axis=2)
    a_to_b, b_to_a = d.min(axis=1), d.min(axis=0)
    mean = float(0.5 * ((wa * a_to_b).sum() + (wb * b_to_a).sum()))
    def missing(w, near, c):
        return [{"lab": [round(float(v), 1) for v in c[i]], "weight": round(float(w[i]), 3), "nearest_delta_e": round(float(near[i]), 1)}
                for i in np.argsort(-w) if w[i] >= MISSING_WEIGHT and near[i] > PALETTE_MISSING_DE]
    return {"mean_delta_e": round(mean, 2), "colours_in_a_missing_from_b": missing(wa, a_to_b, ca), "colours_in_b_missing_from_a": missing(wb, b_to_a, cb)}


def style(rgba: np.ndarray) -> Dict[str, Any]:
    """Features of an illustrated look: dark outline along the edge, interior edge density, share of flat colour."""
    cv2 = _cv2()
    n = normalise(rgba)
    m = _mask(n)
    rgb = np.ascontiguousarray(n[..., :3])
    lab = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB).astype(np.float32)
    L = lab[..., 0] * 100.0 / 255.0
    dist_in = cv2.distanceTransform(m.astype(np.uint8), cv2.DIST_L2, 3)
    band = m & (dist_in <= 0.012 * m.shape[0])                                  # the outer ~1.2 % of the height: where an ink line lives
    ink = float((L[band] < 28.0).mean()) if band.any() else 0.0
    edges = cv2.Canny(cv2.GaussianBlur(np.ascontiguousarray(lab[..., 0].astype(np.uint8)), (0, 0), 1.0), 40, 110)
    interior = m & (dist_in > 0.02 * m.shape[0])
    density = float((edges[interior] > 0).mean()) if interior.any() else 0.0
    px = _lab_pixels(n)
    cv2.setRNGSeed(20261127)
    _, labels, centres = cv2.kmeans(px, 12, None, (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 20, 0.5), 2, cv2.KMEANS_PP_CENTERS)
    flat = float((np.linalg.norm(px - centres[labels.ravel()], axis=1) < 6.0).mean())
    return {"ink_outline_fraction": round(ink, 4), "interior_edge_density": round(density, 4), "flat_colour_fraction": round(flat, 4)}


def compare_views(reference: np.ndarray, render: np.ndarray) -> Dict[str, Any]:
    """Everything above for one pair of matching views, plus the plain-language findings the numbers support."""
    p, s, c = proportions(reference, render), silhouette(reference, render), palette_distance(reference, render)
    sa, sb = style(reference), style(render)
    ink_loss = (sa["ink_outline_fraction"] - sb["ink_outline_fraction"]) / sa["ink_outline_fraction"] if sa["ink_outline_fraction"] > 0.02 else 0.0
    findings: List[str] = []
    if s["iou"] < IOU_LOW:
        findings.append(f"silhouette overlap is {s['iou']:.2f} (below {IOU_LOW}): the outline is a different shape")
    for band, v in s["iou_bands"].items():
        if v < BAND_IOU_LOW:
            findings.append(f"the {band} third overlaps only {v:.2f}")
    if p["aspect_relative_difference"] > ASPECT_REL_HIGH:
        findings.append(f"the figure is {p['aspect_relative_difference'] * 100:.0f}% wider or narrower for its height than the reference")
    if p["width_profile_l1"] > PROFILE_L1_HIGH:
        findings.append(f"width per row differs by {p['width_profile_l1']:.3f} of the height on average (head, shoulders or legs are sized differently)")
    if c["mean_delta_e"] > PALETTE_DE_HIGH:
        findings.append(f"colours are {c['mean_delta_e']:.1f} Lab units apart on average")
    for m in c["colours_in_a_missing_from_b"]:
        findings.append(f"a colour that covers {m['weight'] * 100:.0f}% of the reference is not in the render (nearest is {m['nearest_delta_e']:.0f} away)")
    if ink_loss > INK_DELTA_HIGH:
        findings.append(f"the dark outline along the edge is {ink_loss * 100:.0f}% weaker than in the reference")
    return {"proportions": {k: v for k, v in p.items() if not k.startswith("profile_")}, "silhouette": s, "palette": c,
            "style_reference": sa, "style_render": sb, "ink_outline_loss": round(ink_loss, 3), "findings": findings}


def turn_stability(frames: Sequence[np.ndarray]) -> Dict[str, Any]:
    """A run of renders of a turn or a walk (same camera): does the figure keep its height, does the silhouette jump."""
    heights, jumps = [], []
    prev = None
    for f in frames:
        x0, y0, x1, y1 = _bbox(_mask(f))
        heights.append(y1 - y0)
        n = normalise(f)
        if prev is not None:
            a, b = _pad_to(prev, n)
            ma, mb = _mask(a), _mask(b)
            jumps.append(float((ma & mb).sum() / max(1, (ma | mb).sum())))
        prev = n
    heights_a = np.asarray(heights, float)
    drift = float((heights_a.max() - heights_a.min()) / np.median(heights_a))
    out = {"frames": len(frames), "height_drift": round(drift, 4), "min_consecutive_iou": round(min(jumps), 4) if jumps else 1.0,
           "findings": []}
    if drift > TURN_HEIGHT_DRIFT_HIGH:
        out["findings"].append(f"the figure's height moves {drift * 100:.1f}% across the run")
    if jumps and min(jumps) < TURN_JUMP_IOU_LOW:
        out["findings"].append(f"the silhouette jumps between two frames (overlap {min(jumps):.2f})")
    return out


# ── mesh-level checks on a GLB ───────────────────────────────────────────────────────────────────────────────────────

def _quat_to_mat(q: np.ndarray) -> np.ndarray:
    x, y, z, w = q / np.linalg.norm(q)
    return np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                     [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                     [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])


def _sample(times: np.ndarray, values: np.ndarray, t: float, quat: bool) -> np.ndarray:
    if t <= times[0]:
        return values[0]
    if t >= times[-1]:
        return values[-1]
    i = int(np.searchsorted(times, t) - 1)
    f = (t - times[i]) / (times[i + 1] - times[i])
    a, b = values[i], values[i + 1]
    if not quat:
        return a + (b - a) * f
    d = float(np.dot(a, b))
    if d < 0:
        b, d = -b, -d
    if d > 0.9995:
        q = a + (b - a) * f
    else:
        th = math.acos(min(1.0, d))
        q = (math.sin((1 - f) * th) * a + math.sin(f * th) * b) / math.sin(th)
    return q / np.linalg.norm(q)


class Posed:
    """A GLB's skinned mesh evaluated on the CPU at any time of any of its clips."""

    def __init__(self, glb: bytes):
        mesh = gltf_io.read_mesh(glb)
        self.pos = np.asarray(mesh["POSITION"], float)
        self.uv = np.asarray(mesh["TEXCOORD_0"], float)
        self.faces = np.asarray(mesh["indices"], int).reshape(-1, 3)
        self.joints = np.asarray(mesh["JOINTS_0"], int)
        self.weights = np.asarray(mesh["WEIGHTS_0"], float)
        sk = gltf_io.read_skeleton(glb)
        self.names = list(sk["joints"])
        self.parent = [self.names.index(sk["joints"][n]["parent"]) if sk["joints"][n]["parent"] else -1 for n in self.names]
        self.local = np.array([sk["joints"][n]["translation"] for n in self.names], float)
        self.clips = {c.name: c for c in gltf_io.read_clips(glb)}
        rest_world = np.zeros_like(self.local)
        for i, p in enumerate(self.parent):
            rest_world[i] = self.local[i] + (rest_world[p] if p >= 0 else 0.0)
        self.rest_world = rest_world                           # a rest pose with identity rotations: the bake the builder writes

    def at(self, clip: Optional[str], t: float = 0.0) -> np.ndarray:
        """Vertex positions with the clip applied at time ``t`` (the bind pose when ``clip`` is None)."""
        if clip is None:
            return self.pos.copy()
        c = self.clips[clip]
        world = [np.eye(4) for _ in self.names]
        for i, name in enumerate(self.names):
            tr = _sample(c.times, c.translations[name], t, False) if name in c.translations else self.local[i]
            R = _quat_to_mat(_sample(c.times, c.rotations[name], t, True)) if name in c.rotations else np.eye(3)
            m = np.eye(4)
            m[:3, :3], m[:3, 3] = R, tr
            world[i] = (world[self.parent[i]] @ m) if self.parent[i] >= 0 else m
        skin = np.empty((len(self.names), 4, 4))
        for i in range(len(self.names)):
            ibm = np.eye(4)
            ibm[:3, 3] = -self.rest_world[i]
            skin[i] = world[i] @ ibm
        hp = np.concatenate([self.pos, np.ones((len(self.pos), 1))], axis=1)
        out = np.zeros_like(self.pos)
        for k in range(self.joints.shape[1]):
            w = self.weights[:, k]
            if not w.any():
                continue
            out += w[:, None] * np.einsum("nij,nj->ni", skin[self.joints[:, k]], hp)[:, :3]
        return out

    def part_of_vertex(self) -> np.ndarray:
        dominant = self.joints[np.arange(len(self.joints)), self.weights.argmax(axis=1)]
        return np.array([parts.GROUP.get(self.names[j], "other") for j in dominant])


def _tri_area(p: np.ndarray, f: np.ndarray) -> np.ndarray:
    a, b, c = p[f[:, 0]], p[f[:, 1]], p[f[:, 2]]
    return 0.5 * np.linalg.norm(np.cross(b - a, c - a), axis=1)


def mesh_stretch(glb: bytes, clip: str, samples: int = 24) -> Dict[str, Any]:
    """Skin the mesh through one clip and measure every triangle's area against the bind pose; report the worst frame."""
    P = Posed(glb)
    if clip not in P.clips:
        raise KeyError(f"no clip called {clip}; this file has: {', '.join(P.clips)}")
    dur = P.clips[clip].duration
    rest_area = _tri_area(P.pos, P.faces)
    keep = rest_area > 1e-9
    part = P.part_of_vertex()[P.faces[:, 0]]
    worst = {"ratio": 1.0, "t": 0.0}
    over = np.zeros(len(P.faces), bool)
    share_by_part: Dict[str, float] = {}
    for t in np.linspace(0, dur, samples, endpoint=False):
        r = np.ones(len(P.faces))
        r[keep] = _tri_area(P.at(clip, float(t)), P.faces)[keep] / rest_area[keep]
        bad = (r > STRETCH_AREA_HIGH) | (r < 1.0 / STRETCH_AREA_HIGH)
        over |= bad
        top = float(max(r.max(), 1.0 / max(r.min(), 1e-9)))
        if top > worst["ratio"]:
            worst = {"ratio": top, "t": float(t)}
    for name in sorted(set(part)):
        sel = part == name
        share_by_part[name] = round(float(over[sel].mean()), 4) if sel.any() else 0.0
    out = {"clip": clip, "duration": round(dur, 3), "samples": samples, "triangles": int(len(P.faces)),
           "triangles_ever_stretched_or_collapsed": round(float(over.mean()), 4), "worst_area_ratio": round(worst["ratio"], 2), "worst_at_s": round(worst["t"], 3),
           "share_by_part": share_by_part, "findings": []}
    if over.mean() > 0.02:
        bad_parts = [f"{k} {v * 100:.0f}%" for k, v in sorted(share_by_part.items(), key=lambda kv: -kv[1]) if v > 0.02]
        out["findings"].append(f"{over.mean() * 100:.1f}% of triangles grow or shrink by more than {STRETCH_AREA_HIGH}x against the bind pose in '{clip}' ({', '.join(bad_parts)})")
    return out


def texture_stretch(glb: bytes, yaw_deg: float, clip: Optional[str] = None, t: float = 0.0) -> Dict[str, Any]:
    """How the front picture is used when the avatar is seen at ``yaw_deg``.

    The front half of the texture is one picture of the character. Seen from the front it is used at full sharpness. As a surface
    turns away the same picture is smeared over a thinner and thinner sliver of screen, and past 90 degrees it is hidden. Shares
    are weighted by how much of the *picture* each triangle uses (its area in the texture), because that is what gets smeared:
      seen_well   facing the camera by more than ~71 degrees off edge-on
      edge_on     facing the camera, but within ~71 degrees of edge-on (smeared more than about three-fold)
      hidden      facing away
    ``visible_edge_on_share`` is the same smear as a share of the front picture's screen area (smaller, because smeared surfaces are thin).
    ``visible_from_generated_back`` is the share of everything on screen that comes from the back half of the texture, which the
    builder generates from the front rather than reading from the artist's drawing.
    """
    P = Posed(glb)
    pos = P.at(clip, t)
    th = math.radians(yaw_deg)
    c, s = math.cos(th), math.sin(th)
    R = np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])                  # the avatar turns about +Y; the camera looks down -Z
    q = pos @ R.T
    f = P.faces
    n = np.cross(q[f[:, 1]] - q[f[:, 0]], q[f[:, 2]] - q[f[:, 0]])
    area = 0.5 * np.linalg.norm(n, axis=1)
    cosv = n[:, 2] / np.maximum(2 * area, 1e-12)
    uv = P.uv[f]
    uv_area = 0.5 * np.abs((uv[:, 1, 0] - uv[:, 0, 0]) * (uv[:, 2, 1] - uv[:, 0, 1]) - (uv[:, 2, 0] - uv[:, 0, 0]) * (uv[:, 1, 1] - uv[:, 0, 1]))
    front = uv[:, :, 0].max(axis=1) <= 0.5 + 1e-6                      # the front half of the atlas
    total = float(uv_area[front].sum())
    seen = front & (cosv > EDGE_ON_COS)
    edge = front & (cosv > 0) & (cosv <= EDGE_ON_COS)
    hidden = front & (cosv <= 0)
    on_screen = (area * np.abs(cosv)) * (cosv > 0)
    back = uv[:, :, 0].min(axis=1) >= 0.5 - 1e-6                       # the back half of the atlas: generated, not drawn by the artist
    screen = on_screen[front]
    screen_edge = on_screen[edge]
    from_back = float(on_screen[back].sum() / on_screen.sum()) if on_screen.sum() > 0 else 0.0
    return {"yaw_deg": yaw_deg, "visible_from_generated_back": round(from_back, 4), "seen_well": round(float(uv_area[seen].sum() / total), 4), "edge_on": round(float(uv_area[edge].sum() / total), 4),
            "hidden": round(float(uv_area[hidden].sum() / total), 4),
            "visible_edge_on_share": round(float(screen_edge.sum() / screen.sum()) if screen.sum() > 0 else 0.0, 4)}


__all__ = ["normalise", "width_profile", "proportions", "silhouette", "palette", "palette_distance", "style", "compare_views", "turn_stability",
           "Posed", "mesh_stretch", "texture_stretch"]
