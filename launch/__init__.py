"""CGDA 跨平台一键启动器包。

历史上 ``launch.py`` 是一个 ~2110 行的单文件启动器，混合了路径常量、
日志、子进程工具、Docker 编排、进程生命周期、命令实现与 argparse 入口。
Phase 2 架构评审将其拆分为 ``launch/`` 包，各子模块职责单一：

- :mod:`launch.constants` — 路径常量、服务定义、默认值
- :mod:`launch.logging_setup` — 彩色控制台 + 轮转文件日志（``Log`` 单例）
- :mod:`launch.subprocess_utils` — 跨平台子进程工具（隐藏窗口 / 环境构造 /
  Node.js 解析 / 进程终止 / PID 检活）
- :mod:`launch.docker_manager` — Docker Compose 运行栈（Redis + MinIO +
  Open-Meteo API）生命周期与 Redis 就绪检查
- :mod:`launch.process_manager` — Worker / Beat / FastAPI / Frontend 子进程
  生命周期与信号处理
- :mod:`launch.debug_utils` — 调试诊断与日志文件解析
- :mod:`launch.commands` — CLI 子命令实现（start/stop/status/restart/logs/
  sync/flush/reset-db）
- :mod:`launch.cli` — argparse 配置与 ``main`` 入口

根目录 ``launch.py`` 现为薄入口，仅委托到 :func:`launch.cli.main`。
"""

from __future__ import annotations

__all__ = ["main"]


def main() -> int:
    """委托到 :func:`launch.cli.main`，保持 ``from launch import main`` 可用。"""
    from launch.cli import main as _main

    return _main()
