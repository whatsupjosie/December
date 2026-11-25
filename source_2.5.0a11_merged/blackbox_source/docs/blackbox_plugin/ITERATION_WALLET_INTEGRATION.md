# Iteration Wallet Integration — Canonical Sequence

## Integration decision

BlackBox Part 1 and Part 2 are one lineage. `0.4.x` is the hardened continuation of `0.3.0`; there is no separate merge to perform between them.

Full Wallet integration begins only after:

1. **BBX-005** authoritative Human Intent receipts;
2. **BBX-006** event-specific privacy projections.

That sequencing prevents Wallet from depending on receipt and safe-view behavior already proven invalid by the official benchmark.

## Narrow integration after BBX-005 and BBX-006

1. Wallet creates or loads a verified local human session.
2. Gatekeeper validates protected action, object, scope, and current custody state.
3. Ceremony ledger validates and consumes the scoped token when required.
4. BlackBox records authorization intent.
5. Wallet performs the deterministic custody transition.
6. BlackBox records completion or failure.
7. Wallet receipt service creates the final Human Intent receipt.
8. BlackBox anchors the receipt hash and verifies the semantic graph.
9. Wallet returns success only when the action's evidence policy is satisfied.

BlackBox never grants the action. Wallet never fabricates evidence after the fact.

## Current adapter status

`attach_to_wallet()` currently assigns a transitional adapter to `vault_engine.blackbox` without replacing Vault methods.

Safe to use now:

- ordinary Candidate recorder facts in development;
- chain-head and verification queries;
- Recorder P0 testing.

Not safe to treat as final:

- `issue_human_intent_receipt()`;
- generic closed summaries for secret-bearing payloads;
- final degraded-mode/outbox behavior;
- protected trust crossings.

## Availability policy target

- Trust expansion requires canonical BlackBox acknowledgement.
- Protective restriction may proceed under explicit emergency-gap policy.
- Ordinary admission/observation may queue only under documented degraded mode.
- No queued event is represented as canonical until appended and verified.

## Custody language

`restore` means restore-from-Removed only. Active-program byte repair is performed by a separate external tool. Any externally modified result returns as a new Candidate.
