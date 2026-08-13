#!/usr/bin/env python3
"""角色模型迁移脚本（Phase 2）

将旧角色名迁移到新三角色模型：
  operator → standard
  viewer   → demo

影响的表：
  - users.role
  - sessions.role

用法：
  cd Code/backend
  ../../Env/Python312/python.exe scripts/migrate_roles_v2.py          # 实际执行
  ../../Env/Python312/python.exe scripts/migrate_roles_v2.py --dry-run # 预览不写入

退出码：
  0 — 成功（或 dry-run 完成）
  1 — 数据库未找到 / 不可写
  2 — 已迁移过（无旧角色记录）
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

# 角色映射
ROLE_MAP: dict[str, str] = {
    "operator": "standard",
    "viewer": "demo",
}

# 新模型有效角色
VALID_NEW_ROLES = frozenset({"admin", "standard", "demo"})


def _find_users_db() -> Path | None:
    """定位 users.sqlite3（与 user_repository._users_db_path 对齐）。"""
    backend_root = Path(__file__).resolve().parents[1]
    import os

    env_path = os.getenv("BACKEND_USERS_DB_PATH")
    if env_path:
        p = Path(env_path)
        if p.exists():
            return p

    # 与 user_repository 一致：BACKEND_WORKFLOW_STATE_DIR / users.sqlite3
    state_dir = os.getenv("BACKEND_WORKFLOW_STATE_DIR", "").strip()
    if state_dir:
        candidate = Path(state_dir) / "users.sqlite3"
        if candidate.exists():
            return candidate

    default_sqlite3 = backend_root / ".data" / "users.sqlite3"
    if default_sqlite3.exists():
        return default_sqlite3

    # 兼容旧文件名
    legacy_db = backend_root / ".data" / "users.db"
    if legacy_db.exists():
        return legacy_db

    runtime_root = os.getenv("BACKEND_RUNTIME_ROOT", r"I:\Geograph_DataSet\_runtime")
    for name in ("users.sqlite3", "users.db"):
        alt = Path(runtime_root) / name
        if alt.exists():
            return alt
    return None


def _backup(db_path: Path) -> Path:
    """创建 .bak 备份。"""
    backup_path = db_path.with_suffix(db_path.suffix + ".bak")
    import shutil

    shutil.copy2(db_path, backup_path)
    return backup_path


def migrate(db_path: Path, dry_run: bool = False) -> int:
    """执行迁移，返回受影响行数。"""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    total_affected = 0

    try:
        # 检查表是否存在
        tables = {
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        if "users" not in tables:
            print(f"[SKIP] users 表不存在，数据库可能未初始化: {db_path}")
            return 0

        # 统计旧角色记录
        for table in ("users", "sessions"):
            if table not in tables:
                print(f"[SKIP] {table} 表不存在，跳过")
                continue

            for old_role, new_role in ROLE_MAP.items():
                count_row = conn.execute(
                    f"SELECT COUNT(*) AS c FROM {table} WHERE role = ?",
                    (old_role,),
                ).fetchone()
                count = count_row["c"] if count_row else 0
                if count == 0:
                    continue

                print(f"  {table}: {old_role} → {new_role}  ({count} rows)")

                if not dry_run:
                    conn.execute(
                        f"UPDATE {table} SET role = ? WHERE role = ?",
                        (new_role, old_role),
                    )
                    total_affected += count

        # 检查是否有不在新模型中的角色
        if "users" in tables:
            invalid_rows = conn.execute(
                "SELECT role, COUNT(*) AS c FROM users GROUP BY role"
            ).fetchall()
            for row in invalid_rows:
                role = row["role"]
                if role not in VALID_NEW_ROLES:
                    print(f"  [WARN] users 表中存在未知角色 '{role}' ({row['c']} rows)")
                    print(f"         建议手动检查并迁移到 standard 或 demo")

        if not dry_run and total_affected > 0:
            conn.commit()
            print(f"\n[OK] 迁移完成，共更新 {total_affected} 行")
        elif dry_run and total_affected == 0:
            # dry_run 下 total_affected 始终为 0，需要单独统计
            print("\n[DRY-RUN] 以上为预览，未实际写入")
        else:
            print("\n[OK] 无需迁移（未找到旧角色记录）")

    finally:
        conn.close()

    return total_affected


def main() -> int:
    parser = argparse.ArgumentParser(
        description="角色模型迁移：operator→standard, viewer→demo"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="仅预览，不实际写入数据库",
    )
    parser.add_argument(
        "--db-path",
        type=str,
        default=None,
        help="指定 users.db 路径（默认自动查找）",
    )
    args = parser.parse_args()

    db_path = Path(args.db_path) if args.db_path else _find_users_db()
    if db_path is None or not db_path.exists():
        print("[ERROR] 未找到 users.sqlite3，请用 --db-path 指定路径")
        return 1

    print(f"数据库: {db_path}")
    print(f"模式: {'DRY-RUN' if args.dry_run else 'EXECUTE'}")
    print()

    if not args.dry_run:
        backup = _backup(db_path)
        print(f"备份: {backup}")
        print()

    affected = migrate(db_path, dry_run=args.dry_run)

    if affected == 0 and not args.dry_run:
        return 2  # 已迁移过
    return 0


if __name__ == "__main__":
    sys.exit(main())
