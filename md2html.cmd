@echo off
setlocal

REM 可选：在外部设置 MD2ANKI_PYTHON 指定 Python，例如：
REM set MD2ANKI_PYTHON=C:\path\to\.venv\Scripts\python.exe
if not defined MD2ANKI_PYTHON (
  set "MD2ANKI_PYTHON=python"
)

REM 可选：在外部设置 MD2HTML_COLLECTION_ROOT 覆盖默认 collection root。
REM 默认 collection root 为 D:\JSRS。

REM ====== 运行目录：以 .cmd 所在目录作为 Vault Root ======
for %%I in ("%~dp0.") do set "VAULT_ROOT=%%~fI"
for %%I in ("%VAULT_ROOT%") do set "VAULT_NAME=%%~nI"

if not defined MD2HTML_COLLECTION_ROOT (
  set "COLLECTION_ROOT=D:\JSRS"
) else (
  set "COLLECTION_ROOT=%MD2HTML_COLLECTION_ROOT%"
)

echo [md2html-launcher] vault-root=%VAULT_ROOT%
echo [md2html-launcher] inferred-vault-name=%VAULT_NAME%
echo [md2html-launcher] collection-root=%COLLECTION_ROOT%
echo [md2html-launcher] mode=html
echo [md2html-launcher] python=%MD2ANKI_PYTHON%

REM 你也可以双击外加参数（例如 --file "A/B.md"）
%MD2ANKI_PYTHON% -m md2anki --to-html --vault-root "%VAULT_ROOT%" --collection-root "%COLLECTION_ROOT%" --show-progress %*
set "EXIT_CODE=%ERRORLEVEL%"

echo [md2html-launcher] exit-code=%EXIT_CODE%
if not "%EXIT_CODE%"=="0" (
  echo [md2html-launcher] 执行失败，请查看上面的错误输出。
)
pause
exit /b %EXIT_CODE%
