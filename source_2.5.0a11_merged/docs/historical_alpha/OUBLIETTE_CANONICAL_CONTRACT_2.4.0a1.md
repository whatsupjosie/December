# Oubliette Canonical Contract — Iteration Wallet 2.4.0a1

## Authority map

| Component | Owns | Must never do |
|---|---|---|
| Oubliette | Static byte/archive observations, coverage, bounded risk indicators, inspection reports, protective-action requests | Execute, import modules, extract archives, repair, transform originals, move custody, determine malware, decide trust |
| Iteration Wallet | Custody, compartment transitions, Human Intent ceremony, operation journals, portable receipts, restart reconciliation | Delegate custody authority to Oubliette or an AI |
| Canonical BlackBox | Append-only facts, operation linkage, coverage/limitations, receipt anchors | Authorize, promote, quarantine, release, or determine trust |
| External Laboratory | Executes approved tools against traceable exported copies outside Wallet custody | Access or mutate Wallet custody |
| Bridgewright | Copy-only conversion recipes, declared inputs/outputs, reproducibility evidence | Modify an original, auto-install tools, or grant trust |
| Memory / Collectors | Context capture, derived memory, operational queues | Become project custody or canonical evidence authority |

## Invariants

1. Unknown intake is preserved byte-for-byte before interpretation.
2. Oubliette inspection is static-only and bounded. Findings are indicators, not verdicts.
3. Oubliette may recommend review but cannot change custody.
4. A quarantine crossing requires a Wallet-owned, scoped Human Intent transaction.
5. Quarantine is a fenced custody state, never deletion or spoilage.
6. The quarantined original remains preserved. It is not silently restored to trust.
7. A cleared or transformed derivative may return only as a new Candidate with explicit lineage.
8. Returned material never automatically becomes Prime.
9. Every crossing has an operation ID, journal, canonical evidence graph, portable receipt, and restart reconciliation.
10. Ambiguity freezes and is reported; it is never guessed through or auto-rolled back.
11. AI and bots may read approved closed summaries or request review. They cannot operate Oubliette or consume authority tokens.
12. The historical command-running Oubliette, Bubblewrap enforcer, auto-installers, destructive dye-pack concepts, and separate local audit chains are donor/reference material only.

## 2.4.0a1 vertical slice

This milestone implements:

- static inspection of one already-custodied Raw Source or Candidate;
- write-once inspection-report storage and canonical BlackBox observation;
- Wallet-owned Human Intent quarantine transaction;
- restart reconciliation after authorized interruption;
- preservation of the original in the quarantine compartment;
- Wallet-owned admission of a human-approved derivative as a new Candidate;
- explicit parent/report/hash lineage; and
- no execution, extraction, repair, deletion, release, or trust promotion.

It does **not** implement a general laboratory runner, Bridgewright recipe engine, release from quarantine, automatic remediation, or full generation graph.
