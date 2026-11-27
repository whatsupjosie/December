"""Exercise the shipped Linux renderer through the same adapter used by Pete."""
import json
import platform
import secrets
import socket

import pytest
from websockets import connect

from modules.voxel_webrtc_bridge import VoxelWebRTCBridge


@pytest.mark.skipif(
    (platform.system(), platform.machine()) != ("Linux", "x86_64"),
    reason="The packaged ws_renderer executable targets Linux x86_64",
)
@pytest.mark.asyncio
async def test_bridge_selected_port_frame_capacity_and_camera_focus(monkeypatch):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    token = secrets.token_urlsafe()
    monkeypatch.setenv("PUBCAST_WS_PORT", "0")
    monkeypatch.setenv("PUBCAST_MAX_AVATARS", "2")
    monkeypatch.setenv("PUBCAST_CAMERA_CONTROL_TOKEN", token)
    bridge = VoxelWebRTCBridge(port=port)
    try:
        assert await bridge.connect_renderer_websocket()
        motion = bridge._build_probe_payload()["motion_data"]
        assert await bridge.send_motion_frame("performer", motion)
        assert not await bridge.send_motion_frame("over-capacity", motion)
        assert await bridge.send_motion_frame("performer", motion)

        async with connect(f"ws://127.0.0.1:{port}", open_timeout=2) as ws:
            request = dict(protocol="pubcast.camera.control.v1", token=token,
                           request_id="register", action="register", camera_id="preview", revision=1)
            await ws.send(json.dumps(request))
            assert json.loads(await ws.recv())["ok"]
            request.update(request_id="focus", action="update_pose", revision=2, focus=0.2)
            await ws.send(json.dumps(request))
            reply = json.loads(await ws.recv())
            assert not reply["ok"] and "focus" in reply["error"]
            request.update(focus=2.0)
            await ws.send(json.dumps(request))
            reply = json.loads(await ws.recv())
            assert reply["ok"] and reply["frame_path_proven"] is False
    finally:
        await bridge.shutdown()
