# BBX1 BlackBox 0.5.0a2 Build Report

Date: 2026-07-20

## Scope

This Candidate adds a bounded, read-only migration for the Phase 1/1.2 compact BBX1 format. It does not claim universal migration of every historical Wallet evidence layout.

## Proven behavior

- Legacy source is captured without following symlinks and preserved byte-for-byte.
- Sequence, previous-hash links, and each compact record hash are recalculated before import.
- Imported records enter the one canonical segmented chain with stable retry operation IDs.
- Original session ID, record ID, record hash, previous hash, event codes, coverage, and payload provenance are retained.
- Imported evidence is explicitly `local_consistency_only` and never described as independently authenticated.
- Interruption after a partial import resumes without duplicate canonical facts.
- Corrupt sources remain preserved and produce additive failure evidence; no automatic rollback or deletion occurs.
- A migration seal anchors the preserved source hash and imported record count to the canonical chain.

## Remaining limits

Durable outbox coverage semantics, universal legacy registration, full protected-route Wallet cutover, Oubliette crossings, real PubCast lifecycle wiring, cross-language JCS verification, and broader platform/fault campaigns remain open.
