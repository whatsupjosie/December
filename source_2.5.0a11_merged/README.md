# Iteration Wallet 2.5.0a11

Iteration Wallet is a local-first custody application for AI-assisted project work. It preserves every admitted generation, separates Raw Source, Candidate, Prime, Archive, Retired, and Recovery Holding states, requires exact Human Intent for trust expansion, and records canonical facts through the separately owned BlackBox recorder.

The governing rule of this build is permanent preservation:

> Once material is admitted, its protected content remains preserved. State, visibility, relationships, and trust may change; protected content and BlackBox evidence are not reduced.

The only physical cleanup authority is the strict runtime-residue registry. It can handle only individually registered, program-created, non-authoritative operating artifacts after path, class, ownership marker, identity, content hash, retention, and absence of authoritative references are reverified. Uncertain material remains in place for investigation.

## Hardened in 2.5.0a11

- Implemented exact `Retire` and `Restore` custody transactions that preserve protected bytes, prior-path transition evidence, identity, history, and canonical receipts.
- Kept direct engine bypass methods and legacy ambiguous custody routes absent; state changes are available only through the coordinated Human Intent path.
- Added additive migration from older state labels while preserving identifiers, paths, hashes, bytes, and historical labels.
- Added a signed, allowlisted runtime-residue registry with dry-run planning, exact revalidation, and permanent cleanup receipts.
- Made passkey enrollment required before protected operations by default.
- Replaced passkey removal with credential revocation that preserves the credential history and blocks revocation of the final active credential.
- Added bundled BlackBox source discovery and fail-fast version/schema checks before the browser opens.
- Updated Wallet to `2.5.0a11` and BlackBox to `0.6.0a4` with matching dependency pins and wheels.
- Expanded the Wallet regression suite to 313 tests and the standalone BlackBox suite to 43 tests.

## Supported workflow

- Project and section creation.
- Raw Source and Candidate intake.
- Candidate review.
- Exact Retire and Restore transitions for Raw Source, Candidate, and Archive objects; current Prime requires a replacement before retirement.
- Candidate-to-Prime promotion through exact scope, verified Human Intent, a one-use ceremony token, journaled custody mutation, canonical BlackBox evidence, and a portable receipt.
- HMAC-authenticated LabCopy export, bounded result capture, deterministic classification, and Candidate-only return.
- Canonical BlackBox chain and custody verification.
- Browser WebAuthn enrollment and server-side assertion verification for platform passkeys, phone passkeys where the platform supports them, and FIDO2 security keys.
- Multiple active credentials and history-preserving credential revocation.

Legacy Oubliette compatibility remains backend-only for interpretation of existing alpha material. LabCopy is the supported external-work path.

## Start on Windows

Double-click:

```text
START_ITERATION_WALLET.bat
```

or run:

```powershell
.\START_ITERATION_WALLET.ps1
```

The launcher creates `.venv`, installs Wallet and BlackBox together, stores runtime data under `wallet_home`, requires passkey enrollment for protected operations, starts the loopback service, and opens `http://localhost:7432`.

## Verify the handoff

```powershell
python RUN_VERIFICATION.py
```

For the complete source regression suites, use the isolated release runner:

```powershell
python tools\run_release_tests.py --json-report release-test-run.json
```

It discovers every Wallet test, runs bounded batches in fresh interpreter processes, then runs the standalone BlackBox suite. This prevents completed multiprocessing and fault-injection campaigns from contaminating later campaigns while still proving that every collected test executed.

## Current release boundary

This build is a hardened alpha and is not yet represented as a certified market release. The remaining blockers are listed in `KNOWN_LIMITATIONS_2.5.0a11.md`; the largest are signed Windows service/installer work, protected service identities and ACL deployment, physical authenticator validation, sealed-vault backup implementation, independent security review, and field usability validation.
