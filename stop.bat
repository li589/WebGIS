@echo off
REM ============================================================
REM  CGDA 一键停止 (Windows)
REM  调用跨平台 Python 启动器 launch.py stop
REM ============================================================
setlocal
set "SCRIPT_DIR=%~dp0"

python "%SCRIPT_DIR%launch.py" stop
pause
endlocal
