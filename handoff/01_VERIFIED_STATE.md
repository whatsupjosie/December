# VERIFIED STATE

> **Continuation correction — 2026-07-27:** The previously open `vault_id`
> call-site gap is fixed and regression-tested. The browser Vault-open callers
> are repaired. The full suites were run: 322 Wallet tests, 43 BlackBox tests,
> and 27/27 source checks passed. See
> `04_SECURITY_DEBUG_CONTINUATION_20260727.md`; where this older file says
> “not live-tested” or “partially effective,” the continuation handoff is
> authoritative.

## Fixed this session (full lineage reconciliation)

### 3. `retire_object` missing head-user-approval gate — FIXED AND NOW EFFECTIVE
**File:** `iteration_wallet/gatekeeper.py`

Found while doing the full file-by-file reconciliation you asked for (see
`../evidence/LINEAGE_DIVERGENCE_INVENTORY.md`). The predecessor action to `retire_object`
(`release_from_custody`, in the other lineage) carried an opt-in
`requires_head_user_approval_when_configured=True` gate. It was silently dropped during the
rename/restructure into the new retire/restore state-transition system — the new registry had
**no action at all** requiring approval.

**Continuation fix:** the state-transition coordinator now binds the canonical
Wallet vault ID and supplies it to the gatekeeper. A regression test configures
the Vault Head User, attempts Retire with a different human session, verifies
the denial, and confirms the Candidate remains unchanged.

**Verification:** `evidence/manual_verify_gatekeeper_approval_gate_fix.py`, 2/2 passed — confirms
the flag itself, and documents the `vault_id` gap in its own docstring so it isn't lost.

## Fixed and verified in the prior session

### 1. `submit_approval_decision` unauthenticated fallback — FIXED, VERIFIED
**File:** `iteration_wallet/notification_manager.py`

**Before:** if `decision_session_id` was omitted, the code fell through to a bare check on
`decision_by` (a plain string) against the role list. A caller who knew a real admin identifier
could pass it as `decision_by` with no identity session, no proof of humanity, nothing — and get
approval authority.

**After:** `decision_session_id` is mandatory. It's resolved through
`require_identity_session()`, checked for `has_human_intent_proof()`, and only then is
`decision_by` derived from the verified identity — never trusted as a bare client string. Every
rejection path records an `UNAUTHORIZED_APPROVAL_DECISION_BLOCKED` authority denial, same as the
existing pattern elsewhere in this file.

**Verification:** `evidence/manual_verify_approval_decision_fix.py`, 9/9 passed, including a
direct re-run of the exploit shape (known admin id, no session → now rejected) and the existing
regression cases (write-once terminal state, concurrent decisions have exactly one winner, bot
sessions without human-intent proof rejected, decision_by/session mismatch rejected). Run without
pytest (unavailable, no network) using stdlib + the real `NotificationManager` class — this is the
actual code path, not a reimplementation.

**Tests updated to match the new required signature:** `tests/test_human_intent_gatekeeper_v216.py`,
`tests/test_notification_manager_v215.py`, `tests/test_session2_authority_storage_regressions_v230a2.py`
(3 call sites in that file). These were **not** re-run against the real pytest suite (unavailable)
but were syntax-checked and the equivalent logic was verified via the manual harness above.

### 2. `/vault/open` + `/vault/lock` unauthenticated — FIXED, NOT LIVE-TESTED
**File:** `iteration_wallet/server.py`

**Before:** both routes took no request body and no auth check at all.

**After:** `VaultOpenRequest`/`VaultLockRequest` models added; both routes now call
`human_access.require_identity_session(req.session_id)`. Open additionally requires
`has_human_intent_proof()` and consumes a hardware gate token via
`passkey_gate.consume_gate_token(...)`. Lock only requires a valid session (locking can only
reduce authority, so it's intentionally not gated behind hardware).

This is a direct port of the pattern already proven live (per the RVF handoff's own testing) in
the other lineage, using helper functions (`require_identity_session`, `consume_gate_token`)
already used identically elsewhere in *this* file's ceremony-token-issuance route — so it's not a
novel implementation, it's reuse of an already-working pattern in the same codebase.

**What was NOT possible this session:** starting a live server and hitting the route with a real
HTTP client. `fastapi`/`uvicorn` aren't installable here (no network). **Treat this fix as
code-reviewed and pattern-consistent, not live-tested. Live-test it before treating it as done.**

**Callers updated (all confirmed, full-tree grep, none missed):**
- `cli.py`: `cmd_open`, `cmd_lock`, `cmd_promote`, `_ensure_open_human_session` — the latter two
  required reordering so a session is established *before* the vault-open call, not after (the
  old code opened the vault, then started a session — that ordering is now impossible since
  opening needs the session).
- `private_alpha_runner.py`: 2 call sites, session already in scope at both.
- `tools/oubliette_boundary_demo.py`, `tools/live_law003_probe.py`: 1 call site each, session/
  identity already in scope at both.
- 6 test files: `test_labcopy_http_vertical_slice_v250a1.py`, `test_private_alpha_flow_v223.py`,
  `test_oubliette_http_vertical_slice_v240a1.py`, `test_ceremony_tokens_v222.py`,
  `test_session2_authority_entrance_map_v230a2.py`, `test_session2_canonical_human_intent_red.py`.
  (One more file, `test_session2_legacy_surface_retirement_v230a2.py`, references
  `/api/vault/open` — the *old*, already-retired v2 path, not the v21 route this fix touches;
  confirmed unaffected by reading it.)

Full-tree grep after all edits found zero remaining bare (unauthenticated) calls to either route.

### Build artifact
`source_2.5.0a11_merged/dist/iteration_wallet-2.5.0a11-py3-none-any.whl` was rebuilt from this
patched source using the project's own `python3 setup.py bdist_wheel` — not hand-assembled.
Confirmed by unzipping the wheel and grepping for both fixes' marker strings; both present.

## Explicitly NOT done this session

- **Real pytest suite** (286 tests per the prior handoff) — not run, no network access to install
  `fastapi`/`pydantic`/`uvicorn`/`pytest` here. **This is the single most important thing to do
  next**, before trusting anything else in this package.
- **Live server smoke test of the vault fix** — see above.
- **Full reconciliation of the two lineages** — now done. Every differing file was individually
  read and classified (evolution vs. fork), not just diffed by line count. See
  `../evidence/LINEAGE_DIVERGENCE_INVENTORY.md` for the file-by-file record. This surfaced the
  `retire_object` approval-gate regression above. One exception: `static/app.html` got a
  structural check (looking for dropped functionality) but not a full line-by-line read — it's a
  UI file and this session had no way to render or test it.
- **Wiring `vault_id` through the retire/restore transaction coordinator** so the now-restored
  approval gate actually fires — see item 3 above and `02_TODO.md` P1.
- **The hotspot-style vault UI** you asked about (typewriter/vault-desk image as a clickable
  interface) — not built. See `02_TODO.md` for what I'd recommend and why I didn't start it this
  session.
