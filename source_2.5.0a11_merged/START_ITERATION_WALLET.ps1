$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
if (-not (Test-Path '.venv\Scripts\python.exe')) { py -3 -m venv .venv }
& '.venv\Scripts\python.exe' -m pip install --disable-pip-version-check -q -e '.\blackbox_source' -e '.'
$env:ITERATION_WALLET_ROOT = Join-Path $PSScriptRoot 'wallet_home'
$env:IW_OUBLIETTE_MODE = 'disabled'
$env:IW_REQUIRE_PASSKEY = 'required'
$env:IW_WEBAUTHN_RP_ID = 'localhost'
$env:IW_WEBAUTHN_ORIGINS = 'http://localhost:7432'
& '.venv\Scripts\python.exe' app.py
