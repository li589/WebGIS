"""异常捕获收窄的回归与行为变更验证（QA 阶段新增）。

覆盖 PRD 要求的 6 类场景：
1. 预期缺失 FileNotFoundError -> 404 + 原 detail
2. 客户端校验 ValueError/RuntimeError -> 400 + 原 detail
3. 配额 QuotaExceededError -> 507（验证 507-before-400 isinstance 顺序）
4. 真错误 JSONDecodeError/OSError -> 500 + "Internal server error"（行为变更：不再 404/不再泄露 str(exc)）
5. config_service 探测函数：SSRFBlockedError -> 失败元组；意外异常 -> 失败元组 + logger.exception
6. 信息泄露修复：未知异常含敏感字符串 -> 500 + detail 不含敏感内容
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path
from unittest.mock import patch

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
def api_client(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKEND_ENV", "test")
    monkeypatch.setenv("BACKEND_DATA_ROOT", str(tmp_path / "data"))
    monkeypatch.setenv("BACKEND_OUTPUT_ROOT", str(tmp_path / "out"))
    monkeypatch.setenv("BACKEND_WORKFLOW_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("BACKEND_API_KEYS_ENABLED", "false")

    import app.core.config as cfg_mod
    from app.core.config import Settings

    cfg_mod.settings = Settings()

    monkeypatch.setattr(
        "app.services.effective_config.get_backend_auth_key",
        lambda: "test-key",
    )

    from app.main import create_app

    return TestClient(
        create_app(),
        raise_server_exceptions=False,
        headers={"X-API-Key": "test-key"},
    )


# ---------------------------------------------------------------------------
# 场景 1：预期缺失 -> 404
# ---------------------------------------------------------------------------


def test_import_job_status_not_found_returns_404(api_client: TestClient, monkeypatch):
    """FileNotFoundError(任务不存在) -> 404 + detail 含原消息。"""
    from app.data_io.api import router as router_mod

    def _raise(_job_id: str):
        raise FileNotFoundError("任务不存在: no-such-job")

    monkeypatch.setattr(router_mod, "get_job", _raise)
    resp = api_client.get("/import/jobs/no-such-job")
    assert resp.status_code == 404
    assert "任务不存在" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# 场景 4a：损坏任务文件 JSONDecodeError -> 500（行为变更：旧 404 -> 新 500）
# ---------------------------------------------------------------------------


def test_import_job_status_corrupted_json_returns_500(
    api_client: TestClient, monkeypatch
):
    """JSONDecodeError(任务文件损坏) 不再被强转 404，上抛全局处理器 -> 500 + 通用文案。"""
    from app.data_io.api import router as router_mod

    def _raise(_job_id: str):
        raise json.JSONDecodeError("Expecting value", "doc", 0)

    monkeypatch.setattr(router_mod, "get_job", _raise)
    resp = api_client.get("/import/jobs/broken-job")
    assert resp.status_code == 500
    assert resp.json()["detail"] == "Internal server error"


# ---------------------------------------------------------------------------
# 场景 4b：IO 故障 OSError -> 500
# ---------------------------------------------------------------------------


def test_import_job_status_oserror_returns_500(api_client: TestClient, monkeypatch):
    """OSError(IO 故障) 上抛全局处理器 -> 500 + 通用文案。"""
    from app.data_io.api import router as router_mod

    def _raise(_job_id: str):
        raise OSError("disk I/O failure")

    monkeypatch.setattr(router_mod, "get_job", _raise)
    resp = api_client.get("/import/jobs/io-fail")
    assert resp.status_code == 500
    assert resp.json()["detail"] == "Internal server error"


# ---------------------------------------------------------------------------
# 场景 6：信息泄露修复 — 未知异常含敏感串不外泄
# ---------------------------------------------------------------------------


def test_unknown_exception_does_not_leak_sensitive_path(
    api_client: TestClient, monkeypatch
):
    """未知异常的 str(exc) 可能含服务端路径/凭据，收窄后 detail 仅 'Internal server error'。"""
    from app.data_io.api import router as router_mod

    sensitive = "/home/secret/db密码_very_private_path_3f7a"

    def _raise(_job_id: str):
        raise RuntimeError(f"failed at {sensitive}")

    monkeypatch.setattr(router_mod, "get_job", _raise)
    resp = api_client.get("/import/jobs/leak-test")
    assert resp.status_code == 500
    body = resp.json()
    assert body["detail"] == "Internal server error"
    assert sensitive not in json.dumps(body, ensure_ascii=False)


# ---------------------------------------------------------------------------
# 场景 2 & 3：客户端校验 ValueError->400、配额 QuotaExceededError->507
# 由 _http_err 单元测试覆盖（test_http_err_value_error_400 /
# test_http_err_quota_507_before_runtime_400），此处不重复 API 层测试。
# import_job_status 属 Group B，设计上仅捕获 FileNotFoundError，其余上抛。
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# _http_err 翻译器单元测试（不经过 HTTP 栈，直接验证 isinstance 顺序）
# ---------------------------------------------------------------------------


def test_http_err_file_not_found_404():
    from app.data_io.api.router import _http_err

    exc = _http_err(FileNotFoundError("missing"))
    assert exc.status_code == 404


def test_http_err_quota_507_before_runtime_400():
    """QuotaExceededError(RuntimeError) 须命中 507 而非 400。"""
    from app.data_io.services.paths import QuotaExceededError
    from app.data_io.api.router import _http_err

    exc = _http_err(QuotaExceededError("over quota"))
    assert exc.status_code == 507


def test_http_err_value_error_400():
    from app.data_io.api.router import _http_err

    exc = _http_err(ValueError("bad input"))
    assert exc.status_code == 400


def test_http_err_runtime_error_400():
    from app.data_io.api.router import _http_err

    exc = _http_err(RuntimeError("runtime issue"))
    assert exc.status_code == 400


def test_http_err_unknown_reraises():
    """未知异常类型应 re-raise（上抛全局处理器），不被翻译。"""
    from app.data_io.api.router import _http_err

    with pytest.raises(OSError):
        _http_err(OSError("unknown to translator"))


# ---------------------------------------------------------------------------
# 场景 5：config_service 探测函数
# ---------------------------------------------------------------------------


def _setup_api_key_env(monkeypatch, key_name="tianditu", key_value="fake-key-123"):
    """为 test_api_key 准备配置环境。"""
    import app.services.config_service as svc

    monkeypatch.setattr(svc, "get_effective_api_key", lambda _name: key_value)
    # repo mock：update_test_status 无副作用
    repo = type("R", (), {"update_test_status": lambda *a, **k: None})()
    monkeypatch.setattr(svc, "_get_api_keys_repository", lambda: repo)
    return svc


def test_test_api_key_ssrf_blocked_returns_failure_tuple(monkeypatch):
    """SSRFBlockedError -> (False, '出站 URL 校验失败...')，不记 ERROR。"""
    svc = _setup_api_key_env(monkeypatch)
    from app.core.ssrf import SSRFBlockedError

    with patch(
        "app.core.ssrf.validate_outbound_url",
        side_effect=SSRFBlockedError("blocked host"),
    ):
        ok, msg = asyncio.run(svc.test_api_key("tianditu"))
    assert ok is False
    assert "出站 URL 校验失败" in msg


def test_test_api_key_unexpected_error_logs_and_returns_failure(monkeypatch, caplog):
    """意外异常(非 SSRF/非 httpx.HTTPError) -> (False, '测试失败...') + logger.exception。"""
    svc = _setup_api_key_env(monkeypatch)

    # validate_outbound_url 通过，但 httpx.AsyncClient.get 抛意外 RuntimeError
    with (
        patch("app.core.ssrf.validate_outbound_url", return_value=None),
        patch("httpx.AsyncClient.get", side_effect=RuntimeError("unexpected boom")),
    ):
        with caplog.at_level(logging.ERROR, logger="app.services.config_service"):
            ok, msg = asyncio.run(svc.test_api_key("tianditu"))

    assert ok is False
    # 外层 except 返回 "测试失败" 类文案（非 SSRF 文案）
    assert "失败" in msg
    assert "出站 URL 校验失败" not in msg
    # logger.exception 被调用（意外异常须记 ERROR 日志）
    assert any(
        "unexpected boom" in r.getMessage() or r.levelno >= logging.ERROR
        for r in caplog.records
        if r.name == "app.services.config_service"
    )
