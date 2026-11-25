"""Local read-only reference comparator.

The active target does not silently update its own reference. This module
creates and checks local manifests without executing or repairing the target.
A locally recomputable digest is not independent authentication.
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .models import utc_now
from .recorder import verify_session
from .schema import canonical_json

DEFAULT_IGNORES = {
    ".git", ".pytest_cache", "__pycache__", ".mypy_cache", ".ruff_cache",
    "node_modules", ".venv", "venv",
}


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _iter_files(root: Path, ignores: set[str]) -> Iterable[Path]:
    for current, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in ignores)
        base = Path(current)
        for filename in sorted(files):
            path = base / filename
            if path.name in {".DS_Store"}:
                continue
            if path.is_symlink():
                continue
            yield path


def capture_manifest(root: Path | str, *, ignores: Iterable[str] = DEFAULT_IGNORES) -> dict[str, Any]:
    root = Path(root).expanduser().resolve()
    ignored = set(ignores)
    entries = []
    for path in _iter_files(root, ignored):
        relative = path.relative_to(root).as_posix()
        entries.append({"relative_path": relative, "size": path.stat().st_size, "sha256": _sha256_file(path)})
    manifest_digest = hashlib.sha256(canonical_json({"entries": entries})).hexdigest()
    return {
        "schema_version": 1,
        "root_label": root.name,
        "captured_at": utc_now(),
        "entries": entries,
        "entry_count": len(entries),
        "manifest_digest": manifest_digest,
        "target_executed": False,
    }


@dataclass(slots=True)
class IntegritySentinel:
    """Local comparator for human-commissioned reference manifests."""

    authority_id: str = "sentinel:local-reference-comparator"

    def commission_reference(
        self,
        target_root: Path | str,
        manifest_path: Path | str,
        *,
        actor_id: str,
        human_authorized: bool,
        label: str = "Golden Build",
    ) -> Path:
        if not human_authorized or not actor_id.startswith("human:"):
            raise PermissionError("commissioning a trusted reference requires verified human authorization")
        manifest = capture_manifest(target_root)
        manifest.update(
            {
                "reference_label": label,
                "commissioned_by": actor_id,
                "commissioned_by_authority": self.authority_id,
                "active_target_self_certified": False,
                "automatic_update_allowed": False,
                "independently_authenticated": False,
                "authentication_scope": "local_consistency_only",
            }
        )
        unsigned = dict(manifest)
        manifest["sentinel_digest"] = hashlib.sha256(canonical_json(unsigned)).hexdigest()
        path = Path(manifest_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            raise FileExistsError("reference manifest already exists; silent overwrite is forbidden")
        path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
        return path

    def verify_target(self, target_root: Path | str, manifest_path: Path | str) -> dict[str, Any]:
        reference = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
        supplied_digest = reference.pop("sentinel_digest", None)
        digest_ok = supplied_digest == hashlib.sha256(canonical_json(reference)).hexdigest()
        current = capture_manifest(target_root)
        ref_map = {item["relative_path"]: item for item in reference.get("entries", [])}
        cur_map = {item["relative_path"]: item for item in current.get("entries", [])}
        added = sorted(set(cur_map) - set(ref_map))
        missing = sorted(set(ref_map) - set(cur_map))
        changed = sorted(
            path for path in set(ref_map) & set(cur_map)
            if ref_map[path].get("sha256") != cur_map[path].get("sha256") or ref_map[path].get("size") != cur_map[path].get("size")
        )
        return {
            "ok": digest_ok and not added and not missing and not changed,
            "reference_digest_valid": digest_ok,
            "reference_label": reference.get("reference_label"),
            "added": added,
            "missing": missing,
            "changed": changed,
            "counts": {"added": len(added), "missing": len(missing), "changed": len(changed)},
            "checked_at": utc_now(),
            "target_executed": False,
            "repair_attempted": False,
            "active_target_self_certified": False,
            "independently_authenticated": False,
            "authentication_scope": "local_consistency_only",
            "separate_control_proven": False,
        }

    def verify_blackbox(self, session_dir: Path | str) -> dict[str, Any]:
        result = verify_session(session_dir).to_dict()
        result.update(
            {
                "verified_by": self.authority_id,
                "read_only": True,
                "active_recorder_self_certified": False,
                "independently_authenticated": False,
                "authentication_scope": "local_consistency_only",
                "separate_control_proven": False,
            }
        )
        return result
