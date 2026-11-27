# Beyond-October contents and destinations

All 54 remote branch tips are pinned in [branches.csv](branches.csv). The comparison uses December main-assembly `6a0f36fc451da307877082d6e9f7e461276e95a0` and parts-assembly `4b6042fcba7c30a54de5175d9ee1812bfcce24e2`, before the four files preserved below. Trees were read recursively without a depth cutoff. Each tip row identifies one path, mode and file version across one or more branches.

| Exact content at inspection | Branch-tip items |
|---|---:|
| Main assembly only | 2,212 |
| Parts assembly only | 123 |
| Both | 228 |
| Neither | 297 |

[Files and recommended destinations](files.csv) gives example destination paths, same-path conflicts and branch groups. [Branch groups](branch-groups.csv) maps each group to every branch that contains that version. A match can be a standalone file, a member inside an archive (`!/`), or the verified result of applying a stored patch to the donor Git blob. Match by content does not certify launcher wiring or file-mode equivalence. See the [behavior ledger](../REPOSITORY_SWEEP.md) for exercised connections.

[Historical-only versions](historical-only.csv) adds 520 path/mode/version combinations absent from all current tips across 464 reachable commits, each with a recoverable example commit. One has an exact main-assembly match. For the other 519, use the current implementation and consult the old commit if the branch tips lost a behavior.

## Archives

[Archive review](archives.csv) gives the locations, readable documentation evidence where available, sample contents and recommended use. [Archive members](archive-members.csv) identifies every non-directory member and its exact destination. All 35 distinct ZIP-format containers, including nested ZIP and office/e-book containers, opened successfully. All 598 member occurrences were fully read and CRC checked. Every member is available somewhere in main-assembly, including inside retained archives; 378 also occur in parts-assembly. The same archive stored on several branches was read once. The byte comparison does not prove any archived program is installed.

## What should move

At the comparison baseline, 293 of the 297 unmatched branch-tip versions had a different file at the same path in at least one assembly. Compare their unique behavior before moving any of those revisions. In particular preserve the current offline 2i, recorder clocks and IndexedDB v3. Use the current renderer build and Bubble Stack room engine, and reconcile the older Foresight and cartridge tests with their actual callers. The identity checkpoint implementation and its test can be reconstructed from the parts patch. Its concurrent-turn issue is already recorded.

The four remaining unmatched items had no same-path counterpart. Exact copies are now in this folder on parts-assembly:
- [2i-professional-regression.yml](recovered/2i-professional-regression.yml) from Beyond-October `backup/2i-professional-completion-2026-11-16` at `aaa14b00121c4d0f4369ca9a26021fb18c6f68f3`, path `.github/workflows/2i-professional-regression.yml`.
- [pubpartner-backend-hardening.yml](recovered/pubpartner-backend-hardening.yml) from Beyond-October `gpt/pubpartner-backend-hardening-2026-11-22` at `a594d3017e12457a84ba0b66506c175cbb6aa5fd`, path `.github/workflows/pubpartner-backend-hardening.yml`.
- [BACKEND_HARDENING_CHECKPOINT_2026-11-22.md](recovered/BACKEND_HARDENING_CHECKPOINT_2026-11-22.md) from Beyond-October `gpt/pubpartner-backend-hardening-2026-11-22` at `a594d3017e12457a84ba0b66506c175cbb6aa5fd`, path `docs/pubpartner/BACKEND_HARDENING_CHECKPOINT_2026-11-22.md`.
- [2I_BETA_POLISH_2026-11-17.md](recovered/2I_BETA_POLISH_2026-11-17.md) from Beyond-October `2i-beta-polish` at `df737caaeff206e4128932532663776af74ec0e8`, path `handoffs/2I_BETA_POLISH_2026-11-17.md`.

The workflow files retain the donor regression commands outside the active workflows directory. Compare each command with December's current CI before enabling anything. The two handoffs preserve donor acceptance conditions and limitations. Use them as historical evidence during the 2i and PubPartner checks.
