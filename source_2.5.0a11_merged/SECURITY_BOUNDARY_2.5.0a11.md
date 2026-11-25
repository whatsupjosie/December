# Security Boundary — Iteration Wallet 2.5.0a11

## Permanent-preservation boundary

Iteration Wallet has no supported operation that reduces or discards admitted protected content. BlackBox rotation, migration, repair, and checkpointing are additive. State changes describe what they literally do:

- **Retire** changes active status while preserving the object, bytes, identity, relationships, and evidence.
- **Restore** returns a retired object to active status.
- **Archive** changes long-term organizational status while preserving content.
- **Quarantine** isolates material while preserving content and evidence.
- **Export** creates a separate verified working copy; custody content remains preserved.
- **Revoke passkey** ends that credential's future authority while preserving its credential history.

Retire and Restore are implemented as exact Wallet-owned coordinated transactions. They require a verified human identity session, a fresh action- and object-scoped ceremony token, a durable recovery journal, no-clobber custody publication, canonical BlackBox facts, and a verified portable receipt. The prior active directory entry is preserved as private transition evidence. Current Prime cannot be retired directly; a replacement must first be promoted. Legacy ambiguous routes and direct public engine bypass methods remain absent.

## Runtime-residue boundary

Physical cleanup is limited to `iteration_wallet.runtime_residue.RuntimeResidueRegistry`. An artifact is eligible only when all of the following are true:

1. It resides under one dedicated runtime-residue class root.
2. The class is on the fixed allowlist.
3. It is one regular file, not a symlink or hard link.
4. It has a signed Wallet ownership marker.
5. Device, inode, size, and SHA-256 match the marker.
6. Its retention period has elapsed.
7. It has no authoritative references.
8. The exact candidate is revalidated immediately before cleanup.
9. A permanent receipt is written before execution and finalized afterward.

The cleaner does not sweep arbitrary directories, follow links, infer ownership from filenames, or operate on custody, evidence, backup, recovery, or exported-vault locations. Anything uncertain remains preserved.

## Protected-action path

1. The browser requests a fresh WebAuthn challenge from the local Wallet service.
2. Windows Hello, a phone passkey where supported, or an external FIDO2 authenticator performs user verification and signs the challenge.
3. Wallet verifies client data, challenge, exact origin, RP ID hash, user-presence and user-verification flags, signature, and counter behavior.
4. Wallet mints a short-lived one-use hardware-gate token bound to one action and exact context.
5. The ceremony-token endpoint consumes that token once before issuing the scoped Human Intent ceremony token.
6. The custody coordinator rechecks proposal, hashes, identity session, object scope, and current state.
7. BlackBox records the canonical facts and receipt.

A fresh installation requires passkey enrollment before protected operations. Credential revocation requires an exact `manage_passkeys` approval, preserves revocation history, and cannot leave the installation with zero active credentials.

## Stored authentication material

Wallet stores public credential material, credential identifiers and metadata, signature counters, preserved revocation history, and a local HMAC key for short-lived gate tokens. It does not receive biometric templates, authenticator private keys, or the Windows PIN.

## Current host boundary

The 2.5.0a11 source handoff does not yet install the planned non-interactive Windows custody service identity, separate BlackBox witness identity, or final NTFS ACL layout. Therefore the current build does not yet claim that ordinary same-user applications are technically unable to access the runtime folder. That is a release blocker, not a completed guarantee.

The final Windows architecture must put custody bytes behind a service-owned broker and make the interactive account unable to move, rename, alter, or directly access protected storage. Administrator, kernel, firmware, offline-disk, and physical-destruction compromise remain outside any honest local-software guarantee.
