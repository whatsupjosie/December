# Iteration Wallet UI + LabCopy integration pass — 2026-07-24

## Canonical base
- Recovered actual source: Iteration Wallet 2.5.0a7 + BlackBox 0.6.0a3.
- UI donor: latest Vector Tray Renderer / cinematic spatial tray build.

## Changes
- Replaced the older flat UI with the polished spatial mechanical-tray interface.
- Removed Oubliette from the primary visible workflow.
- Added a complete LabCopy UI for proposal, scoped export ceremony, returned-byte capture, admission proposal, and Candidate-only return.
- Preserved legacy Oubliette backend routes for compatibility; they are not presented as the product's external-work path.
- Added a browser WebAuthn user-verification ceremony that can invoke Windows Hello, a platform fingerprint/Face ID authenticator, or a nearby passkey phone where the browser supports it.
- Biometric status is deliberately described as a local ceremony check, not yet as cryptographic master-key release. Server-side credential registration and assertion verification remain a hardening gate.

## Product truth
The LabCopy transaction path is wired to the tested 2.5.0a7 API. The UI is substantially closer to a professional product shell, but this package does not claim production-grade phone-bound key release or independent security certification.
