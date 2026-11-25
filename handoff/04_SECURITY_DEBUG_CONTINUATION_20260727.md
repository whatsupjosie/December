# Security/debug continuation — final handoff

**Date:** 2026-07-27  
**Base:** `IterationWallet_2.5.0a11_SECURITY_REVIEW_PATCH_20260727.zip`  
**Result:** source, browser UI, tests, documentation, wheel, hashes, and release
manifest updated together.

## What was independently re-verified

- Wallet suite from the received ZIP: **319 passed** before continuation work.
- Standalone BlackBox suite: **43 passed**.
- Source-bundle verifier: **27/27 passed**.
- The prior marker-deletion and passkey-lifetime fixes are present in source,
  not merely described in documentation.

## Additional defects found and fixed

### 1. Browser protected flows could not open a locked Vault

Four UI paths called `/vault/open` without the request body now required by the
server. Promote, Retire/Restore, LabCopy export, and the Vault toggle would fail
at the locked-Vault boundary.

**Fix:** every caller now creates or reuses the local session first, obtains a
fresh passkey approval scoped to `open_vault`, and submits both values. The
browser's ceremony-method name was also corrected to one recognized by the
server's Human Intent policy.

### 2. Retire's configured Head User/admin gate was inert

The registry correctly marked Retire as requiring configured authority, but
the transaction coordinator omitted `vault_id` when evaluating the policy.
That omission skipped the role check.

**Fix:** the coordinator has an explicit canonical vault ID (`vault` by
default), validates it at construction, and supplies it to the policy engine.

### 3. Self-declared identity could decide an approval through HTTP

The local development identity issuer accepts caller-provided actor and
verification claims. The manager required a session, but the HTTP decision
route did not add an independent cryptographic gate.

**Fix:** in hardened mode the route consumes a one-use passkey token scoped to
`decide_approval` plus the exact `approval_id` before it evaluates the local
identity session. Passkey-off development mode remains explicitly
provider-neutral.

## Focused issue-discovery tests

1. **Authentication/authorization/replay campaign — 33 passed**
   - Real WebAuthn signature simulation
   - challenge and scope binding
   - token replay/restart behavior
   - revoked-credential rejection
   - ceremony-token and identity boundaries
   - self-declared approval exploit regression

2. **Custody-integrity/fault campaign — 38 passed**
   - Retire/Restore crash recovery and ambiguity freezes
   - concurrent catalog and incident-bundle behavior
   - runtime-residue exact-identity deletion
   - durable I/O no-delete law
   - BlackBox outbox partial-write and integrity behavior

## Final verification

- Wallet: **322 passed**
- BlackBox: **43 passed**
- Source-bundle checks: **27/27 passed**
- Authentication campaign: **33 passed**
- Integrity/fault campaign: **38 passed**
- Browser JavaScript syntax: **passed**
- Python compile scan: **47 source files passed**

## Remaining release blockers

These are not concealed as completed:

- first-passkey enrollment is still a local bootstrap without a separately
  delivered setup secret;
- the local identity issuer is still provider-neutral/self-asserted, although
  protected operations and approval decisions are passkey-gated in hardened
  mode;
- physical Windows Hello/phone/FIDO2 validation is still required;
- Windows service identity, NTFS ACL isolation, signed installer/update
  lifecycle, sealed-vault recovery, independent penetration testing,
  accessibility testing, and field recovery rehearsal remain incomplete.

See `source_2.5.0a11_merged/KNOWN_LIMITATIONS_2.5.0a11.md` for the complete
market-release boundary.
