"""只读探针：核查生产凭据完整性（2026-08-19 污染事故 aftermath）。

- earthdata 门户用户名非测试载荷 "tessa"
- users.sqlite3 无悬空会话/Token（user_id 无对应用户行）、无测试残留用户
只读 SELECT，不写任何库。用法：
    Env/Python312/python.exe Test/debug/probe_prod_creds_integrity.py
"""

from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPO_ROOT / "Code" / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("ENVIRONMENT", "development")


def check_portal_earthdata(issues: list[str]) -> None:
    from app.services.config_service import get_portal_credentials_runtime

    store = get_portal_credentials_runtime() or {}
    ed = store.get("earthdata")
    if not isinstance(ed, dict):
        print("earthdata: 无门户条目")
        return
    user = str(ed.get("username") or "")
    print(f"earthdata.username = {user!r}")
    if user.strip().lower() == "tessa":
        issues.append("earthdata 用户名为 'tessa'（测试载荷污染残留）")


def check_users_db(issues: list[str]) -> None:
    from app.core.config import settings

    users_db = Path(settings.workflow_state_dir) / "users.sqlite3"
    print(f"users.sqlite3 = {users_db} (exists={users_db.exists()})")
    if not users_db.exists():
        return
    conn = sqlite3.connect(f"file:{users_db}?mode=ro", uri=True)
    try:
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        print(f"tables = {tables}")
        if "sessions" in tables:
            rows = conn.execute(
                "SELECT s.rowid, s.user_id, s.username FROM sessions s "
                "LEFT JOIN users u ON u.id = s.user_id WHERE u.id IS NULL"
            ).fetchall()
            print(f"悬空 sessions（user_id 无对应用户）: {rows}")
            if rows:
                issues.append(f"悬空 sessions: {[(r[0], r[1], r[2]) for r in rows]}")
        if "user_api_tokens" in tables:
            rows = conn.execute(
                "SELECT t.id, t.user_id FROM user_api_tokens t "
                "LEFT JOIN users u ON u.id = t.user_id WHERE u.id IS NULL"
            ).fetchall()
            print(f"悬空 user_api_tokens: {len(rows)} 条 ids={[r[0] for r in rows[:5]]}{'…' if len(rows) > 5 else ''}")
            if rows:
                issues.append(f"悬空 user_api_tokens: {len(rows)} 条（user_id 无对应用户，测试污染残留）")
        if "users" in tables:
            test_like = conn.execute(
                "SELECT id, username, role, enabled FROM users "
                "WHERE lower(username) IN ('tessa', 'test_user', 'pytest_user')"
            ).fetchall()
            print(f"疑似测试用户: {test_like}")
            if test_like:
                issues.append(f"疑似测试用户残留: {test_like}")
    finally:
        conn.close()


def main() -> int:
    issues: list[str] = []
    try:
        check_portal_earthdata(issues)
    except Exception as exc:  # noqa: BLE001
        print(f"portal check error: {exc}")
    try:
        check_users_db(issues)
    except Exception as exc:  # noqa: BLE001
        print(f"users db check error: {exc}")
    if issues:
        print("RESULT: POLLUTED")
        for i in issues:
            print(f"  - {i}")
        return 1
    print("RESULT: CLEAN")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
