# Continuous engineering run report — 2026-07-25

## Release candidate produced

- Iteration Wallet: **2.5.0a11**
- BlackBox: **0.6.0a4**
- Canonical BlackBox client schema: **bbx1-client/1**
- Build label: **Permanent Preservation Hardening**
- Supported external-work path: **LabCopy**
- Network posture: **loopback only**
- Protected-operation posture: **passkey enrollment required by default**

## Governing product law

Once material is admitted to Iteration Wallet, its protected content remains preserved. BlackBox evidence remains preserved. State, visibility, relationships, trust, and organization may change, but Wallet and BlackBox contain no authority that reduces protected content or evidence.

The sole physical cleanup authority is the runtime-residue registry. It is restricted to individually registered, program-created, non-authoritative operating artifacts that pass exact path, class, ownership, identity, link-count, content-hash, retention, and authoritative-reference checks immediately before cleanup. Uncertain material remains in place for investigation.

## Engineering completed in this run

### Permanent-preservation enforcement

- Added one canonical preservation module for Wallet content, BlackBox evidence, state vocabulary, and additive legacy-state migration.
- Replaced ambiguous active vocabulary with exact Retire, Restore, Archive, Recovery Holding, and credential-revocation semantics.
- Implemented exact Retire and Restore custody transactions through a Wallet-owned coordinator; legacy ambiguous routes and direct engine bypass methods remain absent.
- Added durable state-transition journals, exact scoped ceremony consumption, no-clobber publication, preserved prior-path evidence, state history, canonical facts, portable receipts, and restart reconciliation.
- Added UI ceremonies and generation-row actions using literal Retire/Restore language and explicit preservation statements.
- Preserved legacy labels, identifiers, paths, hashes, and payload bytes during additive state normalization.
- Added regression and source-surface checks proving active Wallet, adapter, and BlackBox packages have no physical cleanup authority outside the residue module.

### Runtime-residue safety

- Added a signed residue registry with a strict artifact-class allowlist and dedicated roots.
- Added HMAC ownership markers bound to path, class, device, inode, size, and SHA-256.
- Added dry-run plans with plan hashes and exact revalidation before execution.
- Rejected paths outside approved roots, symbolic links, hard links, forged markers, changed files, unelapsed retention, unknown classes, and authoritative references.
- Added permanent receipts before and after cleanup and an attention-required receipt for interrupted operations.
- Avoided recursive sweeping, wildcard cleanup, filename guessing, and traversal through user-controlled links.

### Passkey and authority hardening

- Made passkey enrollment mandatory before protected operations by default.
- Replaced credential-removal behavior with history-preserving revocation.
- Preserved revoked credential records and approval context.
- Refused revocation of the final active credential.
- Bound passkey-management authority to the exact credential and management action.
- Removed the prior passkey route and published only the revocation route.

### Local boundary and startup hardening

- Restricted the supported service bind address to localhost, 127.0.0.1, or ::1.
- Rejected wildcard, LAN, public, and arbitrary hostname binding.
- Added bundled BlackBox discovery and fail-fast Wallet/BlackBox/schema compatibility checks before the browser opens.
- Updated Windows launchers to require passkey enrollment and use exact localhost WebAuthn scope.
- Rebuilt matching pure-Python Wallet and BlackBox wheels and validated them from a clean installation target.

### BlackBox alignment

- Updated BlackBox views and product laws to exact preservation semantics.
- Preserved evidence across rotation, migration, repair, retirement, and compatibility interpretation.
- Kept BlackBox as recorder and verifier rather than a custody or promotion authority.

### Regression and release closure

- Expanded the Wallet regression suite to 313 tests.
- Expanded the standalone BlackBox suite to 43 tests.
- Added network-policy, runtime-residue, preservation, migration, route-absence, passkey-revocation, final-credential, and state-transition transaction tests.
- Added fault-injection coverage for custody publication, catalog commit, receipt anchoring, receipt persistence, ambiguous destination conflicts, and restart reconciliation.
- Improved multiprocessing-test teardown so full verbose suite execution completes cleanly.
- Added a 27-check source-bundle verifier covering versions, dependency pins, compilation, preservation laws, physical-cleanup authority, published routes, UI contracts, exact visible preservation vocabulary, JavaScript syntax, CLI contracts, fresh-runtime passkey posture, canonical flow, and release files.

## Verification result

- Wallet source regression suite: **313 passed**.
- Standalone BlackBox suite: **43 passed**.
- Source-bundle verification: **27/27 passed**.
- Live loopback smoke: **passed**; UI HTTP 200, Wallet 2.5.0a11, BlackBox chain healthy, custody integrity healthy, passkey enrollment required.
- Reproducible installed-wheel/live-loopback smoke report: `RELEASE_SMOKE_2.5.0a11.json`.
- Clean wheel smoke: **passed**; Wallet 2.5.0a11 and BlackBox 0.6.0a4 import at the pinned schema and `iw doctor` reports healthy.

## Honest release judgment

This handoff is a materially hardened and internally coherent release candidate. The implemented custody-state transitions are no longer a missing workflow: they are coordinated, receipt-backed, restart-safe, and preservation-only. It is suitable for continued engineering validation and controlled alpha/pilot use. It must not yet be represented as the signed market release.

The remaining blockers are architectural deployment and independent-assurance work rather than missing placeholders in this pass: protected Windows service identities and ACLs, signed installer lifecycle, physical authenticator matrix, sealed-vault recovery, independent security review, accessibility audit, and external recovery/usability rehearsal. See `KNOWN_LIMITATIONS_2.5.0a11.md`.
