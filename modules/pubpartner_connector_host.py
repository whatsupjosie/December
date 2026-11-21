"""Owner-operated, fixed-target MCP launcher for a running Reach host."""
import asyncio
import io
import json
import tempfile
import zipfile

import yaml
from importlib.util import find_spec
import os
from pathlib import Path
import shutil
import sys


class ConnectorHost:
    def __init__(self, data_dir):
        self.selected = Path(data_dir) / "secure" / "connector" / "selected.zip"
        self.tunnel_record = self.selected.with_name("workspace-tunnel.json")
        self.process = None
        self.route = None
        self.lock = asyncio.Lock()

    def source(self):
        if self.selected.is_file():
            return self.selected
        configured = os.getenv("PUBPARTNER_CONNECTOR_CARTRIDGE")
        return Path(configured) if configured else None

    async def select(self, payload):
        from pubpartner.schema import Identity, VoiceProfile
        async with self.lock:
            if self.status()["running"]:
                raise ValueError("Stop the running connector before selecting another cartridge.")
            with zipfile.ZipFile(io.BytesIO(payload)) as archive:
                files = [f for f in archive.infolist() if not f.is_dir()]
                if len(files) > 128 or sum(f.file_size for f in files) > 16 * 1024 * 1024:
                    raise ValueError("Choose a cartridge up to 16 MiB unpacked.")
                parents = {Path(f.filename).parent for f in files}
                if (len(parents) != 1 or any(".." in f.filename or "\\" in f.filename or f.filename.startswith("/")
                                             for f in files) or len({f.filename for f in files}) != len(files)):
                    raise ValueError("Choose a cartridge with one folder of files.")
                folder = parents.pop()
                if len(folder.parts) > 1:
                    raise ValueError("Choose a cartridge with at most one outer folder.")
                Identity.from_dict(yaml.safe_load(archive.read((folder / "character.yaml").as_posix())))
                VoiceProfile.from_dict(yaml.safe_load(archive.read((folder / "voice_profile.yaml").as_posix())))
                if archive.testzip():
                    raise ValueError("Cartridge integrity check failed.")
            self.selected.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=self.selected.parent, delete=False) as tmp:
                tmp.write(payload)
            try:
                os.replace(tmp.name, self.selected)
            finally:
                Path(tmp.name).unlink(missing_ok=True)
            return self.status()

    def tunnel_id(self):
        configured = os.getenv("CONTROL_PLANE_TUNNEL_ID")
        if configured:
            return configured
        if self.tunnel_record.is_file():
            record = json.loads(self.tunnel_record.read_text())
            if record.get("workspace") == os.getenv("PUBPARTNER_OPENAI_WORKSPACE_ID"):
                return record.get("id")
        return None

    async def create_tunnel(self):
        # Reserve creation before the external call. A lost response must not
        # create a second workspace resource when the owner retries.
        workspace = os.environ["PUBPARTNER_OPENAI_WORKSPACE_ID"]
        self.tunnel_record.parent.mkdir(parents=True, exist_ok=True)
        try:
            with self.tunnel_record.open("x") as handle:
                json.dump({"workspace": workspace}, handle)
        except FileExistsError:
            raise ValueError("Check the workspace tunnel list and set CONTROL_PLANE_TUNNEL_ID to resume.") from None
        proc = await asyncio.create_subprocess_exec(
            shutil.which("tunnel-client"), "admin", "tunnels", "create", "--name", "PubPartner",
            "--description", "Owner-selected PubPartner cartridge", "--workspace-id", workspace, "--json",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
        output, _ = await proc.communicate()
        if proc.returncode:
            raise ValueError("Creation was not confirmed. Check the workspace tunnel list before retrying.")
        tunnel_id = json.loads(output).get("id")
        if not isinstance(tunnel_id, str) or not tunnel_id:
            raise ValueError("Check the workspace tunnel list for the new tunnel ID.")
        with tempfile.NamedTemporaryFile(mode="w", dir=self.tunnel_record.parent, delete=False) as tmp:
            json.dump({"workspace": workspace, "id": tunnel_id}, tmp)
        os.replace(tmp.name, self.tunnel_record)
        return tunnel_id

    def status(self):
        source = self.source()
        return {
            "cartridge_configured": bool(source and Path(source).exists()),
            "sdk_installed": find_spec("mcp") is not None,
            "tunnel_installed": bool(shutil.which("tunnel-client")),
            "can_create_tunnel": bool(not self.tunnel_record.exists() and os.getenv("OPENAI_ADMIN_KEY")
                                     and os.getenv("PUBPARTNER_OPENAI_WORKSPACE_ID")
                                     and (os.getenv("CONTROL_PLANE_API_KEY") or os.getenv("OPENAI_API_KEY"))),
            "tunnel_id": self.tunnel_id(),
            "tunnel_configured": bool(self.tunnel_id() and
                                      (os.getenv("CONTROL_PLANE_API_KEY") or os.getenv("OPENAI_API_KEY"))),
            "running": self.process is not None and self.process.returncode is None,
            "route": self.route,
            "exit_code": self.process.returncode if self.process else None,
        }

    async def start(self, route, create=False):
        async with self.lock:
            status = self.status()
            if status["running"]:
                if self.route == route:
                    return status
                raise ValueError("Stop the current connector before switching routes.")
            if not status["sdk_installed"] or not status["cartridge_configured"]:
                raise ValueError("Configure the host cartridge and install the connector SDK.")
            source = self.source().resolve()
            if route == "http":
                command = [sys.executable, "-m", "pubpartner.connector", str(source), "--transport", "http"]
            elif route == "openai-tunnel":
                from pubpartner.connector import tunnel_command
                tunnel_id = self.tunnel_id()
                if not tunnel_id and create and status["tunnel_installed"] and status["can_create_tunnel"]:
                    tunnel_id = await self.create_tunnel()
                command = tunnel_command(source, tunnel_id)
            else:
                raise ValueError("Unknown connector route")
            self.process = await asyncio.create_subprocess_exec(*command, stdin=asyncio.subprocess.DEVNULL)
            self.route = route
            return self.status()

    async def stop(self):
        async with self.lock:
            if self.process and self.process.returncode is None:
                self.process.terminate()
                try:
                    await asyncio.wait_for(self.process.wait(), 8)
                except asyncio.TimeoutError:
                    self.process.kill()
                    await self.process.wait()
            self.process = None
            self.route = None
            return self.status()
