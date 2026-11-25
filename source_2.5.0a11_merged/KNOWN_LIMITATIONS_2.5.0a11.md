# Known limitations — Iteration Wallet 2.5.0a11

This is a permanent-preservation hardening build. It is not yet the signed, independently reviewed market release.

## Release blockers

### Windows custody isolation

- Protected non-interactive Windows service identities are designed but not yet installed by this handoff.
- Final NTFS ACLs, service SID ownership, broker-only custody access, and local-console policy are not deployed.
- The current source launcher stores `wallet_home` beneath the extracted working folder; this is suitable for development validation, not the final protected storage class.
- A signed installer, repair path, upgrade rollback, uninstall preservation test, and installer reputation work remain incomplete.

### Physical authentication validation

- WebAuthn assertion verification is covered by automated tests.
- The first enrolled credential is still a local first-run trust bootstrap.
  The current API does not yet bind that first enrollment to a separately
  delivered setup secret or verify manufacturer attestation. After the first
  credential exists, every additional enrollment requires a fresh approval
  from an active passkey.
- Windows Hello, phone-hybrid authentication, and multiple physical FIDO2 vendors still require on-device validation on supported Windows hardware.
- Registration uses `attestation: none`; manufacturer provenance is not certified.
- A complete lost-authenticator recovery policy and sealed recovery ceremony remain to be finalized.

### Local identity boundary

- The local identity provider is a provider-neutral session interface, not a
  complete authentication provider.
- The private-alpha identity-session creation route still accepts caller-
  supplied actor kind and verification-method claims. Passkey approval remains
  the cryptographic gate for protected operations and approval decisions, but
  a production identity issuer must replace this self-asserted development
  surface before market release.

### Portable sealed vault

- The `.iwvault` encrypted full-vault snapshot format is designed but not implemented in this build.
- FIDO PRF/hmac-secret capability discovery, multiple key slots, machine-bound slots, strong recovery passphrase slots, chunked authenticated encryption, and independent recovery tooling remain release work.

### Custody workflow closure

- Canonical Retire and Restore transactions are implemented for Raw Source, Candidate, and Archive objects, including restart reconciliation and verified Human Intent receipts.
- Current Prime cannot be retired directly; the operator must first promote a replacement so a section never loses its current trusted reference through retirement.
- Retire/Restore crash and ambiguity behavior is covered by automated fault-injection tests, but Windows power-loss and filesystem-filter interoperability still require physical-machine campaigns.
- LabCopy export and Candidate-only return are the supported external-work path.
- Legacy Oubliette compatibility remains backend-only for old alpha material and requires a final compatibility-retirement review.

### Independent assurance

- No independent penetration test, formal external threat-model review, accessibility audit, or field usability pilot has been completed.
- No production code-signing or update-signing incident-response drill has been completed.
- BlackBox is tamper-evident local evidence, not yet an independently anchored remote witness.

## Product behavior already enforced

- Protected content and BlackBox evidence are preserved.
- Only signed, individually registered, non-authoritative runtime residue can be physically cleaned.
- Passkey enrollment is required by default before protected operations.
- Additional passkey enrollment requires approval from an already active
  passkey.
- Used hardware-gate tokens remain non-replayable after restart, and tokens
  from revoked credentials are rejected.
- Credential revocation preserves history and cannot revoke the final active credential.
- Wallet does not execute custodied project material.
- Returned LabCopy material cannot replace Prime in place and enters only as a Candidate.
- Legacy unsupported custody routes are absent from the published API.
- Exact Retire and Restore routes preserve protected bytes, prior-path transition evidence, state history, and canonical receipts.

## Market-release gate

Do not label the product market-ready until the Windows service/ACL architecture, signed installer lifecycle, physical authenticator matrix, sealed-vault recovery path, independent security review, accessibility audit, and real-user recovery rehearsal are complete with evidence.
