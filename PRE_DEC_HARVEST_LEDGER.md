# pre-dec branch harvesting ledger

Snapshot: 2026-11-25 Pacific. Source repository whatsupjosie/pre-dec; baseline main 538a40fb2d6efb540347036e3c36605729b57ebf. All 41 branch refs, 40 distinct tips. Read-only donor inventory: no donor changes. Ahead counts are relative to donor main; file counts are GitHub compare output, capped at 300, and — indicates not recorded in this summary. They are not counts of missing files in December. Initial dispositions reflect branch comparisons, existing archive/parts documentation and selected destination inspection. Only cartridge context was newly transferred in this pass; recording was checked against Main Assembly. Other rows are a review queue, not claims of finished audit.

## Operating rule
Inspect one branch at a time at its pinned SHA, identify unique useful changes, reconcile against current target; harvest exact sources and tests into parts-assembly; test and repair; install into main-assembly only when proven, write handoff and archive in same session. No wholesale merging of unrelated histories; keep stable main untouched. Do not label donor test results as fresh December test results.

## Branch inventory

| Branch | Exact tip | Ahead | Changed paths | Initial disposition | Next action / evidence |
|---|---|---:|---:|---|---|
| `2i-beta-polish` | `df737caaeff206e4128932532663776af74ec0e8` | 5 | 6 | RECONCILE | Diverged, 322 behind. Three unique conflicting code commits; reported suite passed at donor tip; reconcile only unique UX fixes. |
| `claude/avatar-live-camera-2026-11-21` | `d11a1ff1921a0cb0adc19a30feda4b62b3f5383e` | 6 | 21 | PRESENT, VERIFY | Main Assembly has live avatar camera page and tests; compare remaining source blobs and browser motion. |
| `claude/bring-in-donor-finds-2026-11-23` | `c812e22387140fd095a70827526d15ba06cda02c` | 1 | 178 | DONOR INVENTORY | Additive recovery folder, not directly installable; evaluate Jeremy Cricket and PEQ variants individually. |
| `claude/camera-fixes-2026-11-21` | `4ad7c0da3f0015d9f6e7deb96bd05577db1d817e` | 5 | 13 | ARCHIVED | Archive camera-fixes lists install e98e3e28; verify current regression. |
| `claude/clean-shape-embed-2026-11-25` | `bb5b3253b8829018039dd3b122da79dbf11b4549` | 189 | 300+ | RECONCILE | Large aggregate; identify final typography/garbled characters fix and any unique embed changes against current assembly. |
| `claude/code-collector-2026-11-24` | `c403fe6814c98b675191305915f0d537023963b2` | 10 | — | SEPARATE PROGRAM | December code-collector branch seeded; compare code, exclude node_modules and moved-out unrelated material; run Electron and extension tests. |
| `claude/eq-foundations-2026-11-23` | `5ef002fcd959779e6c45ce28b3a9128142d0e8ae` | 106 | 300+ | ALEX REVIEW | EQ work assigned to alex branch; separate tested foundations from unbuilt design proposals. |
| `claude/find-what-we-made-2026-11-25` | `b02994cb4514ad11a46797828772fda356586659` | 3 | 10 | RECOVERY REVIEW | Camera v2, VDI, Word workspace and renderer findings; first two already listed in parts; inspect Word workspace. |
| `claude/handoff-cricket-2026-11-23` | `a531ff5e791214bb8ac847f58d289b43bfc93e49` | 3 | 1 | DESIGN ONLY | One handoff file; latest correction says private Cricket line not built; do not treat notes as implementation. |
| `claude/integrate-strongest-parts-2026-11-24` | `ec7895a3c08cde769d2d3997c8bc8fe3d042e637` | 219 | 300+ | HIGH PRIORITY DELTA | Aggregate with later unchecked-join preservation fix. Compare against current Main Assembly; no wholesale merge. |
| `claude/liars-dice-bar-2026-11-24` | `736273ea05f078ad38661b5c3dc616b82f66c0c5` | 1 | 13 | ARCHIVED | Archive liars-dice lists install 2547e26. |
| `claude/live-sources-2026-11-22` | `f1d634e0ae4b75812e6b8b4101b804cdd5ce8bb2` | 8 | 30 | ARCHIVED | Archive live-sources lists install 2d0edaa1; verify real devices. |
| `claude/purfluous-ai-wiring-2026-11-24` | `a9cdde5c1425d6139565c33e9f86c14bc779a068` | 2 | 8 | IN PARTS | Part deliberately withdrawn from Main Assembly; keep canon and paced interruptions; compare current patches. |
| `claude/purfluous-canon-2026-11-24` | `390a88ace3dcb5069efa5cf48b470b8d194ca1ae` | 3 | 9 | IN PARTS | Owner canon decisions; reconcile in character collection. |
| `claude/purfluous-character-salvage-2026-11-24` | `1d30d88afdf4d1ab4c09983c9de0e9fcdd1e208c` | 1 | 1 | IN PARTS | Salvage proposal, not a finished runtime. |
| `claude/purfluous-cue-cards-2026-11-24` | `f762b3ebb5085b7e3800bc4900708ae4d864ab0a` | 8 | 14 | IN PARTS | Card catalog and Pete interruptions; compare staged revisions. |
| `claude/purfluous-more-cards-2026-11-24` | `a959a35ec81406a49e6e76f500559c2bc5c82732` | 21 | 61 | IN PARTS | Diagnostics and cards, previously withdrawn installs; no reinstallation without acceptance. |
| `claude/purfluous-room-read-2026-11-25` | `7139118ac49a65c5bac7ab6948248fd00a9ed6ab` | 22 | 64 | IN PARTS / VERIFY DELTA | Latest room-reading addition; verify whether last commit is fully preserved. |
| `claude/recording-e2e-2026-11-21` | `eddd8f52d69089b931fbb9619f2e40210d283bd1` | 7 | 23 | PRESENT, VERIFY | Compared five-file delta to avatar parent; Main Assembly has encoder aliases, startup errors, stop reports, request size guard, E2E tests and identical handoff. Original 21 pass, two inherited browser failures, real devices untested; review anonymous VOD and studio action stop. |
| `claude/rediscovery-early-repos-2026-11-23` | `a1b40630605b8d483683883458c7754cd12647cd` | 3 | 300+ | DONOR INVENTORY | Additive recovery manifest; select components individually. |
| `claude/renderer-crates-vendored-2026-11-24` | `151ce1dd76c6060307cef53af0b9370ae5435c5f` | 99 | 300+ | IN PARTS | Vendor crates listed; build and validate Rust offline before installing. |
| `claude/studio-assembly-2026-11-23` | `2541c0936155f1ff6158d3cf816e6b208c5caabe` | 98 | 300+ | HIGH PRIORITY DELTA | Studio assembly/recording clocks and modes; compare at subsystem level. |
| `claude/studio-line-missing-fixes-2026-11-24` | `a4fafd1cf611cc1c77aad38c013c35a4f5e5ed35` | 109 | 300+ | HIGH PRIORITY DELTA | Pause in every mode and missing fixes; review current route authority, test. |
| `claude/studio-wire-avatars-2026-11-23` | `45de912aadd6e087c32d62f4887e47d90276a430` | 100 | 300+ | HIGH PRIORITY DELTA | Avatar wiring and browser-verified show clocks; compare current actual paths. |
| `codex/live-production` | `17b29beaf9f2ef0d10bf6e20c7231feef8f8200d` | 1 | 3 | RECONCILE | Startup sequencing and Control Room asset routing; check against newer branch. |
| `codex/main-debug-20261119` | `d3b9db81fc4a35d05db82de1d0de24dacf17e973` | 25 | 46 | RECONCILE | Diverged, 322 behind; clean landing branch has most fixes. Do not replace recording architecture. |
| `codex/pubpartner-connector-baseline` | `2963fd048bfc62eebaa7025a731e2f1873290d10` | 9 | 24 | IN PARTS | Withdrawn from assembly until connector SDK and browser verification. |
| `codex/restore-director-dock` | `f66f28551305355cc8aedc71e6ed520941802359` | 2 | 6 | IN PARTS | Withdrawn until actual browser exercise. |
| `codex/restore-mini-console` | `59675d6f9ff89fe5e7b81c1da0f54e555418d54d` | 3 | 9 | IN PARTS | Withdrawn until wired inside Pub World and browser-tested. |
| `codex/studio-integration` | `0d4d042c8aa243265f3b236b3098a94dbd36959e` | 23 | 108 | HIGH PRIORITY DELTA | Closed Airlock admission, owner-issued temporary passes, paging host staff; inspect current enforcement separately from October airlock. |
| `codex/2i-typewriter-visual-2026-11-17` | `69e155031c2974c63a5360d400762428524d4884` | 2 | 2 | RECONCILE | Diverged, 156 behind; preserve offline artwork fix without replacing interactive console. |
| `console-touch-typewriter-keys` | `3ee394a7ca66edd5e152eb0eca4de1709333bd7c` | 9 | 16 | LIKELY SUPERSEDED | Old convergence report says exact port; verify current implementation and tests. |
| `feat/pubpartner-cartridge-context-2026-11-22` | `7b8c7eaf63b21b56c24b04b24f3b47e7578a6613` | 5 | 5 | HARVESTED THIS PASS | Five exact donor blobs saved at patches/pubpartner-cartridge-context; commit 8c9abe75. Three files missing from both target branches; core/app diverged, merge carefully. Not installed. |
| `gpt/pubpartner-portable-2i-2026-11-22` | `a692d5b2e8f02eb07aecd298dc855ca46889e5bb` | 28 | — | HIGH PRIORITY DELTA | Portable 2i navigation and local chat, later airlock/Waiting Room; check independent PubPartner and Main Assembly separately. |
| `integration/main-debug-land-clean-2026-11-20` | `b282b2ba33f7226d5933ac28cf4e88ca2e041c91` | 28 | 44 | RECONCILE | Clean land except two production25d files; inspect missing fixes and evidence. |
| `integration/main-debug-union-trial-2026-11-20` | `eacde8753402447e3454b07622fb2fcec8dd17e7` | 26 | 43 | TRIAL ONLY | Diverged, two behind; unresolved production25d architecture. Same tip as exact recovery alias. |
| `integration/2i-camera-repairs-2026-11-20` | `8ddfd312a59020630f90cc5fc28436fbaabfeee4` | 4 | 4 | RECONCILE | Auto-switch and config persistence; camera archive may supersede, verify. |
| `integration/2i-unified-2026-11-20` | `c514284da2f31929827e42fa7ca194dafa0d6594` | 15 | 35 | ARCHIVED | Archive 2i-unified lists install 89012cf7; latest branch has Chromium and sustained tone evidence. |
| `main` | `538a40fb2d6efb540347036e3c36605729b57ebf` | 0 | 0 | BASELINE | December main imported this tip and adds workflow documentation. |
| `recovery/beyond-october-studio-exact-2026-11-22` | `eacde8753402447e3454b07622fb2fcec8dd17e7` | 26 | 43 | ALIAS | Same SHA as integration/main-debug-union-trial; inspect once, retain both names. |
| `recovery/control-room-beyond-october-2026-11-22` | `5f053144e4223b0b897523e8cdf5f57a2166b569` | 38 | 162 | RECONCILE | Recovered complete UI files and slate/voxel implementations; select needed features without restoring old UI wholesale. |

## Next acceptance priorities
1. Cartridge continuity: reconcile into current PubPartner; actual authenticated provider and browser privacy/restart tests. Source snapshots are exact blobs, not replacement instructions.
2. Recording: close unresolved browser failures, studio action stop report, device/source tests and 30-minute endurance. Verify authorization before exposing recordings; preserve deliberate public gallery semantics if required.
3. Studio missing fixes / strongest parts: pause all modes, preserve uncheckable joins, clocks, camera registry, Program/Preview, stems and exact recovery files.
4. Airlock: verify closed admission and session-only owner passes against current production routes. Do not switch old unmounted Airlock on blindly.
5. Continue remaining rows, recording file-by-file outcome, tests and commit for each. No completion claim until all rows are individually reconciled.

Local environment cannot resolve github.com; fresh runtime/browser tests were not run in this pass. Source/API reads and Git object writes used the connected GitHub service.
