# Changelog

## 2.5.0a11 market-readiness quality pass — 2026-07-27

- Added permanent release-source quality gates for UTF-8/newline hygiene,
  trailing whitespace, production assertions, duplicate dictionary keys,
  runtime stub bodies, unresolved work markers, duplicate HTML IDs, and dead
  DOM references.
- Replaced optimized-away production assertions with explicit fail-closed
  runtime checks at the continuity and BlackBox compatibility boundaries.
- Made base64url parsing strict and converted malformed Unicode hardware-gate
  tokens and invalid credential algorithms into controlled security errors.
- Standardized active Wallet timestamps on explicit UTC offsets while retaining
  deterministic readability of older offset-free notification records.
- Removed 18 verified unused imports/assignments and corrected stale runtime
  documentation about canonical transaction availability.
- Rebuilt both wheels and verified 330 Wallet tests, 43 standalone BlackBox
  tests, 27/27 source-bundle checks, a clean-wheel doctor run, and live loopback
  HTTP smoke.

## 2.5.0a11 security-review continuation — 2026-07-27

- Closed the HTTP approval-decision exploit boundary: hardened mode now
  requires a one-use passkey token scoped to the exact approval ID before a
  caller-supplied local identity session can decide the approval.
- Made the Retire Head User/admin policy effective by binding the canonical
  state-transition coordinator to the Wallet vault ID.
- Repaired every browser Vault-open call so Promote, Retire/Restore, LabCopy,
  and the Vault toggle supply the required identity session and fresh
  `open_vault` passkey token.
- Corrected the browser session ceremony-method vocabulary so its typed
  ceremonies satisfy the server's Human Intent policy.
- Added three focused regression tests. Verified 322 Wallet tests, 43
  standalone BlackBox tests, 27/27 source-bundle checks, a 33-test
  authentication campaign, and a 38-test custody-integrity campaign.

## 2.5.0a11 security review patch — 2026-07-27

- Pinned runtime-residue marker deletion to the exact marker bytes validated
  during planning instead of hashing the current pathname immediately before
  deletion.
- Required an active passkey approval before enrolling every additional
  credential after the first-run bootstrap.
- Bound that approval to the one-use registration challenge and rejected a
  second stale bootstrap challenge after the first credential is stored.
- Persisted the hardware-gate token replay ledger across Wallet restarts.
- Rejected unconsumed tokens issued by credentials that have since been
  revoked.
- Updated stale approval-decision tests to use the mandatory identity-session
  boundary already enforced by production code.
- Verified 319 Wallet tests and 43 standalone BlackBox tests.

## 2.5.0a11 — Permanent preservation hardening

- Established one canonical permanent-preservation law for Wallet content and BlackBox evidence.
- Added coordinated Retire and Restore transactions with exact object scope, one-use Human Intent authority, durable recovery journals, no-clobber custody publication, preserved transition evidence, canonical BlackBox facts, portable receipts, and restart reconciliation.
- Kept legacy ambiguous custody-transition routes and direct engine bypass methods absent.
- Added additive legacy-state normalization that preserves identifiers, paths, hashes, bytes, and old labels.
- Added strict signed runtime-residue registration, planning, revalidation, and permanent receipts.
- Required passkey enrollment before protected operations by default.
- Replaced credential removal with history-preserving revocation and final-active-credential protection.
- Added bundled BlackBox discovery and fail-fast version/schema compatibility checks.
- Bumped Wallet to 2.5.0a11 and BlackBox to 0.6.0a4.
- Expanded regression coverage to 319 Wallet tests and 43 standalone BlackBox tests.

## 2.5.0a10 — Spatial product shell, LabCopy promotion, and passkey gate

- Rebuilt the primary interface as a cinematic spatial-tray workspace with nine functional trays, irregular vector silhouettes, draggable/resizable/dockable behavior, named layouts, persistence, import/export, undo, responsive fallback, and keyboard support.
- Removed Oubliette from the active UI and CLI; retained hidden backend compatibility routes for existing alpha data.
- Promoted the tested LabCopy export/capture/admission flow as the supported external-work path.
- Added local WebAuthn registration and server-side ES256, RS256, and Ed25519 assertion verification.
- Added short-lived one-use hardware-gate tokens bound to one exact protected action and context.
- Added multiple credential enrollment and passkey removal through a fresh passkey-approved management action.
- Corrected the Windows launchers to use `ITERATION_WALLET_ROOT`, `localhost` WebAuthn scope, and the disabled Oubliette mode.
- Centralized Wallet, BlackBox, and client-schema versions.
- Reconciled stale version tests and corrected a fault-injection test to exercise the secure descriptor-based atomic writer.
- Corrected mobile layout overflow with a true bounded one-column custody document at narrow widths.
- Built and clean-installed pure-Python alpha wheels for Wallet and BlackBox.
- Preserved obsolete alpha/Oubliette reports under `docs/historical_alpha/` instead of leaving stale claims at the release root.
- Verified 286 Wallet tests and 2 BlackBox tests, 16/16 release checks, desktop/mobile headless UI execution, and a live loopback server smoke.

## 2.5.0a5 — Quarantine pipeline access and retry hardening

- Tightened quarantine and transition-evidence directories to owner-only POSIX permissions.
- Proved the quarantine compartment contains payload bytes only; operational state remains in Wallet and canonical BlackBox evidence.
- Refused completed-object re-staging and duplicate quarantine publication.
- Fixed unchanged static-inspection retries that crossed a timestamp boundary and falsely conflicted with the write-once report identity.
- Added donor conformance analysis without importing destructive delete or automatic-install behavior.

## 2.5.0a5 — Standalone BlackBox dependency and host-owned adapters

- Made BlackBox `0.6.0a2` the sole installed owner of `blackbox_plugin`.
- Moved `iteration_wallet_blackbox` into the Wallet distribution.
- Removed the active embedded BlackBox source path from Wallet; preserved it under history.
- Added the neutral `bbx1-client/1` contract and local client implementation.
- Routed Wallet's production evidence path through its durable adapter/outbox.
- Distinguished retryable unavailability, permanent rejection, and acknowledgement-persistence failure.
- Added an Oubliette-owned observation adapter with explicit no-custody/no-authority enforcement.
- Defaulted Oubliette safely to disabled and made demos opt into transaction mode explicitly.
- Sealed authority journals, strengthened no-clobber custody publication, bounded archive claims, and hardened outbox writes in the preceding repair pass.
- Added `iw doctor` for version, client-schema, and installed-package ownership verification.
