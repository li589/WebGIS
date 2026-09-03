"""图层平台 P1：分组运行时管理 + layer_group 组级 ACL 测试。

覆盖：
- LayerGroupRepository CRUD（种子组自动注册、自建组增删改、排序、成员分配）
- /layers/categories* 管理端点（admin 鉴权、种子组删除拒绝）
- layer 访问检查合并组级 ACL（layer 覆盖 > 组覆盖 > 模式默认，user > theme）
- catalog 下发分组（种子 ⊕ 自定义，assignment 覆盖 category）
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

_CODE_ROOT = Path(__file__).resolve().parents[2]
_PYTHON_PROVIDER = _CODE_ROOT / "algorithms" / "providers" / "Python"
for _p in (_PYTHON_PROVIDER, _CODE_ROOT):
    _s = str(_p)
    if _s in sys.path:
        sys.path.remove(_s)
    sys.path.insert(0, _s)


@pytest.fixture()
def auth_client(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKEND_ENV", "test")
    monkeypatch.setenv("BACKEND_USER_AUTH_ENABLED", "true")
    monkeypatch.setenv("BACKEND_ADMIN_USERNAME", "testadmin")
    monkeypatch.setenv("BACKEND_ADMIN_PASSWORD", "test-pass-123")
    monkeypatch.setenv("BACKEND_API_KEY", "test-api-key")
    monkeypatch.setenv("BACKEND_API_KEYS_ENABLED", "true")
    monkeypatch.setenv("BACKEND_API_KEY_ROLE", "standard")
    monkeypatch.setenv("BACKEND_DATA_ROOT", str(tmp_path / "data"))
    monkeypatch.setenv("BACKEND_OUTPUT_ROOT", str(tmp_path / "out"))
    monkeypatch.setenv("BACKEND_WORKFLOW_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("BACKEND_DEV_AUTH_PREFILL", "false")

    from dataclasses import replace
    import app.core.config as cfg_mod
    from app.core.config import Settings

    cfg_mod.settings = replace(
        Settings(),
        admin_username="testadmin",
        admin_password="test-pass-123",
        environment="test",
        api_key="test-api-key",
        api_keys_enabled=True,
    )
    from app.services import user_repository as ur_mod
    from app.services.user_repository import UserRepository
    from app.services import theme_repository as tr_mod
    from app.services.theme_repository import ThemeRepository

    _db_path = tmp_path / "state" / "users.sqlite3"
    _db_path.parent.mkdir(parents=True, exist_ok=True)
    ur_mod._repo = UserRepository(_db_path)
    tr_mod._repo = ThemeRepository(_db_path)

    from app.services import permission_repository as pr_mod
    from app.services.permission_repository import PermissionRepository
    from app.services import layer_group_repository as lgr_mod

    pr_mod._repo = PermissionRepository(_db_path)
    pr_mod.invalidate_access_cache()
    lgr_mod._repo = lgr_mod.LayerGroupRepository(_db_path)

    from app.main import create_app
    from app.services.auth_bootstrap import bootstrap_auth
    from app.services.config_service import (
        _get_api_keys_repository,
        _get_effective_api_key_cached,
    )
    from app.services.effective_config import hydrate_effective_config

    hydrate_effective_config()
    bootstrap_auth()
    _get_api_keys_repository().upsert_key(
        key_name="backend_auth",
        key_value="test-api-key",
        display_name="Test backend auth",
        description="pytest fixture",
        history_source="test",
        archive_previous=False,
    )
    _get_effective_api_key_cached.cache_clear()
    hydrate_effective_config()

    with TestClient(create_app()) as client:
        yield client

    pr_mod._repo = None
    lgr_mod._repo = None
    tr_mod._repo = None
    pr_mod.invalidate_access_cache()


def _login(client: TestClient, username: str, password: str) -> None:
    resp = client.post(
        "/auth/login", json={"username": username, "password": password}
    )
    assert resp.status_code == 200, resp.text


def _create_user(client: TestClient, username: str, role: str = "standard") -> dict:
    resp = client.post(
        "/auth/users",
        json={"username": username, "password": "user-pass-123", "role": role},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


# ---------------------------------------------------------------------------
# LayerGroupRepository 单元测试
# ---------------------------------------------------------------------------


def _repo_factory(tmp_path):
    from app.services.layer_group_repository import LayerGroupRepository

    db_dir = tmp_path / "state"
    db_dir.mkdir(parents=True, exist_ok=True)
    return LayerGroupRepository(db_dir / "users.sqlite3")


def test_group_repo_seed_sync_and_crud(tmp_path):
    repo = _repo_factory(tmp_path)
    groups = repo.list_groups()
    seed_ids = {g.group_id for g in groups}
    # 种子组自动注册（layer_categories.json）
    assert {"climate", "weather", "research-group"} <= seed_ids
    assert all(g.source == "seed" for g in groups)

    # 自建组
    created = repo.create_group("my-group", "我的分组", icon="M", accent_color="#abc")
    assert created.group_id == "my-group"
    assert created.source == "custom"
    assert created.position > max(g.position for g in groups if g.source == "seed")

    # 重复 id 拒绝
    from app.services.layer_group_repository import LayerGroupError

    with pytest.raises(LayerGroupError):
        repo.create_group("my-group", "重复")

    # 改名（种子组也可改）
    renamed = repo.update_group("climate", name="气候与极端天气")
    assert renamed.name == "气候与极端天气"

    # 删除：种子组拒绝，自建组允许
    with pytest.raises(LayerGroupError):
        repo.delete_group("climate")
    repo.delete_group("my-group")
    assert repo.get_by_group_id("my-group") is None


def test_group_repo_reorder_and_members(tmp_path):
    repo = _repo_factory(tmp_path)
    repo.create_group("zeta", "Z 组")
    repo.create_group("alpha", "A 组")

    reordered = repo.reorder_groups(["weather", "zeta", "alpha", "climate"])
    ids = [g.group_id for g in reordered]
    # 未列出的种子组保持相对顺序追加在后
    assert ids[:4] == ["weather", "zeta", "alpha", "climate"]
    assert ids.index("weather") < ids.index("zeta") < ids.index("alpha")

    # 成员分配：layer→group 覆盖
    repo.set_layer_assignments("zeta", ["wind-field", "temperature", "wind-field"])
    assignments = repo.list_assignments()
    assert assignments["wind-field"] == "zeta"
    assert assignments["temperature"] == "zeta"

    # 移动到另一组 = 全量替换旧组员
    repo.set_layer_assignments("alpha", ["wind-field"])
    assignments = repo.list_assignments()
    assert assignments["wind-field"] == "alpha"
    assert assignments["temperature"] == "zeta"

    # 删除组 → 成员关系解除
    repo.delete_group("zeta")
    assignments = repo.list_assignments()
    assert "temperature" not in assignments
    assert assignments["wind-field"] == "alpha"


# ---------------------------------------------------------------------------
# 管理端点测试
# ---------------------------------------------------------------------------


def test_group_repo_personal_isolation_and_theme_preset(tmp_path):
    repo = _repo_factory(tmp_path)
    from app.services.layer_group_repository import LayerGroupError

    a = repo.create_group("lab-a", "A 组", owner_user_id=1)
    b = repo.create_group("lab-b", "B 组", owner_user_id=2)
    assert a.owner_user_id == 1
    assert b.owner_user_id == 2

    ids_a = {g.group_id for g in repo.list_groups(owner_user_id=1)}
    ids_b = {g.group_id for g in repo.list_groups(owner_user_id=2)}
    assert "lab-a" in ids_a and "lab-b" not in ids_a
    assert "lab-b" in ids_b and "lab-a" not in ids_b

    # 种子改名写入个人覆盖，不污染共享种子
    repo.update_group("climate", name="气候-A", owner_user_id=1)
    shared_climate = next(g for g in repo.list_groups(0) if g.group_id == "climate")
    personal_climate = next(
        g for g in repo.list_groups(owner_user_id=1) if g.group_id == "climate"
    )
    assert shared_climate.name != "气候-A"
    assert personal_climate.name == "气候-A"

    repo.set_layer_assignments("lab-a", ["wind-field"], owner_user_id=1)
    assert repo.list_assignments(owner_user_id=1)["wind-field"] == "lab-a"
    assert "wind-field" not in repo.list_assignments(owner_user_id=2)

    meta = repo.sync_workspace_to_theme(1, theme_id=99)
    assert meta["has_preset"] is True
    preset = repo.get_theme_preset(99)
    assert preset is not None
    assert any(g["id"] == "lab-a" for g in preset["groups"])
    assert preset["assignments"]["wind-field"] == "lab-a"

    from app.services.layer_group_repository import CatalogGroupScope

    theme_groups = repo.list_groups_for_scope(CatalogGroupScope.theme(99))
    assert any(g.group_id == "lab-a" for g in theme_groups)
    assert repo.list_assignments_for_scope(CatalogGroupScope.theme(99))[
        "wind-field"
    ] == "lab-a"

    with pytest.raises(LayerGroupError):
        repo.delete_group("climate", owner_user_id=1)


def test_categories_require_auth_when_enabled(auth_client):
    """鉴权开启时 GET /layers/categories 与 /layers 一致：匿名 401。

    管理写操作带 theme_id 时直接写入主题预设（1A）。
    """
    client = auth_client
    resp = client.get("/layers/categories")
    assert resp.status_code == 401
    resp = client.get("/layers")
    assert resp.status_code == 401

    _login(client, "testadmin", "test-pass-123")
    assert client.get("/layers/categories").status_code == 200

    # GET 编辑预览（无预设 = 种子基线）
    resp = client.get("/layers/categories", params={"theme_id": 1})
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert any(c["id"] == "climate" for c in items)

    # 创建自建组 → 主题预设
    resp = client.post(
        "/layers/categories",
        params={"theme_id": 1},
        json={
            "id": "lab-custom",
            "name": "课题组专用",
            "icon": "B",
            "accent_color": "#7fd99a",
            "sub_categories": ["实验区"],
        },
    )
    assert resp.status_code == 200, resp.text
    created = resp.json()
    assert created["id"] == "lab-custom"
    assert created["is_custom"] is True

    # 改名
    resp = client.patch(
        "/layers/categories/lab-custom",
        params={"theme_id": 1},
        json={"name": "课题组专用（改）"},
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "课题组专用（改）"

    # 种子组改名允许、删除拒绝
    resp = client.patch(
        "/layers/categories/climate",
        params={"theme_id": 1},
        json={"name": "气候与灾害"},
    )
    assert resp.status_code == 200
    resp = client.delete("/layers/categories/climate", params={"theme_id": 1})
    assert resp.status_code == 400

    # 成员设置 + 排序
    resp = client.put(
        "/layers/categories/lab-custom/members",
        params={"theme_id": 1},
        json={"layer_ids": ["wind-field", "temperature"]},
    )
    assert resp.status_code == 200
    resp = client.put(
        "/layers/categories/order",
        params={"theme_id": 1},
        json={"order": ["lab-custom", "climate", "weather"]},
    )
    assert resp.status_code == 200
    ids = [c["id"] for c in resp.json()["items"]]
    assert ids.index("lab-custom") < ids.index("climate") < ids.index("weather")

    # 删除自建组
    resp = client.delete(
        "/layers/categories/lab-custom", params={"theme_id": 1}
    )
    assert resp.status_code == 200
    assert all(c["id"] != "lab-custom" for c in resp.json()["items"])


def test_catalog_reflects_group_assignment(auth_client):
    client = auth_client
    _login(client, "testadmin", "test-pass-123")

    client.post(
        "/layers/categories",
        params={"theme_id": 1},
        json={"id": "lab-custom", "name": "课题组专用"},
    )
    client.put(
        "/layers/categories/lab-custom/members",
        params={"theme_id": 1},
        json={"layer_ids": ["wind-field"]},
    )

    resp = client.get("/layers")
    assert resp.status_code == 200
    items = resp.json()["items"]
    by_id = {i["layer_id"]: i for i in items}
    # assignment 覆盖 descriptor.category
    assert by_id["wind-field"]["category"] == "lab-custom"
    # 其他图层回落种子 category
    other = next(i for i in items if i["layer_id"] != "wind-field")
    assert other["category"] != "lab-custom"


# ---------------------------------------------------------------------------
# 组级 ACL：layer 覆盖 > 组覆盖 > 模式默认；user > theme
# ---------------------------------------------------------------------------


def test_layer_group_acl_theme_whitelist(auth_client):
    client = auth_client
    _login(client, "testadmin", "test-pass-123")
    user = _create_user(client, "whitelist-user")
    uid = user["id"]

    # 主题默认 ACL：允许 weather 组、拒绝 climate 组（seed 组 id 即组 id）
    resp = client.put(
        "/auth/themes/1/permissions",
        json={
            "permissions": [
                {"resource_type": "layer_group", "resource_id": "weather", "permission": "allow"},
                {"resource_type": "layer_group", "resource_id": "climate", "permission": "deny"},
            ]
        },
    )
    assert resp.status_code == 200, resp.text

    # 用户切白名单模式
    resp = client.patch(f"/auth/users/{uid}/permission-mode", json={"mode": "whitelist"})
    assert resp.status_code == 200, resp.text

    # 以该用户登录，/layers 应只看到 weather 组图层
    client.post("/auth/logout")
    _login(client, "whitelist-user", "user-pass-123")
    resp = client.get("/layers")
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert items, "whitelist + group allow 应至少看到 weather 组图层"
    assert all(i["category"] == "weather" for i in items)

    # layer 级用户覆盖可以放行单个 climate 图层
    client.post("/auth/logout")
    _login(client, "testadmin", "test-pass-123")
    climate_layer = next(
        i["layer_id"] for i in client.get("/layers").json()["items"]
        if i["category"] == "climate"
    )
    resp = client.put(
        f"/auth/users/{uid}/permissions",
        json={
            "permissions": [
                {"resource_type": "layer", "resource_id": climate_layer, "permission": "allow"},
                {"resource_type": "layer_group", "resource_id": "weather", "permission": "allow"},
            ]
        },
    )
    assert resp.status_code == 200, resp.text

    client.post("/auth/logout")
    _login(client, "whitelist-user", "user-pass-123")
    resp = client.get("/layers")
    categories = {i["category"] for i in resp.json()["items"]}
    assert "weather" in categories
    assert climate_layer in {i["layer_id"] for i in resp.json()["items"]}


def test_layer_group_acl_open_mode_group_deny(auth_client):
    client = auth_client
    _login(client, "testadmin", "test-pass-123")
    user = _create_user(client, "open-user")
    uid = user["id"]

    # 开放模式下：主题对 vegetation 组 deny → 该组图层被拦
    resp = client.put(
        "/auth/themes/1/permissions",
        json={
            "permissions": [
                {"resource_type": "layer_group", "resource_id": "vegetation", "permission": "deny"},
            ]
        },
    )
    assert resp.status_code == 200, resp.text

    client.post("/auth/logout")
    _login(client, "open-user", "user-pass-123")
    resp = client.get("/layers")
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert items
    assert all(i["category"] != "vegetation" for i in items)

    # 用户 layer_group 覆盖 allow → 恢复可见
    client.post("/auth/logout")
    _login(client, "testadmin", "test-pass-123")
    resp = client.put(
        f"/auth/users/{uid}/permissions",
        json={
            "permissions": [
                {"resource_type": "layer_group", "resource_id": "vegetation", "permission": "allow"},
            ]
        },
    )
    assert resp.status_code == 200, resp.text

    client.post("/auth/logout")
    _login(client, "open-user", "user-pass-123")
    items = client.get("/layers").json()["items"]
    assert any(i["category"] == "vegetation" for i in items)


def test_assignment_move_changes_acl_group(auth_client):
    """图层移动分组后，经主题预设同步，组级 ACL 随新组生效。"""
    client = auth_client
    _login(client, "testadmin", "test-pass-123")

    # wind-field 属 weather 组；主题 deny vegetation → 同步预设后移入不可见
    client.put(
        "/auth/themes/1/permissions",
        json={
            "permissions": [
                {"resource_type": "layer_group", "resource_id": "vegetation", "permission": "deny"},
            ]
        },
    )
    client.post("/layers/categories", json={"id": "vg-move", "name": "移动测试组"})
    client.put(
        "/layers/categories/vegetation/members",
        json={"layer_ids": ["wind-field"]},
    )
    # 个人工作区需同步到主题后，绑定用户才消费新归属
    resp = client.post("/layers/categories/sync-to-theme/1")
    assert resp.status_code == 200, resp.text
    assert resp.json()["has_preset"] is True

    user = _create_user(client, "move-user")
    # 绑定主题 1（若创建时未绑定）
    client.patch(f"/auth/users/{user['id']}", json={"theme_id": 1})
    client.post("/auth/logout")
    _login(client, "move-user", "user-pass-123")
    items = client.get("/layers").json()["items"]
    assert all(i["layer_id"] != "wind-field" for i in items)


def test_theme_presets_are_isolated_per_theme(auth_client):
    """不同主题的分组预设彼此隔离（不再按管理员个人工作区隔离）。"""
    client = auth_client
    _login(client, "testadmin", "test-pass-123")
    demo = client.post(
        "/auth/themes",
        json={
            "slug": "demo-lab",
            "name_zh": "演示主题",
            "full_name_zh": "演示主题全称",
            "name_en": "Demo Lab Theme",
            "abbr": "DEMO",
            "default_permission_mode": "open",
        },
    )
    assert demo.status_code == 201, demo.text
    theme_b = int(demo.json()["id"])

    client.post(
        "/layers/categories",
        params={"theme_id": 1},
        json={"id": "only-sgfs", "name": "仅主主题"},
    )
    ids_a = {
        c["id"]
        for c in client.get("/layers/categories", params={"theme_id": 1}).json()["items"]
    }
    assert "only-sgfs" in ids_a

    ids_b = {
        c["id"]
        for c in client.get(
            "/layers/categories", params={"theme_id": theme_b}
        ).json()["items"]
    }
    assert "only-sgfs" not in ids_b

    client.post(
        "/layers/categories",
        params={"theme_id": theme_b},
        json={"id": "only-demo", "name": "仅演示主题"},
    )
    ids_b2 = {
        c["id"]
        for c in client.get(
            "/layers/categories", params={"theme_id": theme_b}
        ).json()["items"]
    }
    assert "only-demo" in ids_b2
    assert "only-demo" not in {
        c["id"]
        for c in client.get("/layers/categories", params={"theme_id": 1}).json()["items"]
    }


def test_theme_preset_direct_write_and_display_names(auth_client):
    """主题直写分组 + 显示名覆盖；清除预设后回落种子；种子 JSON 不变。"""
    import hashlib

    from app.services.layer_catalog import _SEEDS_DIR

    client = auth_client
    _login(client, "testadmin", "test-pass-123")

    categories_file = _SEEDS_DIR / "layer_categories.json"
    descriptors_file = _SEEDS_DIR / "layer_descriptors.json"

    def _digest(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    cat_before = _digest(categories_file)
    desc_before = _digest(descriptors_file)

    resp = client.post(
        "/layers/categories",
        params={"theme_id": 1},
        json={"id": "theme-lab", "name": "主题实验组"},
    )
    assert resp.status_code == 200, resp.text
    assert (
        client.put(
            "/layers/categories/theme-lab/members",
            params={"theme_id": 1},
            json={"layer_ids": ["wind-field"]},
        ).status_code
        == 200
    )

    # 显示名覆盖
    resp = client.put(
        "/layers/categories/theme-preset/1/display-names",
        json={"display_names": {"wind-field": "主题风场名"}},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["has_preset"] is True
    assert resp.json()["display_name_count"] >= 1

    detail = client.get("/layers/categories/theme-preset/1")
    assert detail.status_code == 200
    body = detail.json()
    assert body["has_preset"] is True
    assert body["display_names"]["wind-field"] == "主题风场名"
    assert any(g["id"] == "theme-lab" for g in body["groups"])

    user = _create_user(client, "preset-user")
    assert user["theme_id"] == 1
    client.post("/auth/logout")
    _login(client, "preset-user", "user-pass-123")

    cats = client.get("/layers/categories").json()["items"]
    assert any(c["id"] == "theme-lab" for c in cats)
    by_id = {i["layer_id"]: i for i in client.get("/layers").json()["items"]}
    assert by_id["wind-field"]["category"] == "theme-lab"
    assert by_id["wind-field"]["display_name"] == "主题风场名"

    client.post("/auth/logout")
    _login(client, "testadmin", "test-pass-123")
    assert client.delete("/layers/categories/theme-preset/1").status_code == 200

    # 种子文件未被运行时改写
    assert _digest(categories_file) == cat_before
    assert _digest(descriptors_file) == desc_before

    client.post("/auth/logout")
    _login(client, "preset-user", "user-pass-123")
    cats2 = {c["id"] for c in client.get("/layers/categories").json()["items"]}
    assert "theme-lab" not in cats2
    by_id2 = {i["layer_id"]: i for i in client.get("/layers").json()["items"]}
    assert by_id2["wind-field"]["display_name"] != "主题风场名"


def test_theme_preset_surfaces_synced_groups(auth_client):
    """个人工作区 sync-to-theme 仍可作为一次性导入路径。"""
    client = auth_client
    _login(client, "testadmin", "test-pass-123")
    # 省略 theme_id → 个人工作区（迁移兼容）
    client.post("/layers/categories", json={"id": "theme-lab", "name": "主题实验组"})
    client.put(
        "/layers/categories/theme-lab/members",
        json={"layer_ids": ["wind-field"]},
    )
    assert client.post("/layers/categories/sync-to-theme/1").status_code == 200

    user = _create_user(client, "preset-user")
    client.patch(f"/auth/users/{user['id']}", json={"theme_id": 1})
    client.post("/auth/logout")
    _login(client, "preset-user", "user-pass-123")

    cats = client.get("/layers/categories").json()["items"]
    assert any(c["id"] == "theme-lab" for c in cats)
    by_id = {i["layer_id"]: i for i in client.get("/layers").json()["items"]}
    assert by_id["wind-field"]["category"] == "theme-lab"


def test_theme_group_hidden_filtered_for_consumers(auth_client):
    """主题预设 hidden / hidden_sub_categories：消费者侧栏过滤；admin preview 全量。"""
    client = auth_client
    _login(client, "testadmin", "test-pass-123")

    assert (
        client.post(
            "/layers/categories",
            params={"theme_id": 1},
            json={"id": "hidden-lab", "name": "隐藏实验组"},
        ).status_code
        == 200
    )
    patch_climate = client.patch(
        "/layers/categories/climate",
        params={"theme_id": 1},
        json={"hidden": True},
    )
    assert patch_climate.status_code == 200, patch_climate.text
    assert patch_climate.json()["hidden"] is True

    patch_research = client.patch(
        "/layers/categories/research-group",
        params={"theme_id": 1},
        json={"hidden_sub_categories": ["模型输入"]},
    )
    assert patch_research.status_code == 200, patch_research.text
    assert "模型输入" in patch_research.json()["hidden_sub_categories"]

    # Admin preview with theme_id keeps hidden groups for editing.
    preview = {
        c["id"]: c
        for c in client.get("/layers/categories", params={"theme_id": 1}).json()["items"]
    }
    assert preview["climate"]["hidden"] is True
    assert "hidden-lab" in preview
    assert "模型输入" in preview["research-group"]["hidden_sub_categories"]

    detail = client.get("/layers/categories/theme-preset/1").json()
    assert any(g["id"] == "climate" and g.get("hidden") for g in detail["groups"])

    user = _create_user(client, "hide-user")
    assert user["theme_id"] == 1
    client.post("/auth/logout")
    _login(client, "hide-user", "user-pass-123")

    consumer = {c["id"]: c for c in client.get("/layers/categories").json()["items"]}
    assert "climate" not in consumer
    assert "hidden-lab" in consumer
    assert "模型输入" in consumer["research-group"]["hidden_sub_categories"]
