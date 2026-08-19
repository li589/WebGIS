import subprocess
import sys

try:
    import psutil
except ImportError:
    print("psutil not available")
    sys.exit(0)

pids = set()
for conn in psutil.net_connections(kind="tcp"):
    if conn.laddr and conn.laddr.port == 8000 and conn.status == "LISTEN":
        pids.add(conn.pid)
print("listener pids:", pids)
for pid in pids:
    try:
        p = psutil.Process(pid)
    except psutil.NoSuchProcess:
        print(pid, "-> gone")
        continue
    print("PID:", pid, "name:", p.name())
    for label, fn in (("exe", p.exe), ("cwd", p.cwd), ("cmdline", p.cmdline)):
        try:
            print(f"{label}:", fn())
        except Exception as e:
            print(f"{label}: <err>", e)
    try:
        env = p.environ()
        for key in (
            "BACKEND_DATA_ROOT",
            "BACKEND_RUNTIME_ROOT",
            "BACKEND_WORKFLOW_STATE_DIR",
        ):
            print(f"env {key}=", env.get(key, "<unset>"))
    except Exception as e:
        print("env: <err>", e)
