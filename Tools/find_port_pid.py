#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""查找监听 8000 端口的进程 PID。"""
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

try:
    out = subprocess.check_output(
        ["netstat", "-ano", "-p", "TCP"], text=True, encoding="gbk", errors="replace"
    )
except Exception as e:
    print(f"[ERROR] netstat failed: {e}")
    sys.exit(1)

found = []
for line in out.splitlines():
    parts = line.split()
    if len(parts) >= 5 and parts[1].endswith(":8000") and parts[3] == "LISTENING":
        try:
            pid = int(parts[4])
            found.append((parts[1], parts[2], pid))
        except ValueError:
            continue

if not found:
    print("[INFO] No process listening on port 8000")
    sys.exit(0)

print(f"[INFO] Found {len(found)} listener(s) on port 8000:")
for local, foreign, pid in found:
    print(f"  local={local} foreign={foreign} PID={pid}")
    # Try to get process info
    try:
        pout = subprocess.check_output(
            ["wmic", "process", "where", f"ProcessId={pid}", "get", "Name,CommandLine,ProcessId"],
            text=True, encoding="gbk", errors="replace", stderr=subprocess.DEVNULL
        )
        for pline in pout.splitlines():
            pline = pline.strip()
            if pline and pline != "Name  CommandLine  ProcessId":
                print(f"    -> {pline}")
    except Exception:
        pass
