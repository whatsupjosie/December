# Lineage Divergence Inventory — the two `2.5.0a11` builds (RECONCILED)

Both of your uploaded zips contained a build calling itself `2.5.0a11`, but they diverged from a
common ancestor into two different directions:

- **`IterationWallet_2.5.0a11_PERMANENT_PRESERVATION_HARDENING`** — the more complete tree (full
  release scaffolding, its own local `iteration_wallet_blackbox` adapter package), plus four
  modules the other lineage didn't have: `network_policy.py`, `preservation.py`,
  `runtime_residue.py`, `state_transition_transaction.py`.
- **The RVF handoff's `source_2.5.0a11_patched`** — thinner, wouldn't import on its own, but
  carried a tested fix for the `/vault/open`+`/vault/lock` authentication gap.

## Every file that differed has now been individually reviewed, not just diffed

For each file below: I read the actual diff (not just a line count), determined whether the
difference was a real fork (independent, potentially-conflicting functionality) or a straight-line
evolution (one side is simply a later draft of the same idea), and ported forward anything real
that the evolution had silently dropped.

| file | verdict | action taken |
|---|---|---|
| `vault_v21.py` (318 changed lines) | Pure evolution. The `PERMANENT_PRESERVATION_HARDENING` side replaces the old `removed`/`released` compartments and a disabled `restore_file` stub with a real, working `retired`/`recovery_holding` state-transition system. Checked all 5 "pure removal" hunks by hand — every one was either the `released` field being renamed or a disabled stub being replaced by a working implementation. Nothing lost. | Kept as-is. |
| `server.py` (181 changed lines) | Same story: the routes for `remove`/`restore`/`release` were disabled stubs in the older lineage; the newer one replaces them with real `/retire` and `/restore` endpoints (already correctly session-gated). The `VaultOpenRequest`/`VaultLockRequest` gap was the already-known vault fix. | Vault fix already ported (prior session). Nothing further needed. |
| `passkey_gate.py` (99 changed lines) | Pure evolution: schema migration v1→v2, passkey now required-by-default instead of conditional, credential revoke-with-history instead of hard delete. Strictly more hardened. | Kept as-is. |
| `private_alpha_runner.py` (132 changed lines) | Pure evolution: the older lineage's runner proves the retire/restore actions are correctly *unavailable* (503); the newer one proves they now *work end-to-end* with real receipts, because the feature now exists. Two vault-open/lock call sites needed the session_id fix. | Both call sites fixed (prior session). Nothing further needed. |
| `cli.py` (82 changed lines) | The diff looked asymmetric (48 vs 28 changed lines) but on inspection every substantive "older lineage" line was the vault-open/lock/promote session-ordering fix that had already been ported forward; the rest was `network_policy.py` loopback-binding (new, security-positive, already present) and cosmetic wording. | Already fully reconciled (prior session's vault fix). |
| `gatekeeper.py` (30 changed lines) | **Real regression found.** The older lineage's `release_from_custody` action carried an opt-in `requires_head_user_approval_when_configured=True` gate. When it was renamed/restructured into `retire_object` during the preservation rewrite, **that flag was silently dropped** — no action in the new registry required approval at all. | **Fixed this session**: restored the flag on `retire_object` (the outbound/sensitive direction; `restore_retired_object` correctly stays ungated, matching how `restore_to_active` was never gated either). See `manual_verify_gatekeeper_approval_gate_fix.py`. |
| `durable_io.py`, `intake_capsule.py`, `vault.py`, `runtime_continuity.py`, `__init__.py` (4–8 lines each) | Cosmetic only — "no-delete"/"removed" language updated to "permanent-preservation"/"missing" terminology. No functional difference. | Kept as-is. |
| `static/app.html` (105 changed lines, 12 removed / 91 added) | Checked for removal-heavy sections specifically (the pattern that would indicate dropped UI functionality); found none. Consistent with the same pure-evolution pattern as everything else. Not reviewed line-by-line beyond that — it's a UI file and this session had no way to render/test it. | Kept as-is; flagged as the one file with only a structural check, not a full read. |
| `tests/` (27 files differ), `tools/` (5 files differ) | The bulk of this is the natural result of the newer lineage testing features (retire/restore, preservation rules) that only exist on that side. The specific files affected by the two security fixes (vault auth, approval-decision auth) were updated in the prior session; nothing else required changes. | No further action. |

## One gap the `retire_object` fix surfaces but does not close

Restoring the flag is necessary but **not sufficient**. `evaluate_protected_action()` only enforces
the approval gate when it's called with both `gate` and a truthy `vault_id`. I traced the actual
call site for retire/restore — `state_transition_transaction.py`'s `_policy_decision()` — and it
passes `gate=self.human_access` but **never passes `vault_id` at all**, because the
`StateTransitionTransactionCoordinator` class has no concept of `vault_id` in its `retire()`/
`restore()` signatures (`project_id`/`section_id`/`object_id` only). So today, even with the flag
restored, the approval gate is a no-op for retire/restore specifically — it silently doesn't fire.

This is now the top item in `02_TODO.md`. Wiring it up correctly means adding a `vault_id`
parameter through `StateTransitionTransactionCoordinator.retire()`/`.restore()`, the
`StateTransitionRequest` model in `server.py`, and the `/retire`/`/restore` routes — and then
testing it live, since a mis-wired approval gate is worse than a documented gap. I did not attempt
this blind, without the ability to run the real test suite or a live server (see `00_START_HERE.md`
for why).
