"""Picture-to-avatar builder (modules/avatar_likeness): contract, build, export/reimport, edits, retargeting, Studio player.

Runs offline with no model files: the cut-out is the classical one and joints come from the build template, which is the
guaranteed path. Tests that need the optional models (cut-out network, pose detector) are skipped unless the files are named
in PUBCAST_AVATAR_MATTE_ONNX / PUBCAST_AVATAR_POSE_TASK. The browser test is skipped where there is no Chromium with WebGL.
"""
import os
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
FIX = ROOT / "tests" / "fixtures" / "avatar_likeness"
PETE = FIX / "fresh" / "fresh_woman_tpose_biker_jacket.png"
REPEAT = FIX / "fresh" / "fresh_man_tpose_camera_bag.png"
HUMPHREY = FIX / "humphrey" / "Baby_Detective_Character_First_Sample.png"
XBOT = ROOT / "static" / "world" / "test_avatars" / "Xbot.glb"
PETE_M = 67 * 0.0254          # Josie, 2026-11-27: "canonically 5'7\""

pytest.importorskip("cv2")
pytest.importorskip("scipy")
pytest.importorskip("PIL")
from modules.avatar_likeness import gltf_io, intake, landmarks, motion, parts, pipeline, retarget, rig, skeleton  # noqa: E402


@pytest.fixture(scope="module")
def pete():
    return pipeline.build(PETE.read_bytes(), pipeline.Settings(name="pete", height_m=PETE_M))


# ── the mocap contract ─────────────────────────────────────────────────────────────────────────────────────────────

def test_skeleton_agrees_with_the_mocap_contract():
    pytest.importorskip("websockets")
    assert skeleton.parity_with_mocap_contract() == []


def test_rest_pose_is_a_world_aligned_t_pose(pete):
    r = pete.rigged.rest
    assert np.allclose(r["Root"], 0)
    assert r["UpperArm_L"][0] > 0 > r["UpperArm_R"][0]                                  # left is +X
    for a, b, axis, sign in (("UpperArm_L", "LowerArm_L", 0, 1), ("LowerArm_L", "Hand_L", 0, 1), ("UpperArm_R", "LowerArm_R", 0, -1),
                             ("Thigh_L", "Calf_L", 1, -1), ("Calf_L", "Foot_L", 1, -1), ("Spine_01", "Spine_02", 1, 1), ("Foot_L", "Ball_L", 2, 1)):
        d = r[b] - r[a]
        d = d / np.linalg.norm(d)
        assert d[axis] == pytest.approx(sign, abs=1e-6), (a, b, d)
    assert r["UpperArm_L"][1] == pytest.approx(r["UpperArm_R"][1])                      # shoulders level


def test_bone_names_are_the_ones_the_motion_consumer_resolves():
    js = (ROOT / "static" / "avatar_glb_motion_consumer.js").read_text(encoding="utf-8")
    for name in skeleton.NAMES:
        if name not in ("Ball_L", "Ball_R"):
            assert f'"{name}"' in js, f"{name} is not a name the motion consumer looks for"


# ── building ───────────────────────────────────────────────────────────────────────────────────────────────────────

def test_height_is_the_height_that_was_stated(pete):
    assert pete.report["height_m"] == pytest.approx(PETE_M, rel=0.02)
    assert pete.report["height_pub_blocks"] == pytest.approx(PETE_M / 0.254, rel=0.02)
    assert pete.rigged.pos[:, 1].min() == pytest.approx(0.0, abs=1e-4)                  # standing on the floor


def test_the_pub_block_constant_matches_the_repository():
    from modules.voxel_set_contract import PUB_BLOCK_METERS
    assert pipeline.PUB_BLOCK_M == PUB_BLOCK_METERS


def test_a_figure_drawn_in_a_t_pose_barely_moves_when_baked(pete):
    assert pete.rigged.moved_m < 0.12 * PETE_M


def test_every_vertex_is_skinned_and_weights_sum_to_one(pete):
    w = pete.rigged.weights
    assert np.allclose(w.sum(axis=1), 1.0, atol=1e-4)
    assert (pete.rigged.joints.max()) < len(skeleton.NAMES)
    assert int(pete.shell.faces.max()) < len(pete.rigged.pos)


def test_the_front_of_the_avatar_is_the_supplied_artwork(pete):
    import cv2
    from modules.avatar_likeness.texture import split_atlas
    front, _ = split_atlas(pete.atlas)
    x0, y0, w, h = pete.shell.crop
    th, tw = front.shape[:2]
    src = cv2.resize(pete.cutout.rgb[y0:y0 + h, x0:x0 + w], (tw, th), interpolation=cv2.INTER_AREA).astype(float)   # compare at the atlas's own size
    solid = cv2.resize(pete.cutout.alpha[y0:y0 + h, x0:x0 + w], (tw, th), interpolation=cv2.INTER_AREA) > 0.97
    assert solid.sum() > 10000
    assert np.abs(front[..., :3].astype(float)[solid] - src[solid]).mean() < 1.0        # the supplied colours, not repainted or tinted


def test_the_template_fallback_is_reported_when_no_pose_model_is_present(pete):
    assert pete.landmarks.detector_used is False
    assert set(pete.landmarks.source.values()) == {"template"}
    assert any("template" in w for w in pete.report["warnings"])
    assert pete.report["not_in_the_picture"]                                             # the report states what the picture cannot show


def test_height_picks_the_build():
    assert landmarks.build_for_height(0.89) == "toddler"
    assert landmarks.build_for_height(1.3) == "child"
    assert landmarks.build_for_height(1.75) == "adult"


@pytest.mark.parametrize("data,why", [(b"", "empty"), (b"not an image at all, just text", "not an image"), (b"\x89PNG\r\n\x1a\n" + b"0" * 40, "not an image")])
def test_bad_uploads_are_refused_in_plain_words(data, why):
    with pytest.raises(intake.IntakeError) as e:
        pipeline.build(data, pipeline.Settings(height_m=1.7))
    assert why in str(e.value) or "image" in str(e.value)


@pytest.mark.parametrize("kw", [{"height_m": 0.01}, {"height_m": 9.0}, {"build": "giant"}, {"depth": {"tail": 1.0}}, {"depth": {"head": 9.0}}, {"back_mode": "nope"}])
def test_bad_settings_are_refused(kw):
    with pytest.raises(intake.IntakeError):
        pipeline.validate(pipeline.Settings(**{"height_m": 1.7, **kw}))


# ── the file ───────────────────────────────────────────────────────────────────────────────────────────────────────

def test_the_glb_has_the_skeleton_the_clips_the_texture_and_the_recipe(pete):
    sk = gltf_io.read_skeleton(pete.glb)
    assert set(sk["joints"]) == set(skeleton.NAMES)
    assert sk["joints"]["Head"]["parent"] == "Neck_01" and sk["joints"]["Root"]["parent"] is None
    assert set(sk["clips"]) == {"Idle", "Walk"}                                          # the names static/world_walk_glb.js looks for
    recipe = gltf_io.read_recipe(pete.glb)
    assert recipe["settings"]["height_m"] == pytest.approx(PETE_M, abs=1e-4)
    assert gltf_io.read_atlas(pete.glb).shape == pete.atlas.shape


def test_building_twice_gives_the_same_bytes():
    a = pipeline.build(PETE.read_bytes(), pipeline.Settings(name="p", height_m=PETE_M)).glb
    b = pipeline.build(PETE.read_bytes(), pipeline.Settings(name="p", height_m=PETE_M)).glb
    assert pipeline.fingerprint(a) == pipeline.fingerprint(b)


def test_the_repository_import_store_accepts_the_file_and_measures_the_height(pete, tmp_path):
    avatar_imports = pytest.importorskip("modules.avatar_imports")
    store = avatar_imports.AvatarImportStore(tmp_path)
    entry = store.add(pete.glb, name="Pete", height_in=67, owner="test", source_format="glb", source_name="pete.glb")
    assert entry["measured"]["height_m"] == pytest.approx(PETE_M, rel=0.03)
    assert store.path_for(entry["id"]).read_bytes() == pete.glb


# ── editing: a user edit survives export and reimport ──────────────────────────────────────────────────────────────

def test_a_moved_joint_and_a_depth_change_survive_export_and_reimport(pete, tmp_path):
    avatar_imports = pytest.importorskip("modules.avatar_imports")
    sh = pete.landmarks.points["shoulder_L"]
    edits = {"joints": {"elbow_L": [sh[0] + 130.0, sh[1] + 40.0]}, "depth": {"torso": 1.3}}
    edited = pipeline.rebuild(pete.glb, edits)
    assert edited.recipe["landmarks"]["source"]["elbow_L"] == "user"
    assert edited.shell.pos[:, 2].max() != pete.shell.pos[:, 2].max() or not np.allclose(edited.rigged.pos, pete.rigged.pos)
    store = avatar_imports.AvatarImportStore(tmp_path)
    entry = store.add(edited.glb, name="Pete edited", height_in=67, owner="test", source_format="glb", source_name="pete.glb")
    stored = store.path_for(entry["id"]).read_bytes()
    recipe = gltf_io.read_recipe(stored)
    assert recipe["settings"]["joints"]["elbow_L"] == [sh[0] + 130.0, sh[1] + 40.0]
    assert recipe["settings"]["depth"]["torso"] == 1.3
    again = pipeline.rebuild(stored)                                                     # reimport with no further edits changes nothing
    assert np.allclose(again.rigged.pos, edited.rigged.pos, atol=2e-3)
    assert again.recipe["settings"]["joints"] == recipe["settings"]["joints"]
    more = pipeline.rebuild(stored, {"depth": {"head": 1.4}})                            # a later edit keeps the earlier one
    assert more.recipe["settings"]["depth"] == {"torso": 1.3, "head": 1.4}
    assert more.recipe["landmarks"]["source"]["elbow_L"] == "user"


def test_a_texture_repainted_outside_the_builder_survives_a_rebuild(pete):
    atlas = gltf_io.read_atlas(pete.glb).copy()
    h, w = atlas.shape[:2]
    atlas[h // 2: h // 2 + 30, w // 8: w // 8 + 30] = (255, 0, 255, 255)                 # a magenta patch painted into the front
    doc, binb = gltf_io.read_glb(pete.glb)
    mesh = gltf_io.read_mesh(pete.glb)
    local = skeleton.local_translations(pete.rigged.rest)
    repainted = gltf_io.write_glb(mesh["POSITION"], mesh["TEXCOORD_0"], mesh["indices"], mesh["JOINTS_0"], mesh["WEIGHTS_0"], local,
                                  pete.rigged.ibm, atlas, [], pete.recipe, "pete")
    rebuilt = pipeline.rebuild(repainted, {"depth": {"torso": 1.1}})
    front = rebuilt.atlas[:, : rebuilt.atlas.shape[1] // 2]
    patch = front[h // 2 + 5: h // 2 + 25, w // 8 + 5: w // 8 + 25, :3].reshape(-1, 3)
    assert (np.abs(patch.astype(int) - np.array([255, 0, 255])).sum(axis=1) < 40).mean() > 0.9


def test_rebuilding_a_file_that_was_not_made_here_says_so():
    with pytest.raises(intake.IntakeError) as e:
        pipeline.rebuild(XBOT.read_bytes())
    assert "recipe" in str(e.value)


def test_the_back_view_can_be_changed_without_touching_the_front(pete):
    other = pipeline.rebuild(pete.glb, {"back_mode": "mirror"})
    f0, b0 = __import__("modules.avatar_likeness.texture", fromlist=["x"]).split_atlas(pete.atlas)
    f1, b1 = __import__("modules.avatar_likeness.texture", fromlist=["x"]).split_atlas(other.atlas)
    assert np.array_equal(f0, f1) and not np.array_equal(b0, b1)


# ── motion ─────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_default_clips_loop_and_use_canonical_joints(pete):
    for clip in motion.default_clips(pete.rigged.rest, pete.rigged.local, list(skeleton.NAMES)):
        assert set(clip.rotations) <= set(skeleton.NAMES)
        for q in clip.rotations.values():
            assert np.allclose(np.linalg.norm(q, axis=1), 1.0, atol=1e-6)
            assert np.allclose(q[0], q[-1], atol=1e-6)                                   # loops


def test_cadence_scales_with_leg_length():
    short = {"Thigh_L": np.array([0, 0.3, 0]), "Calf_L": np.array([0, 0.18, 0]), "Foot_L": np.array([0, 0.06, 0]), "Pelvis": np.array([0, 0.3, 0.0])}
    tall = {"Thigh_L": np.array([0, 0.9, 0]), "Calf_L": np.array([0, 0.5, 0]), "Foot_L": np.array([0, 0.08, 0]), "Pelvis": np.array([0, 0.9, 0.0])}
    local = {"Pelvis": np.array([0, 0.3, 0.0])}
    assert motion.make_walk(short, local, list(skeleton.NAMES)).duration < motion.make_walk(tall, local, list(skeleton.NAMES)).duration


def test_a_recorded_mannequin_clip_retargets_with_real_motion(pete):
    src = retarget.SourceRig(XBOT.read_bytes())
    walk = retarget.retarget_clip(src, "walk", pete.rigged.rest, pete.rigged.local)
    assert walk.duration == pytest.approx(src.clips["walk"]["samplers"] and max(float(gltf_io._accessor_array(src.doc, src.bin, s["input"]).max()) for s in src.clips["walk"]["samplers"]), rel=0.02)
    for q in walk.rotations.values():
        assert np.isfinite(q).all() and np.allclose(np.linalg.norm(q, axis=1), 1.0, atol=1e-5)
    def swing_deg(joint):
        q = walk.rotations[joint]
        ang = 2 * np.degrees(np.arccos(np.clip(np.abs(q[:, 3]), 0, 1)))
        return float(ang.max() - ang.min())
    assert swing_deg("Thigh_L") > 20 and swing_deg("Thigh_R") > 20                      # the recorded legs actually swing
    t = walk.translations["Pelvis"]
    assert np.allclose(t[:, 0], t[0, 0]) and np.allclose(t[:, 2], t[0, 2])             # in place: no sideways or forward travel
    assert t[:, 1].max() > t[:, 1].min()                                                 # but the hips still bob
    with pytest.raises(KeyError):
        retarget.retarget_clip(src, "no-such-clip", pete.rigged.rest, pete.rigged.local)


def test_a_retargeted_clip_is_written_into_the_glb(pete):
    src = retarget.SourceRig(XBOT.read_bytes())
    glb = pipeline.add_clips(pete, [retarget.retarget_clip(src, "run", pete.rigged.rest, pete.rigged.local, name="Mocap_run")])
    assert set(gltf_io.read_skeleton(glb)["clips"]) == {"Idle", "Walk", "Mocap_run"}


# ── optional models ────────────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.skipif(not os.environ.get("PUBCAST_AVATAR_MATTE_ONNX"), reason="cut-out network not installed")
def test_the_cutout_network_rescues_a_dark_background():
    from modules.avatar_likeness import matte
    m = matte.load()
    bad = intake.prepare(HUMPHREY.read_bytes())
    good = intake.prepare(HUMPHREY.read_bytes(), matte=m)
    assert good.report.method == "matting-network"
    assert good.report.foreground_fraction > 1.5 * bad.report.foreground_fraction       # the classical cut-out lost a third of him
    assert any("dark" in w for w in bad.report.warnings)                                 # and said so


@pytest.mark.skipif(not os.environ.get("PUBCAST_AVATAR_POSE_TASK"), reason="pose detector not installed")
def test_the_pose_detector_is_used_on_a_t_pose_adult_and_refused_on_a_toddler():
    b = pipeline.build(PETE.read_bytes(), pipeline.Settings(height_m=PETE_M))
    assert b.landmarks.detector_used and b.landmarks.source["knee_L"] == "detector"
    c = pipeline.build(PETE.read_bytes(), pipeline.Settings(height_m=0.89))
    assert not c.landmarks.detector_used


# ── the real Studio player ─────────────────────────────────────────────────────────────────────────────────────────

def test_the_studio_player_loads_walks_and_turns_the_avatar(pete, tmp_path):
    pytest.importorskip("playwright.sync_api")
    from tools.avatar_likeness.render import Studio
    glb = tmp_path / "pete.glb"
    glb.write_bytes(pete.glb)
    try:
        studio = Studio("static/world_walk.html?view=writers_room/main").__enter__()
    except Exception as exc:                                                             # no Chromium with WebGL here
        pytest.skip(f"no browser: {exc}")
    try:
        info = studio.studio_load(glb, "pete")
        assert info["hasWalk"] and info["hasIdle"] and info["skinned"] == 1 and info["bones"] == len(skeleton.NAMES)
        assert info["nativeHeight"] == pytest.approx(PETE_M, rel=0.03)
        script = [dict(vx=0, vy=1, moving=True, dt=1 / 24)] * 12 + [dict(vx=1, vy=0, moving=True, dt=1 / 24)] * 20
        frames = studio.studio_frames("pete", script, H=400, size=(500, 560))
        widths = []
        for f in frames:
            a = np.asarray(f)[..., 3] > 40
            assert a.any(), "a frame came back empty"
            cols = np.nonzero(a.any(axis=0))[0]
            widths.append(cols[-1] - cols[0])
        assert max(widths) > 1.6 * min(widths)                                           # front view is wider than the turned side view
        assert [p for p in studio.problems if "404" not in p] == []
    finally:
        studio.__exit__(None, None, None)
