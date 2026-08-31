"""查看指定 run 的早期事件（下载/预处理阶段）。用法: python check_run_events_early.py <run_id> [limit]"""
import json
import sqlite3
import sys

run_id = sys.argv[1] if len(sys.argv) > 1 else "run-f6b15b8181ce"
limit = int(sys.argv[2]) if len(sys.argv) > 2 else 30

conn = sqlite3.connect(r"I:\Geograph_DataSet\_runtime\workflow_state\workflow_state.sqlite3")
rows = conn.execute(
    "SELECT created_at, payload_json FROM workflow_events WHERE run_id=? ORDER BY created_at ASC LIMIT ?",
    (run_id, limit),
).fetchall()
for ts, pj in rows:
    d = json.loads(pj)
    msg = d.get("message", "")
    print(ts[11:19], "|", msg[:140])
