"""探针：验证 app fixture 内 settings 的 DB 路径指向（判断测试是否污染生产 DB）。"""

import os


def test_probe_settings_paths(app):
    import app.core.config as c

    print("\n=== settings paths inside app fixture ===")
    print("BACKEND_DATA_ROOT env =", os.environ.get("BACKEND_DATA_ROOT"))
    print("gee_credentials_db_path =", c.settings.gee_credentials_db_path)
    print("workflow_state_dir =", c.settings.workflow_state_dir)
    print("data_root =", c.settings.data_root)

    from app.services.config_service import _research_data_repo

    repo = _research_data_repo()
    print("research_data_settings db_path =", repo.db_path)
