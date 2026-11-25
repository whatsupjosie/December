# Quarantine Pipeline Conformance

## Authority

This document records the review of the supplied `quarantine-spec.md` donor against the active Iteration Wallet laws. The donor is useful design input, not controlling authority.

## Adopted directly

- One protected object per quarantine crossing.
- No in-place edits while material is quarantined.
- No status, log, or verdict sidecars inside the quarantine payload compartment.
- Partial publication must not become visible as a completed custody transition.
- Duplicate or competing publication must fail rather than overwrite.
- BlackBox receives factual results and does not open or govern quarantined bytes.
- Quarantine is a one-way protected crossing: Raw Source/Candidate to fenced quarantine. A cleared derivative returns only through a new Intake Capsule and Candidate proposal.

## Adapted to the active architecture

The donor describes a transient inbound workspace. The active product uses two separate concepts:

1. **Wallet Intake Capsule** — immutable, untrusted bytes preserved before admission.
2. **Fenced Quarantine Custody** — preserved user material under Wallet authority after a scoped Human Intent transaction.

The active quarantine compartment contains only the quarantined payload. Operational state lives in the Wallet catalog, sealed transaction journal, Human Intent receipt, and canonical BlackBox chain.

The active implementation preserves interrupted or displaced bytes under private transition-evidence storage rather than deleting them.

## Rejected as incompatible

The following donor rules are not adopted:

- deleting quarantine immediately after a verdict;
- force-deleting stale folders at startup;
- treating rejection as authority to destroy bytes;
- allowing a helper module to delete user or evidentiary material;
- using `REJECTED` as a destructive disposition.

They conflict with the product laws: no delete, no silent evidence loss, ambiguity freeze, and preservation of original material.

## Code-level guarantees

- `VaultEngine._quarantine_file_unchecked()` performs the physical crossing only after static report validation and exact proposal-scoped Human Intent.
- `move_custody_no_clobber()` publishes without overwriting and preserves the prior entry as transition evidence.
- `ensure_private_directory()` enforces owner-only POSIX permissions on quarantine and transition-evidence roots.
- `OublietteTransactionCoordinator` records canonical stages and returns a verifiable receipt.
- Oubliette never executes the target and never owns custody.

## Regression proof

`tests/test_quarantine_pipeline_conformance_v250a3.py` proves:

- quarantine contains exactly the payload and no sidecars;
- quarantine and transition-evidence directories are owner-only on POSIX;
- the canonical `OBJECT_QUARANTINED` event exists;
- a second quarantine attempt cannot re-stage or duplicate a completed object.

## Other donor material reviewed

### External Evidence Packets v2.2.7

Useful principles retained: outside assertions are observational, bounded, non-executing, and cannot promote trust. The old module itself was not imported because it uses `shutil.copy2` and duplicates functions now handled more safely by Intake Capsules, LabCopy manifests, the Wallet adapter, and canonical BlackBox evidence.

### Private Alpha Flow Runner v2.2.4

The current runner supersedes it and is more honest about bounded scope. No older runner code was imported.

### Runtime Continuity handoff

The current `runtime_continuity.py` already implements the approved static-only observation and classification boundary. The planning document remains useful lineage but adds no missing runtime code.

### PubPartner Windows launcher

The visible startup stages and precise log-location behavior are good UI/launcher guidance. Automatic runtime or dependency installation is not imported into Iteration Wallet because it would violate the present no-hidden-system-mutation and consent constraints. Windows execution remains separately unverified.

### Concept images and logos

These are retained as visual direction only. They do not establish functionality and were not inserted into the backend package during this pass.
