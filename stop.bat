@echo off
REM ============================================================
REM  CGDA 一键停止 (Windows)
REM  强制使用 Env\Python312\python.exe
REM ============================================================
setlocal
set "SCRIPT_DIR=%~dp0"
set "ENV_PY=%SCRIPT_DIR%Env\Python312\python.exe"

if not exist "%ENV_PY%" (
    echo [ERROR] 未找到 %ENV_PY%
    echo         本仓库必须使用 Env\Python312。
    pause
    exit /b 1
)

echo [INFO] Python: %ENV_PY%
"%ENV_PY%" "%SCRIPT_DIR%launch.py" stop
set "ERR=%ERRORLEVEL%"
if not "%ERR%"=="0" pause
endlocal & exit /b %ERR%
