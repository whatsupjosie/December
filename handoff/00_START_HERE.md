# START HERE — Iteration Wallet, Merged & Hardened Build

> **2026-07-27 continuation:** Read
> `04_SECURITY_DEBUG_CONTINUATION_20260727.md` first. It supersedes the old
> environment/testing caveats below: the complete suites were run, the
> `vault_id` policy gap was closed, the browser Vault-open flows were repaired,
> and the final Wallet count is 322 passed.

**Prepared:** 2026-07-25/26, by Claude (Anthropic), from two uploaded `2.5.0a11` zips.
**Package version:** `iteration_wallet-2.5.0a11` (BlackBox `bbx1_iteration_wallet_plugin-0.6.0a4`),
build label `Permanent Preservation Hardening + Vault Open/Lock Auth Fix + Approval Decision Auth
Fix (merged 2026-07-25)`.

## Read order

1. `04_SECURITY_DEBUG_CONTINUATION_20260727.md` — latest verified state
2. This file — original reconciliation history
3. `01_VERIFIED_STATE.md` — original findings, with continuation notice
4. `02_TODO.md` — remaining release work
5. `03_FILE_MANIFEST.md`
5. `../evidence/LINEAGE_DIVERGENCE_INVENTORY.md` — **read this before assuming the two source
   zips you had were simple duplicates.** They weren't.
6. `../evidence/manual_verify_approval_decision_fix.py` + its `_OUTPUT.txt` — the verification
   that was actually run, and its result

## What you gave me and what I found

You uploaded two builds that both call themselves `2.5.0a11`. They are not the same code with a
small patch on top — they're two lineages that diverged from a common ancestor:

1. **`IterationWallet_2.5.0a11_PERMANENT_PRESERVATION_HARDENING`** — the complete, installable
   tree (full release scaffolding, its own local `iteration_wallet_blackbox` package, plus four
   preservation/durability modules the other lineage doesn't have). But its `/vault/open` and
   `/vault/lock` HTTP routes had **zero authentication** — a locked vault could be reopened by a
   bare, unauthenticated `POST`, confirmed by reading the actual route code.
2. **The RVF handoff's `source_2.5.0a11_patched`** — a thinner tree missing the local
   `iteration_wallet_blackbox` package (it will not import on its own as delivered), but it
   carries a tested fix for that exact vault auth gap, plus a second, already-identified-but-not-
   yet-fixed bug: `submit_approval_decision` accepted an unauthenticated `decision_by` string as
   a fallback when no session was supplied.

## What this package is

I used lineage #1 (the complete one) as the base — it's the only one that actually runs — and
ported in the security-relevant fix from lineage #2, plus fixed the second bug that lineage #2
had only identified but not yet patched. Both fixes are **in this package's source and in the
freshly-rebuilt wheel** (`source_2.5.0a11_merged/dist/iteration_wallet-2.5.0a11-py3-none-any.whl`
— rebuilt with the project's own `setup.py bdist_wheel`, not hand-assembled).

I then went back through **every single file that differed between the two lineages** — not just
the two security-critical ones — and classified each as either a straight-line evolution (nothing
to port) or a real fork. That surfaced a third, previously-unknown gap: an approval-gate flag that
existed on the older lineage's `release_from_custody` action got silently dropped when it was
renamed to `retire_object`. That's fixed too, though the fix comes with an honest caveat — see
`01_VERIFIED_STATE.md` #3 and `02_TODO.md` P1.

This is now a genuinely complete reconciliation, not a two-fix patch. See
`../evidence/LINEAGE_DIVERGENCE_INVENTORY.md` for the file-by-file record of what was checked and
why each verdict was reached.

## Environment note — read before you try to run the test suite

**Superseded:** dependencies were available during the 2026-07-27 continuation.
The complete Wallet suite passed 322/322, BlackBox passed 43/43, and the
source-bundle verifier passed 27/27. The text below is retained only as a record
of the earlier session.

This session had **no network egress**. `fastapi`, `pydantic`, `uvicorn`, `requests`, `pytest`
were not installable, so the real pytest suite (the 286-test regression this project normally
runs) could not be executed here, and neither could a live server smoke test. What I could and did
run: a manual `unittest`-free verification harness (stdlib only + the project's own
`NotificationManager`, using the locally-available wheels) that directly exercises the approval-
decision fix, including a re-run of the original exploit shape. See `../evidence/`. **The first
thing to do in a networked environment is `pip install -r requirements.txt` and run the real
suite** — don't treat my manual harness as a substitute for it.
