@echo off
REM ============================================================
REM CGDA Celery Worker 启动脚本（支持指定队列）
REM ============================================================
REM 用法:
REM   run_worker.bat                    # 启动所有队列的 worker
REM   run_worker.bat realtime           # 只启动 realtime 队列
REM   run_worker.bat standard heavy     # 启动 standard 和 heavy 队列
REM
REM 队列说明:
REM   realtime              - 实时数据工作流
REM   standard              - 标准数据工作流
REM   heavy                 - 重计算工作流
REM   batch                 - 批处理工作流
REM   download-realtime     - 实时下载
REM   download-standard     - 标准下载
REM   gee-realtime          - GEE 实时导出
REM   gee-standard          - GEE 标准导出
REM   gee-heavy             - GEE 重计算导出
REM   gee-batch             - GEE 批处理导出
REM   weather-realtime      - 天气实时
REM   weather-standard      - 天气标准
REM   weather-heavy         - 天气重计算
REM   weather-batch         - 天气批处理
REM ============================================================
setlocal enabledelayedexpansion

set "SCRIPT_DIR=%~dp0"
set "BACKEND_DIR=%SCRIPT_DIR%"
set "PYTHON=python"

cd /d "%BACKEND_DIR%"

REM 构建队列参数
set "queues="
if "%~1"=="" (
    set "queues=realtime,standard,heavy,batch,download-realtime,download-standard,analysis-standard,analysis-heavy,analysis-batch,algorithm-realtime,algorithm-standard,algorithm-heavy,algorithm-batch,gee-realtime,gee-standard,gee-heavy,gee-batch,weather-realtime,weather-standard,weather-heavy,weather-batch"
) else (
    for %%q in (%*) do (
        if defined queues (
            set "queues=!queues!,%%~q"
        ) else (
            set "queues=%%~q"
        )
    )
)

set "log_dir=%BACKEND_DIR%\.data\logs"
if not exist "%log_dir%" mkdir "%log_dir%"

set "log_file=%log_dir%\worker.log"

echo Starting Celery worker(s): %queues%
echo Log file: %log_file%
echo.

%PYTHON% start_celery_worker.py worker --loglevel=INFO --queues=%queues% -f "%log_file%"
