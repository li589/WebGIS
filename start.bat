@echo off
REM ============================================================
REM  CGDA 一键启动 (Windows)
REM  强制使用仓库内 Env\Python312\python.exe（本地联调唯一解释器）
REM
REM  用法:
REM    start.bat                         → start all
REM    start.bat start [component] ...
REM    start.bat stop | status | restart | logs | flush | sync
REM ============================================================
setlocal
set "SCRIPT_DIR=%~dp0"
set "ENV_PY=%SCRIPT_DIR%Env\Python312\python.exe"

if not exist "%ENV_PY%" (
    echo [ERROR] 未找到本地联调解释器:
    echo         %ENV_PY%
    echo         本仓库必须使用 Env\Python312，请勿改用系统 PATH 中的 python。
    pause
    exit /b 1
)

echo [INFO] Python: %ENV_PY%

if "%~1"=="" (
    "%ENV_PY%" "%SCRIPT_DIR%launch.py" start
) else (
    "%ENV_PY%" "%SCRIPT_DIR%launch.py" %*
)

set "ERR=%ERRORLEVEL%"
if not "%ERR%"=="0" (
    echo.
    echo [ERROR] 启动器返回错误码 %ERR%
    pause
)
endlocal & exit /b %ERR%
