"""API key list/toggle/effective semantics for basemap settings."""

from __future__ import annotations

import sys
from pathlib import Path

_CODE_ROOT = Path(__file__).resolve().parents[2]
_PYTHON_PROVIDER = _CODE_ROOT / "algorithms" / "providers" / "Python"
for _p in (_PYTHON_PROVIDER, _CODE_ROOT):
    _s = str(_p)
    if _s in sys.path:
        sys.path.remove(_s)
    sys.path.insert(0, _s)


def _fresh_repo(tmp_path, monkeypatch, *, env_keys: dict[str, str] | None = None):
    from app.services import config_service

    monkeypatch.setenv("BACKEND_ENVIRONMENT", "development")
    db_parent = tmp_path / "workflow_state"
    db_parent.mkdir(parents=True, exist_ok=True)
    object.__setattr__(
        config_service.settings,
        "gee_credentials_db_path",
        str(db_parent / "gee.sqlite3"),
    )
    object.__setattr__(config_service.settings, "gee_credentials_encryption_key", "")

    env = env_keys or {}
    monkeypatch.setattr(
        config_service,
        "_env_api_key_value",
        lambda name: str(env.get(name) or "").strip(),
    )

    # 关闭上一个 lru_cache 中的 repository 连接池，避免 Windows 文件句柄泄漏
    # 导致 tmp_path 清理时 PermissionError [WinError 5]
    if config_service._get_api_keys_repository.cache_info().currsize > 0:
        config_service._get_api_keys_repository().close()
    config_service._get_api_keys_repository.cache_clear()
    config_service._get_effective_api_key_cached.cache_clear()
    return config_service


def test_list_shows_none_placeholder(tmp_path, monkeypatch):
    cs = _fresh_repo(tmp_path, monkeypatch)
    keys = {k["key_name"]: k for k in cs.list_api_keys()}
    assert keys["tianditu"]["source"] == "none"
    assert keys["tianditu"]["has_value"] is False
    assert keys["tianditu"]["enabled"] is False


def test_list_shows_env_masked(tmp_path, monkeypatch):
    cs = _fresh_repo(tmp_path, monkeypatch, env_keys={"tianditu": "tdt-env-key-abcdef"})
    keys = {k["key_name"]: k for k in cs.list_api_keys()}
    assert keys["tianditu"]["source"] == "env"
    assert keys["tianditu"]["has_value"] is True
    assert keys["tianditu"]["enabled"] is True
    assert "****" in keys["tianditu"]["masked_value"]
    assert cs.get_effective_api_key("tianditu") == "tdt-env-key-abcdef"


def test_toggle_without_value_raises(tmp_path, monkeypatch):
    import pytest

    cs = _fresh_repo(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="请先保存"):
        cs.toggle_api_key("tianditu", True)


def test_toggle_env_materializes_and_disable_blocks_env(tmp_path, monkeypatch):
    cs = _fresh_repo(tmp_path, monkeypatch, env_keys={"tianditu": "tdt-env-key-abcdef"})
    assert cs.get_effective_api_key("tianditu") == "tdt-env-key-abcdef"

    cs.toggle_api_key("tianditu", False)
    cs._get_effective_api_key_cached.cache_clear()
    assert cs.get_effective_api_key("tianditu") is None

    listed = {k["key_name"]: k for k in cs.list_api_keys()}
    assert listed["tianditu"]["source"] == "db"
    assert listed["tianditu"]["enabled"] is False

    cs.toggle_api_key("tianditu", True)
    cs._get_effective_api_key_cached.cache_clear()
    assert cs.get_effective_api_key("tianditu") == "tdt-env-key-abcdef"


def test_upsert_respects_enabled_false(tmp_path, monkeypatch):
    cs = _fresh_repo(tmp_path, monkeypatch)
    cs.upsert_api_key("baidu", "baidu-secret-value-01", enabled=False)
    cs._get_effective_api_key_cached.cache_clear()
    assert cs.get_effective_api_key("baidu") is None
    cs.toggle_api_key("baidu", True)
    cs._get_effective_api_key_cached.cache_clear()
    assert cs.get_effective_api_key("baidu") == "baidu-secret-value-01"
