"""查看指定 run 在时间窗 [start, end) 内的事件与失败消息。用法: python check_run_window.py <run_id> <start> <end>"""
import json
import sqlite3
import sys

run_id = sys.argv[1]
start = sys.argv[2]
end = sys.argv[3]

conn = sqlite3.connect(r"I:\Geograph_DataSet\_runtime\workflow_state\workflow_state.sqlite3")
rows = conn.execute(
    "SELECT created_at, payload_json FROM workflow_events WHERE run_id=? AND created_at >= ? AND created_at <= ? ORDER BY created_at ASC",
    (run_id, start, end),
).fetchall()
for ts, pj in rows:
    d = json.loads(pj)
    lvl = d.get("level", "")
    print(ts[11:19], "|", lvl, "|", d.get("message", "")[:160])
