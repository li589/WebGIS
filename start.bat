@echo off
REM ============================================================
REM  CGDA 一键启动 (Windows)
REM  调用跨平台 Python 启动器 launch.py
REM
REM  用法:
REM    start.bat                         → start all
REM    start.bat start [component] ...
REM    start.bat stop | status | restart | logs | flush | sync
REM ============================================================
setlocal
set "SCRIPT_DIR=%~dp0"

where python >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python 未找到，请确保 Python 在 PATH 中
    pause
    exit /b 1
)

if "%~1"=="" (
    python "%SCRIPT_DIR%launch.py" start
) else (
    python "%SCRIPT_DIR%launch.py" %*
)

set "ERR=%ERRORLEVEL%"
if not "%ERR%"=="0" (
    echo.
    echo [ERROR] 启动器返回错误码 %ERR%
    pause
)
endlocal & exit /b %ERR%
