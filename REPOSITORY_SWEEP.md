# December source sweep

Baseline assembly 06c69eb, parts 94ef55b, main 38787ec. Current verified installation 205da084542b1f3a0364f4656491a7d3d357bcfb. No repository has reached full accounting yet.

## Repository queue

1. Beyond-October — open, 54 refs pinned below.
2. pre-dec — refresh the 41-ref inventory in PRE_DEC_HARVEST_LEDGER.md when opened.
3. October-24
4. October
5. The-Prime
6. Wednesday-
7. Pubcast-Reach
8. Pub-Partner-Base-Horizon
9. The-Counter-and-2i
10. Pubcaast-Breaking-Dawn
11. 6.0-
12. friday
13. Just-The-Pubcast
14. Storage
15. Pubcast-Phase-2-

Older repository references come from December's AGENTS.md and docs/missions/pubcast-lead-engineer-2026-10-31/SOURCE_RECONCILIATION.md. Extend the queue when donor manifests identify additional repositories. When inspecting each repository check Foresight's UI, renderer and main engines, Bubble Stack, cartridge continuity, studio/admission, Sir Purfluous and offline 2i. Preserve the three recording modes, clocks, and IndexedDB v3 across overlapping changes.

## Beyond-October decisions

| Candidate | Destination and evidence |
|---|---|
| backend-hardening a594d30 | Already installed at 6247ed2. modules/pubpartner_routes.py supplies the archive, backup and calibration routes mounted by main.py and pubpartner_app.py. Backup, guidance, calibration and archive modules match the donor. The current core adds a restored-session audience check. Exercised private archive capture through run_turn, shared-room exclusion, scoped backup/restore verification and calibration approval tests. |
| calibration c677a56 | main-assembly static/pubpartner.html loads static/pubpartner_calibration_ui.js. Chromium opened the served mobile form, saved an answer and explicitly approved it. Current follow-ups use saved answers. Original variants remain in patches/pubpartner-nov22/calibration. |
| cartridge-memory-wiring 3e275aa | main-assembly PubPartnerSpine.build_turn_packet includes ranked SQLite memories in the private FCP1 packet. At 205da08 recall also checks the original cartridge creator before opening memories. Four destination regressions passed including a completed turn with mismatched profile and cartridge ownership. The separate pre-dec identity/voice bridge remains in patches/pubpartner-cartridge-context. |
| existing-wiring 9a75052 | pubpartner_app.py serves the cartridge router and registers avatar imports. Standalone HTTP cartridge list, restored provider connection and private guidance tests passed. Existing calibration patch retained in parts. |
| identity-checkpoint 2e2c1e3 | parts-assembly patches/pubpartner-nov22/identity-checkpoint/SOURCE.patch contains modules/pubpartner_identity_checkpoint.py, the run_turn change and test. December already constructs FCP1 before dispatch. The donor counts verified receipts before awaiting dispatch and appends afterward, so concurrent dispatches can select the same ordinal. Its validator also assumes one prompt serialization. Reconcile scheduling with durable per-session turn ordering and exercise simultaneous and restarted turns across prompt modes before installation. |
| unification-foundation a29149d | Older backup and Blackbox Light code overlaps installed hardening. Current calibration UI asks for the user's own account and adapts the next question. Its authority map and exact original delta remain in patches/pubpartner-nov22/unification-foundation/SOURCE.patch. |
| project work notes 4dc10a4 | modules/pubpartner_work_notes.py and tests/test_pubpartner_work_notes.py match the donor. The core records drafts and reads committed notes. The mounted work-notes routes support save and source verification. All 23 work-note tests passed. |

58 destination tests passed at 06c69eb across backup isolation, Blackbox Light, explicit calibration approval, cartridge memory, existing wiring, calibration, calibration UI, menu browser and work notes. Chromium used the real run_reach.py server. The four cartridge regressions were rerun after the creator check. Provider calls used the deterministic test provider.

## Resume point

Beyond-October, gpt/speech-playback-lifecycle, Pete's synthesized line through the active studio mixer and jaw rig. Compare 6707e7c with December and run the focused browser exercise. The branch inventory below pins sources only. Rows without a disposition above still require behavioral reconciliation.
- `11-12-merge` — `d70952e52c81f89178f4ab557206fcde109bf970`
- `2i-beta-polish` — `df737caaeff206e4128932532663776af74ec0e8`
- `audit/standard-first-2026-11-19` — `6cccfd7a5b2b74f3c29829ed723c0e85128ee322`
- `backup/2i-professional-completion-2026-11-16` — `aaa14b00121c4d0f4369ca9a26021fb18c6f68f3`
- `backup/claude-2i-beta-polish-2026-11-17` — `df737caaeff206e4128932532663776af74ec0e8`
- `backup/claude-console-touch-typewriter-2026-11-17` — `3ee394a7ca66edd5e152eb0eca4de1709333bd7c`
- `backup/fable-2i-beta-polish-2026-11-17` — `cbc529583202628075c4c319482ae011da2a123f`
- `backup/main-before-integration-2026-11-11` — `bfbdcf0676c11163063ef369cd419b5667792cfe`
- `chatgpt-work-2026-11-05` — `1cfb2d2ed96fa9ff183592a1930c9229373e0d79`
- `claude-work` — `f3b8863d819dd3f7f635cd8be0facff5b26bf912`
- `claude-work-2026-11-12` — `5c039e532fa71ab651dbdb83384c266365832329`
- `claude/2i-coalesce-saves-2026-11-18` — `2a5abdb5255d78c9e14b6c937cc25002213f2a22`
- `claude/pubpartner-work-notes-2026-11-19` — `4dc10a4265111f7ea55584b9e0630c031e9c06b7`
- `codex/2i-beta-test-gates-2026-11-17` — `f52125a8229d01c923a7fb28c2caa9d50dcf25dc`
- `codex/2i-claude-console-consolidation-2026-11-17` — `32d142457d041d0f7bba54ab96c16dca908717e3`
- `codex/2i-claude-functional-integration-2026-11-17` — `e0cc000c2adf1a9bad069fe9c650f04e4354fe10`
- `codex/2i-claude-functional-reconcile-2026-11-18` — `1e3b3620bdbb5b118ac74a550d8eacdf11a54930`
- `codex/2i-integration-readiness-2026-11-18` — `ef879b6d3cbb7fb5365a22ddc5ddd31d3b6adb9c`
- `codex/2i-offline-save-2026-11-16` — `45d572194f7dfd52212a5686f935c9f54ed663a9`
- `codex/2i-save-routing-hardening-2026-11-18` — `7e70e0536416490ae42a97208915c70073740973`
- `codex/2i-typewriter-manuscript-bridge-2026-11-18` — `4ca32875bcc58ecefe5b06ce718398457340c32d`
- `codex/2i-typewriter-visual-2026-11-17` — `69e155031c2974c63a5360d400762428524d4884`
- `codex/2i-ui-readability-2026-11-16` — `f47b11b6767bb164ba3fbb4886b893d865ee53b5`
- `codex/github-browser-tests-2026-11-17` — `5965e97801e445154168405ffc3b59ae43a9fff6`
- `codex/main-debug-20261119` — `d3b9db81fc4a35d05db82de1d0de24dacf17e973`
- `codex/recovery-floor-2026-11-01` — `1e33789ba82d231384b04063b1b68325ca94df4c`
- `console-touch-typewriter-keys` — `3ee394a7ca66edd5e152eb0eca4de1709333bd7c`
- `fable/2i-beta-polish-2026-11-16` — `cbc529583202628075c4c319482ae011da2a123f`
- `fable/2i-polish-2026-11-16` — `51a34cafae0a6965e75eebe9001f392463063a0f`
- `fable/integration-2026-11-13` — `764874a74627adf455c97a99bc56597257170282`
- `fix/2i-save-freshness-2026-11-19` — `27b074109fdc9f9c32a16db636353e5083226aa4`
- `gpt-work` — `43e71839bd243b47768256980b376bf90424cd7d`
- `gpt/2i-narrative-intelligence-2026-11-15` — `84d9e27c7e74f1345d6d07401a125b54ca2c82c2`
- `gpt/2i-professional-completion-2026-11-15` — `aaa14b00121c4d0f4369ca9a26021fb18c6f68f3`
- `gpt/clacker-timecode-verification` — `e8d779830256d2a9a325fbecac7546c85167bcd4`
- `gpt/control-ui-wiring-2026-11-08` — `e86d20b970368918448e6008d45f5b690620bba1`
- `gpt/guest-recording-triage-2026-11-13` — `ffd58a84e2a0038e566998b0fe240b0046c6eb26`
- `gpt/live-studio-setup-2026-11-09` — `1cfb2d2ed96fa9ff183592a1930c9229373e0d79`
- `gpt/participant-clock-prototype-2026-11-13` — `466eee8e7c17d48d92f5907e2a0727f60f5070e0`
- `gpt/primp-canvas-preparation-2026-11-07` — `946016ed083da61f1034f94c44cd9e271be32acd`
- `gpt/pubpartner-backend-hardening-2026-11-22` — `a594d3017e12457a84ba0b66506c175cbb6aa5fd`
- `gpt/pubpartner-calibration-2026-11-22` — `c677a564d11c7a0d7ae59c697ad81eb7130ff79b`
- `gpt/pubpartner-cartridge-memory-wiring-2026-11-22` — `3e275aa081f30bf1cfb8d662ae0ae18e873cb779`
- `gpt/pubpartner-existing-wiring-2026-11-22` — `9a7505244d13df15e08e35a835a251bd8736d98c`
- `gpt/pubpartner-identity-checkpoint-2026-11-22` — `2e2c1e3e37a99da48bb92f1acbaa210607ae4f41`
- `gpt/pubpartner-unification-foundation-2026-11-22` — `a29149de3ce8de99a167ead225c8f0f977fb434a`
- `gpt/recording-endurance-2026-11-13` — `0857cf5f807e368b105a12929740ff20c5b3d6dc`
- `gpt/speech-playback-lifecycle` — `6707e7cdeb5f4b6f517742b97939fd70a6437365`
- `integration-2026-11-04` — `c82069b47b04eac56cca1fb4f6a4eb16c44d32ae`
- `integration/converge-2026-11-20` — `538a40fb2d6efb540347036e3c36605729b57ebf`
- `integration/main-debug-union-trial-2026-11-20` — `eacde8753402447e3454b07622fb2fcec8dd17e7`
- `main` — `7fd1fea88aea102067c58136daf407412b3ec188`
- `preview/2i-live-2026-11-17` — `95cfde06fa863ad7ffdff6495d90451647001e6e`
- `sandbox-as-code-2026-11-01` — `8a06383b420495f9c71b20c7bef711814fc8b6f1`
