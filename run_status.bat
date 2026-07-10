@echo off
REM ============================================================
REM CGDA 后端状态检查脚本（Windows）
REM ============================================================
setlocal enabledelayedexpansion

set "BACKEND_DIR=%~dp0Code\backend"

echo.
echo ============================================================
echo  CGDA 后端状态检查
echo ============================================================
echo.

REM ---- Docker 容器 ----
echo [Docker 容器]
docker compose -f "%BACKEND_DIR%\docker-compose.yml" ps 2>nul
if errorlevel 1 echo   (Docker Compose 不可用)
echo.

REM ---- Redis 连通性 ----
echo [Redis 连通性]
docker exec cgda-redis redis-cli ping >nul 2>&1
if not errorlevel 1 (
    echo   OK - redis://127.0.0.1:6379/0
) else (
    echo   FAIL - Redis 未运行
)
echo.

REM ---- MinIO 健康检查 ----
echo [MinIO 健康检查]
docker exec cgda-minio mc ready local >nul 2>&1
if not errorlevel 1 (
    echo   OK - http://127.0.0.1:9000
) else (
    echo   FAIL - MinIO 未就绪
)
echo.

REM ---- Celery Workers ----
echo [Celery Workers]
for %%w in (realtime standard heavy batch gee weather) do (
    docker exec cgda-redis redis-cli -p 6379 KEYS "celery*%%w*" >nul 2>&1
    if not errorlevel 1 (
        echo   %%w: OK
    ) else (
        echo   %%w: ^(按窗口标题 "CGDA-Worker: %%w" 查找^)
    )
)
echo   注意: Worker 以最小化窗口运行，检查任务管理器确认进程存在
echo.

REM ---- FastAPI ----
echo [FastAPI 服务]
curl -s http://127.0.0.1:8000/docs >nul 2>&1
if not errorlevel 1 (
    echo   OK - http://127.0.0.1:8000
    echo   Docs: http://127.0.0.1:8000/docs
) else (
    echo   FAIL - FastAPI 未运行
)
echo.

echo ============================================================
echo  检查完成
echo ============================================================
pause
