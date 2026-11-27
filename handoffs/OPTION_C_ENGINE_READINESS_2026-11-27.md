# Option C engine readiness (Main Camera Only)

Base 1c23312b1219220b25d390427102382254b39c63. Candidate branch, not merged. No changes to character, Airlock, EQ, or user data.

Recording: distinguish FFmpeg video frame counts from A/V duration; reject a cold-cut timeout with zero encoded video frames even if process lives. Positive encoder counters are not independent decoded pixel or switch provenance evidence. Existing preview arm path, synthetic source exclusion, dissolve fidelity and final file validation require further work.

Bridge: honor explicitly chosen renderer port in child environment, without depending on new binary CLI. Expose motion protocol acknowledgement separately from pixel proof. Preserve existing binary.

Distributed workers: replace fabricated output with explicit unsupported errors and advertise no media capabilities until real workers exist. This intentionally changes the placeholder contract; verify consumers before landing.

Architecture: retain browser Three.js/2.5D for first accepted production; native renderer modular behind RenderFrame(show_state,camera,time,quality) and a media sink. CameraManager and Program audio remain canonical. No second authority. Main Camera Only must preserve continuous Program pixels/audio across cuts/dissolves; idle cameras hold data and confidence preview only. Verify source revision, decoded pixels, continuity, stems, reopen/export, data replay, and 30-minute endurance. Rust wgpu is not a prerequisite. No runtime tests or full acceptance performed in repository at authoring.
