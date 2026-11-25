# Known limitations — Iteration Wallet 2.5.0a10

This build is an advanced local alpha with a substantially completed product surface. It is not yet a certified production security product.

## Security boundary

- Passkeys gate issuance of protected ceremony tokens. They do **not** yet unseal a master Wallet encryption key from TPM/DPAPI.
- Registration requests `attestation: none`; the first local enrollment does not prove a manufacturer attestation chain.
- Phone approval uses the browser and operating system's WebAuthn/passkey flow, including hybrid/cross-device authenticators where the platform offers them. There is no separate remote push-notification service.
- There is no recovery-code bypass, enterprise MDM binding, or centrally managed recovery path.
- A compromised operating system, local administrator, malicious browser, or attacker controlling an unlocked session remains outside this alpha's protection claim.
- BlackBox is tamper-evident local evidence, not an independent remote witness.

## Custody workflow

- Remove from active use, restore, and release from custody remain deliberately unavailable until their transaction contracts are complete.
- LabCopy can export a signed working copy and return changed material only as a new Candidate. It does not replace Prime in place.
- Legacy Oubliette backend code and historical tests remain for compatibility and provenance, but Oubliette is absent from the supported UI and CLI.

## Product distribution

- The bundle includes tested pure-Python alpha wheels and source launchers, not a signed Windows installer.
- First-run source installation needs Python 3.10+ and access to required third-party packages unless an offline wheelhouse is supplied.
- Automatic updates, rollback, crash telemetry, code signing, and installer reputation are not implemented.
- The physical Windows Hello and phone-passkey ceremony could not be exercised in the Linux build container. Cryptographic registration/assertion verification was exercised with generated credentials, and browser UI flows were headlessly executed.
- Direct Chromium navigation to the live loopback server was blocked by the build environment's browser policy. The server was tested over loopback with HTTP smoke calls, while the UI was executed headlessly with mocked API responses and no page-script errors.

## UI and accessibility

- Desktop trays support drag, resize, dock, collapse, reflow, workspace persistence, import/export, and keyboard movement.
- Narrow screens use a deliberate one-column document layout rather than freeform tray manipulation. Long custody forms remain vertically lengthy on phones.
- Accessibility has keyboard/focus and reduced-motion support, but it has not received an independent WCAG audit or assistive-technology certification.
- Localization is not implemented.

## Release assurance still required

Before describing the product as production-ready, complete at least: independent threat modeling, penetration testing, Windows hardware validation, signed installer/update work, recovery design, destructive-transition completion, accessibility audit, and a real-user usability trial.
