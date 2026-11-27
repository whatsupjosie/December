# PubCast AI — avatar_likeness/matte.py
# Copyright © 2024–2026 Josie Curtsey Cobbley (Joshua Cobbley)
# Rearview Foresight LLC — All Rights Reserved
# Feic Mo Chroí — See My Heart
"""Optional illustration matting through a local ONNX network (anime-seg ``isnetis.onnx``, Apache-2.0).

Why it exists: the classical cut-out in ``intake`` separates a figure from a plain background by colour. It works for
the white-background T-pose sheets and fails on a dark picture (Humphrey's hat band, hair, trousers and shoes are
nearly the colour of his backdrop). A segmentation network does not depend on that colour gap.

Rules this module keeps:
- Never downloads anything. The model file must already be on disk; ``locate`` looks in the places below and
  returns ``None`` when it is not there, so the pipeline falls back to the classical cut-out and says so.
- ``onnxruntime`` is imported only when a matte is actually requested.
- Runs on CPU. One 1024 px pass takes about three seconds on a laptop-class CPU.

Where ``locate`` looks, in order: the ``path`` argument, the ``PUBCAST_AVATAR_MATTE_ONNX`` environment variable,
``<data_dir>/models/avatar/isnetis.onnx`` when a data directory is given.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Callable, Optional

import numpy as np

from . import deps

ENV_VAR = "PUBCAST_AVATAR_MATTE_ONNX"
MODEL_FILE = "isnetis.onnx"
SIDE = 1024


def locate(path: Optional[os.PathLike] = None, data_dir: Optional[os.PathLike] = None) -> Optional[Path]:
    """Return the model file if one is present, else ``None``. Never fetches."""
    candidates = []
    if path:
        candidates.append(Path(path))
    if os.environ.get(ENV_VAR):
        candidates.append(Path(os.environ[ENV_VAR]))
    if data_dir:
        candidates.append(Path(data_dir) / "models" / "avatar" / MODEL_FILE)
    for p in candidates:
        if p.is_file() and p.stat().st_size > 1_000_000:
            return p
    return None


class IsnetMatte:
    """Callable ``rgb uint8 HxWx3 -> alpha float32 HxW`` (0..1) backed by an ONNX session."""

    def __init__(self, model_path: os.PathLike):
        ort = deps.require("onnxruntime")
        self.path = Path(model_path)
        self._session = ort.InferenceSession(str(self.path), providers=["CPUExecutionProvider"])
        self._input = self._session.get_inputs()[0].name

    def __call__(self, rgb: np.ndarray) -> np.ndarray:
        cv2 = deps.require("cv2", "opencv-python-headless")
        h, w = rgb.shape[:2]
        if h >= w:
            nh, nw = SIDE, max(1, round(SIDE * w / h))
        else:
            nw, nh = SIDE, max(1, round(SIDE * h / w))
        small = cv2.resize(rgb, (nw, nh), interpolation=cv2.INTER_AREA)
        ph, pw = SIDE - nh, SIDE - nw
        canvas = np.zeros((SIDE, SIDE, 3), np.float32)
        canvas[ph // 2: ph // 2 + nh, pw // 2: pw // 2 + nw] = small / 255.0
        out = self._session.run(None, {self._input: canvas.transpose(2, 0, 1)[None]})[0][0, 0]
        out = out[ph // 2: ph // 2 + nh, pw // 2: pw // 2 + nw]
        return cv2.resize(out, (w, h), interpolation=cv2.INTER_LINEAR).astype(np.float32)


def load(path: Optional[os.PathLike] = None, data_dir: Optional[os.PathLike] = None) -> Optional[Callable[[np.ndarray], np.ndarray]]:
    """The matte callable, or ``None`` when the model or onnxruntime is not available."""
    model = locate(path, data_dir)
    if model is None or deps.optional("onnxruntime") is None:
        return None
    return IsnetMatte(model)
