"""API key history archive / restore / trim."""
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


def _repo(tmp_path, monkeypatch, *, limit: int = 20):
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
    object.__setattr__(config_service.settings, "api_key_history_limit", limit)
    monkeypatch.setattr(config_service, "_env_api_key_value", lambda _n: "")

    # 关闭上一个 lru_cache 中的 repository 连接池，避免 Windows 文件句柄泄漏
    # 导致 tmp_path 清理时 PermissionError [WinError 5]
    if config_service._get_api_keys_repository.cache_info().currsize > 0:
        config_service._get_api_keys_repository().close()
    config_service._get_api_keys_repository.cache_clear()
    config_service._get_effective_api_key_cached.cache_clear()
    return config_service


def test_upsert_archives_previous_version(tmp_path, monkeypatch):
    cs = _repo(tmp_path, monkeypatch)
    cs.upsert_api_key("tianditu", "first-key-value-aaa", history_label="v1")
    cs.upsert_api_key("tianditu", "second-key-value-bbb", history_label="v2")
    hist = cs.list_api_key_history("tianditu")
    assert len(hist) == 1
    assert "****" in hist[0]["masked_value"]
    assert hist[0]["label"] == "v2" or hist[0]["source"] == "user"
    assert cs.get_effective_api_key("tianditu") == "second-key-value-bbb"


def test_restore_archives_current_and_applies_old(tmp_path, monkeypatch):
    cs = _repo(tmp_path, monkeypatch)
    cs.upsert_api_key("baidu", "baidu-key-alpha-111")
    cs.upsert_api_key("baidu", "baidu-key-beta-2222")
    hist = cs.list_api_key_history("baidu")
    assert len(hist) == 1
    hid = hist[0]["id"]
    cs.restore_api_key_history("baidu", hid)
    assert cs.get_effective_api_key("baidu") == "baidu-key-alpha-111"
    # current beta should now be archived
    hist2 = cs.list_api_key_history("baidu")
    assert len(hist2) >= 2
    sources = {h["source"] for h in hist2}
    assert "restore" in sources or "user" in sources


def test_history_trim_limit(tmp_path, monkeypatch):
    cs = _repo(tmp_path, monkeypatch, limit=3)
    for i in range(6):
        cs.upsert_api_key("tianditu", f"tianditu-rotating-key-{i:02d}")
    hist = cs.list_api_key_history("tianditu")
    assert len(hist) <= 3


def test_delete_and_clear_history(tmp_path, monkeypatch):
    cs = _repo(tmp_path, monkeypatch)
    cs.upsert_api_key("tianditu", "key-one-aaaaaaa")
    cs.upsert_api_key("tianditu", "key-two-bbbbbbb")
    hist = cs.list_api_key_history("tianditu")
    assert len(hist) == 1
    assert cs.delete_api_key_history_entry("tianditu", hist[0]["id"]) is True
    assert cs.list_api_key_history("tianditu") == []
    cs.upsert_api_key("tianditu", "key-three-cccccc")
    assert cs.clear_api_key_history("tianditu") >= 1
    assert cs.list_api_key_history("tianditu") == []


def test_remote_storage_secret_history(tmp_path, monkeypatch):
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
    object.__setattr__(config_service.settings, "remote_storage_history_limit", 20)
    config_service._get_remote_storage_repository.cache_clear()

    config_service.upsert_remote_storage_profile(
        "nas-lab",
        protocol="sftp",
        host="nas.local",
        username="u",
        secret="secret-one",
    )
    config_service.upsert_remote_storage_profile(
        "nas-lab",
        protocol="sftp",
        host="nas.local",
        username="u",
        secret="secret-two",
    )
    hist = config_service.list_remote_storage_history("nas-lab")
    assert len(hist) == 1
    assert "****" in hist[0]["masked_secret"]
    hid = hist[0]["id"]
    config_service.restore_remote_storage_history("nas-lab", hid)
    bundle = config_service._get_remote_storage_repository().get_secret_bundle("nas-lab")
    assert bundle is not None
    assert bundle["secret"] == "secret-one"
