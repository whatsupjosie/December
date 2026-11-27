"""The picture-to-avatar routes (modules/avatar_likeness/routes.py): draft, edit, undo, recorded motion, save to the library.

Checked directly with a FastAPI test client and a real build of the Pete fixture (no model files needed). The real-host
launch, the page itself and quit-and-restart are exercised by tests/test_avatar_from_picture_browser.py.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
pytest.importorskip("cv2")
pytest.importorskip("scipy")
pytest.importorskip("PIL")
pytest.importorskip("websockets")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from modules.auth import create_access_token  # noqa: E402
from modules.avatar_imports import create_avatar_import_router  # noqa: E402
from modules.avatar_likeness import gltf_io, routes  # noqa: E402

PETE = ROOT / "tests" / "fixtures" / "avatar_likeness" / "fresh" / "fresh_woman_tpose_biker_jacket.png"


def _auth(user="josie", role="owner"):
    return {"Authorization": "Bearer " + create_access_token({"sub": user, "role": role})}


def _client(data_dir: Path):
    app = FastAPI()
    imports = create_avatar_import_router(data_dir)
    app.include_router(imports)
    router = routes.create_avatar_likeness_router(data_dir, imports.store)
    app.include_router(router)
    app.state.likeness_router = router
    return TestClient(app), imports


@pytest.fixture(scope="module")
def host(tmp_path_factory):
    data = tmp_path_factory.mktemp("likeness_host")
    client, imports = _client(data)
    with client:
        client.data_dir, client.imports = data, imports
        yield client


def _create(client, name="Pete", height_in=67, **extra):
    q = {"name": name, "height_in": height_in, **extra}
    return client.post("/api/avatars/likeness/drafts", params=q, content=PETE.read_bytes(), headers={**_auth(), "Content-Type": "image/png"})


@pytest.fixture(scope="module")
def pete_draft(host):
    r = _create(host)
    assert r.status_code == 201, r.text
    return r.json()


def test_status_says_what_this_host_can_do_without_downloading_anything(host):
    s = host.get("/api/avatars/likeness/status").json()
    assert s["ready"] is True and s["missing_packages"] == []
    assert set(s["models"]) == {"cutout_network", "pose_detector"}
    assert s["pub_block_m"] == pytest.approx(0.254)
    assert {"toddler", "child", "adult"} <= set(s["builds"]) and "mirror" in s["back_modes"]
    assert "run" in s["bundled_motion"] and "walk" in s["bundled_motion"]
    assert s["not_in_the_picture"]
    from modules.avatar_likeness import parts
    assert tuple(sorted(s["depth_parts"])) == tuple(sorted(parts.PARTS)) and set(s["depth_defaults"]) == set(parts.PARTS)   # every slider the page offers is one the builder accepts


def test_a_picture_becomes_a_draft_at_the_stated_height(pete_draft):
    d = pete_draft
    assert d["version"] == 1 and len(d["versions"]) == 1
    assert d["report"]["height_m"] == pytest.approx(67 * 0.0254, rel=0.02)
    assert d["report"]["height_pub_blocks"] == pytest.approx(6.7, rel=0.03)
    assert set(d["clips"]) == {"Idle", "Walk"}
    assert set(d["landmarks"]["points"]) == set(d["joints"])
    assert d["landmarks"]["source"]["knee_L"] == "template"                              # the page is told where each joint came from
    assert d["working_size"][0] > 100 and d["crop"][2] > 100


def test_the_draft_files_are_served_and_the_glb_is_the_one_the_recipe_describes(host, pete_draft):
    glb = host.get(pete_draft["urls"]["glb"], headers=_auth())
    assert glb.status_code == 200 and glb.headers["content-type"] == "model/gltf-binary" and glb.content[:4] == b"glTF"
    assert gltf_io.read_recipe(glb.content)["settings"]["height_m"] == pytest.approx(67 * 0.0254, abs=1e-4)
    pic = host.get(pete_draft["urls"]["picture"], headers=_auth())
    assert pic.status_code == 200 and pic.content[:8] == b"\x89PNG\r\n\x1a\n"
    from PIL import Image
    import io
    assert list(Image.open(io.BytesIO(pic.content)).size) == pete_draft["working_size"]       # joint pixels line up with this picture
    assert host.get(pete_draft["urls"]["source"], headers=_auth()).content == PETE.read_bytes()   # the upload, byte for byte


def test_an_edit_makes_a_new_version_and_an_earlier_one_can_be_brought_back(host):
    first = _create(host, "Edit me").json()
    elbow = first["landmarks"]["points"]["elbow_L"]
    new = [elbow[0] + 90.0, elbow[1] + 30.0]
    r = host.post(f"/api/avatars/likeness/drafts/{first['id']}/edit", headers=_auth(), json={"joints": {"elbow_L": new}, "depth": {"torso": 1.3}, "hair": "#3a2417"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["version"] == 2 and [v["n"] for v in d["versions"]] == [1, 2]
    assert d["landmarks"]["source"]["elbow_L"] == "user" and d["landmarks"]["points"]["elbow_L"] == pytest.approx(new, abs=0.01)
    assert d["settings"]["depth"] == {"torso": 1.3} and d["settings"]["hair_rgb"] == [0x3a, 0x24, 0x17]
    glb2 = host.get(d["urls"]["glb"], headers=_auth()).content
    assert gltf_io.read_recipe(glb2)["settings"]["joints"]["elbow_L"] == new                    # the edit is in the file itself
    back = host.post(f"/api/avatars/likeness/drafts/{first['id']}/select", params={"version": 1}, headers=_auth()).json()
    assert back["version"] == 1 and back["landmarks"]["source"]["elbow_L"] == "template" and len(back["versions"]) == 2   # nothing was deleted
    assert host.get(f"/api/avatars/likeness/drafts/{first['id']}/model.glb", params={"version": 2}, headers=_auth()).content == glb2
    assert host.post(f"/api/avatars/likeness/drafts/{first['id']}/select", params={"version": 9}, headers=_auth()).status_code == 404


def test_a_refused_edit_leaves_the_draft_exactly_as_it_was(host):
    d = _create(host, "Keep me").json()
    files_before = sorted(p.name for p in (host.data_dir / "avatars" / "likeness_drafts" / d["id"]).iterdir())
    for body, word in (({"joints": {"tail_tip": [1, 2]}}, "unknown joint"), ({"joints": {"elbow_L": [1]}}, "[x, y]"), ({"wings": 2}, "unknown edit"),
                       ({"depth": {"tail": 1.0}}, "tail"), ({"back_mode": "nope"}, "back"), ({"height_in": 900}, "height"), ({"hair": "red"}, "hair colour")):
        r = host.post(f"/api/avatars/likeness/drafts/{d['id']}/edit", headers=_auth(), json=body)
        assert r.status_code == 422 and word in r.json()["detail"], (body, r.text)
    assert host.post(f"/api/avatars/likeness/drafts/{d['id']}/edit", headers=_auth(), content=b"not json").status_code == 400
    assert host.post(f"/api/avatars/likeness/drafts/{d['id']}/edit", headers=_auth(), json={}).status_code == 400
    after = host.get(f"/api/avatars/likeness/drafts/{d['id']}", headers=_auth()).json()
    assert after["version"] == 1 and len(after["versions"]) == 1
    assert sorted(p.name for p in (host.data_dir / "avatars" / "likeness_drafts" / d["id"]).iterdir()) == files_before


def test_a_failed_write_rolls_back_and_leaves_no_stray_file(host, monkeypatch):
    d = _create(host, "Rollback").json()
    folder = host.data_dir / "avatars" / "likeness_drafts" / d["id"]
    files_before = sorted(p.name for p in folder.iterdir())
    store = routes_store(host)
    real = store._put_manifest
    def fail(_m):
        raise OSError("disk full (simulated)")
    monkeypatch.setattr(store, "_put_manifest", fail)
    r = host.post(f"/api/avatars/likeness/drafts/{d['id']}/edit", headers=_auth(), json={"depth": {"torso": 1.2}})
    monkeypatch.setattr(store, "_put_manifest", real)
    assert r.status_code == 500 and "draft was not changed" in r.json()["detail"]
    assert sorted(p.name for p in folder.iterdir()) == files_before                              # no v2.glb, no temp file
    again = host.get(f"/api/avatars/likeness/drafts/{d['id']}", headers=_auth()).json()
    assert again["version"] == 1 and len(again["versions"]) == 1
    ok = host.post(f"/api/avatars/likeness/drafts/{d['id']}/edit", headers=_auth(), json={"depth": {"torso": 1.2}})   # and it still works afterwards
    assert ok.status_code == 200 and ok.json()["version"] == 2


def routes_store(client):
    return client.app.state.likeness_router.drafts


def test_recorded_motion_is_retargeted_onto_the_draft_and_kept_through_later_edits(host):
    d = _create(host, "Moves").json()
    r = host.post(f"/api/avatars/likeness/drafts/{d['id']}/mocap", params={"clip": "run"}, headers=_auth())
    assert r.status_code == 200, r.text
    m = r.json()
    assert set(m["clips"]) == {"Idle", "Walk", "Mocap_run"} and m["recorded_clips"] == ["Mocap_run"]
    e = host.post(f"/api/avatars/likeness/drafts/{d['id']}/edit", headers=_auth(), json={"depth": {"leg_L": 1.2, "leg_R": 1.2}}).json()
    assert set(e["clips"]) == {"Idle", "Walk", "Mocap_run"}
    assert host.post(f"/api/avatars/likeness/drafts/{d['id']}/mocap", params={"clip": "moonwalk"}, headers=_auth()).status_code == 422
    assert host.post(f"/api/avatars/likeness/drafts/{d['id']}/mocap", params={"source": "upload"}, headers=_auth()).status_code == 400


def test_saving_puts_the_file_in_the_library_which_measures_it_itself(host):
    d = _create(host, "Library Pete", 67).json()
    r = host.post(f"/api/avatars/likeness/drafts/{d['id']}/save", params={"character_id": "pete"}, headers=_auth())
    assert r.status_code == 201, r.text
    a = r.json()["avatar"]
    assert a["measured"]["height_m"] == pytest.approx(67 * 0.0254, rel=0.03)
    stored = host.imports.store.path_for(a["id"]).read_bytes()
    assert gltf_io.read_recipe(stored)["settings"]["name"] == "Library Pete"                       # the recipe travels into the library
    assert host.get(a["url"]).status_code == 200
    wrong = host.post(f"/api/avatars/likeness/drafts/{d['id']}/save", params={"height_in": 40}, headers=_auth())
    assert wrong.status_code == 422                                                                  # the library refuses a height that does not match the file


def test_nobody_reads_or_edits_someone_elses_draft(host, pete_draft):
    other = _auth("someone_else", "user")
    for method, url, kw in (("get", f"/api/avatars/likeness/drafts/{pete_draft['id']}", {}), ("get", pete_draft["urls"]["glb"], {}),
                            ("post", f"/api/avatars/likeness/drafts/{pete_draft['id']}/edit", {"json": {"depth": {"torso": 1.1}}}),
                            ("post", f"/api/avatars/likeness/drafts/{pete_draft['id']}/save", {}), ("delete", f"/api/avatars/likeness/drafts/{pete_draft['id']}", {})):
        assert getattr(host, method)(url, headers=other, **kw).status_code == 403, url
    assert [x["id"] for x in host.get("/api/avatars/likeness/drafts", headers=other).json()["drafts"]] == []
    assert pete_draft["id"] in [x["id"] for x in host.get("/api/avatars/likeness/drafts", headers=_auth()).json()["drafts"]]


@pytest.mark.parametrize("content_type,body,code,word", [
    ("text/plain", b"hello", 415, "image/png"), ("image/png", b"", 400, "empty"), ("image/png", b"this is not a picture", 422, "image"),
    ("image/png", b"\x89PNG\r\n\x1a\n" + b"0" * 64, 422, "image")])
def test_bad_uploads_are_refused_in_plain_words(host, content_type, body, code, word):
    r = host.post("/api/avatars/likeness/drafts", params={"name": "x", "height_in": 67}, content=body, headers={**_auth(), "Content-Type": content_type})
    assert r.status_code == code and word in r.json()["detail"]


def test_missing_or_silly_parameters_are_refused(host):
    h = {**_auth(), "Content-Type": "image/png"}
    assert host.post("/api/avatars/likeness/drafts", params={"height_in": 67}, content=b"x", headers=h).status_code == 400
    assert host.post("/api/avatars/likeness/drafts", params={"name": "x"}, content=b"x", headers=h).status_code == 400
    assert host.post("/api/avatars/likeness/drafts", params={"name": "x", "height_in": 0.1}, content=PETE.read_bytes(), headers=h).status_code == 422
    assert host.post("/api/avatars/likeness/drafts", params={"name": "x", "height_in": 67, "hair": "red"}, content=b"x", headers=h).status_code == 422


def test_an_oversized_upload_is_refused_before_a_build_starts(host, monkeypatch):
    monkeypatch.setattr(routes, "MAX_IMAGE_BYTES", 1000)
    r = host.post("/api/avatars/likeness/drafts", params={"name": "x", "height_in": 67}, content=b"x" * 2000, headers={**_auth(), "Content-Type": "image/png"})
    assert r.status_code == 413


def test_drafts_survive_a_restart_of_the_host(tmp_path):
    client, _ = _client(tmp_path)
    with client:
        d = _create(client, "Restart me").json()
        glb = client.get(d["urls"]["glb"], headers=_auth()).content
    client2, _ = _client(tmp_path)                                                                    # a fresh process over the same data folder
    with client2:
        again = client2.get(f"/api/avatars/likeness/drafts/{d['id']}", headers=_auth()).json()
        assert again["version"] == 1 and again["name"] == "Restart me"
        assert client2.get(again["urls"]["glb"], headers=_auth()).content == glb


def test_deleting_a_draft_is_an_explicit_request_and_removes_only_that_draft(host):
    a, b = _create(host, "Delete me").json(), _create(host, "Keep me too").json()
    assert host.delete(f"/api/avatars/likeness/drafts/{a['id']}", headers=_auth()).status_code == 200
    assert host.get(f"/api/avatars/likeness/drafts/{a['id']}", headers=_auth()).status_code == 404
    assert host.get(f"/api/avatars/likeness/drafts/{b['id']}", headers=_auth()).status_code == 200
    assert host.get("/api/avatars/likeness/drafts/not-an-id", headers=_auth()).status_code == 400


def test_the_draft_limit_asks_the_person_instead_of_deleting_their_work(tmp_path, monkeypatch):
    monkeypatch.setattr(routes, "MAX_DRAFTS_PER_OWNER", 1)
    client, _ = _client(tmp_path)
    with client:
        assert _create(client, "one").status_code == 201
        r = _create(client, "two")
        assert r.status_code == 409 and "delete" in r.json()["detail"]
        assert len(client.get("/api/avatars/likeness/drafts", headers=_auth()).json()["drafts"]) == 1
