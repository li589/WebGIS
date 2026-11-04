#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""停止监听 8000 端口的 FastAPI 后端；加 ``--start`` 则停完再启动。

⚠ 2026-11-04 更正：本脚本**原先只停不启**，但名字叫 restart，被当成「重启」
  提供给别人用过 —— 结果后端停掉没起来，页面上全站 502（网关 access.log
  17:49:57~17:53:24 连着 29 条，登录、/agent/chat 全中）。所以：
    · 不带参数：只停，并把启动命令打印出来；
    · 带 --start：停完自动开一个新控制台窗口跑 ``start.bat start fastapi``。
"""

import argparse
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_ROOT = Path(__file__).resolve().parents[1]


def find_pid_on_port(port: int) -> int | None:
    """通过 netstat 查找监听指定端口的 PID。"""
    try:
        out = subprocess.check_output(
            ["netstat", "-ano", "-p", "TCP"],
            text=True,
            encoding="gbk",
            errors="replace",
        )
    except Exception as e:
        print(f"[ERROR] netstat failed: {e}")
        return None
    for line in out.splitlines():
        parts = line.split()
        if (
            len(parts) >= 5
            and parts[1].endswith(f":{port}")
            and parts[3] == "LISTENING"
        ):
            try:
                return int(parts[4])
            except ValueError:
                continue
    return None


def start_backend() -> int:
    """在新控制台窗口里跑 start.bat（认 E: 盘这套的唯一入口）。"""
    bat = _ROOT / "start.bat"
    if not bat.exists():
        print(f"[ERROR] 找不到启动脚本：{bat}")
        return 1
    print(f"[INFO] 启动后端：{bat} start fastapi")
    try:
        subprocess.Popen(
            ["cmd", "/c", "start", "", str(bat), "start", "fastapi"],
            cwd=str(_ROOT),
            creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0),
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[ERROR] 启动失败：{exc}；请手动执行：{bat} start fastapi")
        return 1
    print("[OK] 已在新窗口启动（加载图层表约需 10~20 秒）")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="停止（可选重启）FastAPI 后端")
    parser.add_argument(
        "--start",
        action="store_true",
        help="停完立刻在新窗口启动；不加则只停，并打印启动命令",
    )
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    port = args.port

    pid = find_pid_on_port(port)
    if pid is None:
        print(f"[INFO] 端口 {port} 上没有进程，后端本来就没在跑。")
        if args.start:
            return start_backend()
        return _print_start_hint()

    print(f"[INFO] Found backend PID={pid} on port {port}")
    try:
        # 优先发送 Ctrl+Break (Windows 上等同 SIGINT)
        os.kill(pid, signal.CTRL_BREAK_EVENT)
        print(f"[INFO] Sent Ctrl+Break to PID={pid}")
    except (AttributeError, OSError):
        try:
            os.kill(pid, signal.SIGTERM)
            print(f"[INFO] Sent SIGTERM to PID={pid}")
        except Exception as e:
            print(f"[WARN] Could not signal PID={pid}: {e}; trying taskkill")
            subprocess.run(["taskkill", "/PID", str(pid), "/F"], check=False)

    # 等待端口释放
    released = False
    for _ in range(30):
        time.sleep(1)
        if find_pid_on_port(port) is None:
            print(f"[OK] Port {port} released")
            released = True
            break
    if not released:
        print(f"[WARN] Port {port} still in use after 30s; forcing kill")
        subprocess.run(["taskkill", "/PID", str(pid), "/F"], check=False)
        time.sleep(2)

    if args.start:
        return start_backend()
    return _print_start_hint()


def _print_start_hint() -> int:
    print("")
    print("[NOTE] 本脚本只负责停止，不会自动启动。")
    print("       要启动请执行（PowerShell）：")
    print(f'         cd "{_ROOT}"')
    print("         .\\start.bat start fastapi")
    print("       或者下次直接加参数：python Tools\\restart_backend.py --start")
    return 0


if __name__ == "__main__":
    sys.exit(main())
