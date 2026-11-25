# Security review patch — 2026-07-27

This patch is additive to Iteration Wallet 2.5.0a11. It preserves every
uploaded original and changes only the reviewed working copy.

## Confirmed fixes

1. **Runtime-residue marker deletion**
   - Marker size and SHA-256 are captured after the signed marker is validated.
   - Revalidation requires the planned marker identity to match.
   - Deletion uses the pinned marker values instead of checking the current
     file against a hash calculated from itself.

2. **Additional passkey enrollment**
   - Once one credential exists, registration options require a fresh
     `manage_passkeys` approval scoped to `operation=enroll_passkey`.
   - The approval is carried by the single-use in-memory registration
     challenge.
   - Two simultaneous first-run challenges cannot both bootstrap credentials;
     the stale second challenge is rejected after the first credential lands.

3. **Hardware-gate token lifetime**
   - Consumed nonces are durably stored and remain blocked after restart.
   - A token minted by a credential that is later revoked is rejected even if
     the token has not yet expired.

4. **Regression-suite coherence**
   - Four stale tests that still passed bare usernames into the hardened
     approval-decision path now create and use verified human identity
     sessions.

5. **Approval-decision HTTP boundary**
   - In hardened mode, the decision route consumes a fresh passkey token
     scoped to `action_key=decide_approval` and the exact `approval_id`.
   - A caller-created local "human" session can no longer decide an approval
     through the API without the enrolled authenticator.

6. **Retire role-policy binding**
   - The state-transition coordinator now supplies the canonical Wallet
     `vault_id` to the gatekeeper.
   - A configured Head User/admin restriction on Retire is no longer silently
     skipped.

7. **Browser Vault-open repair**
   - Promote, Retire/Restore, LabCopy, and the Vault toggle now create/reuse
     the identity session first, obtain a fresh `open_vault` passkey approval,
     and send the complete request body.
   - Browser Human Intent method names now match the server policy vocabulary.

## Verification

- Targeted authentication/authorization campaign: **33 passed**
- Targeted custody-integrity/fault campaign: **38 passed**
- Complete Wallet suite: **322 passed**
- Standalone BlackBox suite: **43 passed**
- Source-bundle verification: **27/27 passed**
- Python syntax compilation: **passed**

## Explicitly unresolved

- The first credential remains a local first-run trust bootstrap. A separate
  setup secret or equivalent owner-binding ceremony is still required before
  this can be treated as a hostile-local-process security boundary.
- Registration uses `attestation: none`; authenticator manufacturer provenance
  is not established.
- The private-alpha local identity-session issuer remains provider-neutral and
  self-asserted. It is not a production authentication provider.
- Runtime-residue directories are owner-only, but portable pathname deletion
  cannot by itself defend against a malicious concurrent process running as
  the same operating-system account. The marker fix closes the identified
  plan-to-execute inconsistency; Windows service identity and ACL isolation
  remain the intended production boundary.
