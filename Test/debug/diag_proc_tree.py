import datetime
import psutil

print("=== python processes with ppid ===")
for p in psutil.process_iter(["pid", "ppid", "name", "cmdline", "create_time"]):
    try:
        if p.info["name"] and "python" in p.info["name"].lower():
            ct = datetime.datetime.fromtimestamp(p.info["create_time"]).strftime("%H:%M:%S")
            cmd = " ".join(p.info["cmdline"] or [])
            if "start_fastapi" in cmd:
                tag = "UVICORN-MASTER"
            elif "spawn_main" in cmd:
                tag = "UVICORN-CHILD"
            elif "celery" in cmd:
                tag = "WORKER/BEAT"
            else:
                tag = "OTHER"
            print("%6d ppid=%6d %s %-15s %s" % (p.info["pid"], p.info["ppid"], ct, tag, cmd[:90]))
    except Exception as e:
        print(p.info["pid"], "iter-ERR", e)

print()
print("=== handle-access test ===")
for pid in (20848, 40068, 23368, 32388, 8692):
    try:
        p = psutil.Process(pid)
        n = len(p.open_files())
        print(pid, "open_files OK, count =", n)
    except Exception as e:
        print(pid, "open_files ERR:", type(e).__name__, str(e)[:100])
