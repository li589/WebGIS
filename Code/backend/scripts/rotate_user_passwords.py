#!/usr/bin/env python3
"""账号口令轮换与泄漏审计。

**为什么需要本脚本**：``BACKEND_ADMIN_PASSWORD`` 只在用户表为空时用于初始播种
（见 ``app/services/bootstrap_auth`` → ``bootstrap_auth()``）；对**已存在**的用户
它不会生效。因此在已初始化的库上改 ``.env`` 口令是「表面功夫」—— 库里的哈希不变，
泄漏的旧口令依然可登录。这曾导致一次真实的排查弯路：轮换后 4 个账号仍接受旧口令，
其中 2 个是 admin 角色。

正确语义：**库是运行期口令的真源**，``.env`` 的口令仅用于首次播种与开发预填。
本脚本据此提供运行期轮换与审计，走 ``UserRepository.update_user`` ——
与 ``PATCH /auth/users/{id}`` 完全同一代码路径，无需启动 HTTP 服务。

用法（在 Code/backend 下执行）::

  # 列出账号，并检测哪些账号仍接受给定口令（默认探测值见 --probe）
  python scripts/rotate_user_passwords.py list --probe cgda-dev-admin

  # 轮换单个账号（自动生成强随机口令并打印）
  python scripts/rotate_user_passwords.py rotate --user admin

  # 轮换所有仍接受泄漏口令的账号
  python scripts/rotate_user_passwords.py rotate --all --probe cgda-dev-admin

  # 显式指定口令
  python scripts/rotate_user_passwords.py set --user onlyread --password 'xxx'

  # 预览不写入
  python scripts/rotate_user_passwords.py rotate --all --dry-run

退出码::

  0 — 成功（rotate --dry-run 也算成功）
  1 — 用户库未找到或不可写
  2 — 参数错误
  3 — list --probe 发现仍有账号接受该口令（供巡检/CI 作失败判定）

注意：``update_user(password=...)`` 只更新 ``password_hash`` 与 ``updated_at``，
**不会吊销已签发会话**；已登录的浏览器不会被踢出。
"""

from __future__ import annotations

import argparse
import secrets
import string
import sys
from pathlib import Path

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

_ALPHABET = string.ascii_letters + string.digits
DEFAULT_PROBE = "cgda-dev-admin"


def _generate(length: int = 28) -> str:
    return "".join(secrets.choice(_ALPHABET) for _ in range(length))


def _load() -> tuple[object, object, Path]:
    """返回 (repo, verify_password, users_db_path)。"""
    try:
        from app.core.config import settings
        from app.services.passwords import verify_password
        from app.services.user_repository import get_user_repository
    except Exception as exc:  # noqa: BLE001 - 统一转为退出码 1
        print(f"[错误] 无法导入后端模块（请在 Code/backend 下执行）：{exc}")
        raise SystemExit(1) from exc

    db_path = Path(settings.workflow_state_dir) / "users.sqlite3"
    if not db_path.is_file():
        print(f"[错误] 用户库不存在：{db_path}")
        raise SystemExit(1)
    return get_user_repository(), verify_password, db_path


def _all_users(repo) -> list[dict]:  # type: ignore[no-untyped-def]
    # UserRepository 未暴露 list_users 时退回直查（只读）。
    list_fn = getattr(repo, "list_users", None)
    if callable(list_fn):
        return list(list_fn())
    import sqlite3

    conn = sqlite3.connect(str(repo.db_path))
    try:
        rows = conn.execute(
            "SELECT id, username, role, enabled FROM users ORDER BY id"
        ).fetchall()
    finally:
        conn.close()
    return [{"id": r[0], "username": r[1], "role": r[2], "enabled": r[3]} for r in rows]


def cmd_list(args: argparse.Namespace) -> int:
    repo, verify_password, db_path = _load()
    users = _all_users(repo)
    print(f"用户库：{db_path}")
    print(f"账号数：{len(users)}")
    print(f"探测口令：{'（未提供，跳过检测）' if not args.probe else '***'}")
    print()

    vulnerable: list[str] = []
    for u in users:
        name = str(u["username"])
        stored = str(repo.get_by_username(name)["password_hash"])
        accepts = verify_password(args.probe, stored) if args.probe else None
        mark = "" if accepts is None else ("  ← 接受探测口令" if accepts else "")
        print(
            f"  id={u['id']:<3} {name:<12} role={str(u['role']):<9} "
            f"enabled={u['enabled']} 哈希算法={stored.split('$', 1)[0]}{mark}"
        )
        if accepts:
            vulnerable.append(name)

    if args.probe:
        print()
        if vulnerable:
            print(
                f"[警告] {len(vulnerable)} 个账号仍接受探测口令：{', '.join(vulnerable)}"
            )
            return 3
        print("[通过] 无账号接受探测口令。")
    return 0


def _rotate(repo, users: list[dict], dry_run: bool) -> list[tuple[str, str]]:
    results: list[tuple[str, str]] = []
    for u in users:
        name = str(u["username"])
        new_pw = _generate()
        if not dry_run:
            repo.update_user(int(u["id"]), password=new_pw)
        results.append((name, new_pw))
    return results


def cmd_rotate(args: argparse.Namespace) -> int:
    repo, verify_password, db_path = _load()
    users = _all_users(repo)
    by_name = {str(u["username"]): u for u in users}

    if args.all:
        if args.probe:
            targets = [
                u
                for u in users
                if verify_password(
                    args.probe,
                    str(repo.get_by_username(str(u["username"]))["password_hash"]),
                )
            ]
            if not targets:
                print(f"[跳过] 无账号接受探测口令，无需轮换。（库：{db_path}）")
                return 0
        else:
            targets = users
    elif args.user:
        missing = [n for n in args.user if n not in by_name]
        if missing:
            print(f"[错误] 账号不存在：{', '.join(missing)}")
            print(f"       现有账号：{', '.join(by_name)}")
            return 2
        targets = [by_name[n] for n in args.user]
    else:
        print("[错误] 需指定 --user <名字>（可多次）或 --all")
        return 2

    results = _rotate(repo, targets, args.dry_run)
    verb = "将轮换" if args.dry_run else "已轮换"
    print(f"{verb} {len(results)} 个账号（库：{db_path}）：")
    for name, new_pw in results:
        print(f"  {name:<12} {new_pw}")
    if args.dry_run:
        print("\n[dry-run] 未写入；去掉 --dry-run 生效。")
    else:
        print("\n请将这些口令存入本地凭据文件（勿入库）。")
    return 0


def cmd_set(args: argparse.Namespace) -> int:
    repo, _verify_password, db_path = _load()
    by_name = {str(u["username"]): u for u in _all_users(repo)}
    if args.user not in by_name:
        print(f"[错误] 账号不存在：{args.user}（现有：{', '.join(by_name)}）")
        return 2
    if not args.password:
        print("[错误] --password 不能为空")
        return 2
    repo.update_user(int(by_name[args.user]["id"]), password=args.password)
    print(f"已设置 {args.user} 的口令（库：{db_path}）。")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(
        description="账号口令轮换与泄漏审计（库为运行期真源，.env 仅首次播种）",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list", help="列出账号，可探测哪些仍接受某口令")
    p_list.add_argument(
        "--probe",
        nargs="?",
        const=DEFAULT_PROBE,
        default=None,
        help=f"探测口令（默认 {DEFAULT_PROBE}）；仅 --probe 无值时用默认",
    )
    p_list.set_defaults(func=cmd_list)

    p_rot = sub.add_parser("rotate", help="轮换为强随机口令")
    p_rot.add_argument("--user", action="append", help="账号名，可重复")
    p_rot.add_argument(
        "--all", action="store_true", help="全部账号（可配 --probe 限定）"
    )
    p_rot.add_argument(
        "--probe",
        nargs="?",
        const=DEFAULT_PROBE,
        default=None,
        help="配合 --all：只轮换仍接受该口令的账号",
    )
    p_rot.add_argument("--dry-run", action="store_true", help="预览不写入")
    p_rot.set_defaults(func=cmd_rotate)

    p_set = sub.add_parser("set", help="显式设置某账号口令")
    p_set.add_argument("--user", required=True)
    p_set.add_argument("--password", required=True)
    p_set.set_defaults(func=cmd_set)

    args = p.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
