"""列出各候选库的全部表与行数。"""

import sqlite3

DBS = {
    "i_drive": r"I:\Geograph_DataSet\_runtime\workflow_state\workflow_state.sqlite3",
    "repo_old": r"Code\backend\.data\workflow_state\workflow_state.sqlite3",
}
for name, path in DBS.items():
    print(f"=== [{name}] {path} ===")
    conn = sqlite3.connect(path)
    tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
    for t in tables:
        try:
            n = conn.execute(f"SELECT COUNT(*) FROM [{t}]").fetchone()[0]
            print(f"  {t}: {n} rows")
        except Exception as exc:
            print(f"  {t}: ERR {exc}")
    conn.close()
    print()
