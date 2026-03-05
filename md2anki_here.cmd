@echo off
setlocal

REM ====== 配置区（按你的本机实际路径修改）======
set "PROJECT_ROOT=D:\JBYO\md2anki"
set "PYTHON_EXE=%PROJECT_ROOT%\.venv\Scripts\python.exe"

REM ====== 运行目录：以 .cmd 所在目录作为 Vault Root ======
for %%I in ("%~dp0.") do set "VAULT_ROOT=%%~fI"
for %%I in ("%VAULT_ROOT%") do set "VAULT_NAME=%%~nI"

if not exist "%PYTHON_EXE%" (
  echo [md2anki-launcher] Python not found: %PYTHON_EXE%
  echo [md2anki-launcher] 请检查 PROJECT_ROOT 或先创建 .venv
  pause
  exit /b 1
)

echo [md2anki-launcher] vault-root=%VAULT_ROOT%
echo [md2anki-launcher] inferred-vault-name=%VAULT_NAME%
echo [md2anki-launcher] mode=apply

REM 不依赖 pip install -e .：直接通过 PYTHONPATH 指向项目源码
set "PYTHONPATH=%PROJECT_ROOT%;%PYTHONPATH%"

REM 默认 apply；你也可以双击外加参数（例如 --file "A/B.md"）
"%PYTHON_EXE%" -m md2anki --vault-root "%VAULT_ROOT%" --show-progress --apply-anki-changes %*
set "EXIT_CODE=%ERRORLEVEL%"

echo [md2anki-launcher] exit-code=%EXIT_CODE%
if not "%EXIT_CODE%"=="0" (
  echo [md2anki-launcher] 执行失败，请查看上面的错误输出。
)
pause
exit /b %EXIT_CODE%
