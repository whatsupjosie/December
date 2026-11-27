# ws_renderer.rs, render-subscriber version (where it came from is unknown)

One Rust source file, parked here Nov 27, 2026 because it was sitting in the project folder at `pubcast/ws_renderer/ws_renderer.rs` (file dated Nov 26, 03:59 UTC), outside any repository.

- Git blob: bde5ff171d68b46ed1b4675c38800a112a387ed1. 1,280 lines.
- **Where it came from is not known.** This exact blob is on no branch of pre-dec, Beyond-October or December (checked Nov 27). No note next to it says who made it or why.
- What it is (READ from its header comment): the receiving end of the live mocap pipeline. Performers send motion frames over WebSocket; it keeps one animator per avatar and publishes render ticks to render subscribers over WebSocket and/or stdout.

## Not a drop-in for main-assembly

December main-assembly's `rust_crate/src/ws_renderer.rs` is blob 46fcc3b6afb165eb1005b25606c532b488840d76 (793 lines), last changed in 75b2e33 on Nov 27 ("Ship rebuilt renderer with launch controls, truthful capacity ACKs and December camera focus"). That version uses `mod camera_control` (December's camera focus). This file has no camera_control at all, so copying it over main-assembly's would drop that. If any of it is wanted, it has to be merged in by hand.

Not compiled or run for this copy.
