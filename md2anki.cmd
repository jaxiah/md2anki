@echo off
setlocal

REM 可选：在外部设置 MD2ANKI_PYTHON 指定 Python，例如：
REM set MD2ANKI_PYTHON=C:\path\to\.venv\Scripts\python.exe
if not defined MD2ANKI_PYTHON (
  set "MD2ANKI_PYTHON=python"
)

REM ====== 运行目录：以 .cmd 所在目录作为 Vault Root ======
for %%I in ("%~dp0.") do set "VAULT_ROOT=%%~fI"
for %%I in ("%VAULT_ROOT%") do set "VAULT_NAME=%%~nI"

echo [md2anki-launcher] vault-root=%VAULT_ROOT%
echo [md2anki-launcher] inferred-vault-name=%VAULT_NAME%
echo [md2anki-launcher] mode=apply
echo [md2anki-launcher] python=%MD2ANKI_PYTHON%

REM 默认 apply；你也可以双击外加参数（例如 --file "A/B.md"）
"%MD2ANKI_PYTHON%" -m md2anki --to-anki --vault-root "%VAULT_ROOT%" --show-progress --apply-anki-changes %*
set "EXIT_CODE=%ERRORLEVEL%"

echo [md2anki-launcher] exit-code=%EXIT_CODE%
if not "%EXIT_CODE%"=="0" (
  echo [md2anki-launcher] 执行失败，请查看上面的错误输出。
)
pause
exit /b %EXIT_CODE%
