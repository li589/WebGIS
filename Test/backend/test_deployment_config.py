"""部署配置中心（deployment.config.json）真源与派生测试。

覆盖：_RUNTIME_ROOT 派生优先级、json>.env 覆盖、坏文件拒启（fail-closed）、
schema 校验规则、原子应用 + 失败回滚、备份轮换、脱敏。
"""

from __future__ import annotations

import importlib
import json
import os
from pathlib import Path
from types import ModuleType

import pytest

import app.core.config as config_module
from app.services import deployment_config as dc
from app.services.effective_config import assert_deployment_config_policy

_RELOAD_KEYS = ("BACKEND_DATA_ROOT", "BACKEND_RUNTIME_ROOT", "BACKEND_DEPLOYMENT_CONFIG")


@pytest.fixture()
def reload_config(tmp_path: Path):
    """受控重载 app.core.config：显式派生键 + 隔离 deployment.json；teardown 复原。

    用空串（而非删除键）表示"未设置"：load_dotenv(override=False) 不会覆盖
    已存在的键（含空值），从而屏蔽机器 .env 注入，保证重载确定性。
    """
    saved = {key: os.environ.get(key) for key in _RELOAD_KEYS}

    def _reload(**env: str) -> ModuleType:
        for key, value in env.items():
            os.environ[key] = value
        return importlib.reload(config_module)

    try:
        yield _reload
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        importlib.reload(config_module)


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch):
    """管理员级 TestClient（服务密钥 + admin 角色），覆盖 conftest 匿名 client。

    /config/deployment* 走 require_config_read_access / require_config_management_access，
    无凭据会 401；与 test_config_write_offload 同款鉴权模式。
    """
    from dataclasses import replace

    from fastapi.testclient import TestClient

    from app.core.config import settings
    from app.main import create_app

    monkeypatch.setattr(
        "app.services.effective_config.get_backend_auth_key",
        lambda: "test-key",
    )
    monkeypatch.setattr(
        "app.core.config.settings",
        replace(settings, api_key_role="admin"),
    )
    return TestClient(create_app(), headers={"X-API-Key": "test-key"})


@pytest.fixture()
def isolated_apply_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """把 deployment_config 的写入面整体隔离到 tmp（json/backend .env/sync .env）。"""
    monkeypatch.setattr(dc, "_BACKEND_ROOT", tmp_path)
    monkeypatch.setenv("BACKEND_DEPLOYMENT_CONFIG", str(tmp_path / "deployment.config.json"))
    monkeypatch.setenv(
        "BACKEND_OPEN_METEO_SYNC_COMPOSE_DIR", str(tmp_path / "data-sync")
    )
    return tmp_path


# ── _RUNTIME_ROOT 派生优先级（H1 去硬编码）─────────────────────────────────


def test_runtime_root_explicit_env_wins(tmp_path: Path, reload_config) -> None:
    mod = reload_config(
        BACKEND_DATA_ROOT=str(tmp_path / "geo"),
        BACKEND_RUNTIME_ROOT=str(tmp_path / "rt"),
        BACKEND_DEPLOYMENT_CONFIG=str(tmp_path / "absent.json"),
    )
    assert mod._RUNTIME_ROOT == Path(str(tmp_path / "rt"))


def test_runtime_root_derives_from_data_root(tmp_path: Path, reload_config) -> None:
    mod = reload_config(
        BACKEND_DATA_ROOT=str(tmp_path / "geo"),
        BACKEND_RUNTIME_ROOT="",
        BACKEND_DEPLOYMENT_CONFIG=str(tmp_path / "absent.json"),
    )
    expected = Path(str(tmp_path / "geo")) / "_runtime"
    assert mod._RUNTIME_ROOT == expected
    assert mod.DEFAULT_LOG_DIR == expected / "logs"
    assert mod.DEFAULT_WORKFLOW_STATE_DIR == expected / "workflow_state"
    assert mod.DEFAULT_CACHE_DIR == expected / "cache"
    assert mod.DEFAULT_ARTIFACT_DIR == expected / "artifacts"


def test_runtime_root_dev_fallback_without_any_root(tmp_path: Path, reload_config) -> None:
    mod = reload_config(
        BACKEND_DATA_ROOT="",
        BACKEND_RUNTIME_ROOT="",
        BACKEND_DEPLOYMENT_CONFIG=str(tmp_path / "absent.json"),
    )
    assert mod._RUNTIME_ROOT == mod.BACKEND_ROOT / ".data" / "_runtime"


def test_no_lab_drive_default_in_config_source() -> None:
    source = Path(config_module.__file__).read_text(encoding="utf-8")
    assert "Geograph_DataSet" not in source


# ── deployment.json 启动覆盖（json 优先于 .env，fail-closed）────────────────


def test_deployment_json_overrides_env_and_derivation(
    tmp_path: Path, reload_config
) -> None:
    data_dir = tmp_path / "geo_json"
    data_dir.mkdir()
    rt_dir = tmp_path / "rt_json"
    json_path = tmp_path / "deploy.json"
    json_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "data": {"data_root": str(data_dir)},
                "runtime": {"runtime_root": str(rt_dir)},
            }
        ),
        encoding="utf-8",
    )
    mod = reload_config(
        BACKEND_DATA_ROOT=str(tmp_path / "env_style_root"),
        BACKEND_RUNTIME_ROOT="",
        BACKEND_DEPLOYMENT_CONFIG=str(json_path),
    )
    assert mod._RUNTIME_ROOT == Path(str(rt_dir))
    assert os.environ["BACKEND_DATA_ROOT"] == str(data_dir)
    assert mod.DEPLOYMENT_OVERRIDES_APPLIED == [
        "BACKEND_DATA_ROOT",
        "BACKEND_RUNTIME_ROOT",
    ]


def test_deployment_json_data_root_drives_runtime_derivation(
    tmp_path: Path, reload_config
) -> None:
    data_dir = tmp_path / "geo_only"
    data_dir.mkdir()
    json_path = tmp_path / "deploy.json"
    json_path.write_text(
        json.dumps({"schema_version": 1, "data": {"data_root": str(data_dir)}}),
        encoding="utf-8",
    )
    mod = reload_config(
        BACKEND_DATA_ROOT="",
        BACKEND_RUNTIME_ROOT="",
        BACKEND_DEPLOYMENT_CONFIG=str(json_path),
    )
    assert mod._RUNTIME_ROOT == Path(str(data_dir)) / "_runtime"


def test_corrupt_json_refuses_startup_with_bak_hint(
    tmp_path: Path, reload_config
) -> None:
    json_path = tmp_path / "deploy.json"
    json_path.write_text("{ not valid json", encoding="utf-8")
    json_path.with_name("deploy.json.bak.1").write_text("{}", encoding="utf-8")
    with pytest.raises(dc.DeploymentConfigError, match="bak.1"):
        reload_config(
            BACKEND_DATA_ROOT="",
            BACKEND_RUNTIME_ROOT="",
            BACKEND_DEPLOYMENT_CONFIG=str(json_path),
        )


def test_schema_invalid_json_refuses_startup(tmp_path: Path, reload_config) -> None:
    json_path = tmp_path / "deploy.json"
    json_path.write_text(
        json.dumps({"schema_version": 1, "data": {"data_root": "relative/path"}}),
        encoding="utf-8",
    )
    with pytest.raises(dc.DeploymentConfigError, match="校验失败"):
        reload_config(
            BACKEND_DATA_ROOT="",
            BACKEND_RUNTIME_ROOT="",
            BACKEND_DEPLOYMENT_CONFIG=str(json_path),
        )


def test_assert_deployment_config_policy_corrupt_file_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    json_path = tmp_path / "deploy.json"
    json_path.write_text("broken", encoding="utf-8")
    monkeypatch.setenv("BACKEND_DEPLOYMENT_CONFIG", str(json_path))
    with pytest.raises(RuntimeError, match="deployment config"):
        assert_deployment_config_policy()


def test_assert_deployment_config_policy_missing_file_noop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BACKEND_DEPLOYMENT_CONFIG", str(tmp_path / "absent.json"))
    assert_deployment_config_policy()  # no raise


# ── validate_payload 规则 ────────────────────────────────────────────────────


def test_validate_rejects_unknown_keys_and_bad_version() -> None:
    result = dc.validate_payload(
        {"schema_version": 2, "unknown_group": {}, "data": {"nope": "x"}, "notes": 5}
    )
    assert not result.ok
    assert any("schema_version" in e for e in result.errors)
    assert any("未知顶层键" in e for e in result.errors)
    assert any("未知键" in e for e in result.errors)
    assert any("notes" in e for e in result.errors)


def test_validate_path_rules(tmp_path: Path) -> None:
    good_dir = tmp_path / "geo"
    good_dir.mkdir()
    result = dc.validate_payload(
        {
            "schema_version": 1,
            "data": {
                "data_root": str(good_dir),
                "output_root": "relative/path",
                "project_backup_root": str(tmp_path / "not_yet"),
            },
        }
    )
    assert not result.ok
    assert any("绝对路径" in e for e in result.errors)
    # must_exist 的 data_root 已存在 → 无误；output_root 相对 → 误
    assert result.normalized["data"]["data_root"] == str(good_dir)

    missing = dc.validate_payload(
        {"schema_version": 1, "data": {"data_root": str(tmp_path / "missing_root")}}
    )
    assert any("不存在" in e for e in missing.errors)


def test_validate_cache_dir_missing_warns_then_creates(tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache_new"
    payload = {"schema_version": 1, "caches": {"cache_dir": str(cache_dir)}}
    preview = dc.validate_payload(payload)
    assert preview.ok
    assert any("自动创建" in w for w in preview.warnings)
    assert not cache_dir.exists()  # preview 纯只读

    applied = dc.validate_payload(payload, create_dirs=True)
    assert applied.ok
    assert cache_dir.is_dir()


def test_validate_int_and_level_and_url_rules() -> None:
    result = dc.validate_payload(
        {
            "schema_version": 1,
            "runtime": {"log_level": "debug", "spatialite_db_path": "C:/x/db.sq3"},
            "caches": {"static_cache_ttl_seconds": True},
            "imports": {"max_imports_total_bytes": 0},
            "docker": {
                "open_meteo_host_port": 70000,
                "open_meteo_local_url": "ftp://x",
            },
        }
    )
    assert not result.ok
    assert any("static_cache_ttl_seconds" in e for e in result.errors)
    assert any("max_imports_total_bytes" in e for e in result.errors)
    assert any("open_meteo_host_port" in e for e in result.errors)
    assert any("http(s)" in e for e in result.errors)
    assert result.normalized["runtime"]["log_level"] == "DEBUG"

    bad_level = dc.validate_payload(
        {"schema_version": 1, "runtime": {"log_level": "VERBOSE"}}
    )
    assert any("VERBOSE" in e for e in bad_level.errors)


def test_validate_empty_values_mean_unset() -> None:
    result = dc.validate_payload(
        {
            "schema_version": 1,
            "data": {"data_root": ""},
            "docker": {"minio_root_password": ""},
        }
    )
    assert result.ok
    assert result.normalized == {}


# ── 原子应用：成功 / 双写 / 回滚 / 备份轮换 ──────────────────────────────────


def _valid_payload(tmp_path: Path) -> dict:
    root = tmp_path / "geo_root"
    root.mkdir(parents=True, exist_ok=True)
    return {
        "schema_version": 1,
        "data": {"data_root": str(root)},
        "docker": {
            "minio_root_user": "cgda-minio",
            "open_meteo_data_volume": "vol-x",
            "open_meteo_sync_domains": "gfs_global",
        },
    }


def test_apply_writes_env_sync_env_and_json(tmp_path: Path, isolated_apply_env) -> None:
    result = dc.apply_deployment_config(_valid_payload(tmp_path))
    assert result["restart_level"] == "restart-full"
    assert result["pending_restart"] is True

    env_text = (tmp_path / ".env").read_text(encoding="utf-8")
    assert "BACKEND_DATA_ROOT=" in env_text
    assert "MINIO_ROOT_USER=cgda-minio" in env_text
    assert "OPEN_METEO_DATA_VOLUME=vol-x" in env_text
    assert "OPEN_METEO_SYNC_DOMAINS=gfs_global" in env_text

    sync_text = (tmp_path / "data-sync" / ".env").read_text(encoding="utf-8")
    assert "OPEN_METEO_DATA_VOLUME=vol-x" in sync_text
    assert "OPEN_METEO_SYNC_DOMAINS=gfs_global" in sync_text
    assert "MINIO_ROOT_USER" not in sync_text  # sync 只双写限定的键

    doc = json.loads((tmp_path / "deployment.config.json").read_text(encoding="utf-8"))
    assert doc["schema_version"] == 1
    assert doc["data"]["data_root"].endswith("geo_root")


def test_apply_creates_backup_and_rotates(tmp_path: Path, isolated_apply_env) -> None:
    dc.apply_deployment_config(_valid_payload(tmp_path))
    dc.apply_deployment_config(_valid_payload(tmp_path))
    dc.apply_deployment_config(_valid_payload(tmp_path))
    dc.apply_deployment_config(_valid_payload(tmp_path))
    names = {b["name"] for b in dc.list_backups()}
    assert names == {
        "deployment.config.json.bak.1",
        "deployment.config.json.bak.2",
        "deployment.config.json.bak.3",
    }


def test_apply_invalid_payload_touches_nothing(tmp_path: Path, isolated_apply_env) -> None:
    payload = _valid_payload(tmp_path)
    payload["data"]["output_root"] = "relative/path"
    with pytest.raises(dc.DeploymentConfigError, match="校验失败"):
        dc.apply_deployment_config(payload)
    assert not (tmp_path / ".env").exists()
    assert not (tmp_path / "deployment.config.json").exists()


def test_apply_rolls_back_all_files_on_failure(
    tmp_path: Path, isolated_apply_env, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / ".env").write_text("BACKEND_EXISTING=1\n", encoding="utf-8")
    real_write = dc._atomic_write_bytes

    def flaky_write(path: Path, data: bytes) -> None:
        if path.name == "deployment.config.json":
            raise OSError("simulated disk full")
        return real_write(path, data)

    monkeypatch.setattr(dc, "_atomic_write_bytes", flaky_write)
    with pytest.raises(dc.DeploymentConfigError, match="回滚"):
        dc.apply_deployment_config(_valid_payload(tmp_path))

    assert (tmp_path / ".env").read_text(encoding="utf-8") == "BACKEND_EXISTING=1\n"
    assert not (tmp_path / "deployment.config.json").exists()
    sync_dir = tmp_path / "data-sync"
    if (sync_dir / ".env").exists():
        # 回滚后 sync .env 若被创建过应被删除（原本不存在）
        assert (sync_dir / ".env").read_text(encoding="utf-8").strip() == ""


def test_rotate_backups_shifts_and_drops_oldest(tmp_path: Path) -> None:
    json_path = tmp_path / "deployment.config.json"
    json_path.write_text("current", encoding="utf-8")
    for i in (1, 2, 3):
        json_path.with_name(f"deployment.config.json.bak.{i}").write_text(
            f"old{i}", encoding="utf-8"
        )
    dc.rotate_backups(json_path)
    assert json_path.read_text(encoding="utf-8") == "current"
    assert json_path.with_name("deployment.config.json.bak.1").read_text(encoding="utf-8") == "current"
    assert json_path.with_name("deployment.config.json.bak.2").read_text(encoding="utf-8") == "old1"
    assert json_path.with_name("deployment.config.json.bak.3").read_text(encoding="utf-8") == "old2"


# ── 元数据与脱敏 ─────────────────────────────────────────────────────────────


def test_key_metadata_groups_and_restart_levels() -> None:
    meta = dc.key_metadata()
    groups = {m["group"] for m in meta}
    assert groups == {"data", "runtime", "caches", "imports", "docker"}
    by_key = {(m["group"], m["key"]): m for m in meta}
    assert by_key[("docker", "minio_root_password")]["restart_level"] == "restart-full"
    assert by_key[("docker", "minio_root_password")]["sensitive"] is True
    assert by_key[("data", "data_root")]["must_exist"] is True
    assert by_key[("docker", "open_meteo_data_volume")]["double_write_sync"] is True


def test_redact_payload_masks_password_only() -> None:
    payload = {
        "schema_version": 1,
        "docker": {"minio_root_password": "s3cret", "minio_root_user": "u1"},
        "notes": "deploy notes",
    }
    redacted = dc.redact_payload(payload)
    assert redacted["docker"]["minio_root_password"] == "••••"
    assert redacted["docker"]["minio_root_user"] == "u1"
    assert payload["docker"]["minio_root_password"] == "s3cret"  # 原对象不被改


def test_apply_startup_overrides_returns_applied_keys(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_dir = tmp_path / "geo"
    data_dir.mkdir()
    json_path = tmp_path / "deploy.json"
    json_path.write_text(
        json.dumps({"schema_version": 1, "data": {"data_root": str(data_dir)}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("BACKEND_DEPLOYMENT_CONFIG", str(json_path))
    saved = os.environ.get("BACKEND_DATA_ROOT")
    try:
        applied = dc.apply_startup_overrides()
        assert applied == ["BACKEND_DATA_ROOT"]
        assert os.environ["BACKEND_DATA_ROOT"] == str(data_dir)
        status = dc.startup_status()
        assert status["exists"] is True
        assert status["applied_env_keys"] == ["BACKEND_DATA_ROOT"]
    finally:
        if saved is None:
            os.environ.pop("BACKEND_DATA_ROOT", None)
        else:
            os.environ["BACKEND_DATA_ROOT"] = saved


# ── 状态查询与预览（Batch 2）─────────────────────────────────────────────────


def test_get_deployment_status_masks_and_detects_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from dataclasses import replace
    from unittest.mock import patch

    from app.core import config

    monkeypatch.setattr(dc, "_BACKEND_ROOT", tmp_path)
    monkeypatch.setenv(
        "BACKEND_DEPLOYMENT_CONFIG", str(tmp_path / "deployment.config.json")
    )
    (tmp_path / ".env").write_text(
        "BACKEND_LOG_LEVEL=DEBUG\nMINIO_ROOT_PASSWORD=hunter2\n", encoding="utf-8"
    )
    (tmp_path / "deployment.config.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "runtime": {"log_level": "WARNING"},
                "docker": {"minio_root_password": "newpass"},
                "notes": "lab deploy",
            }
        ),
        encoding="utf-8",
    )

    with patch(
        "app.core.config.settings", replace(config.settings, log_level="INFO")
    ):
        status = dc.get_deployment_status()

    by = {(k["group"], k["key"]): k for k in status["keys"]}
    # password 全链路脱敏（env 与 config 两侧）
    assert by[("docker", "minio_root_password")]["env_value"] == "••••"
    assert by[("docker", "minio_root_password")]["config_value"] == "••••"
    # config 优先于 env 作为来源；运行值未加载 → pending
    assert by[("runtime", "log_level")]["source"] == "config"
    assert by[("runtime", "log_level")]["pending"] is True
    assert status["pending_restart"] is True
    assert status["notes"] == "lab deploy"
    assert status["exists"] is True
    # env-only 键（json 未覆盖）：来源 env
    assert by[("data", "project_backup_root")]["source"] in {"env", "default"}


def test_preview_deployment_config_masks_password_diff(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BACKEND_DEPLOYMENT_CONFIG", str(tmp_path / "x.json"))
    result = dc.preview_deployment_config(
        {"schema_version": 1, "docker": {"minio_root_password": "topsecret"}}
    )
    assert result["ok"] is True
    item = next(d for d in result["diff"] if d["key"] == "minio_root_password")
    assert item["new"] == "••••"
    assert "topsecret" not in json.dumps(result)
    assert result["restart_level"] == "restart-full"


def test_preview_no_change_yields_empty_diff(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from dataclasses import replace
    from unittest.mock import patch

    from app.core import config

    monkeypatch.setenv("BACKEND_DEPLOYMENT_CONFIG", str(tmp_path / "x.json"))
    with patch(
        "app.core.config.settings", replace(config.settings, log_level="DEBUG")
    ):
        result = dc.preview_deployment_config(
            {"schema_version": 1, "runtime": {"log_level": "DEBUG"}}
        )
    assert result["ok"] is True
    assert result["diff"] == []
    assert result["restart_level"] == "none"


# ── data_root 变更联动派生 output_root（"所有数据都存在数据根下"）────────────


def _read_env_mirror(tmp_path: Path) -> dict[str, str]:
    from app.services.env_file_upsert import read_env_file_values

    return read_env_file_values(tmp_path / ".env")


def test_apply_data_root_change_links_output_root(
    tmp_path: Path, isolated_apply_env
) -> None:
    root = tmp_path / "geo_root"
    root.mkdir()
    result = dc.apply_deployment_config(
        {"schema_version": 1, "data": {"data_root": str(root)}}
    )
    derived = str(root / "ProjectOutput")
    assert "BACKEND_OUTPUT_ROOT" in result["applied_env_keys"]
    assert _read_env_mirror(tmp_path)["BACKEND_OUTPUT_ROOT"] == derived
    assert Path(derived).is_dir()  # 应用时自动创建派生产物根
    doc = json.loads((tmp_path / "deployment.config.json").read_text(encoding="utf-8"))
    assert "output_root" not in doc.get("data", {})  # 保持隐式：换根继续跟随
    assert any("联动派生" in w for w in result["warnings"])


def test_apply_data_root_unchanged_keeps_output_root(
    tmp_path: Path, isolated_apply_env
) -> None:
    root = tmp_path / "geo_root"
    root.mkdir()
    custom_out = tmp_path / "custom_out"
    (tmp_path / ".env").write_text(
        f"BACKEND_DATA_ROOT={root}\nBACKEND_OUTPUT_ROOT={custom_out}\n",
        encoding="utf-8",
    )
    result = dc.apply_deployment_config(
        {"schema_version": 1, "data": {"data_root": str(root)}}
    )
    assert "BACKEND_OUTPUT_ROOT" not in result["applied_env_keys"]
    assert _read_env_mirror(tmp_path)["BACKEND_OUTPUT_ROOT"] == str(custom_out)


def test_apply_explicit_output_root_wins(
    tmp_path: Path, isolated_apply_env
) -> None:
    root = tmp_path / "geo_root"
    out = tmp_path / "custom_out"
    root.mkdir()
    out.mkdir()
    dc.apply_deployment_config(
        {
            "schema_version": 1,
            "data": {"data_root": str(root), "output_root": str(out)},
        }
    )
    doc = json.loads((tmp_path / "deployment.config.json").read_text(encoding="utf-8"))
    assert doc["data"]["output_root"] == str(out)
    assert _read_env_mirror(tmp_path)["BACKEND_OUTPUT_ROOT"] == str(out)


def test_preview_marks_linked_output_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BACKEND_DEPLOYMENT_CONFIG", str(tmp_path / "x.json"))
    monkeypatch.setattr(dc, "_BACKEND_ROOT", tmp_path)
    root = tmp_path / "geo_new"
    root.mkdir()
    result = dc.preview_deployment_config(
        {"schema_version": 1, "data": {"data_root": str(root)}}
    )
    assert result["ok"] is True
    item = next(d for d in result["diff"] if d["key"] == "output_root")
    assert item["derived"] is True
    assert item["new"] == str(root / "ProjectOutput")
    assert item["restart_level"] == "restart-backend"
    assert any("联动派生" in w for w in result["warnings"])
    assert not (root / "ProjectOutput").exists()  # 预览纯只读，不建目录


# ── API 端点（Batch 2）───────────────────────────────────────────────────────


def test_deployment_api_roundtrip(
    client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(dc, "_BACKEND_ROOT", tmp_path)
    monkeypatch.setenv(
        "BACKEND_DEPLOYMENT_CONFIG", str(tmp_path / "deployment.config.json")
    )
    monkeypatch.setenv(
        "BACKEND_OPEN_METEO_SYNC_COMPOSE_DIR", str(tmp_path / "data-sync")
    )
    root = tmp_path / "geo_root"
    root.mkdir()

    status = client.get("/config/deployment")
    assert status.status_code == 200
    body = status.json()
    assert body["exists"] is False
    assert len(body["keys"]) >= 20

    # preview：无效相对路径 → errors，且不产生任何文件（纯只读）
    prev = client.post(
        "/config/deployment/preview",
        json={"schema_version": 1, "data": {"output_root": "relative/x"}},
    )
    assert prev.status_code == 200
    assert prev.json()["ok"] is False
    assert not (tmp_path / "deployment.config.json").exists()

    # preview：有效 → diff 含 data_root
    prev2 = client.post(
        "/config/deployment/preview",
        json={"schema_version": 1, "data": {"data_root": str(root)}},
    )
    assert prev2.json()["ok"] is True
    assert any(item["key"] == "data_root" for item in prev2.json()["diff"])

    # PUT：保存 + 双 .env 镜像 + json 落盘
    put = client.put(
        "/config/deployment",
        json={
            "schema_version": 1,
            "data": {"data_root": str(root)},
            "docker": {"minio_root_user": "cgda-minio"},
        },
    )
    assert put.status_code == 200
    result = put.json()
    assert result["restart_level"] == "restart-full"
    assert "已保存" in result["message"]
    assert "MINIO_ROOT_USER=cgda-minio" in (tmp_path / ".env").read_text(encoding="utf-8")
    assert (tmp_path / "deployment.config.json").is_file()

    # 保存后状态：config 值可见，来源 config
    status2 = client.get("/config/deployment").json()
    by_key = {(k["group"], k["key"]): k for k in status2["keys"]}
    assert by_key[("data", "data_root")]["config_value"].endswith("geo_root")
    assert by_key[("data", "data_root")]["source"] == "config"

    # 导出：默认脱敏
    client.put(
        "/config/deployment",
        json={
            "schema_version": 1,
            "docker": {"minio_root_password": "s3cret-value"},
        },
    )
    exp = client.get("/config/deployment/export")
    assert exp.status_code == 200
    assert "s3cret-value" not in exp.text
    assert "attachment" in exp.headers["content-disposition"]


def test_deployment_export_404_when_file_missing(
    client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BACKEND_DEPLOYMENT_CONFIG", str(tmp_path / "none.json"))
    resp = client.get("/config/deployment/export")
    assert resp.status_code == 404


def test_deployment_put_invalid_returns_400(
    client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(dc, "_BACKEND_ROOT", tmp_path)
    monkeypatch.setenv(
        "BACKEND_DEPLOYMENT_CONFIG", str(tmp_path / "deployment.config.json")
    )
    resp = client.put(
        "/config/deployment",
        json={"schema_version": 1, "data": {"data_root": "relative/nope"}},
    )
    assert resp.status_code == 400
    assert not (tmp_path / "deployment.config.json").exists()
