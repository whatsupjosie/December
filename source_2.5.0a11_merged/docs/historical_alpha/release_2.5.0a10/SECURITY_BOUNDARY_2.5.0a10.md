# Security Boundary — Iteration Wallet 2.5.0a10

## Protected-action path

1. The browser asks the local Wallet server for a fresh WebAuthn challenge.
2. Windows Hello, a phone passkey, or a FIDO2 authenticator performs user verification and signs the challenge.
3. Wallet verifies client data, challenge, exact origin, RP ID hash, user-presence and user-verification flags, signature, and counter behavior.
4. Wallet mints a signed hardware-gate token containing one action key, one exact context, a short expiry, and a random nonce.
5. The ceremony-token endpoint consumes that token once before issuing the existing scoped Human Intent ceremony token.
6. The custody transaction performs its own proposal/hash/session checks and records the result through BlackBox.

The hardware token cannot be reused, expanded to another action, or applied to a different project, section, object, proposal, or proposal hash.

## Stored material

Wallet stores:

- the public WebAuthn credential in DER SubjectPublicKeyInfo form;
- the credential ID, algorithm, transports, attachment, label, and signature counter;
- a local HMAC secret for short-lived gate tokens;
- no fingerprint, face image, biometric template, authenticator private key, or Windows PIN.

Authority files are written with the same descriptor-based, private, atomic JSON path used by other Wallet authority records.

## Enrollment trust caveat

Registration requests `attestation: none` and uses browser-exposed standard public-key/authenticator-data accessors. The first local enrollment therefore trusts the local browser ceremony and does not prove a hardware manufacturer attestation chain. Subsequent authentications are verified cryptographically against the enrolled public key.

## Not yet implemented

- TPM/DPAPI sealing and unsealing of the Wallet master encryption key.
- Remote push-notification infrastructure.
- Independently attested device provenance.
- Enterprise device policy, MDM binding, or centrally managed recovery.
- A recovery-code bypass. Adding one carelessly would weaken the passkey boundary.
- Protection against malware or an administrator already controlling the operating system.
