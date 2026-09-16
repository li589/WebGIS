@echo off
REM ============================================================
REM  CGDA 一键启动 (Windows)
REM  强制使用仓库内 Env\Python312\python.exe（本地联调唯一解释器）
REM
REM  【重要】Docker Desktop 与本终端建议以管理员身份运行；
REM  否则可能出现镜像无法访问、volume/配置读取失败等问题。
REM  默认启动【含】Nginx Gateway（同域入口 http://localhost:5175）。
REM  本地前端 HMR: start.bat start --vite（入口仍 :5175，背后 Vite :5174）
REM  可选单启网关: start.bat start gateway（见 Code\infra\gateway\README.md）
REM
REM  用法:
REM    start.bat                         → start all
REM    start.bat start [component] ...
REM    start.bat start gateway
REM    start.bat stop | stop gateway | status | restart | logs | flush | sync
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
echo [INFO] Windows: 请确认 Docker Desktop 以管理员身份运行（镜像/配置访问依赖此权限）

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
