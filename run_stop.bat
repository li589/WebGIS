@echo off
REM ============================================================
REM CGDA 后端停止脚本（Windows）
REM ============================================================
set "SCRIPT_DIR=%~dp0"
set "BACKEND_DIR=%SCRIPT_DIR%Code\backend"

echo.
echo ============================================================
echo  停止 CGDA 后端服务
echo ============================================================
echo.

REM ---- 关闭 FastAPI / Celery 进程 ----
echo [1/2] 停止 FastAPI 和 Celery Worker 进程...
taskkill /FI "WINDOWTITLE eq CGDA*" /F >nul 2>&1
REM 额外清理可能残留的 worker 进程（python.exe 调用 start_celery_worker.py）
for /f "tokens=2" %%p in ('tasklist /FI "WINDOWTITLE eq *worker*" /FO LIST ^| findstr "PID:"') do taskkill /PID %%p /F >nul 2>&1

REM ---- 停止 Docker 容器 ----
echo [2/2] 停止 Redis + MinIO 容器...
cd /d "%BACKEND_DIR%"
docker compose down >nul 2>&1

echo.
echo ============================================================
echo  停止完成
echo ============================================================
echo.
pause
