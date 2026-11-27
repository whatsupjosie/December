# PubCast AI — avatar_likeness/deps.py
# Copyright © 2024–2026 Josie Curtsey Cobbley (Joshua Cobbley)
# Rearview Foresight LLC — All Rights Reserved
# Feic Mo Chroí — See My Heart
"""Optional-dependency gate. The avatar-from-image pipeline needs Pillow, SciPy and OpenCV, none of which the core
PubCast host requires. Nothing is installed on startup (project rule); a missing package is reported by name,
with the exact command, so the Foundry can show it instead of failing silently."""
from __future__ import annotations

import importlib
from typing import Any, Dict, List, Optional

INSTALL_HINT = "python -m pip install -r requirements-avatar.txt"

# import name -> pip name
REQUIRED: Dict[str, str] = {"PIL": "Pillow", "scipy": "scipy", "cv2": "opencv-python-headless"}


class MissingDependency(RuntimeError):
    def __init__(self, module: str, package: str):
        self.module, self.package = module, package
        super().__init__(f"the avatar-from-image pipeline needs '{package}' (import '{module}'); run: {INSTALL_HINT}")


def require(module: str, package: Optional[str] = None) -> Any:
    try:
        return importlib.import_module(module)
    except (ImportError, OSError) as exc:  # native wheels can fail with OSError (missing libGL)
        raise MissingDependency(module, package or module.split(".")[0]) from exc


def optional(module: str) -> Optional[Any]:
    try:
        return importlib.import_module(module)
    except (ImportError, OSError):
        return None


def missing() -> List[str]:
    out = []
    for mod, pkg in REQUIRED.items():
        try:
            importlib.import_module(mod)
        except (ImportError, OSError):
            out.append(pkg)
    return out


def status() -> Dict[str, Any]:
    gone = missing()
    return {"ready": not gone, "missing": gone, "install": INSTALL_HINT if gone else "",
            "optional": {"mediapipe": optional("mediapipe") is not None, "trimesh": optional("trimesh") is not None}}
