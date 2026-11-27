"""Development renderer for avatar_likeness: turntables and clip frames from a GLB, and the real Studio player for walk-and-turn.

Needs Playwright and a Chromium with WebGL (swiftshader is fine). Not part of the product; the product's own path is the
Foundry page and /walk. ``viewer.html`` uses the same vendored three.js build as the Studio.
"""
from __future__ import annotations

import base64
import functools
import http.server
import io
import os
import shutil
import tempfile
import threading
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
GL_ARGS = ["--no-sandbox", "--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"]


class _Handler(http.server.SimpleHTTPRequestHandler):
    avatars_dir: Path

    def translate_path(self, path: str) -> str:
        if path.startswith("/__avatars__/"):
            return str(self.avatars_dir / path[len("/__avatars__/"):].split("?")[0])
        return super().translate_path(path)

    def log_message(self, *a, **k):  # quiet
        pass


class Studio:
    """Context manager: static server for the repository, a scratch folder for GLBs, one headless page."""

    def __init__(self, page: str = "tools/avatar_likeness/viewer.html", viewport=(1500, 900)):
        self.page_path, self.viewport = page, viewport

    def __enter__(self) -> "Studio":
        from playwright.sync_api import sync_playwright
        self.tmp = Path(tempfile.mkdtemp(prefix="avatar_studio_"))
        handler = type("H", (_Handler,), {"avatars_dir": self.tmp})
        handler = functools.partial(handler, directory=str(ROOT))
        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        self._pw = sync_playwright().start()
        browser = None
        for kw in ({}, {"executable_path": os.environ.get("PLAYWRIGHT_CHROMIUM", "/usr/bin/google-chrome")}):
            try:
                browser = self._pw.chromium.launch(args=GL_ARGS, **kw)
                break
            except Exception:
                continue
        if browser is None:
            raise RuntimeError("no Chromium with WebGL available")
        self.browser = browser
        self.page = browser.new_page(viewport={"width": self.viewport[0], "height": self.viewport[1]})
        self.problems: List[str] = []
        self.page.on("pageerror", lambda e: self.problems.append(str(e)))
        self.page.on("console", lambda m: self.problems.append(m.text) if m.type == "error" else None)
        self.page.goto(f"{self.base}/{self.page_path}")
        return self

    def __exit__(self, *exc) -> None:
        self.browser.close()
        self._pw.stop()
        self.httpd.shutdown()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def stage(self, glb: Path, name: Optional[str] = None) -> str:
        dest = self.tmp / (name or Path(glb).name)
        shutil.copyfile(glb, dest)
        return f"/__avatars__/{dest.name}"

    # viewer.html ----------------------------------------------------------------------------------------------------
    def viewer_load(self, glb: Path) -> Dict:
        self.page.wait_for_function("document.documentElement.dataset.ready==='1'", timeout=20000)
        return self.page.evaluate("u => window.loadAvatar(u)", self.stage(glb))

    def viewer_frame(self, **kw) -> Image.Image:
        url = self.page.evaluate("o => window.show(o)", kw)
        return Image.open(io.BytesIO(base64.b64decode(url.split(",", 1)[1]))).convert("RGBA")

    # world_walk.html (the real Studio player) -----------------------------------------------------------------------
    def studio_load(self, glb: Path, cid: str = "avatar") -> Dict:
        self.page.wait_for_function("document.documentElement.dataset.ready==='1' && !!window.PubCastGLB", timeout=30000)
        return self.page.evaluate("async ([id,u]) => window.PubCastGLB.load(id, u, id)", [cid, self.stage(glb)])

    def studio_frames(self, cid: str, script: Sequence[Dict], H: int = 520, size=(520, 660)) -> List[Image.Image]:
        """Run the player through ``script`` (each step: vx, vy, moving, dt) and return the drawn frame of every step."""
        return [Image.open(io.BytesIO(base64.b64decode(u.split(",", 1)[1]))).convert("RGBA") for u in self.page.evaluate(
            """([id, steps, H, w, h]) => { const G = window.PubCastGLB, out = [];
                 const c = document.createElement('canvas'); c.width = w; c.height = h; const x = c.getContext('2d');
                 for (const s of steps) { x.clearRect(0, 0, w, h); G.draw(x, id, w / 2, h - 40, H, {vx: s.vx, vy: s.vy, moving: s.moving, dt: s.dt, pxScale: 1}); out.push(c.toDataURL('image/png')); }
                 return out; }""", [cid, list(script), H, size[0], size[1]])]


def over(img: Image.Image, bg=(255, 255, 255)) -> Image.Image:
    base = Image.new("RGB", img.size, bg)
    base.paste(img, mask=img.split()[3])
    return base


def sheet(images: Iterable[Image.Image], height: int = 420, bg=(255, 255, 255), gap: int = 6) -> Image.Image:
    ims = [over(i, bg).resize((max(1, int(i.width * height / i.height)), height)) for i in images]
    out = Image.new("RGB", (sum(i.width for i in ims) + gap * (len(ims) - 1), height), bg)
    x = 0
    for i in ims:
        out.paste(i, (x, 0)); x += i.width + gap
    return out
