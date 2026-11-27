"""Record what the OLD picture-to-avatar workflow does with a picture, through the real host and the real pages.

Starts run_reach.py over a throwaway data folder, signs in through the real login page, opens the Dressing Room, gives its
photo box the picture, presses its bake button, and records: the host's answer to /api/avatars/me/bake, what the page says,
screenshots of the Dressing Room and the Avatar Foundry afterwards, and /api/avatars/me. Nothing is judged here; the files are
evidence for the comparison sheet.

    python tools/avatar_likeness/baseline_old_workflow.py PICTURE.png OUT_DIR

Needs Playwright with Chromium. PowerShell 5: python tools\\avatar_likeness\\baseline_old_workflow.py PICTURE.png OUT
"""
from __future__ import annotations

import json
import secrets
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def main(picture: Path, out: Path) -> int:
    from playwright.sync_api import sync_playwright
    out.mkdir(parents=True, exist_ok=True)
    data = Path(__import__("tempfile").mkdtemp(prefix="old_workflow_"))
    port = _free_port()
    log = open(data / "reach.log", "w", encoding="utf-8")
    proc = subprocess.Popen([sys.executable, "run_reach.py", "--port", str(port), "--data-dir", str(data), "--no-browser", "--no-legacy-2i"],
                            cwd=str(ROOT), stdout=log, stderr=subprocess.STDOUT)
    base = f"http://127.0.0.1:{port}"
    c = httpx.Client(base_url=base, timeout=30, trust_env=False)
    record = {"picture": picture.name, "host": "run_reach.py over a throwaway data folder", "steps": []}
    try:
        deadline = time.time() + 120
        while time.time() < deadline:
            if proc.poll() is not None:
                raise SystemExit("run_reach.py exited during startup:\n" + (data / "reach.log").read_text(encoding="utf-8")[-3000:])
            try:
                if c.get("/health", timeout=0.5).status_code == 200:
                    break
            except httpx.RequestError:
                pass
            time.sleep(0.3)
        pw = secrets.token_urlsafe(18) + "A1!"
        r = c.post("/api/auth/setup", json={"username": "owner-old", "password": pw, "confirm_password": pw, "display_name": "Owner", "email": "o@example.com"})
        r.raise_for_status()
        auth = {"Authorization": "Bearer " + r.json()["access_token"]}
        with sync_playwright() as p:
            browser = p.chromium.launch(args=["--no-sandbox", "--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"])
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            seen = []
            page.on("response", lambda resp: seen.append((resp.url, resp.status)) if "/api/avatars/me/bake" in resp.url else None)
            page.goto(base + "/login?next=%2Fdressing")
            page.fill("#loginUser", "owner-old")
            page.fill("#loginPass", pw)
            page.keyboard.press("Enter")
            page.wait_for_url("**/dressing**", timeout=30000)
            page.wait_for_timeout(1500)
            page.screenshot(path=str(out / "old_dressing_before.png"))
            page.set_input_files("#photoInput", str(picture))
            page.click("button:has-text('Bake Voxel Portrait')")      # the page's own bake button
            page.wait_for_function("document.getElementById('bakeStatus').textContent.length > 0 && !document.getElementById('bakeStatus').textContent.includes('Baking')", timeout=60000)
            record["bake_status_text_on_the_page"] = page.locator("#bakeStatus").inner_text()
            record["bake_responses"] = seen
            page.wait_for_timeout(800)
            page.screenshot(path=str(out / "old_dressing_after.png"))
            page.goto(base + "/static/avatar_foundry.html")
            page.wait_for_timeout(1500)
            page.screenshot(path=str(out / "old_foundry_after.png"))
            try:                                         # what Studio draws for this user afterwards
                page.goto(base + "/walk", wait_until="load")
                page.wait_for_function("document.documentElement.dataset.ready === '1'", timeout=45000)
                page.wait_for_timeout(3000)
                page.screenshot(path=str(out / "old_studio_after.png"))
                record["studio_screenshot"] = "old_studio_after.png"
            except Exception as exc:                     # recorded, not hidden
                record["studio_screenshot"] = f"not captured: {type(exc).__name__}: {str(exc)[:200]}"
            browser.close()
        record["api_avatars_me"] = c.get("/api/avatars/me", headers=auth).json()
        # the same call the page makes, with the picture and the token, to keep the full payload
        with open(picture, "rb") as fh:
            rr = c.post("/api/avatars/me/bake", headers=auth, files={"file": (picture.name, fh, "image/png")})
        record["bake_api_status"] = rr.status_code
        record["bake_api_body"] = rr.json() if rr.headers.get("content-type", "").startswith("application/json") else rr.text[:500]
    finally:
        c.close()
        proc.terminate()
        try:
            proc.wait(20)
        except subprocess.TimeoutExpired:
            proc.kill()
        log.close()
    (out / "old_workflow_record.json").write_text(json.dumps(record, indent=1), encoding="utf-8")
    print(json.dumps(record, indent=1)[:3000])
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    sys.exit(main(Path(sys.argv[1]), Path(sys.argv[2])))
