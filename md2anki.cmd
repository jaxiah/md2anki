@echo off
setlocal

REM Optionally set MD2ANKI_PYTHON to select a Python interpreter, for example:
REM set MD2ANKI_PYTHON=C:\path\to\.venv\Scripts\python.exe
if not defined MD2ANKI_PYTHON (
  set "MD2ANKI_PYTHON=python"
)

REM Use the directory containing this script as the vault root.
for %%I in ("%~dp0.") do set "VAULT_ROOT=%%~fI"

REM Apply by default. Extra arguments such as --file "A/B.md" are forwarded.
REM Pass --verbose explicitly when per-item progress details are needed.
"%MD2ANKI_PYTHON%" -m md2anki --vault-root "%VAULT_ROOT%" --apply-anki-changes %*
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" (
  echo [md2anki-launcher] Failed with exit code %EXIT_CODE%. Review the errors above.
)
pause
exit /b %EXIT_CODE%
