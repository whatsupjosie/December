"""The art-analysis checks (modules/avatar_likeness/analysis.py) on shapes whose answer is known, then on a real build."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
pytest.importorskip("cv2")
pytest.importorskip("scipy")
pytest.importorskip("PIL")
import cv2  # noqa: E402

from modules.avatar_likeness import analysis, motion, pipeline  # noqa: E402

PETE = ROOT / "tests" / "fixtures" / "avatar_likeness" / "fresh" / "fresh_woman_tpose_biker_jacket.png"


def _figure(w=200, h=400, body=(200, 120, 60), outline=None, head_r=30, shoulders=80, legs=40):
    """A stick-and-block person: head, shoulders, torso, two legs. Optionally with a dark outline."""
    img = np.zeros((h, w, 4), np.uint8)
    cx = w // 2
    def fill(draw):
        m = np.zeros((h, w), np.uint8)
        draw(m)
        return m > 0
    m = fill(lambda m: (cv2.circle(m, (cx, head_r + 8), head_r, 255, -1), cv2.rectangle(m, (cx - shoulders // 2, 2 * head_r + 14), (cx + shoulders // 2, int(h * 0.62)), 255, -1),
                        cv2.rectangle(m, (cx - legs, int(h * 0.62)), (cx - 4, h - 4), 255, -1), cv2.rectangle(m, (cx + 4, int(h * 0.62)), (cx + legs, h - 4), 255, -1)))
    img[m] = (*body, 255)
    if outline:
        edge = cv2.morphologyEx(m.astype(np.uint8), cv2.MORPH_GRADIENT, np.ones((7, 7), np.uint8)) > 0
        img[edge & m] = (*outline, 255)
    return img


def test_the_same_figure_at_a_different_size_and_place_is_the_same_silhouette():
    a = _figure()
    big = cv2.resize(a, (400, 800), interpolation=cv2.INTER_AREA)
    canvas = np.zeros((1000, 900, 4), np.uint8)
    canvas[100:900, 300:700] = big
    r = analysis.silhouette(a, canvas)
    assert r["iou"] > 0.97 and min(r["iou_bands"].values()) > 0.95


def test_a_different_body_is_told_apart_and_the_band_that_differs_is_named():
    a, b = _figure(), _figure(legs=22, shoulders=140)
    r = analysis.silhouette(a, b)
    assert r["iou"] < 0.9
    p = analysis.proportions(a, b)
    assert p["width_profile_l1"] > 0.02 and p["aspect_relative_difference"] > 0.05
    f = analysis.compare_views(a, b)
    assert any("width per row" in x or "wider or narrower" in x or "silhouette" in x for x in f["findings"])


def test_a_big_head_is_seen_in_the_width_profile():
    small, big = _figure(head_r=18), _figure(head_r=55)
    top = slice(0, 6)
    assert analysis.width_profile(big)[top].mean() > 1.5 * analysis.width_profile(small)[top].mean()


def test_identical_colours_have_no_distance_and_a_missing_colour_is_named():
    a = _figure(body=(200, 40, 40))
    assert analysis.palette_distance(a, a)["mean_delta_e"] < 0.5
    blue = _figure(body=(40, 60, 200))
    d = analysis.palette_distance(a, blue)
    assert d["mean_delta_e"] > 30 and d["colours_in_a_missing_from_b"] and d["colours_in_b_missing_from_a"]
    assert any("not in the render" in x for x in analysis.compare_views(a, blue)["findings"])


def test_a_lost_ink_outline_is_reported():
    inked, plain = _figure(outline=(10, 10, 10)), _figure()
    assert analysis.style(inked)["ink_outline_fraction"] > 0.5 > analysis.style(plain)["ink_outline_fraction"]
    r = analysis.compare_views(inked, plain)
    assert r["ink_outline_loss"] > 0.5 and any("outline" in x for x in r["findings"])
    assert analysis.compare_views(inked, inked)["findings"] == []


def test_a_figure_compared_with_itself_has_no_findings():
    a = _figure(outline=(10, 10, 10))
    r = analysis.compare_views(a, a)
    assert r["silhouette"]["iou"] == pytest.approx(1.0) and r["palette"]["mean_delta_e"] < 0.5 and r["findings"] == []


def test_an_empty_image_is_refused_in_words():
    with pytest.raises(ValueError, match="no figure"):
        analysis.silhouette(np.zeros((10, 10, 4), np.uint8), _figure())


def test_turn_stability_notices_a_height_that_wanders_and_a_frame_that_jumps():
    base = _figure()
    steady = [base.copy() for _ in range(8)]
    assert analysis.turn_stability(steady)["findings"] == []
    wander = [cv2.resize(base, (200, 400 - 12 * i), interpolation=cv2.INTER_AREA) for i in range(8)]
    canvas = []
    for f in wander:
        c = np.zeros((400, 200, 4), np.uint8)
        c[:f.shape[0]] = f
        canvas.append(c)
    assert any("height" in x for x in analysis.turn_stability(canvas)["findings"])
    jump = [base.copy() for _ in range(4)] + [_figure(shoulders=170, legs=15)] + [base.copy() for _ in range(3)]
    assert any("jumps" in x for x in analysis.turn_stability(jump)["findings"])


# ── on a real build ────────────────────────────────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def pete():
    return pipeline.build(PETE.read_bytes(), pipeline.Settings(name="pete", height_m=67 * 0.0254))


def test_skinning_on_the_cpu_reproduces_the_bind_pose_for_an_identity_clip(pete):
    P = analysis.Posed(pete.glb)
    names = P.names
    ident = motion.Clip("identity", 1.0, np.array([0.0, 1.0]),
                        {n: np.array([[0, 0, 0, 1], [0, 0, 0, 1]], float) for n in names},
                        {n: np.array([P.local[i], P.local[i]]) for i, n in enumerate(names)})
    P.clips["identity"] = ident
    assert np.abs(P.at("identity", 0.5) - P.pos).max() < 1e-6


def test_a_joint_turned_moves_its_own_part_and_nothing_else(pete):
    P = analysis.Posed(pete.glb)
    names = P.names
    q = np.array([0, 0, np.sin(np.radians(45)), np.cos(np.radians(45))], float)           # 90 degrees about Z at the left shoulder
    rot = {n: np.array([[0, 0, 0, 1], [0, 0, 0, 1]], float) for n in names}
    rot["UpperArm_L"] = np.array([q, q])
    P.clips["raise"] = motion.Clip("raise", 1.0, np.array([0.0, 1.0]), rot, {n: np.array([P.local[i], P.local[i]]) for i, n in enumerate(names)})
    moved = np.linalg.norm(P.at("raise", 0.5) - P.pos, axis=1)
    part = P.part_of_vertex()
    assert moved[part == "arm_L"].max() > 0.3 and moved[part == "hand_L"].max() > 0.5
    assert moved[(part == "leg_L") | (part == "leg_R") | (part == "head") | (part == "arm_R")].max() < 0.02


def test_mesh_stretch_is_small_for_the_default_walk_and_large_for_a_broken_clip(pete):
    walk = analysis.mesh_stretch(pete.glb, "Walk", samples=8)
    assert walk["triangles_ever_stretched_or_collapsed"] < 0.02                          # the arms-down base pose and the swing do not tear the shoulders
    P = analysis.Posed(pete.glb)
    names = P.names
    rot = {n: np.array([[0, 0, 0, 1], [0, 0, 0, 1]], float) for n in names}
    tr = {n: np.array([P.local[i], P.local[i]]) for i, n in enumerate(names)}
    a = np.radians(150.0) / 2                                                           # the middle of the spine folded 150 degrees forward
    rot["Spine_02"] = np.array([[np.sin(a), 0, 0, np.cos(a)], [np.sin(a), 0, 0, np.cos(a)]])
    broken = motion.Clip("pulled", 1.0, np.array([0.0, 1.0]), rot, tr)
    from modules.avatar_likeness import gltf_io
    built = pipeline.add_clips(pete, [broken])
    bad = analysis.mesh_stretch(built, "pulled", samples=4)
    assert bad["triangles_ever_stretched_or_collapsed"] > 5 * walk["triangles_ever_stretched_or_collapsed"] and bad["findings"]
    with pytest.raises(KeyError):
        analysis.mesh_stretch(pete.glb, "no-such-clip")


def test_the_front_picture_is_used_well_at_the_front_smeared_at_the_sides_and_hidden_behind(pete):
    t = {y: analysis.texture_stretch(pete.glb, y) for y in (0, 45, 90, 180)}
    assert t[0]["seen_well"] > 0.9 and t[0]["hidden"] < 0.05 and t[0]["visible_from_generated_back"] < 0.05
    assert t[45]["visible_from_generated_back"] > t[0]["visible_from_generated_back"]
    assert t[90]["seen_well"] < 0.45 and t[90]["hidden"] > 0.3 and 0.2 < t[90]["visible_from_generated_back"] < 0.8   # the sides mix drawn and generated
    assert t[180]["hidden"] > 0.99 and t[180]["visible_from_generated_back"] > 0.9                                  # from behind, what is seen is the generated back
    assert t[0]["seen_well"] > t[45]["seen_well"] > t[90]["seen_well"] > t[180]["seen_well"]
