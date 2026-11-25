@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  py -3 -m venv .venv || goto :fail
)
call ".venv\Scripts\activate.bat"
python -m pip install --disable-pip-version-check -q -e ".\blackbox_source" -e "." || goto :fail
set ITERATION_WALLET_ROOT=%~dp0wallet_home
set IW_OUBLIETTE_MODE=disabled
set IW_REQUIRE_PASSKEY=required
set IW_WEBAUTHN_RP_ID=localhost
set IW_WEBAUTHN_ORIGINS=http://localhost:7432
python app.py
goto :eof
:fail
echo.
echo Iteration Wallet could not start. Review the message above.
pause
exit /b 1
