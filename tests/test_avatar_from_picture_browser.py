"""Avatar from a picture, the way a person uses it: run_reach.py with a throwaway data folder, a real browser signed in through
the real login page, the real page.

1. Open /avatar-from-picture. 2. Choose the Pete picture, type her height (5 ft 7 in), Build.
3. The picture shows the joints, the avatar shows in 3D. 4. Drag a joint on the picture and Apply: version 2, the edit is in the file.
5. Animations play (the picture of the avatar changes over time); the side view is narrower than the front.
6. Put a recorded clip (run) on the avatar. 7. Save to the library; the host measures it itself.
8. Quit the host, start it again on the same folder, sign in, reopen the draft: the versions, the edit and the recording are still there.

Skips without Playwright/Chromium. Uses software WebGL (SwiftShader) so it needs no GPU.
"""
from __future__ import annotations

import base64
import io
import secrets
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]
sync_api = pytest.importorskip("playwright.sync_api")
np = pytest.importorskip("numpy")
PIL_Image = pytest.importorskip("PIL.Image")
pytest.importorskip("cv2")
pytest.importorskip("scipy")
PETE = ROOT / "tests" / "fixtures" / "avatar_likeness" / "fresh" / "fresh_woman_tpose_biker_jacket.png"
GL_ARGS = ["--no-sandbox", "--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"]


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Host:
    """run_reach.py over one data folder; ``start`` again after ``stop`` is a restart of the same installation."""

    def __init__(self, data: Path):
        self.data, self.proc, self.base, self.log = data, None, "", None

    def start(self) -> None:
        port = _free_port()
        self.log = open(self.data / "reach.log", "a", encoding="utf-8")
        self.proc = subprocess.Popen([sys.executable, "run_reach.py", "--port", str(port), "--data-dir", str(self.data), "--no-browser", "--no-legacy-2i"],
                                     cwd=str(ROOT), stdout=self.log, stderr=subprocess.STDOUT)
        self.base = f"http://127.0.0.1:{port}"
        c = httpx.Client(base_url=self.base, timeout=20, trust_env=False)
        try:
            deadline = time.time() + 120
            while time.time() < deadline:
                if self.proc.poll() is not None:
                    self.log.flush()
                    raise AssertionError("run_reach.py exited during startup:\n" + (self.data / "reach.log").read_text(encoding="utf-8")[-4000:])
                try:
                    if c.get("/health", timeout=0.5).status_code == 200:
                        return
                except httpx.RequestError:
                    pass
                time.sleep(0.3)
            raise AssertionError("PubCast did not start within 120 s")
        finally:
            c.close()

    def stop(self) -> None:
        if self.proc is not None:
            self.proc.terminate()
            try:
                self.proc.wait(30)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(5)
            self.proc = None
        if self.log:
            self.log.close()


@pytest.fixture(scope="module")
def reach(tmp_path_factory):
    data = tmp_path_factory.mktemp("likeness_userdata")
    host = Host(data)
    host.start()
    pw = secrets.token_urlsafe(18) + "A1!"
    try:
        r = httpx.post(host.base + "/api/auth/setup", trust_env=False, timeout=20,
                       json={"username": "owner-likeness", "password": pw, "confirm_password": pw, "display_name": "Josie", "email": "josie@example.com"})
        assert r.status_code == 201, r.text
        yield host, "owner-likeness", pw
    finally:
        host.stop()


def _canvas_png(page, selector):
    url = page.evaluate("(s) => document.querySelector(s).toDataURL('image/png')", selector)
    return PIL_Image.open(io.BytesIO(base64.b64decode(url.split(",", 1)[1]))).convert("RGBA")


def _extent(img):
    a = np.asarray(img)[..., 3] > 40
    cols = np.nonzero(a.any(axis=0))[0]
    return (int(cols[-1] - cols[0] + 1) if len(cols) else 0, int(a.sum()))


def _login(page, host, user, pw):
    page.goto(host.base + "/login?next=%2Favatar-from-picture")
    page.fill("#loginUser", user)
    page.fill("#loginPass", pw)
    page.keyboard.press("Enter")
    page.wait_for_url("**/avatar-from-picture**", timeout=30000)
    page.wait_for_function("document.documentElement.dataset.ready === '1'", timeout=60000)


def _token(host, user, pw):
    r = httpx.post(host.base + "/api/auth/login", json={"username": user, "password": pw}, trust_env=False, timeout=20)
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["access_token"]}


def test_from_a_picture_to_a_saved_avatar_and_back_after_a_restart(reach):
    host, user, pw = reach
    with sync_api.sync_playwright() as p:
        try:
            browser = p.chromium.launch(args=GL_ARGS)
        except Exception as exc:
            pytest.skip(f"no Chromium available: {exc}")
        try:
            page = browser.new_page(viewport={"width": 1500, "height": 900})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.on("console", lambda m: errors.append(m.text) if m.type == "error" and "favicon" not in m.text else None)
            _login(page, host, user, pw)
            assert page.locator("#buildBtn").is_disabled()                                      # nothing to build from yet
            assert "missing packages" not in page.locator("#status").inner_text()

            # 1. the picture and her height
            page.set_input_files("#file", str(PETE))
            assert page.locator("#name").input_value() == "fresh woman tpose biker jacket"[:80]
            page.fill("#name", "Pete")
            page.fill("#ft", "5")
            page.fill("#inch", "7")
            assert "6.70 pub blocks" in page.locator("#blocks").inner_text()
            page.click("#buildBtn")
            page.wait_for_function("(window.avatarFromPicture.state.shown || '').endsWith(':1')", timeout=180000)
            d1 = page.evaluate("window.avatarFromPicture.state.draft")
            assert d1["report"]["height_m"] == pytest.approx(67 * 0.0254, rel=0.02)
            page.wait_for_function("document.getElementById('status').textContent.includes('Built version 1')", timeout=20000)

            # 2. the picture view shows the joints; the avatar view shows a figure
            page.wait_for_timeout(1500)
            pic = _canvas_png(page, "#pic")
            assert _extent(pic)[1] > 5000
            front = _canvas_png(page, "#view")
            assert _extent(front)[1] > 5000

            # 3. drag a joint on the picture, apply, and the edit is in the file itself
            x0, y0 = page.evaluate("window.avatarFromPicture.jointScreen('elbow_L')")
            before = d1["landmarks"]["points"]["elbow_L"]
            page.mouse.move(x0, y0)
            page.mouse.down()
            page.mouse.move(x0 + 40, y0 + 20, steps=6)
            page.mouse.up()
            assert "1 unapplied change" in page.locator("#pending").inner_text()
            page.click("#applyBtn")
            page.wait_for_function("(window.avatarFromPicture.state.shown || '').endsWith(':2')", timeout=180000)
            d2 = page.evaluate("window.avatarFromPicture.state.draft")
            assert d2["landmarks"]["source"]["elbow_L"] == "user"
            moved = d2["landmarks"]["points"]["elbow_L"]
            assert abs(moved[0] - before[0]) > 5 and abs(moved[1] - before[1]) > 2
            auth = _token(host, user, pw)
            from modules.avatar_likeness import gltf_io
            glb = httpx.get(host.base + d2["urls"]["glb"], headers=auth, trust_env=False, timeout=60).content
            assert gltf_io.read_recipe(glb)["settings"]["joints"]["elbow_L"] == moved
            assert [v["n"] for v in d2["versions"]] == [1, 2]

            # 4. the walk plays (the figure changes over time) and the side is narrower than the front
            page.select_option("#clip", "Walk")
            page.click("#front")
            page.wait_for_timeout(400)
            a = _canvas_png(page, "#view")
            page.wait_for_timeout(450)
            b = _canvas_png(page, "#view")
            assert np.abs(np.asarray(a, float) - np.asarray(b, float)).mean() > 0.2             # the legs and arms moved between frames
            page.select_option("#clip", "")
            page.click("#front")
            page.wait_for_timeout(300)
            wf = _extent(_canvas_png(page, "#view"))[0]
            page.click("#side")
            page.wait_for_timeout(300)
            ws = _extent(_canvas_png(page, "#view"))[0]
            assert 0 < ws < 0.8 * wf, (wf, ws)

            # 5. a recorded clip, retargeted on the host and played in the page
            page.select_option("#mocapClip", "run")
            page.click("#mocapBtn")
            page.wait_for_function("(window.avatarFromPicture.state.shown || '').endsWith(':3') && window.avatarFromPicture.state.draft.recorded_clips.includes('Mocap_run')", timeout=180000)
            assert page.locator("#clip").input_value() == "Mocap_run"
            page.click("#front")
            page.wait_for_timeout(300)
            r1 = _canvas_png(page, "#view")
            page.wait_for_timeout(350)
            r2 = _canvas_png(page, "#view")
            assert np.abs(np.asarray(r1, float) - np.asarray(r2, float)).mean() > 0.3

            # 6. keep it: the library measures the file itself
            page.fill("#charId", "pete")
            page.click("#saveBtn")
            page.wait_for_selector("#saved .good", timeout=60000)
            assert "Saved to the library" in page.locator("#saved").inner_text()
            library = httpx.get(host.base + "/api/avatars/imports", trust_env=False, timeout=20).json()["avatars"]
            assert len(library) == 1 and library[0]["measured"]["height_m"] == pytest.approx(67 * 0.0254, rel=0.03)
            saved_blob = httpx.get(host.base + library[0]["url"], trust_env=False, timeout=60).content
            assert "Mocap_run" in gltf_io.read_skeleton(saved_blob)["clips"]
            draft_id = d2["id"]
            assert errors == [], errors
            page.close()
        finally:
            browser.close()

        # 7. quit the host and start it again over the same folder
        host.stop()
        host.start()
        browser = p.chromium.launch(args=GL_ARGS)
        try:
            page = browser.new_page(viewport={"width": 1500, "height": 900})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            _login(page, host, user, pw)
            page.select_option("#drafts", draft_id)
            page.wait_for_function("(window.avatarFromPicture.state.shown || '').endsWith(':3')", timeout=120000)
            d3 = page.evaluate("window.avatarFromPicture.state.draft")
            assert [v["n"] for v in d3["versions"]] == [1, 2, 3]
            assert d3["landmarks"]["source"]["elbow_L"] == "user" and d3["landmarks"]["points"]["elbow_L"] == moved
            assert set(d3["clips"]) == {"Idle", "Walk", "Mocap_run"}
            page.wait_for_timeout(1500)
            assert _extent(_canvas_png(page, "#view"))[1] > 5000                                   # and it draws again after the restart
            page.click("#versions button:has-text('v1')")                                         # undo is still there
            page.wait_for_function("(window.avatarFromPicture.state.shown || '').endsWith(':1')", timeout=120000)
            assert page.evaluate("window.avatarFromPicture.state.draft.landmarks.source.elbow_L") == "template"
            assert len(page.evaluate("window.avatarFromPicture.state.draft.versions")) == 3
            library = httpx.get(host.base + "/api/avatars/imports", trust_env=False, timeout=20).json()["avatars"]
            assert len(library) == 1                                                              # the saved avatar survived too
            assert errors == [], errors
        finally:
            browser.close()
