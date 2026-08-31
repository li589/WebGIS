import shutil
import sqlite3
from pathlib import Path

src = Path(r"I:\Geograph_DataSet\_runtime\workflow_state")
tmp = Path(r"d:\temp_desktop\Proj\Comprehensive Geographic Data Analysis system\Test\debug\_wal_copy")
tmp.mkdir(exist_ok=True)

for name in (
    "workflow_state.sqlite3",
    "workflow_state.sqlite3-wal",
    "workflow_state.sqlite3-shm",
):
    s = src / name
    d = tmp / name
    if s.exists():
        shutil.copy2(s, d)
        print("copied", name, d.stat().st_size)

conn = sqlite3.connect(str(tmp / "workflow_state.sqlite3"))
for rid in ("run-19e73c905550", "run-c7d6aa7153d2", "run-cb99870d887c"):
    row = conn.execute(
        "SELECT status, updated_at FROM workflow_runs WHERE run_id=?", (rid,)
    ).fetchone()
    print(rid, "->", row)
count = conn.execute("SELECT COUNT(*) FROM workflow_runs").fetchone()[0]
print("total rows in copy:", count)
latest = conn.execute(
    "SELECT run_id, status, updated_at FROM workflow_runs ORDER BY updated_at DESC LIMIT 5"
).fetchall()
for r in latest:
    print("  latest:", r)
