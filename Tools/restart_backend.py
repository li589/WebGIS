#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""查找并重启 FastAPI 后端进程（监听 8000 端口）。"""
import os
import signal
import subprocess
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def find_pid_on_port(port: int) -> int | None:
    """通过 netstat 查找监听指定端口的 PID。"""
    try:
        out = subprocess.check_output(
            ["netstat", "-ano", "-p", "TCP"], text=True, encoding="gbk", errors="replace"
        )
    except Exception as e:
        print(f"[ERROR] netstat failed: {e}")
        return None
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[1].endswith(f":{port}") and parts[3] == "LISTENING":
            try:
                return int(parts[4])
            except ValueError:
                continue
    return None


def main() -> int:
    port = 8000
    pid = find_pid_on_port(port)
    if pid is None:
        print(f"[INFO] No process listening on port {port}; backend not running.")
        return 0

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
    for _ in range(30):
        time.sleep(1)
        if find_pid_on_port(port) is None:
            print(f"[OK] Port {port} released")
            return 0
    print(f"[WARN] Port {port} still in use after 30s; forcing kill")
    subprocess.run(["taskkill", "/PID", str(pid), "/F"], check=False)
    time.sleep(2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
