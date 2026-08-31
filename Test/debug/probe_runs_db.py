"""检查 workflow_runs.sqlite3 的表结构与内容。"""

import sqlite3

p = r"I:\Geograph_DataSet\_runtime\workflow_state\workflow_runs.sqlite3"
conn = sqlite3.connect(p)
tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
print("tables:", tables)
if "workflow_runs" in tables:
    total = conn.execute("SELECT COUNT(*) FROM workflow_runs").fetchone()[0]
    print("total:", total)
    latest = conn.execute(
        "SELECT run_id, status, updated_at FROM workflow_runs ORDER BY updated_at DESC LIMIT 5"
    ).fetchall()
    print("latest:", latest)
    for rid in ("run-3e3a4a01b1bb", "run-probe0001", "run-19e73c905550", "run-cb99870d887c"):
        row = conn.execute(
            "SELECT status, updated_at FROM workflow_runs WHERE run_id=?", (rid,)
        ).fetchone()
        print("probe", rid, ":", row)
conn.close()
