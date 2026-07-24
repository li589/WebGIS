#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CGDA 跨平台一键启动器（薄入口）
================================

历史上此文件是一个 ~2110 行的单体启动器，混合了路径常量、日志、子进程
工具、Docker 编排、进程生命周期、命令实现与 argparse 入口。Phase 2 架构
评审已将实现拆分到 ``launch/`` 包（见 :mod:`launch` 包 docstring）。

本文件现在仅做两件事：
1. 在 Windows 上将控制台输出重配置为 UTF-8（必须在任何 print 之前）。
2. 委托到 :func:`launch.cli.main`。

所有命令实现见 :mod:`launch.commands`；argparse 配置见 :mod:`launch.cli`。
外部调用方式（``python launch.py``、``start.bat``、``./start.sh``）保持不变。

用法:
    python launch.py                     # 等同 start（无参数默认）
    python launch.py start [component] [options]
    python launch.py stop
    python launch.py status
    python launch.py restart [component] [options]
    python launch.py logs [component] [-n N]
    python launch.py flush [--yes] [--dry-run]
    python launch.py sync [job]          # 数据面一次性同步（默认 open-meteo-sync）
    python launch.py reset-db [--yes] [--no-snapshot] [--clear-user] [--force]

组件 (component):
    (无) 或 all        启动全部服务并进入监控循环（默认）
    docker              仅启动 Docker 运行栈（Redis + MinIO + cgda-open-meteo）
    fastapi             仅启动 FastAPI 后端（需要 Redis 已运行）
    beat                仅启动 Celery Beat 调度器
    worker              仅启动全部 7 个 Celery Worker
    worker:all          同上
    worker:realtime     仅启动 realtime 队列 Worker
    worker:standard     仅启动 standard 队列 Worker
    worker:heavy        仅启动 heavy 队列 Worker
    worker:batch        仅启动 batch 队列 Worker
    worker:download     仅启动 download 队列 Worker
    worker:gee          仅启动 gee 队列 Worker
    worker:weather      仅启动 weather 队列 Worker
    frontend            仅启动前端 Vite 开发服务器

完整示例见 ``python launch.py --help``。
Windows: start.bat / stop.bat    Linux/macOS: ./start.sh / ./stop.sh
"""

from __future__ import annotations

import sys

# ─── Windows 控制台 UTF-8 输出 ───────────────────────────────────────────────
# 必须在导入 launch 包（会触发日志初始化）之前完成，确保首行日志就是 UTF-8。
if sys.platform in ("win32", "win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass


def main() -> int:
    """委托到 :func:`launch.cli.main`。"""
    # 延迟导入：先完成控制台 UTF-8 配置，再加载包（包初始化会创建日志文件）。
    from launch.cli import main as cli_main

    return cli_main()


if __name__ == "__main__":
    sys.exit(main())
