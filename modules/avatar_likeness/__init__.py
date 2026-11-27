# PubCast AI — avatar_likeness
# Copyright © 2024–2026 Josie Curtsey Cobbley (Joshua Cobbley)
# Rearview Foresight LLC — All Rights Reserved
# Feic Mo Chroí — See My Heart
"""Single-image, likeness-preserving, rigged avatars.

Pipeline: intake -> landmarks -> parts -> shape -> texture -> rig -> motion -> glTF (with the recipe embedded).
Importing this package is cheap and needs only numpy; the heavy stages import Pillow/SciPy/OpenCV on demand
through ``deps`` so a host without them still starts and reports the gap by name.
"""
from . import deps  # noqa: F401

__all__ = ["deps"]
