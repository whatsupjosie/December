# Installation — Iteration Wallet 2.5.0a11

## Recommended Windows source launch

1. Extract the handoff ZIP to a normal writable development folder.
2. Double-click `START_ITERATION_WALLET.bat`.
3. Allow the first-run environment installation to finish.
4. Use the browser window at `http://localhost:7432`.
5. Open the **Phone / biometric gate** tray and enroll at least two independent passkeys or FIDO2 authenticators before relying on the vault.

Runtime state is stored under `wallet_home`. The launcher disables Oubliette as an active workflow, uses LabCopy for external work, requires passkey enrollment before protected actions, and scopes WebAuthn to `localhost`.

## PowerShell launch

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\START_ITERATION_WALLET.ps1
```

## Manual source install

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .\blackbox_source -e .
$env:ITERATION_WALLET_ROOT = "$PWD\wallet_home"
$env:IW_OUBLIETTE_MODE = "disabled"
$env:IW_REQUIRE_PASSKEY = "required"
$env:IW_WEBAUTHN_RP_ID = "localhost"
$env:IW_WEBAUTHN_ORIGINS = "http://localhost:7432"
.\.venv\Scripts\python.exe app.py
```

## Wheel install

```powershell
python -m pip install .\dist\bbx1_iteration_wallet_plugin-0.6.0a4-py3-none-any.whl .\dist\iteration_wallet-2.5.0a11-py3-none-any.whl
```

Third-party dependencies must be available from the configured package index or an offline wheelhouse.

## Verify

```powershell
iw doctor
python RUN_VERIFICATION.py
```

`iw doctor` checks installed versions, client-schema compatibility, package ownership, and runtime imports. `RUN_VERIFICATION.py` checks the permanent-preservation contract, route surface, passkey defaults, source compilation, browser JavaScript syntax, bounded canonical flow, release files, and wheel presence without touching custody content.

## Important distribution boundary

The current handoff is not a signed Windows installer and does not yet install the planned protected Windows service identities or custody ACLs. Do not describe this ZIP as the final consumer installer. See `KNOWN_LIMITATIONS_2.5.0a11.md`.
