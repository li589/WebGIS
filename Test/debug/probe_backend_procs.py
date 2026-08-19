"""用 psutil 定位 :8000 监听进程与全部后端相关进程。

用法: python probe_backend_procs.py
"""
import datetime

import psutil


def main() -> None:
    me = psutil.Process().pid
    seen = set()
    print("== listeners :8000 ==")
    for c in psutil.net_connections(kind="tcp"):
        if c.laddr and c.laddr.port == 8000 and c.status == psutil.CONN_LISTEN and c.pid and c.pid != me:
            p = psutil.Process(c.pid)
            print(f"PID {c.pid} created {datetime.datetime.fromtimestamp(p.create_time()):%m-%d %H:%M:%S}")
            print("  exe:", p.exe())
            print("  cwd:", p.cwd())
            print("  cmd:", " ".join(p.cmdline())[:300])
            env = p.environ()
            for k in ("BACKEND_DATA_ROOT", "BACKEND_RUNTIME_ROOT", "BACKEND_OUTPUT_ROOT"):
                print(f"  env {k}={env.get(k)!r}")
            seen.add(c.pid)
    print("== backend-ish processes (uvicorn/celery/fastapi) ==")
    for p in psutil.process_iter(["pid", "name", "cmdline", "create_time"]):
        try:
            cmd = " ".join(p.info["cmdline"] or [])
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        if any(k in cmd for k in ("uvicorn", "celery", "start_fastapi", "launch.py")) and p.info["pid"] != me:
            ct = datetime.datetime.fromtimestamp(p.info["create_time"])
            print(f"PID {p.info['pid']:>7} {ct:%m-%d %H:%M:%S} {cmd[:200]}")


if __name__ == "__main__":
    main()
