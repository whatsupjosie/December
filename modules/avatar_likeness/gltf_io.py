# PubCast AI — avatar_likeness/gltf_io.py
# Copyright © 2024–2026 Josie Curtsey Cobbley (Joshua Cobbley)
# Rearview Foresight LLC — All Rights Reserved
# Feic Mo Chroí — See My Heart
"""Write and read the avatar as one binary glTF 2.0 file, with the recipe that built it embedded.

The file is an ordinary skinned avatar: a skeleton with the canonical joint names, one mesh with positions, normals,
UVs and four-bone skin weights, one texture atlas, and Idle/Walk animations. Anything that opens glTF opens it. The
recipe (``asset.extras.pubcast_likeness``) is what makes it editable after export: it holds the landmarks, the
per-part depth multipliers, the back-view choice, the height and the warnings, so a re-import can rebuild the avatar
with the person's edits instead of treating the file as a dead mesh. The atlas inside the file is the source of truth
for the artwork, so repainting the texture in another program survives a rebuild.

No third-party glTF library is used; the format is small and this keeps the offline install light.
"""
from __future__ import annotations

import io
import json
import struct
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from . import deps
from .motion import Clip
from .skeleton import BONES, NAMES

_MAGIC, _JSON, _BIN = 0x46546C67, 0x4E4F534A, 0x004E4942
RECIPE_KEY = "pubcast_likeness"
FLOAT, USHORT, UINT = 5126, 5123, 5125
ARRAY, ELEMENT = 34962, 34963


def _vertex_normals(pos: np.ndarray, faces: np.ndarray) -> np.ndarray:
    p0, p1, p2 = pos[faces[:, 0]], pos[faces[:, 1]], pos[faces[:, 2]]
    fn = np.cross(p1 - p0, p2 - p0)
    n = np.zeros_like(pos, dtype=np.float64)
    for k in range(3):
        np.add.at(n, faces[:, k], fn)
    ln = np.linalg.norm(n, axis=1, keepdims=True)
    n = np.where(ln > 1e-12, n / np.maximum(ln, 1e-12), np.array([0.0, 0.0, 1.0]))
    return n.astype(np.float32)


class _Buf:
    def __init__(self) -> None:
        self.data = bytearray()
        self.views: List[Dict[str, Any]] = []
        self.accessors: List[Dict[str, Any]] = []

    def view(self, raw: bytes, target: Optional[int] = None) -> int:
        while len(self.data) % 4:
            self.data.append(0)
        v = {"buffer": 0, "byteOffset": len(self.data), "byteLength": len(raw)}
        if target:
            v["target"] = target
        self.data += raw
        self.views.append(v)
        return len(self.views) - 1

    def accessor(self, arr: np.ndarray, ctype: int, kind: str, target: Optional[int] = None, minmax: bool = False) -> int:
        a = np.ascontiguousarray(arr)
        acc: Dict[str, Any] = {"bufferView": self.view(a.tobytes(), target), "componentType": ctype, "count": int(a.shape[0]), "type": kind}
        if minmax:
            acc["min"], acc["max"] = a.min(axis=0).astype(float).tolist(), a.max(axis=0).astype(float).tolist()
        self.accessors.append(acc)
        return len(self.accessors) - 1


def _png(rgba: np.ndarray) -> bytes:
    Image = deps.require("PIL.Image", "Pillow")
    out = io.BytesIO()
    Image.fromarray(rgba, "RGBA").save(out, "PNG", optimize=True)
    return out.getvalue()


def write_glb(pos: np.ndarray, uv: np.ndarray, faces: np.ndarray, joints: np.ndarray, weights: np.ndarray,
              local: Dict[str, np.ndarray], ibm: np.ndarray, atlas_rgba: np.ndarray, clips: List[Clip],
              recipe: Dict[str, Any], name: str = "avatar", unlit: bool = True) -> bytes:
    b = _Buf()
    normals = _vertex_normals(pos, faces)
    attrs = {"POSITION": b.accessor(pos.astype(np.float32), FLOAT, "VEC3", ARRAY, minmax=True),
             "NORMAL": b.accessor(normals, FLOAT, "VEC3", ARRAY),
             "TEXCOORD_0": b.accessor(uv.astype(np.float32), FLOAT, "VEC2", ARRAY),
             "JOINTS_0": b.accessor(joints.astype(np.uint16), USHORT, "VEC4", ARRAY),
             "WEIGHTS_0": b.accessor(weights.astype(np.float32), FLOAT, "VEC4", ARRAY)}
    big = int(faces.max()) > 65534
    idx = b.accessor(faces.reshape(-1).astype(np.uint32 if big else np.uint16), UINT if big else USHORT, "SCALAR", ELEMENT)
    # glTF stores matrices column-major; ``ibm`` is row-major here
    ibm_acc = b.accessor(np.transpose(ibm, (0, 2, 1)).astype(np.float32).reshape(len(NAMES), 16), FLOAT, "MAT4")
    img_view = b.view(_png(atlas_rgba))

    index = {n: i for i, n in enumerate(NAMES)}
    nodes: List[Dict[str, Any]] = []
    for n, parent in BONES:
        node: Dict[str, Any] = {"name": n, "translation": [float(v) for v in local[n]]}
        kids = [index[c] for c, p in BONES if p == n]
        if kids:
            node["children"] = kids
        nodes.append(node)
    mesh_node = len(nodes)
    nodes.append({"name": f"{name}_body", "mesh": 0, "skin": 0})

    material: Dict[str, Any] = {"name": "artwork", "doubleSided": True, "alphaMode": "MASK", "alphaCutoff": 0.5,
                                "pbrMetallicRoughness": {"baseColorTexture": {"index": 0}, "metallicFactor": 0.0, "roughnessFactor": 1.0}}
    extensions_used: List[str] = []
    if unlit:
        material["extensions"] = {"KHR_materials_unlit": {}}
        extensions_used.append("KHR_materials_unlit")

    animations: List[Dict[str, Any]] = []
    for clip in clips:
        t_acc = b.accessor(clip.times.astype(np.float32), FLOAT, "SCALAR", minmax=True)
        samplers, channels = [], []
        for joint, q in clip.rotations.items():
            samplers.append({"input": t_acc, "output": b.accessor(q.astype(np.float32), FLOAT, "VEC4"), "interpolation": "LINEAR"})
            channels.append({"sampler": len(samplers) - 1, "target": {"node": index[joint], "path": "rotation"}})
        for joint, tr in clip.translations.items():
            samplers.append({"input": t_acc, "output": b.accessor(tr.astype(np.float32), FLOAT, "VEC3"), "interpolation": "LINEAR"})
            channels.append({"sampler": len(samplers) - 1, "target": {"node": index[joint], "path": "translation"}})
        animations.append({"name": clip.name, "samplers": samplers, "channels": channels})

    doc: Dict[str, Any] = {
        "asset": {"version": "2.0", "generator": "PubCast avatar_likeness", "extras": {RECIPE_KEY: recipe}},
        "scene": 0, "scenes": [{"name": name, "nodes": [0, mesh_node]}], "nodes": nodes,
        "meshes": [{"name": f"{name}_mesh", "primitives": [{"attributes": attrs, "indices": idx, "material": 0, "mode": 4}]}],
        "skins": [{"name": f"{name}_skin", "joints": list(range(len(NAMES))), "skeleton": 0, "inverseBindMatrices": ibm_acc}],
        "materials": [material],
        "textures": [{"source": 0, "sampler": 0}],
        "samplers": [{"magFilter": 9729, "minFilter": 9987, "wrapS": 33071, "wrapT": 33071}],
        "images": [{"name": "atlas", "mimeType": "image/png", "bufferView": img_view}],
        "accessors": b.accessors, "bufferViews": b.views, "buffers": [{"byteLength": len(b.data)}],
    }
    if animations:
        doc["animations"] = animations
    if extensions_used:
        doc["extensionsUsed"] = extensions_used
    js = json.dumps(doc, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    js += b" " * (-len(js) % 4)
    binb = bytes(b.data) + b"\0" * (-len(b.data) % 4)
    total = 12 + 8 + len(js) + 8 + len(binb)
    return struct.pack("<III", _MAGIC, 2, total) + struct.pack("<II", len(js), _JSON) + js + struct.pack("<II", len(binb), _BIN) + binb


def read_glb(data: bytes) -> Tuple[Dict[str, Any], bytes]:
    if len(data) < 20:
        raise ValueError("file is too small to be a GLB")
    magic, version, length = struct.unpack_from("<III", data, 0)
    if magic != _MAGIC or version != 2:
        raise ValueError("not a glTF 2.0 binary")
    off, doc, binb = 12, None, b""
    while off + 8 <= min(len(data), length):
        clen, ctype = struct.unpack_from("<II", data, off)
        chunk = data[off + 8: off + 8 + clen]
        if ctype == _JSON:
            doc = json.loads(chunk.decode("utf-8"))
        elif ctype == _BIN:
            binb = bytes(chunk)
        off += 8 + clen
    if doc is None:
        raise ValueError("GLB has no JSON chunk")
    return doc, binb


def read_recipe(data: bytes) -> Optional[Dict[str, Any]]:
    doc, _ = read_glb(data)
    r = doc.get("asset", {}).get("extras", {}).get(RECIPE_KEY)
    return r if isinstance(r, dict) else None


def _accessor_array(doc: Dict[str, Any], binb: bytes, i: int) -> np.ndarray:
    acc = doc["accessors"][i]
    view = doc["bufferViews"][acc["bufferView"]]
    dtype = {FLOAT: np.float32, USHORT: np.uint16, UINT: np.uint32, 5121: np.uint8}[acc["componentType"]]
    width = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}[acc["type"]]
    start = view.get("byteOffset", 0) + acc.get("byteOffset", 0)
    arr = np.frombuffer(binb, dtype=dtype, count=acc["count"] * width, offset=start)
    return arr.reshape(acc["count"], width) if width > 1 else arr


def read_atlas(data: bytes) -> np.ndarray:
    """The texture atlas inside a GLB as RGBA uint8. This is the artwork as it is now, including any repainting."""
    Image = deps.require("PIL.Image", "Pillow")
    doc, binb = read_glb(data)
    img = doc["images"][0]
    view = doc["bufferViews"][img["bufferView"]]
    raw = binb[view.get("byteOffset", 0): view.get("byteOffset", 0) + view["byteLength"]]
    return np.asarray(Image.open(io.BytesIO(raw)).convert("RGBA")).copy()


def read_mesh(data: bytes) -> Dict[str, np.ndarray]:
    """Positions, UVs, faces, joints and weights of the first primitive, for analysis and for comparing round trips."""
    doc, binb = read_glb(data)
    prim = doc["meshes"][0]["primitives"][0]
    a = prim["attributes"]
    out = {k: _accessor_array(doc, binb, a[k]) for k in ("POSITION", "TEXCOORD_0", "JOINTS_0", "WEIGHTS_0") if k in a}
    out["indices"] = _accessor_array(doc, binb, prim["indices"]).reshape(-1, 3)
    return out


def read_skeleton(data: bytes) -> Dict[str, Any]:
    """Joint names, parents and rest translations from the skin, plus clip names and durations."""
    doc, binb = read_glb(data)
    skin = doc["skins"][0]
    nodes = doc["nodes"]
    parent: Dict[int, int] = {}
    for i, n in enumerate(nodes):
        for c in n.get("children", []):
            parent[c] = i
    joints = {nodes[j]["name"]: {"parent": nodes[parent[j]]["name"] if j in parent else None, "translation": nodes[j].get("translation", [0, 0, 0])}
              for j in skin["joints"]}
    clips = {}
    for an in doc.get("animations", []):
        dur = 0.0
        for s in an["samplers"]:
            t = _accessor_array(doc, binb, s["input"])
            dur = max(dur, float(t.max()))
        clips[an["name"]] = dur
    return {"joints": joints, "clips": clips}
