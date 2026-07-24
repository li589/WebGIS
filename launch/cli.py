"""argparse 配置与 ``main`` 入口 for the CGDA launcher.

Extracted from the original ``launch.py``. Builds the sub-command parser
tree (start / stop / status / restart / logs / flush / reset-db / sync),
dispatches to the ``cmd_*`` functions in :mod:`launch.commands`, and
owns the top-level ``KeyboardInterrupt`` / ``finally`` cleanup.

Keeping the parser here (rather than in ``commands.py``) separates
"what the CLI surface looks like" from "what each command does", so
adding a new flag does not require touching command implementations
and vice versa.
"""

from __future__ import annotations

import argparse
import sys

from launch.commands import (
    cmd_flush,
    cmd_logs,
    cmd_reset_db,
    cmd_restart,
    cmd_start,
    cmd_status,
    cmd_stop,
    cmd_sync,
)
from launch.constants import DEFAULT_FRONTEND_PORT, DEFAULT_MAX_SNAPSHOTS
from launch.logging_setup import log

# ─── 子命令帮助文本（集中声明，便于审阅 CLI 表面） ──────────────────────────
_COMPONENT_HELP = (
    "组件: all/docker/fastapi/beat/worker/worker:<name>/frontend（默认 all）"
)
_LOGS_COMPONENT_HELP = (
    "组件: fastapi/beat/frontend/worker/worker:<name>（默认合并全部）"
)


def _add_start_restart_args(p: argparse.ArgumentParser) -> None:
    """为 start / restart 子命令添加共享参数。"""
    p.add_argument("component", nargs="?", default="all", help=_COMPONENT_HELP)
    p.add_argument("--no-frontend", action="store_true", help="不启动前端开发服务器")
    p.add_argument("--no-docker", action="store_true", help="不启动 Docker 容器")
    p.add_argument(
        "--no-open-meteo",
        action="store_true",
        help=(
            "不启动 cgda-open-meteo API（仍启动 Redis/MinIO；"
            "同步见 Code/infra/data-sync）"
        ),
    )
    p.add_argument(
        "--frontend-only",
        action="store_true",
        help="仅启动前端（等同 start frontend）",
    )
    p.add_argument(
        "--debug",
        action="store_true",
        help="调试模式：不隐藏窗口，Celery 日志级别 DEBUG",
    )
    p.add_argument(
        "--frontend-port",
        type=int,
        default=DEFAULT_FRONTEND_PORT,
        help=f"前端端口（默认 {DEFAULT_FRONTEND_PORT}）",
    )


def build_parser() -> argparse.ArgumentParser:
    """构造 CGDA 启动器的 argparse 解析器。"""
    parser = argparse.ArgumentParser(
        prog="launch.py",
        description="CGDA 跨平台一键启动器（Windows / Linux）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例:\n"
            "  python launch.py start                      # 启动全部，进入监控循环\n"
            "  python launch.py start docker               # 仅 Redis + MinIO + Open-Meteo API\n"
            "  python launch.py sync                       # 跑 data-sync open-meteo-sync\n"
            "  python launch.py start worker:weather       # 仅启动 weather Worker\n"
            "  python launch.py start fastapi --debug      # 调试模式启动 FastAPI\n"
            "  python launch.py start --frontend-port 3000 # 全部启动，前端用 3000 端口\n"
            "  python launch.py logs fastapi -n 100        # 查看 FastAPI 最后 100 行日志\n"
            "  python launch.py logs worker:all            # 查看所有 Worker 日志\n"
            "  python launch.py flush                      # 清空 Redis + 文件缓存（需确认）\n"
            "  python launch.py flush --dry-run            # 预览将要清空的对象，不执行\n"
            "  python launch.py flush --yes                # 跳过确认直接执行\n"
            "  python launch.py reset-db                   # 清空 workflow_state，自动快照 + 重 seed\n"
            "  python launch.py reset-db --yes             # 跳过确认直接执行\n"
            "  python launch.py reset-db --clear-user      # 同时清空用户自定义工作流\n"
            "  python launch.py stop                       # 停止全部服务\n"
            "  python launch.py status                     # 查看服务状态\n"
            "\n"
            "Windows: start.bat / stop.bat    Linux/macOS: ./start.sh / ./stop.sh"
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # start
    p_start = sub.add_parser("start", help="启动服务")
    _add_start_restart_args(p_start)

    # stop
    sub.add_parser("stop", help="停止全部服务")

    # status
    sub.add_parser("status", help="查看服务状态")

    # restart
    p_restart = sub.add_parser("restart", help="重启服务")
    _add_start_restart_args(p_restart)

    # logs
    p_logs = sub.add_parser("logs", help="查看日志")
    p_logs.add_argument("component", nargs="?", default=None, help=_LOGS_COMPONENT_HELP)
    p_logs.add_argument("-n", type=int, default=50, help="显示行数（默认 50）")

    # flush
    p_flush = sub.add_parser("flush", help="清空 Redis DB + 应用天气文件缓存")
    p_flush.add_argument(
        "--yes", "-y", action="store_true", help="跳过确认提示直接执行"
    )
    p_flush.add_argument(
        "--dry-run",
        action="store_true",
        help="仅预览将要清空的对象，不执行任何删除",
    )

    # reset-db
    p_reset = sub.add_parser(
        "reset-db",
        help="清空 workflow_state 运行时数据库并重新 seed 工作流定义",
    )
    p_reset.add_argument(
        "--yes", "-y", action="store_true", help="跳过确认提示直接执行"
    )
    p_reset.add_argument(
        "--no-snapshot",
        action="store_true",
        help="跳过快照备份（不推荐，无法回滚）",
    )
    p_reset.add_argument(
        "--keep-snapshots",
        type=int,
        default=DEFAULT_MAX_SNAPSHOTS,
        help=f"保留快照数量（默认 {DEFAULT_MAX_SNAPSHOTS}）",
    )
    p_reset.add_argument(
        "--clear-user",
        action="store_true",
        help="同时清空用户自定义工作流定义（默认保留）",
    )
    p_reset.add_argument(
        "--force",
        action="store_true",
        help="即使后端服务正在运行也强制执行（可能导致文件锁失败）",
    )

    # sync
    p_sync = sub.add_parser("sync", help="数据面一次性同步（Code/infra/data-sync）")
    p_sync.add_argument(
        "job",
        nargs="?",
        default="open-meteo-sync",
        help="compose service 名（默认 open-meteo-sync）",
    )

    return parser


# ─── 命令分发表 ──────────────────────────────────────────────────────────────
# 集中声明 command → handler 映射，避免长 if/elif 链。
# stop / status 无参数；其余命令接收 argparse.Namespace。
def _dispatch(args: argparse.Namespace) -> int:
    command = args.command
    if command == "start":
        return cmd_start(args)
    if command == "stop":
        return cmd_stop()
    if command == "status":
        return cmd_status()
    if command == "restart":
        return cmd_restart(args)
    if command == "logs":
        return cmd_logs(args)
    if command == "flush":
        return cmd_flush(args)
    if command == "reset-db":
        return cmd_reset_db(args)
    if command == "sync":
        return cmd_sync(args.job)
    # argparse 的 required=True 已保证不会走到这里
    log.error("Launcher", f"未知命令: {command}")
    return 2


def main() -> int:
    """CGDA 启动器入口：解析参数并分派到对应命令。"""
    # 无子命令时默认 start（兼容直接 python launch.py / start.bat）
    if len(sys.argv) == 1:
        sys.argv.append("start")

    parser = build_parser()
    args = parser.parse_args()

    try:
        return _dispatch(args)
    except KeyboardInterrupt:
        log.warn("Launcher", "用户中断")
        return 130
    finally:
        log.close()


if __name__ == "__main__":
    sys.exit(main())
