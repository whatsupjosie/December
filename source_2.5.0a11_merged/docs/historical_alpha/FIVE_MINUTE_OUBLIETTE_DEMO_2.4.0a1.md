# Five-Minute Oubliette Demonstration — 2.4.0a1

## Story in one sentence

Iteration Wallet preserves an unknown file without running it, lets Oubliette report bounded static indicators, requires a human to quarantine it, and permits only a separately reviewed derivative to return as a brand-new untrusted Candidate while the original remains preserved.

## 0:00–0:35 — The problem

Show `unknown_intake.py`. Explain:

> We have material we may need, but do not yet understand or trust. Ordinary workflows pressure us either to open it, delete it, or casually mix it into the project. Iteration Wallet does none of those things.

Point out the marker behavior in the file: if executed, it would create `EXECUTION_WOULD_HAVE_CREATED_THIS.txt`.

## 0:35–1:20 — Preserve and inspect

1. Add the file as a Candidate.
2. Select it in **Oubliette intake boundary**.
3. Run static inspection.
4. Show the report ID, hash, coverage, and risk indicators.
5. Show that the execution marker does not exist.

Say:

> Oubliette observed bytes and archive structure. It did not run the target and it did not decide that the file was safe or malicious.

## 1:20–2:15 — Human-controlled quarantine

1. Enter a reason.
2. Type `QUARANTINE` in the paste-blocked ceremony field.
3. Authorize quarantine.
4. Show the original in `quarantined` state.
5. Open the receipt and chain verification.

Say:

> The inspection report was not authority. A local human identity session, Gatekeeper policy, an object-scoped one-time ceremony, a journaled Wallet transaction, and canonical BlackBox evidence were all required before custody moved.

## 2:15–3:15 — Work remains outside custody

Show `reviewed_derivative.py` under the external laboratory directory.

Say:

> Oubliette is not a runner. Any testing or transformation happens outside Wallet on a copy. Here is a separately reviewed derivative. It does not receive trust merely because someone produced it.

Run **Inspect external derivative** and show its independent report ID and hash.

## 3:15–4:20 — Candidate-only return

1. Enter the admission reason.
2. Type `ADMIT` in the paste-blocked ceremony field.
3. Admit the derivative.
4. Show the new Candidate ID and its parent lineage.
5. Show that the original remains quarantined.
6. Show `trust_status=candidate_only_no_automatic_trust`.

Say:

> The reviewed derivative gets a new identity. It does not replace the original and does not become Prime. Trust can expand only through another deliberate promotion ceremony.

## 4:20–5:00 — Verify and state limitations

Show:

- canonical chain verification;
- custody verification;
- both Human Intent receipts;
- original and derivative hashes;
- absence of the execution marker.

Close with:

> This build proves the intake and return boundary. It does not claim perfect threat detection, independent identity, complete LabCopy authority, Windows certification, or production security. It proves something narrower and useful: unknown material can be preserved long enough to be understood without being executed, destroyed, or quietly trusted.

## Reproducible command

```bash
python tools/oubliette_boundary_demo.py \
  --run-root ./demo-run \
  --json-output ./demo-evidence/demo.json \
  --markdown-output ./demo-evidence/demo.md
```

The command refuses to overwrite an existing run root or output artifact.
