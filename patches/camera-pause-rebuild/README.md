# Camera pause rebuild

This is the pause rebuild for the recording studio, kept here as a patch because it is still being built: it has not been tried on Windows yet.

What it does, from its commit message: "Pause really pauses in every take mode." It changes modules/capture.py, modules/production_routes.py, modules/recording_modes.py, the two recording tests and the studio-line handoff.

Where it came from: pre-dec branch `claude/studio-line-missing-fixes-2026-11-24`, commit a4fafd1 (Nov 25). The patch file here is that commit, exported as it is. It was not changed.

Why a patch and not the files: the files it changes belong to main and main-assembly. Copying the changed files in here would put two different versions of capture.py in December. The patch applies cleanly on top of pre-dec's assembly branch (checked with `git apply --check`, nothing applied).

To install it once it has been tried on Windows: on main-assembly, run `git apply patches/camera-pause-rebuild/0001-pause-really-pauses-in-every-take-mode.patch` from a copy of this file, run its two tests, write the handoff, then move this folder to Parts-Live-Archive.
