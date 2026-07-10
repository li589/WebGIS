@echo off
REM ============================================================
REM CGDA 后端一键启动脚本（Windows）
REM ============================================================
setlocal enabledelayedexpansion

set "SCRIPT_DIR=%~dp0"
set "BACKEND_DIR=%SCRIPT_DIR%Code\backend"
set "PYTHON=python"

REM ---- 检查 Python ----
%PYTHON% --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python 未找到，请确保 Python 在 PATH 中
    exit /b 1
)

REM ---- 检查 Docker ----
docker info >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Docker 未运行或未安装
    exit /b 1
)

echo.
echo ============================================================
echo  启动 CGDA 后端基础设施
echo ============================================================
echo.

REM ---- 启动 Redis + MinIO ----
echo [1/3] 启动 Redis + MinIO...
cd /d "%BACKEND_DIR%"
docker compose up -d redis minio minio-init
if errorlevel 1 (
    echo [ERROR] Docker Compose 启动失败
    exit /b 1
)
echo        Redis:   redis://127.0.0.1:6379/0
echo        MinIO:   http://127.0.0.1:9000  (Console: http://127.0.0.1:9001)
echo.

REM ---- 等待 Redis 就绪 ----
echo [2/3] 等待 Redis 就绪...
set "redis_ok=0"
for /L %%i in (1,1,30) do (
    docker exec cgda-redis redis-cli ping >nul 2>&1
    if not errorlevel 1 (
        set "redis_ok=1"
        goto :redis_ready
    )
    timeout /t 1 /nobreak >nul
)
:redis_ready
if "%redis_ok%"=="1" (
    echo        Redis 就绪
) else (
    echo [WARN] Redis 未在 30 秒内就绪，继续...
)
echo.

REM ---- 等待额外缓冲时间确保 Redis 完全就绪 ----
timeout /t 5 /nobreak >nul

REM ---- 启动 Celery Workers ----
echo [3/3] 启动 Celery Workers（7 个队列）...
echo        所有 worker 日志输出到 .data\logs\worker-{queue}.log

REM 创建日志目录
if not exist "%BACKEND_DIR%\.data\logs" mkdir "%BACKEND_DIR%\.data\logs"
if not exist "%BACKEND_DIR%\.data\workflow_state" mkdir "%BACKEND_DIR%\.data\workflow_state"
if not exist "%BACKEND_DIR%\.data\artifacts" mkdir "%BACKEND_DIR%\.data\artifacts"
if not exist "%BACKEND_DIR%\.data\cache" mkdir "%BACKEND_DIR%\.data\cache"

start "CGDA-Worker: realtime" /min %PYTHON% "%BACKEND_DIR%\start_celery_worker.py" worker --loglevel=INFO --queues=realtime --hostname=worker-realtime@%COMPUTERNAME% -f "%BACKEND_DIR%\.data\logs\worker-realtime.log"
start "CGDA-Worker: standard" /min %PYTHON% "%BACKEND_DIR%\start_celery_worker.py" worker --loglevel=INFO --queues=standard --hostname=worker-standard@%COMPUTERNAME% -f "%BACKEND_DIR%\.data\logs\worker-standard.log"
start "CGDA-Worker: heavy" /min %PYTHON% "%BACKEND_DIR%\start_celery_worker.py" worker --loglevel=INFO --queues=heavy --hostname=worker-heavy@%COMPUTERNAME% -f "%BACKEND_DIR%\.data\logs\worker-heavy.log"
start "CGDA-Worker: batch" /min %PYTHON% "%BACKEND_DIR%\start_celery_worker.py" worker --loglevel=INFO --queues=batch --hostname=worker-batch@%COMPUTERNAME% -f "%BACKEND_DIR%\.data\logs\worker-batch.log"
start "CGDA-Worker: download" /min %PYTHON% "%BACKEND_DIR%\start_celery_worker.py" worker --loglevel=INFO --queues=download-realtime,download-standard --hostname=worker-download@%COMPUTERNAME% -f "%BACKEND_DIR%\.data\logs\worker-download.log"
start "CGDA-Worker: gee-standard" /min %PYTHON% "%BACKEND_DIR%\start_celery_worker.py" worker --loglevel=INFO --queues=gee-realtime,gee-standard,gee-heavy,gee-batch --hostname=worker-gee@%COMPUTERNAME% -f "%BACKEND_DIR%\.data\logs\worker-gee.log"
start "CGDA-Worker: weather-standard" /min %PYTHON% "%BACKEND_DIR%\start_celery_worker.py" worker --loglevel=INFO --queues=weather-realtime,weather-standard,weather-heavy,weather-batch --hostname=worker-weather@%COMPUTERNAME% -f "%BACKEND_DIR%\.data\logs\worker-weather.log"

echo        Workers 已启动（最小化窗口中运行）
echo.

REM ---- 启动 Celery Beat（定时任务调度器，仅当天气定时启用时需要）----
start "CGDA-CeleryBeat" /min %PYTHON% "%BACKEND_DIR%\start_celery_beat.py" --loglevel=INFO -f "%BACKEND_DIR%\.data\logs\beat.log"

echo        Celery Beat 已启动（天气定时刷新调度器）
echo.

REM ---- 启动 FastAPI ----
echo ============================================================
echo  启动 FastAPI 后端服务
echo ============================================================
echo  API:  http://127.0.0.1:8000
echo  Docs: http://127.0.0.1:8000/docs
echo  (按 Ctrl+C 停止)
echo.
cd /d "%BACKEND_DIR%"
start "CGDA-FastAPI" %PYTHON% "%BACKEND_DIR%\start_fastapi.py"
timeout /t 3 /nobreak >nul

echo ============================================================
echo  启动完成！
echo ============================================================
echo.
echo  停止方式: run_stop.bat
echo.
pause
