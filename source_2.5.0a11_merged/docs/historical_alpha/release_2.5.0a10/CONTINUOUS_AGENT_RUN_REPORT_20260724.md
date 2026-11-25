# Continuous agent run report — 2026-07-24

## Release produced

- Iteration Wallet: **2.5.0a10**
- BlackBox: **0.6.0a3**
- Canonical BlackBox client schema: **bbx1-client/1**
- Supported external-work path: **LabCopy**
- Active Oubliette product surface: **retired from UI and CLI**

## Canonical-base decision

The run used the recovered Iteration Wallet 2.5.0a7 / BlackBox 0.6.0a3 source as the authority-bearing base, then integrated the latest spatial/vector tray work as a UI donor. Authority, custody, Human Intent, LabCopy, and BlackBox contracts were preserved rather than rewritten around a visual prototype.

## Completed product work

### 1. Spatial-tray interface

- Rebuilt the application around nine functional trays: Projects, Candidate Intake, LabCopy, Phone/Biometric Gate, Promotion, Generations, Boundary, Receipts, and Events.
- Added vector-owned mechanical silhouettes, layered brass/pearl/sapphire/emerald/amethyst/obsidian/copper materials, beveled seams, rivets, lighting, particles, and depth.
- Added tray drag, resize, collision settling, snapping, left/right docking, collapse, z-order, material cycling, and reflow.
- Added named workspaces, local persistence, import/export, reset, compact layout, and undo.
- Added keyboard tray movement, visible focus, reduced-motion handling, and responsive behavior.
- Corrected the narrow-screen layout to force every tray into one bounded column with no horizontal tray panning.

### 2. LabCopy promoted to the supported external-work path

- Removed Oubliette references and routes from the active UI.
- Removed Oubliette commands from the active CLI.
- Kept hidden compatibility code and historical tests so earlier alpha records are not silently destroyed.
- Exposed the tested LabCopy sequence in the UI: exact proposal, passkey/human authorization, HMAC export, external result capture, immutable return capsule, review, and Candidate-only admission.

### 3. Passkey / phone / biometric gate

- Added local WebAuthn registration and authentication routes.
- Added ES256, RS256, and Ed25519 public-key verification with `cryptography`.
- Verified client-data type, challenge, exact origin, RP ID hash, user-presence/user-verification flags, signature, user handle when provided, and authenticator counter behavior.
- Added multiple credential enrollment for platform authenticators, phone/hybrid passkeys, and security keys.
- Added short-lived, HMAC-signed, one-use hardware-gate tokens bound to one action and exact project/section/object/proposal context.
- Required those hardware tokens before the existing ceremony-token endpoint may issue protected-action authority.
- Added credential removal only after a fresh `manage_passkeys` approval scoped to the exact credential ID.

### 4. Startup and packaging

- Corrected runtime-root configuration to use `ITERATION_WALLET_ROOT` consistently.
- Corrected local WebAuthn scope to use the exact `localhost` origin printed by the launcher.
- Disabled Oubliette in both Windows launchers.
- Added one-click Batch and PowerShell launchers.
- Centralized Wallet, BlackBox, and schema versions.
- Rebuilt pure-Python Wallet and BlackBox wheels and performed a clean target-directory install/import smoke test.
- Updated the alpha migration utility to identify the 2.5.0a10 / 0.6.0a3 release.
- Moved stale alpha/Oubliette reports into `docs/historical_alpha/` rather than deleting them.

## Verification result

- Source/product verification: **16/16 passed**.
- Wallet pytest suite: **286 passed**.
- Standalone BlackBox pytest suite: **2 passed**.
- JavaScript syntax: **passed**.
- Python compile scan: **43 source files passed**.
- Desktop headless UI: **9 trays, no page-script errors**.
- Mobile headless UI: **9 trays, no page-script errors; all tray boxes bounded to 394 px inside a 430 px viewport**.
- Live loopback server smoke: root UI served, version 2.5.0a10 returned, passkey status returned, registration challenge issued for RP `localhost`.
- Clean wheel install: both distributions imported at their declared versions; LabCopy commands present; Oubliette commands absent; passkey verification route present.

## Honest release judgment

This run moves the project from a collection of alpha systems and visual experiments into a coherent, installable advanced alpha with a strong product identity and an internally consistent supported path. The UI is substantially complete enough for demonstration and hands-on alpha use. It is not yet appropriate to claim certified production security, TPM-backed master-key release, signed Windows distribution, independent attestation, or resistance to a compromised operating system.

See `KNOWN_LIMITATIONS_2.5.0a10.md` for the remaining release boundary.
