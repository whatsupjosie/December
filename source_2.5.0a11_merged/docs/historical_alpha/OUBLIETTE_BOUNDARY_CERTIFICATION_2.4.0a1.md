# Oubliette Boundary Semantic Certification — 2.4.0a1

## Certification scope

This document certifies only the bounded intake/quarantine/derivative-return boundary implemented in Iteration Wallet `2.4.0a1`. It does not override the unchanged official benchmark, whose OUB gates remain manual and therefore OPEN.

## OUB-001 — Static inspection only

**Implemented and semantically tested for the bounded scope.**

Evidence:

- `iteration_wallet/oubliette.py::inspect_static()` reads bounded bytes and archive metadata without importing, launching, compiling, extracting, or executing the target.
- `OublietteTransactionCoordinator.inspect_object()` verifies the custodied hash before and after observation.
- AI and bot actor kinds are refused.
- A demonstration target that would create an execution marker never creates it.
- Tests cover scripts, archive traversal names, executable archive members, symlinks, root escape, bounded evidence envelopes, and no target modification.

Limit: this is not a claim that static inspection detects every threat.

## OUB-002 — Quarantine is fence and warning, never deletion

**Implemented and semantically tested for Raw Source and Candidate intake.**

Evidence:

- Direct engine quarantine refuses; only `OublietteTransactionCoordinator` may initiate the Wallet-owned mutation.
- Wallet moves the existing custodied file into the quarantine compartment and preserves the byte hash.
- The catalog records previous state/path, report identity/hash, operation identity, reason, and `execution_allowed=false`.
- No delete call is used in the transaction.
- Failed or ambiguous transactions preserve evidence and freeze trust rather than removing material.

Limit: release from quarantine is not implemented in this milestone.

## OUB-003 — Human-controlled crossing and Candidate-only re-entry

**Implemented and semantically tested for two explicit actions.**

Actions:

- `quarantine`
- `admit_oubliette_derivative_as_candidate`

Each action requires:

- a current local human identity-continuity session;
- Gatekeeper approval;
- an exact object/action-scoped one-time ceremony token;
- a matching immutable static inspection report;
- a durable operation journal;
- a five-stage canonical evidence graph; and
- a Wallet-minted receipt that verifies against current custody state and report lineage.

The returned derivative receives a new object ID, remains `candidate`, records the quarantined parent and report hashes, and carries `trust_status=candidate_only_no_automatic_trust`. The original remains quarantined and byte-identical.

Limit: a complete LabCopy export/result-envelope protocol remains open.

## OUB-004 — Canonical BlackBox only

**Implemented and semantically tested for this boundary.**

- Inspection observations and custody transactions use the existing `CanonicalEvidenceAdapter`.
- The Oubliette report store is an immutable artifact store, not an event chain or authority source.
- Oubliette does not instantiate or maintain a second BlackBox.
- Receipts are anchored to the same canonical chain used by promotion.
- Restart reconciliation returns to the same operation IDs and does not mint duplicate custody facts.

Limit: independent external witnessing is not claimed.

## Recovery campaigns

The suite proves:

- crash after quarantine move but before final evidence;
- crash after authorization but before quarantine mutation;
- crash after derivative bytes enter Candidate custody but before catalog registration;
- crash after derivative authorization but before copy;
- retry after external derivative source moves away;
- report tampering;
- report reuse across objects;
- derivative mutation after inspection;
- direct engine bypass; and
- bot/AI operation attempts.

## Test evidence

- Complete Wallet suite: `195 passed` after the runnable demo test is included.
- BBX1 suite: `57 passed, 1 intentional skip`.
- Source-free installed-wheel smoke: pass.
- Bounded API demo: pass.
- Official locked benchmark: `59/100 Candidate`, no constitutional failure; OUB gates remain OPEN because the frozen runner requires manual qualification and does not infer closure from source or this document.

## Certification language

The accurate claim is:

> Iteration Wallet 2.4.0a1 implements and tests a bounded static-only Oubliette intake boundary in which Wallet—not Oubliette—performs Human Intent quarantine and admits separately inspected derivatives only as new Candidates while preserving the original.

It is not accurate to claim that Oubliette is a complete sandbox, malware detector, laboratory authority, automatic repair system, or production-certified security boundary.
