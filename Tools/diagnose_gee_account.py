"""诊断当前配置的 GEE 服务账号连通性与权限状态。"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

# 保证导入 backend 路径
REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "Code" / "backend"
sys.path.insert(0, str(BACKEND_ROOT))
sys.path.insert(0, str(REPO_ROOT / "Code"))

from app.core.config import settings
from app.services.config_gee_accounts import _get_gee_credentials_repository
from app.gee.core.src.webgis_gee.accounts.credentials import GeeCredentialsLoader

def main():
    repo = _get_gee_credentials_repository()
    print("=== GEE 诊断信息 ===")
    print(f"数据库路径: {repo.db_path} (存在: {repo.db_path.exists()})")
    print(f"加密密钥配置: {'已配置 (64 hex)' if len(settings.gee_credentials_encryption_key or '') == 64 else '未配置或不合规'}")
    print(f"HTTP Proxy: {os.environ.get('HTTP_PROXY') or os.environ.get('http_proxy') or 'None'}")
    print(f"HTTPS Proxy: {os.environ.get('HTTPS_PROXY') or os.environ.get('https_proxy') or 'None'}")

    accounts = repo.list_accounts(include_disabled=True)
    print(f"\n找到账号数量: {len(accounts)}")
    for acc in accounts:
        acc_id = acc["account_id"]
        print(f"\n--- 账号: {acc_id} ---")
        print(f"Display Name: {acc.get('display_name')}")
        print(f"Project ID: {acc.get('project_id')}")
        print(f"Enabled: {acc.get('enabled')}")
        print(f"上次测试时间: {acc.get('last_tested_at')}")
        print(f"上次测试状态: {acc.get('last_test_status')}")

        sa_json = repo.get_account_credentials(acc_id)
        if not sa_json:
            print("❌ 无法解密凭证或凭证为空！")
            continue

        print(f"client_email: {sa_json.get('client_email')}")
        print(f"private_key_id: {sa_json.get('private_key_id')}")
        print(f"project_id: {sa_json.get('project_id')}")
        has_key = bool(sa_json.get("private_key"))
        print(f"private_key 存在: {has_key}")

        print("\n正在尝试加载并测试 GEE 凭据 (通过 ee.Initialize)...")
        try:
            creds = GeeCredentialsLoader.load_service_account_credentials(sa_json)
            project = sa_json.get("project_id")
            success, msg = GeeCredentialsLoader.test_credentials(creds, project)
            if success:
                print(f"[SUCCESS] Test passed: {msg}")
            else:
                print(f"[FAILED] Test failed: {msg}")
        except Exception as exc:
            import traceback
            print(f"[ERROR] Exception occurred: {exc}")
            traceback.print_exc()

if __name__ == "__main__":
    main()
