# PubCast — Bridge Merge & Avatar Maker
## Full Session Record — March 2026
### For the next Claude to read before touching anything

---

## WHAT THIS DOCUMENT IS

This is a complete record of one session's work across two parallel tracks:

**Track 1:** Merging the best parts of Gemini's Bulletproof Twin Engine Bridge into our
real VoxelBridge engine. The goal is a better, more resilient bridge — not a finished one.
The merge exposed real problems. They are all documented here.

**Track 2:** Building a standalone Avatar Maker using the systems we already have.
The sculptor exists and works. The bake endpoint exists and works. What's missing is
the platform UI that gives the user somewhere to stand while it happens.

These two tracks are INDEPENDENT. The avatar maker does not need the bridge work to be
finished. Read this whole document before writing a line of code.

---

## THE THREE CODEBASES INVOLVED

### 1. Our Real Engine — `modules/bridge.py` (VoxelBridge v1)
**1,010 lines. This is the foundation. Everything real lives here.**

Triple-path transport: Shared Memory → TCP → File System. "Path A, Path B, Path C. One
always works." Full CommandType enum including AVATAR_UPDATE=41. Priority command queue.
Full async background task architecture. All compatibility aliases.

Backed up at: `modules/bridge_v1_backup.py`

### 2. Gemini's Simple Bridge — Pasted in session, not a file in the repo
**~80 lines. The original simpler version.**

Uses /dev/shm/ directly as a flat file with a file-lock. No POSIX shared memory, no ring
buffers, no TCP fallback. CommandType enum has VOXEL_BAKE=1, SKELETON_RIG=2,
LIGHTING_UPDATE=3 — these are Gemini's invented command types, NOT in our real bridge.

### 3. Gemini's Bulletproof Engine — uploaded as `bulletproof_twin_engine_bridge.py`
**1,355 lines. The evolved version with real additions worth studying.**

The file Josie uploaded. This is what Gemini built after combining the simple bridge with
our real engine — or rather, after TRYING to. It has genuine good ideas (circuit breaker,
IRM, camera sequencing, SHM magic check) mixed with phantom dependencies (msgpack not
installed) and invented command types.

---

## ALL GEMINI CODE — VERBATIM

### GEMINI BLOCK 1: Setup Script
**File: `setup_bridge.sh` (not in repo — Gemini's suggestion)**

```bash
#!/bin/bash
# PubCast Environment Hardening
echo "Initiating SHM Hardening..."
sudo mount -o remount,size=2G /dev/shm
touch /dev/shm/pubcast_bridge
touch /dev/shm/pubcast.lock
sudo chmod 777 /dev/shm/pubcast_bridge
sudo chmod 777 /dev/shm/pubcast.lock
echo "Bridge is OPEN and SECURE"
```

**What it does:** Remounts /dev/shm at 2GB, creates flat files for SHM and lock.
**Assessment:** The /dev/shm approach is valid — it's RAM-backed tmpfs on Linux, fast,
no posix_ipc dependency. The 777 permissions are fine for a single-user dev machine,
wrong for production. The 2G resize is a real thing you may need if voxel data is large.
**Keep?** The remount idea is worth noting. The script itself isn't needed if we use
POSIX shared memory (posix_ipc handles its own allocation).

---

### GEMINI BLOCK 2: Config
**File: `config.py` (not in repo — Gemini's suggestion)**

```python
# PubCast Global Settings
MODE = "ORBITAL"  # Options: SURFACE (Low RAM), TRACK (Balanced), ORBITAL (Max)

# Voxel Resolution
RESOLUTION = 128 if MODE == "ORBITAL" else 64

# Hardware Offsets
SHM_PATH = "/dev/shm/pubcast_bridge"
LOCK_PATH = "/dev/shm/pubcast.lock"

# Emotional Settings
NURTURE_THRESHOLD = 0.8
GRIT_SENSITIVITY = 1.2
```

**What it does:** Global config with resolution modes and SHM paths.
**Assessment:** The SURFACE/TRACK/ORBITAL mode names are genuinely good — they're now in
our sculptor and in the dressing room UI. NURTURE_THRESHOLD and GRIT_SENSITIVITY were
intended to feed a personality/emotional system that was never built. The SHM_PATH using
/dev/shm/ flat files differs from our posix_ipc approach.
**Keep?** The mode names yes — already adopted. The rest no.

---

### GEMINI BLOCK 3: Simple Bridge
**File: `modules/bridge.py` (Gemini's simpler version, NOT our current bridge)**

```python
import os
import mmap
import json
import time
import struct
from enum import IntEnum

class CommandType(IntEnum):
    VOXEL_BAKE = 1
    SKELETON_RIG = 2
    LIGHTING_UPDATE = 3

class VoxelBridge:
    def __init__(self, shm_path="/dev/shm/pubcast_bridge", size=157286400):
        self.path = shm_path
        self.lock_path = "/dev/shm/pubcast.lock"
        self.size = size
        self._ensure_file()
        self.file = open(self.path, "r+b")
        self.mm = mmap.mmap(self.file.fileno(), self.size)

    def _ensure_file(self):
        if not os.path.exists(self.path):
            with open(self.path, "wb") as f:
                f.write(b"\0" * self.size)
        os.chmod(self.path, 0o777)

    def _wait_for_engine(self):
        while os.path.exists(self.lock_path):
            time.sleep(0.005)

    def _lock(self):
        open(self.lock_path, 'a').close()

    def _unlock(self):
        if os.path.exists(self.lock_path):
            os.remove(self.lock_path)

    def send_command(self, cmd_type, data, priority=1):
        self._wait_for_engine()
        self._lock()
        try:
            payload = json.dumps(data).encode('utf-8')
            payload_size = len(payload)
            header = struct.pack("III", int(cmd_type), priority, payload_size)
            self.mm.seek(0)
            self.mm.write(header)
            self.mm.write(payload)
            self.mm.flush()
        finally:
            self._unlock()

    def close(self):
        self.mm.close()
        self.file.close()
```

**What it does:** Flat-file mmap IPC with a filesystem lock. Dead simple.
**The phantom command types:** VOXEL_BAKE, SKELETON_RIG, LIGHTING_UPDATE — these DO NOT
exist in our real bridge. When Gemini later wrote the avatar maker code calling these
commands, it was writing against THIS bridge, not ours. That is the root cause of the
mismatch. These command types were never real.
**Assessment:** The flat-file approach actually works and has no external dependencies.
It's slower than POSIX SHM but useful as a standalone fallback mode for the avatar maker
when the full engine isn't running.
**Keep?** The concept yes, for standalone avatar maker fallback. These command types no.

---

### GEMINI BLOCK 4: Simple Sculptor
**File: `modules/sculptor.py` (Gemini's simpler version)**

```python
import numpy as np
import cv2
from scipy.ndimage import binary_erosion

class Sculptor:
    def __init__(self, resolution=128):
        self.res = resolution

    def _sigmoid_norm(self, x):
        return 1 / (1 + np.exp(-10 * (x - 0.5)))

    def _apply_painterly_grit(self, img):
        clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8,8))
        img = clahe.apply(img)
        img = cv2.bilateralFilter(img, 5, 50, 50)
        return img

    def process_to_grit(self, path):
        img = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
        if img is None:
            return None
        h, w = img.shape
        side = min(h, w)
        img = img[(h-side)//2 : (h+side)//2, (w-side)//2 : (w+side)//2]
        img = cv2.resize(img, (self.res, self.res), interpolation=cv2.INTER_LANCZOS4)
        refined = self._apply_painterly_grit(img)
        return self._sigmoid_norm(refined.astype(float) / 255.0)

    def extrude_with_safety(self, grit_map, thickness=1.0):
        z_indices = np.linspace(0, 1, self.res).reshape(self.res, 1, 1)
        full_vol = (z_indices < (grit_map[None, :, :] * thickness)).astype(np.uint8)
        eroded = binary_erosion(full_vol, iterations=2)
        shell = full_vol ^ eroded
        return shell.astype(np.uint8)
```

**What it does:** Grayscale grit map + voxel extrusion. No face detection.
**Assessment:** The math is correct. CLAHE + bilateral filter on grayscale is a valid
pipeline. The sigmoid normalization is real and good — protects midtones. The extrusion
broadcasting (`z_indices < grit_map`) is numpy-efficient, ~5ms at 128res.
The shell culling (XOR with eroded) is correct, saves ~70% memory.
**What it's missing vs our real sculptor:** No MediaPipe face detection, no EXIF rotation,
no skin/hair color sampling, no LAB colorspace processing.
**Keep?** The math — yes, it's already in our real sculptor. This simpler version is useful
as a reference for what the pipeline looks like without MediaPipe.

---

### GEMINI BLOCK 5: Bulletproof Twin Engine Bridge
**File: uploaded as `bulletproof_twin_engine_bridge.py` — 1,355 lines**
**This is the full file Josie uploaded. Key classes:**

**IRMSensor** — rolling FPS + latency window, health score 0-100, status:
excellent/stable/struggling/critical. Real math, real concept. Problem: we don't have
frame timing data to feed it correctly.

**IRMActuator** — adjusts batch size based on health score. +10% when excellent, -40%
when struggling, floor when critical. Real concept. Problem: PubCast doesn't process
in batches — we stream motion data and send discrete commands. Batch size is not a
meaningful knob for our architecture.

**CircuitBreaker** — trips after N failures, OPEN/HALF_OPEN/CLOSED states, recovery
timeout. This is genuinely good and genuinely useful. The implementation uses a
threading.Lock and a `.call(func)` wrapper. Real pattern, real code.

**AtomicSharedMemory** — uses /tmp/ flat files with fcntl locking (POSIX) or msvcrt
(Windows). Requires msgpack (NOT installed). Header format includes magic "PUBC",
version, py_alive, cpp_alive, sequence, timestamp. IRM data section in shared memory.
The magic number check on attach is a real improvement.

**ReliableUDPBridge** — UDP with ACK/retry, exponential backoff, circuit breaker,
backpressure queue. Requires msgpack. Our bridge uses SHM→TCP→File which is more
reliable than UDP for this use case.

**VoxelMeshBaker** — text-to-voxel mesh generation. The `_bake_to_gpu()` method
returns a fake GPU buffer ID string. This is a stub. Not real.

**BulletproofTwinEngineBridge** — the main class. Has per-component IRMSensor,
IRMActuator, circuit breaker, camera sequencing. The IRM background thread is a good
pattern. The `_update_metrics()` uses `np.random.uniform(30, 70)` for GPU usage — that
is a placeholder, not real monitoring.

**Phantom dependency:** `import msgpack` at the top. Not installed. The whole file
fails to import on our system.

**Phantom command types from this file's perspective:** It references VOXEL_BAKE and
SKELETON_RIG from the simple bridge. These don't exist in our real bridge either.

---

## ATTEMPT 1: First Merge (Claude's attempt)

**What I did:** Identified the four genuinely good things in the Bulletproof engine
and grafted them into VoxelBridge v1:
- CircuitBreaker + CircuitBreakerState classes
- IRMSensor + IRMActuator classes
- CameraPosition dataclass with sequence number
- SHM magic number changed from "PUBC" to "PBC2" with version check on attach

**Result:** `modules/bridge.py` — VoxelBridge v2.0, 1,229 lines.
**Backup of original:** `modules/bridge_v1_backup.py`

**Bugs found AFTER writing it:**

**Bug 1 — Circuit breaker success path never reset failure_count.**
The dispatch code hand-rolled failure counting instead of using `CircuitBreaker.call()`.
On success, failure_count was never reset to zero. This meant the threshold was
cumulative lifetime failures, not consecutive failures. A bad minute could permanently
lower how many failures it takes to trip the breaker for the rest of the session.
Fixed by resetting `failure_count = 0` on every successful send.

**Bug 2 — IRM would false-alarm immediately on any healthy system.**
`_update_irm()` ran inside the 10-second health monitor loop and fed that 10-second
interval as a "frame time" to `IRMSensor.record_frame()`. A 10-second delta = 0.1 FPS.
0.1 FPS scores as "critical". "critical" slams batch size to emergency minimum.
This would have triggered on the very first health monitor run, on a perfectly
healthy machine, doing nothing wrong.
Fixed by feeding real FPS from the SHM header (Path A) or estimating from command
latency (Paths B/C) instead of the monitor loop interval.

**Design problems identified AFTER merging (not yet fixed):**

**Problem 1 — One global circuit breaker for three very different paths.**
Path A (SHM): SHM failure means a crash. Should trip fast (3 failures), recover fast
(5 seconds). Path B (TCP): Network path, standard thresholds fine (5 failures, 15s).
Path C (File): Last resort. Should NEVER trip — if it's failing you want to keep trying,
not go silent for 30 seconds. One breaker with one threshold fits none of these.

**Problem 2 — 30-second default recovery timeout is wrong for live production.**
30 seconds of dropped commands during a live stream is a visible on-air failure.
Also too long for development where the C++ engine isn't always running.
Should be configurable at init, shorter by default.

**Problem 3 — IRM batch size doesn't map to PubCast's architecture.**
PubCast streams motion data and sends discrete control commands. There is no batch to
size. The IRM concept is solving a problem we don't have. What we actually need is
automatic path-stepping (A→B→C on failure, B→A on recovery) rather than batch tuning.
The health monitor currently logs warnings and does nothing. It should act.

**Problem 4 — Weak reference callbacks have a silent failure mode.**
`bridge.add_callback(lambda e: print(e))` — the lambda has no other owner. The weak
reference is immediately dead. The callback never fires. No error, no warning. This
will look like the callback system just doesn't work.

**Honest assessment of Attempt 1:**
The circuit breaker and SHM magic check are genuine improvements worth keeping.
The IRM and camera sequencing are good code that's ahead of where the system is —
not harmful, but not earning their keep yet. The bridge is better than v1.
It is not dramatically better. The design problems identified above are real.

---

## WHAT SHOULD BE BUILT NEXT: Bridge v3 Plan

**Strip:** IRMSensor, IRMActuator, CameraPosition sequencing, single global CircuitBreaker.

**Add: Per-path circuit breakers**
```python
self._cb_shm = CircuitBreaker(failure_threshold=3, recovery_timeout=5.0)
self._cb_tcp = CircuitBreaker(failure_threshold=5, recovery_timeout=15.0)
# Path C: no circuit breaker — last resort always tries
```
Both timeouts configurable at __init__.

**Add: PathManager class**
```python
class PathManager:
    def on_path_failure(self, path: BridgeStatus) -> BridgeStatus  # step down A→B→C
    def on_path_recovery(self, path: BridgeStatus) -> BridgeStatus  # step up C→B→A
    def current_path(self) -> BridgeStatus
    # Tracks: step_downs, step_ups, last_step timestamp
```
Step-down: circuit breaker opens → PathManager steps down immediately.
Step-up: health monitor finds current path degraded AND higher path's breaker is CLOSED
→ attempt reconnect → if successful, step up. Checked every 30 seconds.

**Make _check_connection_health actionable:**
- queue_depth > 50 → log
- queue_depth > 200 → drop oldest low-priority commands
- failure_rate > 10% → PathManager.on_path_failure()
- heartbeat stale > 30s → PathManager.on_path_failure()

**Build order:**
1. PathManager class
2. Make CircuitBreaker.call() async-native
3. Rewrite _dispatch_command to use per-path breakers via PathManager
4. Update _check_connection_health to call PathManager
5. Update get_metrics() with path_manager block
6. Strip IRM classes, CameraPosition, global breaker
7. Full test pass

Zero breaking changes to callers. All public methods and aliases unchanged.

---

## TRACK 2: AVATAR MAKER — CURRENT STATE & BUILD PLAN

### What exists RIGHT NOW and actually works:

**`modules/sculptor.py`** — Real photo-to-voxel pipeline.
Full pipeline: load + EXIF fix → center crop → CLAHE (LAB colorspace) → bilateral filter
→ MediaPipe FaceMesh → face crop → skin/hair color sampling → sigmoid grit map →
broadcasting extrusion → binary erosion shell → bridge payload dict.
Timing: ~140ms per part, under 1 second for a full body.
Output: dict with avatar_id, mode, resolution, voxel_count, density, grit_index,
skin_color, hair_color, voxel_data_hex, timestamp.
Sends via: bridge.send_command("AVATAR_UPDATE", result)
Resolution modes: SURFACE=48, TRACK=64, ORBITAL=96

**`POST /api/avatars/me/bake`** in main.py — Real route.
Receives UploadFile, runs Sculptor in thread executor (non-blocking), broadcasts
avatar_baked event via WebSocket, returns preview dict (no hex blob in response).

**`GET /api/avatars/me/bake/status`** — Checks if user has existing baked photo.

**`static/dressing.html / dressing.js / dressing.css`** — Dressing room with bake panel.
Photo upload, drag-and-drop onto mirror, mode selection (Surface/Track/Orbital),
bake button → POST /api/avatars/me/bake, progress spinner, stats display after bake.

**`avatar_foundry_platform.html`** — Standalone sci-fi platform UI (in outputs/).
This is a complete standalone file. It has: animated MoCap skeleton SVG on a glowing
platform stage, perspective grid floor, three-tab panel (BAKE / IDENTITY / RIG),
face slot + body part slots with drag-and-drop, quality selector, Fine Voxel Face toggle,
forge progress bar + log, stats grid. Calls /api/avatars/me/bake. Works offline gracefully.
THIS IS NOT YET INTEGRATED INTO THE DRESSING ROOM.

### What the Avatar Maker needs to be:

A separate platform inside the dressing room — not a panel, not a modal, not a page.
A dedicated zone the user steps into. The current dressing room has:
  - Mirror area (left) — reflection/preview
  - Wardrobe panel (right) — bake controls

The Avatar Foundry should be a THIRD ZONE. A "Step onto Platform" button below the mirror
activates it. The mirror area slides away or fades. The foundry platform appears in its place.
A "Return to Mirror" button exits. Everything on one page, one URL, no navigation.

### Integration task (no new backend needed):

1. Add "Step onto Platform" button below the mirror in dressing.html
2. On click: hide `.mirror-view` div, show `.foundry-view` div
3. `.foundry-view` contains the platform stage, skeleton SVG, bake/identity/rig tabs
   — ported CSS and HTML from `avatar_foundry_platform.html` into dressing
4. The existing bake endpoint (POST /api/avatars/me/bake) is already wired — no new routes
5. "Return to Mirror" button exits foundry view

The JS already exists in avatar_foundry_platform.html. The CSS already exists.
This is a UI integration task, not a feature build.

### Does this need Bridge v3?

NO. The sculptor already sends via AVATAR_UPDATE=41 using the current bridge.
The avatar maker works with the engine as-is. Bridge v3 improves reliability but is
not a dependency. Build the avatar maker integration first.

### Fine Voxel Face:

Face sculpts at 2× resolution (128px when body is 64px). Mesh-baked to a single geometry
piece before mounting to the skeleton. Body parts use standard resolution.
Toggled in the BAKE tab as "Fine Voxel Face" toggle.
The sculptor supports this — it's a resolution parameter on the face crop step.

### What's still missing (not built yet):

- The foundry view integrated into dressing.html (standalone file exists, not wired in)
- CS-1 chibi skeleton rig definition
- Humphrey character (chibi toddler detective, NPR painterly style)
- LipSync module (lipsync.py does not exist in codebase)
- Bake history stored to data/voxels/registry/ (directory not in ensure_dirs)
- Bake history stored to data/memory/ (directory not in ensure_dirs)

---

## FILE REFERENCE

```
modules/
  bridge.py              VoxelBridge v2.0 — current merged engine (1,229 lines)
  bridge_v1_backup.py    VoxelBridge v1.0 — original before merge (1,010 lines)
  sculptor.py            Real photo-to-voxel pipeline with MediaPipe (real, works)
  avatar.py              Preset system: Lumen/Azure/Nova
  avatar_assets.py       GLB manifest loader
  avatar_system.py       Motion capture, swing-twist decomposition

static/
  dressing.html          Dressing room — has bake panel, needs foundry view added
  dressing.js            Bake logic wired to /api/avatars/me/bake
  dressing.css           Dressing room styles including bake-ring animation

outputs/ (session deliverables)
  bridge.py              Same as modules/bridge.py — v2.0 merged engine
  avatar_foundry_platform.html  Standalone foundry UI — needs integration into dressing

Gemini source files (NOT in repo, referenced in this document):
  setup_bridge.sh        /dev/shm hardening script
  config.py              Global config with SURFACE/TRACK/ORBITAL modes
  Simple bridge          ~80 lines, flat-file mmap, phantom command types
  Simple sculptor        ~50 lines, grayscale only, no MediaPipe
  bulletproof_twin_engine_bridge.py  Full upload — 1,355 lines (uploaded by Josie)
```

---

## INSTALLED DEPENDENCIES (confirmed working)

```
numpy       2.4.2   ✓
cv2         4.13.0  ✓
scipy       1.17.0  ✓
mediapipe   0.10.32 ✓
PIL         12.1.1  ✓
psutil              ✓
msgpack             ✗  NOT INSTALLED — bulletproof engine requires this, we do not
posix_ipc           depends on platform — bridge falls through to TCP/File if absent
```

---

## SUMMARY FOR NEXT CLAUDE

Read this whole document. Then:

1. The bridge merge (Attempt 1) is done but imperfect. The current bridge.py works and
   is better than v1. Don't touch it unless you are building v3 per the plan above.

2. The avatar maker integration is the next concrete task. The foundry platform UI exists
   as a standalone file. It needs to be wired into dressing.html as a second view inside
   the mirror area. No new backend. No bridge changes needed.

3. Don't let Gemini's phantom command types (VOXEL_BAKE, SKELETON_RIG) confuse you.
   They never existed in our real bridge. AVATAR_UPDATE=41 is the real command.

4. The two tracks are independent. You can build the avatar maker without touching the
   bridge. You can build bridge v3 without touching the avatar maker. Don't conflate them.

