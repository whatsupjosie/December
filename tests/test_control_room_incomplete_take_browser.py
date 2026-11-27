"""Control Room names incomplete camera captures and retains the evidence on reload.

The HTTP recording service is isolated here. The served Control Room, recording
adapter, confirmation dialog, session tracker, session storage, and UI are real.
"""
from __future__ import annotations

import functools
import json
import os
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

pw = pytest.importorskip("playwright.sync_api")
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def origin():
    class QuietHandler(SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass

    handler = functools.partial(QuietHandler, directory=str(ROOT))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()


def test_control_room_names_partial_take_before_and_after_reload(origin):
    with pw.sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE") or None
        )
        context = browser.new_context(viewport={"width": 1440, "height": 1000})
        context.add_init_script("""sessionStorage.setItem('pubcast_user',
          JSON.stringify({username:'director',user_id:'director',role:'owner'}));
          sessionStorage.setItem('pubcast_token','test-token');""")
        state = {"sessions": {}, "start_errors": [], "stop_reports": []}
        camera = {"id": "cam_main", "name": "Main camera", "transport": "local"}

        def route_handler(route):
            request = route.request
            path = request.url.split("?", 1)[0][len(origin):]
            if not path.startswith("/api/") and path != "/health":
                return route.continue_()
            body = request.post_data_json if request.method == "POST" and request.post_data else {}
            if path == "/api/switcher/state":
                data = {"program": "cam_main", "preview": "cam_main", "sources": [camera]}
            elif path == "/api/recording/preflight":
                data = {"ready": True, "ok": True, "issues": [], "warnings": [],
                        "sources": body.get("sources", [])}
            elif path == "/api/recording/sessions":
                data = list(state["sessions"].values())
            elif path == "/api/studio/actions/recording.start":
                assert body.get("confirm") is True
                sid = body["session_id"]
                row = {"session_id": sid, "operator": "director", "state": "active",
                       "sources": body["sources"], "mode": body["mode"],
                       # The real recording service commits startup failures into
                       # session metadata, which is the authority after reload.
                       "capture_errors": list(state["start_errors"])}
                state["sessions"][sid] = row
                data = {"ok": True, "result": row}
            elif path == "/api/studio/actions/recording.stop":
                assert body.get("confirm") is True
                row = state["sessions"][body["session_id"]]
                row["state"] = "stopped"
                data = {"ok": True, "result": {**row, "capture_report": state["stop_reports"]}}
            elif path == "/api/state/production":
                data = {"blackout": False, "preview_bars": False,
                        "panic_seq": 0, "blackout_seq": 0}
            elif path == "/api/timeline/status":
                data = {"state": "idle", "elapsed": 0, "timeline_name": None, "duration": None}
            elif path == "/api/timeline/list":
                data = {"timelines": []}
            elif path == "/api/program-audio/status":
                data = {"ok": True, "status": {"buses": {}, "master_volume": 1}}
            elif path in {"/api/studio/actions", "/api/recordings", "/api/recording/storage"}:
                data = {"actions": []} if path.endswith("actions") else []
            else:
                data = {"ok": True}
            route.fulfill(status=200, content_type="application/json", body=json.dumps(data))

        context.route(origin + "/**", route_handler)
        page = context.new_page()
        page_errors = []
        page.on("pageerror", lambda error: page_errors.append(str(error)))
        page.goto(origin + "/static/control_room.html", wait_until="domcontentloaded")
        page.wait_for_function("typeof sessionTracker !== 'undefined' && CAMS.some(c=>c.sourceId==='cam_main')")

        state["start_errors"] = [{"source_id": "cam_main", "error": "device busy", "phase": "start"}]
        page.locator("#tRec").click()
        page.locator("[data-confirm-ok]").click()
        page.wait_for_function("sessionTracker.view().state === 'active' && !sessionTracker.view().busy")
        assert page.locator("#srRec").inner_text() == "CAPTURE ERROR: cam_main"
        assert page.locator("#rec-status-badge").inner_text() == "ACTIVE"
        assert page.locator("#rec-status-badge").evaluate("element => element.style.background") == "rgb(157, 48, 47)"

        sid = page.evaluate("sessionTracker.view().id")
        page.reload(wait_until="domcontentloaded")
        page.wait_for_function("id => typeof sessionTracker !== 'undefined' && sessionTracker.view().id === id && sessionTracker.view().verified", arg=sid)
        assert page.locator("#srRec").inner_text() == "CAPTURE ERROR: cam_main"

        state["stop_reports"] = [{"source_id": "cam_main", "warnings": []},
                                 {"source_id": "cam_two", "warnings": ["No media written"]}]
        page.locator("#tRec").click()
        page.locator("[data-confirm-ok]").click()
        page.wait_for_function("sessionTracker.view().state === 'stopped' && !sessionTracker.view().busy")
        assert page.locator("#srRec").inner_text() == "CAPTURE ERROR: cam_main, cam_two"
        assert page.evaluate("failedRecordingSources") == ["cam_main", "cam_two"]
        assert page_errors == []
        context.close()
        browser.close()
