@echo off
REM ============================================================
REM  CGDA 一键启动 (Windows)
REM  调用跨平台 Python 启动器 launch.py
REM ============================================================
setlocal
set "SCRIPT_DIR=%~dp0"

REM 检测 Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python 未找到，请确保 Python 在 PATH 中
    pause
    exit /b 1
)

REM 转发所有参数给 launch.py
python "%SCRIPT_DIR%launch.py" %*

if errorlevel 1 (
    echo.
    echo [ERROR] 启动器返回错误码 %errorlevel%
    pause
)
endlocal
