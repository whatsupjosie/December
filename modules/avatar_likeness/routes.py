"""HTTP routes for the picture-to-avatar builder, mounted by main.py next to the avatar import routes.

The flow the page static/avatar_from_picture.html drives:

1. POST   /api/avatars/likeness/drafts?name=&height_in=      body: the picture (png, jpeg or webp)  -> a draft, version 1
2. POST   /api/avatars/likeness/drafts/{id}/edit             body: JSON edits (joints, depth, back view, hair, height...) -> next version
3. POST   /api/avatars/likeness/drafts/{id}/mocap            recorded motion retargeted onto this avatar -> next version
4. POST   /api/avatars/likeness/drafts/{id}/select?version=  go back to an earlier version (nothing is deleted)
5. POST   /api/avatars/likeness/drafts/{id}/save?name=&height_in=   put the current version in the avatar library
   (modules/avatar_imports.AvatarImportStore, which re-measures the height and the feet before it accepts the file)

A draft is a folder under <data>/avatars/likeness_drafts/<id>/ holding the original picture, every version as its own GLB,
and a manifest. Each write goes to a temporary file and is renamed into place, and a build that fails leaves the draft as
it was. Drafts are runtime data: nothing here deletes them behind the person's back; DELETE is an explicit request.
Builds run one at a time on a worker thread so a long build never blocks the host's event loop.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, Response

from modules.route_security import current_identity

from . import deps, gltf_io, intake, landmarks, matte, pipeline, retarget, shape, texture

logger = logging.getLogger("pubcast.avatar_likeness")

_ID = re.compile(r"^[a-f0-9]{16}$")
MAX_IMAGE_BYTES = 25 * 1024 * 1024
MAX_SOURCE_GLB_BYTES = 50 * 1024 * 1024
MAX_VERSIONS = 100
MAX_DRAFTS_PER_OWNER = 50
INCH_M = 0.0254
IMAGE_TYPES = ("image/png", "image/jpeg", "image/webp", "application/octet-stream")
#: the bundled recorded clips (Mixamo's mannequin) that any avatar can be put through without supplying a recording
BUNDLED_MOTION = Path(__file__).resolve().parents[2] / "static" / "world" / "test_avatars" / "Xbot.glb"
#: pairs of joints the page draws as the stick figure over the picture
LINKS = [["head_top", "chin"], ["chin", "neck"], ["neck", "shoulder_L"], ["neck", "shoulder_R"], ["shoulder_L", "elbow_L"], ["elbow_L", "wrist_L"],
         ["wrist_L", "hand_tip_L"], ["shoulder_R", "elbow_R"], ["elbow_R", "wrist_R"], ["wrist_R", "hand_tip_R"], ["neck", "pelvis"],
         ["pelvis", "hip_L"], ["pelvis", "hip_R"], ["hip_L", "knee_L"], ["knee_L", "ankle_L"], ["ankle_L", "toe_L"],
         ["hip_R", "knee_R"], ["knee_R", "ankle_R"], ["ankle_R", "toe_R"]]


class DraftError(ValueError):
    """A request the draft store cannot honour, worded for the person."""


def _owner(identity: Dict[str, Any]) -> str:
    return str(identity.get("user_id") or identity.get("sub") or "local")


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix="." + path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


class DraftStore:
    """Versioned drafts on disk. Every public method takes the lock; files are replaced atomically."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()

    def _dir(self, draft_id: str) -> Path:
        if not _ID.match(draft_id):
            raise DraftError("that is not a draft id")
        return self.root / draft_id

    def manifest(self, draft_id: str) -> Dict[str, Any]:
        path = self._dir(draft_id) / "manifest.json"
        if not path.is_file():
            raise KeyError(draft_id)
        return json.loads(path.read_text(encoding="utf-8"))

    def _put_manifest(self, m: Dict[str, Any]) -> None:
        _atomic_write(self._dir(m["id"]) / "manifest.json", json.dumps(m, indent=1, sort_keys=True).encode("utf-8"))

    def glb(self, draft_id: str, version: Optional[int] = None) -> bytes:
        m = self.manifest(draft_id)
        n = int(m["current"] if version is None else version)
        if n not in [v["n"] for v in m["versions"]]:
            raise KeyError(f"{draft_id} version {n}")
        return (self._dir(draft_id) / f"v{n}.glb").read_bytes()

    def source(self, draft_id: str) -> Path:
        m = self.manifest(draft_id)
        return self._dir(draft_id) / m["source"]["file"]

    def owned_by(self, owner: str) -> List[Dict[str, Any]]:
        out = []
        for d in sorted(self.root.iterdir()) if self.root.is_dir() else []:
            try:
                m = self.manifest(d.name)
            except (KeyError, DraftError, ValueError, OSError):
                continue
            if m.get("owner") == owner:
                out.append(m)
        return sorted(out, key=lambda m: m.get("updated", 0), reverse=True)

    def create(self, owner: str, name: str, image: bytes, source_name: str, glb: bytes, note: str) -> Dict[str, Any]:
        with self.lock:
            if len(self.owned_by(owner)) >= MAX_DRAFTS_PER_OWNER:
                raise DraftError(f"you already have {MAX_DRAFTS_PER_OWNER} drafts. Save the ones you want to the library and delete the ones you don't, then start another.")
            draft_id = uuid.uuid4().hex[:16]
            d = self._dir(draft_id)
            ext = ".png" if image[:8] == b"\x89PNG\r\n\x1a\n" else ".webp" if image[8:12] == b"WEBP" else ".jpg"
            _atomic_write(d / f"source{ext}", image)
            _atomic_write(d / "v1.glb", glb)
            now = time.time()
            m = {"id": draft_id, "owner": owner, "name": name, "created": now, "updated": now, "current": 1,
                 "source": {"file": f"source{ext}", "name": source_name, "bytes": len(image), "sha256": hashlib.sha256(image).hexdigest()},
                 "versions": [{"n": 1, "at": now, "note": note, "sha256": pipeline.fingerprint(glb), "bytes": len(glb)}]}
            self._put_manifest(m)
            return m

    def add_version(self, draft_id: str, glb: bytes, note: str) -> Dict[str, Any]:
        """Write the next version. The new file lands first; the manifest points at it only once both are on disk."""
        with self.lock:
            m = self.manifest(draft_id)
            if len(m["versions"]) >= MAX_VERSIONS:
                raise DraftError(f"this draft already has {MAX_VERSIONS} versions. Save it to the library and start a new draft from it.")
            n = max(v["n"] for v in m["versions"]) + 1
            path = self._dir(draft_id) / f"v{n}.glb"
            _atomic_write(path, glb)
            now = time.time()
            m["versions"].append({"n": n, "at": now, "note": note, "sha256": pipeline.fingerprint(glb), "bytes": len(glb)})
            m["current"], m["updated"] = n, now
            try:
                self._put_manifest(m)
            except BaseException:
                try:
                    path.unlink()
                except OSError:
                    pass
                raise
            return m

    def select(self, draft_id: str, version: int) -> Dict[str, Any]:
        with self.lock:
            m = self.manifest(draft_id)
            if version not in [v["n"] for v in m["versions"]]:
                raise DraftError(f"this draft has no version {version}")
            m["current"], m["updated"] = version, time.time()
            self._put_manifest(m)
            return m

    def remove(self, draft_id: str) -> None:
        with self.lock:
            d = self._dir(draft_id)
            if not (d / "manifest.json").is_file():
                raise KeyError(draft_id)
            for f in sorted(d.iterdir()):
                f.unlink()
            d.rmdir()


def _hex_to_rgb(value: Any) -> Optional[List[int]]:
    if value in (None, "", False):
        return None
    m = re.fullmatch(r"#?([0-9a-fA-F]{6})", str(value).strip())
    if not m:
        raise intake.IntakeError("hair colour must be six hex digits such as #3a2417")
    h = m.group(1)
    return [int(h[i:i + 2], 16) for i in (0, 2, 4)]


def _edits_from_json(body: Dict[str, Any]) -> Dict[str, Any]:
    """The page's words for settings turned into pipeline.Settings fields; anything unknown is refused, not ignored."""
    allowed = {"joints", "depth", "back_mode", "hair", "height_in", "build", "name", "floor_y", "pose_hint"}
    unknown = sorted(set(body) - allowed)
    if unknown:
        raise intake.IntakeError("unknown edit: " + ", ".join(unknown))
    edits: Dict[str, Any] = {}
    for key in ("joints", "depth", "back_mode", "build", "name", "floor_y", "pose_hint"):
        if key in body:
            edits[key] = body[key]
    if "joints" in edits:
        bad = [k for k in edits["joints"] if k not in landmarks.JOINTS]
        if bad:
            raise intake.IntakeError("unknown joint: " + ", ".join(bad))
        for k, v in edits["joints"].items():
            if not (isinstance(v, (list, tuple)) and len(v) == 2 and all(isinstance(x, (int, float)) for x in v)):
                raise intake.IntakeError(f"joint {k} needs [x, y] in picture pixels")
    if "hair" in body:
        edits["hair_rgb"] = _hex_to_rgb(body["hair"])
    if "height_in" in body:
        try:
            edits["height_m"] = float(body["height_in"]) * INCH_M
        except (TypeError, ValueError):
            raise intake.IntakeError("height_in must be a number of inches") from None
    return edits


def create_avatar_likeness_router(data_dir: Path, import_store: Any) -> APIRouter:
    data_dir = Path(data_dir)
    drafts = DraftStore(data_dir / "avatars" / "likeness_drafts")
    router = APIRouter(prefix="/api/avatars/likeness", tags=["avatar-likeness"])
    router.drafts = drafts  # type: ignore[attr-defined]
    gate = asyncio.Semaphore(1)

    def models() -> Dict[str, Any]:
        mp = matte.locate(None, data_dir)
        pp = landmarks.locate_pose_model(None, data_dir)
        return {"cutout_network": bool(mp), "pose_detector": bool(pp)}

    async def work(fn: Callable[..., Any], *a: Any, **kw: Any) -> Any:
        """Run a build off the event loop, one at a time, and turn its failures into plain-worded HTTP errors."""
        async with gate:
            try:
                return await asyncio.to_thread(lambda: fn(*a, **kw))
            except intake.IntakeError as exc:
                raise HTTPException(422, str(exc)) from None
            except deps.MissingDependency as exc:
                raise HTTPException(503, str(exc)) from None
            except DraftError as exc:
                raise HTTPException(409, str(exc)) from None
            except KeyError as exc:
                raise HTTPException(404, f"not found: {exc}") from None
            except Exception as exc:                     # a bug, not the person's fault: say so and keep the traceback in the log
                logger.exception("avatar likeness build failed")
                raise HTTPException(500, f"the builder failed ({type(exc).__name__}: {exc}). The draft was not changed.") from None

    def mine(draft_id: str, identity: Dict[str, Any]) -> Dict[str, Any]:
        try:
            m = drafts.manifest(draft_id)
        except DraftError:
            raise HTTPException(400, "invalid draft id") from None
        except KeyError:
            raise HTTPException(404, "draft not found") from None
        from modules.auth import role_gte
        if m["owner"] != _owner(identity) and not role_gte(identity.get("role", "guest"), "mod"):
            raise HTTPException(403, "this draft belongs to someone else")
        return m

    def describe(m: Dict[str, Any], glb: Optional[bytes] = None) -> Dict[str, Any]:
        glb = glb if glb is not None else drafts.glb(m["id"])
        recipe = gltf_io.read_recipe(glb) or {}
        sk = gltf_io.read_skeleton(glb)
        base = f"/api/avatars/likeness/drafts/{m['id']}"
        return {"ok": True, "id": m["id"], "name": m["name"], "version": m["current"],
                "versions": [{"n": v["n"], "at": v["at"], "note": v["note"], "bytes": v["bytes"]} for v in m["versions"]],
                "settings": recipe.get("settings"), "landmarks": recipe.get("landmarks"), "links": LINKS, "joints": list(landmarks.JOINTS),
                "crop": recipe.get("crop"), "working_size": (recipe.get("intake") or {}).get("working_size"), "report": recipe.get("report"),
                "clips": sk["clips"], "recorded_clips": recipe.get("recorded_clips", []), "bytes": len(glb),
                "urls": {"glb": f"{base}/model.glb?version={m['current']}", "picture": f"{base}/picture.png?version={m['current']}", "source": f"{base}/source"}}

    @router.get("/status")
    async def status():
        """What this host can do right now. Missing optional files are listed, never downloaded."""
        d = deps.status()
        clips: List[str] = []
        if BUNDLED_MOTION.is_file():
            try:
                clips = sorted(retarget.SourceRig(BUNDLED_MOTION.read_bytes()).clips)
            except Exception:
                logger.exception("bundled motion file could not be read")
        return {"ok": True, "ready": d["ready"], "missing_packages": d["missing"], "install": d["install"], "models": models(),
                "pub_block_m": pipeline.PUB_BLOCK_M, "builds": sorted(landmarks.BUILDS),
                "back_modes": list(texture.BACK_MODES), "depth_parts": sorted(shape.DEFAULT_DEPTH), "depth_defaults": dict(shape.DEFAULT_DEPTH),
                "bundled_motion": clips, "not_in_the_picture": list(pipeline.UNSEEN),
                "model_help": "Optional models are placed by hand and never downloaded by the host: PUBCAST_AVATAR_MATTE_ONNX (cut-out network) and PUBCAST_AVATAR_POSE_TASK (pose detector)."}

    @router.get("/drafts")
    async def list_drafts(identity: Dict[str, Any] = Depends(current_identity)):
        return {"ok": True, "drafts": [{"id": m["id"], "name": m["name"], "version": m["current"], "updated": m["updated"]} for m in drafts.owned_by(_owner(identity))]}

    @router.post("/drafts", status_code=201)
    async def create_draft(request: Request, identity: Dict[str, Any] = Depends(current_identity)):
        q = request.query_params
        name = (q.get("name") or "").strip()
        if not name:
            raise HTTPException(400, "name is required")
        try:
            height_in = float(q.get("height_in", ""))
        except ValueError:
            raise HTTPException(400, "height_in (the character's height in inches) is required") from None
        if request.headers.get("content-type", "").split(";")[0].strip().lower() not in IMAGE_TYPES:
            raise HTTPException(415, "send the picture as image/png, image/jpeg or image/webp")
        image = await request.body()
        if not image:
            raise HTTPException(400, "the picture was empty")
        if len(image) > MAX_IMAGE_BYTES:
            raise HTTPException(413, f"the picture is over {MAX_IMAGE_BYTES // (1024 * 1024)} MB")
        try:
            hair = _hex_to_rgb(q.get("hair"))
        except intake.IntakeError as exc:
            raise HTTPException(422, str(exc)) from None
        settings = pipeline.Settings(name=name, height_m=height_in * INCH_M, build=q.get("build") or None, pose_hint=q.get("pose_hint") or None,
                                     back_mode=q.get("back_mode") or "plain", hair_rgb=tuple(hair) if hair else None)

        def go():
            built = pipeline.build(image, settings, data_dir=str(data_dir), prefer_matte=q.get("prefer_matte") == "1")
            m = drafts.create(_owner(identity), name, image, q.get("source_name", ""), built.glb, "first build")
            return describe(m, built.glb)
        return await work(go)

    @router.get("/drafts/{draft_id}")
    async def get_draft(draft_id: str, identity: Dict[str, Any] = Depends(current_identity)):
        m = mine(draft_id, identity)
        return describe(m)

    @router.get("/drafts/{draft_id}/model.glb")
    async def draft_glb(draft_id: str, version: Optional[int] = None, identity: Dict[str, Any] = Depends(current_identity)):
        mine(draft_id, identity)
        try:
            data = drafts.glb(draft_id, version)
        except KeyError:
            raise HTTPException(404, "no such version") from None
        return Response(data, media_type="model/gltf-binary", headers={"Cache-Control": "no-store"})

    @router.get("/drafts/{draft_id}/source")
    async def draft_source(draft_id: str, identity: Dict[str, Any] = Depends(current_identity)):
        """The picture exactly as it was uploaded."""
        mine(draft_id, identity)
        return FileResponse(drafts.source(draft_id), headers={"Cache-Control": "no-store"})

    @router.get("/drafts/{draft_id}/picture.png")
    async def draft_picture(draft_id: str, version: Optional[int] = None, identity: Dict[str, Any] = Depends(current_identity)):
        """The cut-out at the size joint positions are measured in, so the page can draw joints straight onto it."""
        mine(draft_id, identity)
        try:
            glb = drafts.glb(draft_id, version)
        except KeyError:
            raise HTTPException(404, "no such version") from None

        def go() -> bytes:
            import io
            import numpy as np
            from PIL import Image
            recipe = gltf_io.read_recipe(glb)
            front, _ = texture.split_atlas(gltf_io.read_atlas(glb))
            x0, y0, w, h = recipe["crop"]
            wh = recipe["intake"]["working_size"]
            canvas = np.zeros((wh[1], wh[0], 4), np.uint8)
            canvas[y0:y0 + h, x0:x0 + w] = front
            buf = io.BytesIO()
            Image.fromarray(canvas, "RGBA").save(buf, "PNG")
            return buf.getvalue()
        return Response(await work(go), media_type="image/png", headers={"Cache-Control": "no-store"})

    @router.post("/drafts/{draft_id}/edit")
    async def edit_draft(draft_id: str, request: Request, identity: Dict[str, Any] = Depends(current_identity)):
        m = mine(draft_id, identity)
        try:
            body = await request.json()
        except ValueError:
            raise HTTPException(400, "send the edits as JSON") from None
        if not isinstance(body, dict) or not body:
            raise HTTPException(400, "send at least one edit")

        def go():
            edits = _edits_from_json(body)
            built = pipeline.rebuild(drafts.glb(draft_id), edits, data_dir=str(data_dir))
            note = "edit: " + ", ".join(sorted(body))
            return describe(drafts.add_version(draft_id, built.glb, note), built.glb)
        return await work(go)

    @router.post("/drafts/{draft_id}/select")
    async def select_version(draft_id: str, version: int, identity: Dict[str, Any] = Depends(current_identity)):
        mine(draft_id, identity)
        try:
            return describe(drafts.select(draft_id, version))
        except DraftError as exc:
            raise HTTPException(404, str(exc)) from None

    @router.post("/drafts/{draft_id}/mocap")
    async def add_mocap(draft_id: str, request: Request, source: str = "bundled", clip: str = "", identity: Dict[str, Any] = Depends(current_identity)):
        """Retarget a recorded clip onto this avatar. ``source=bundled`` uses the mannequin recordings shipped with PubCast;
        otherwise send a Mixamo-skeleton GLB as the body. Leave ``clip`` empty to take every clip in the source."""
        mine(draft_id, identity)
        if source == "bundled":
            if not BUNDLED_MOTION.is_file():
                raise HTTPException(404, "the bundled mannequin recordings are not in this install")
            data = BUNDLED_MOTION.read_bytes()
        else:
            data = await request.body()
            if not data:
                raise HTTPException(400, "send the recorded clips as a GLB body, or use source=bundled")
            if len(data) > MAX_SOURCE_GLB_BYTES:
                raise HTTPException(413, f"the recording is over {MAX_SOURCE_GLB_BYTES // (1024 * 1024)} MB")

        def go():
            src = retarget.SourceRig(data)
            names = [clip] if clip else sorted(src.clips)
            missing = [n for n in names if n not in src.clips]
            if missing:
                raise intake.IntakeError(f"the recording has no clip called {missing[0]}; it has: {', '.join(sorted(src.clips)) or 'none'}")
            built = pipeline.rebuild(drafts.glb(draft_id), None, data_dir=str(data_dir))
            new = [retarget.retarget_clip(src, n, built.rigged.rest, built.rigged.local, name="Mocap_" + re.sub(r"[^A-Za-z0-9_]+", "_", n)) for n in names]
            built = pipeline.attach_clips(built, new)
            return describe(drafts.add_version(draft_id, built.glb, "recorded motion: " + ", ".join(names)), built.glb)
        return await work(go)

    @router.post("/drafts/{draft_id}/save", status_code=201)
    async def save_to_library(draft_id: str, request: Request, identity: Dict[str, Any] = Depends(current_identity)):
        """Put the current version in the avatar library. The library measures the file itself and may refuse it."""
        m = mine(draft_id, identity)
        q = request.query_params
        name = (q.get("name") or m["name"]).strip()
        glb = drafts.glb(draft_id)
        settings = (gltf_io.read_recipe(glb) or {}).get("settings") or {}
        try:
            height_in = float(q.get("height_in") or (settings.get("height_m", 0) / INCH_M))
        except ValueError:
            raise HTTPException(400, "height_in must be a number of inches") from None
        try:
            entry = import_store.add(glb, name=name, height_in=height_in, owner=_owner(identity), source_format="glb",
                                     source_name=f"{m['name']}-v{m['current']}.glb", character_id=q.get("character_id", ""))
        except Exception as exc:                          # GLBError from the store is a ValueError subclass with its own plain wording
            if type(exc).__name__ == "GLBError":
                raise HTTPException(422, str(exc)) from None
            raise
        return {"ok": True, "avatar": entry}

    @router.delete("/drafts/{draft_id}")
    async def delete_draft(draft_id: str, identity: Dict[str, Any] = Depends(current_identity)):
        mine(draft_id, identity)
        drafts.remove(draft_id)
        return {"ok": True}

    return router


__all__ = ["create_avatar_likeness_router", "DraftStore", "DraftError", "LINKS"]
