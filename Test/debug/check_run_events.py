"""查看指定 run 的状态、进度与最近事件。用法: python check_run_events.py <run_id> [limit]"""
import json
import sqlite3
import sys

run_id = sys.argv[1] if len(sys.argv) > 1 else "run-f6b15b8181ce"
limit = int(sys.argv[2]) if len(sys.argv) > 2 else 8

conn = sqlite3.connect(r"I:\Geograph_DataSet\_runtime\workflow_state\workflow_state.sqlite3")
row = conn.execute(
    "SELECT status, updated_at, payload_json FROM workflow_runs WHERE run_id=?", (run_id,)
).fetchone()
if not row:
    print("run not found:", run_id)
    sys.exit(0)
pj = json.loads(row[2])
print("status:", row[0], "| updated_at:", row[1])
print("progress:", pj.get("progress"), "| current_node:", pj.get("current_node"))
print("command_label:", pj.get("command_label"))

tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
event_table = next((t for t in tables if "event" in t), None)
if event_table:
    cols = [r[1] for r in conn.execute(f"PRAGMA table_info({event_table})")]
    print(f"event table: {event_table} cols={cols}")
    time_col = next((c for c in ("created_at", "timestamp", "occurred_at") if c in cols), cols[0])
    msg_col = next((c for c in ("message", "msg", "payload_json", "data") if c in cols), None)
    sel = f"SELECT {time_col}" + (f", {msg_col}" if msg_col else "") + f" FROM {event_table} WHERE run_id=? ORDER BY {time_col} DESC LIMIT ?"
    for e in conn.execute(sel, (run_id, limit)).fetchall():
        print(e[0], "|", (str(e[1])[:150] if len(e) > 1 else ""))
else:
    print("tables:", tables)
