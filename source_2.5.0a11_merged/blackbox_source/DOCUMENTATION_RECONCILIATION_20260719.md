# Documentation and Architecture Reconciliation — 2026-07-19

## Scope

Reviewed the master plan, benchmark v1.0 and clarification, Part 2 reset decisions, Oubliette contract, Recorder P0 build report, benchmark rerun, and packaged 0.4.0a1 source/docs.

## Corrections folded into 0.4.0a3

1. Replaced “independent Sentinel” claims with “local reference comparator.”
2. Added explicit `independently_authenticated: false` output.
3. Distinguished restore-from-Removed from active-program repair.
4. Defined static analysis as allowed while target activation remains prohibited.
5. Marked the inherited compatibility Human Intent method as benchmark-proven non-authoritative.
6. Marked generic closed payload filtering as benchmark-proven unsafe for secrets.
7. Clarified that the current outbox is transitional and not yet the final availability/coverage system.
8. Clarified Wallet as the only physical quarantine-transition owner.
9. Clarified that Part 2 is the continuation of Part 1, not a later merge target.
10. Consolidated the next integration sequence: BBX-005, BBX-006, narrow Wallet integration, combined attack pass, then remaining services.

## Code behavior changed

Only the local comparator's claim/output semantics changed. Recorder behavior, receipt behavior, privacy behavior, and Wallet integration behavior were not altered in this reconciliation checkpoint.

## Known red gates intentionally preserved

- BBX-005 Human Intent;
- BBX-006 privacy projections;
- BBX-007 final outbox/coverage;
- BBX-008 migration;
- Wallet helper law failures;
- Oubliette, Runtime Continuity, and real PubCast integration.

## Final verification seam

The runtime version and project metadata are now tested for equality, and the complete benchmark test-path command has a real `tests/` directory.
