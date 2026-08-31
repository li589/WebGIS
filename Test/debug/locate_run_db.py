"""在候选状态库中定位 run-1a0f754b7f0a，并枚举 workflow_runs 表结构。

用法: python locate_run_db.py [run_id]
"""
import sqlite3
import sys
from pathlib import Path

RUN_ID = sys.argv[1] if len(sys.argv) > 1 else "run-1a0f754b7f0a"
CANDIDATES = [
    r"I:\Geograph_DataSet\_runtime\workflow_state\workflow_state.sqlite3",
    r"I:\test\_runtime\workflow_state\workflow_state.sqlite3",
    r"D:\temp_desktop\Proj\Comprehensive Geographic Data Analysis system\Code\backend\.data\_runtime\workflow_state\workflow_state.sqlite3",
]


def main() -> None:
    for db in CANDIDATES:
        p = Path(db)
        print(f"== {db} (exists={p.exists()}) ==")
        if not p.exists():
            continue
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
            print("  tables:", tables[:20])
            for t in tables:
                if "run" not in t:
                    continue
                cols = [c[1] for c in conn.execute(f"PRAGMA table_info({t})").fetchall()]
                id_col = next((c for c in ("run_id", "id") if c in cols), None)
                if not id_col:
                    continue
                try:
                    row = conn.execute(f"SELECT * FROM {t} WHERE {id_col}=?", (RUN_ID,)).fetchone()
                except sqlite3.OperationalError:
                    continue
                print(f"  {t}: {'FOUND' if row else 'not found'} (cols={cols[:8]})")
                if row and t == "workflow_runs":
                    d = dict(zip(cols, row))
                    for k in ("run_id", "status", "created_at", "updated_at"):
                        print(f"    {k}: {d.get(k)}")
        finally:
            conn.close()


if __name__ == "__main__":
    main()
