"""问题反馈 API 测试（/feedback/api/*）。

覆盖：
- 匿名上传（multipart）：落盘结构 / token 返回 / 重复上传 409 / 非法输入 422
- 进展查询：token 鉴权（错误 token 401 / 不存在 404）
- 工程师端：未认证 401 / 非 admin 403 / admin 列表 / 详情 / 附件下载 / 发布进展
- 路径穿越与非法文件名防护
"""

from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

_CODE_ROOT = Path(__file__).resolve().parents[2]
for _p in (_CODE_ROOT,):
    _s = str(_p)
    if _s not in sys.path:
        sys.path.insert(0, _s)

from app.services.feedback_store import get_feedback_store  # noqa: E402

_TINY_PNG = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQ"
    "DwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


def _export(report_id: str = "CGDA-BUG-20260820-TEST") -> dict:
    return {
        "schema": "cgda-feedback-export/1",
        "generatedAt": "2026-08-20T06:00:00+08:00",
        "report": {
            "id": report_id,
            "createdAtTs": 1755638400000,
            "createdAt": "2026-08-20T06:00:00+08:00",
            "title": "测试反馈标题",
            "description": "测试问题描述，超过十个字。",
            "category": "ui",
            "categoryLabel": "界面与交互",
            "severity": "high",
            "severityLabel": "高",
            "contact": {
                "name": "测试用户",
                "role": "研究员",
                "contact": "t@example.org",
                "deviceId": "U-TEST01",
            },
            "env": {"timezone": "Asia/Shanghai"},
            "attachments": [
                {
                    "id": "a1",
                    "name": "shot.png",
                    "ext": "png",
                    "size": 95,
                    "mime": "image/png",
                    "kind": "image",
                },
            ],
        },
        "attachments": [
            {
                "name": "shot.png",
                "mime": "image/png",
                "size": 95,
                "kind": "image",
                "ext": "png",
                "dataBase64": _TINY_PNG,
            },
        ],
    }


@pytest.fixture()
def fb_client(tmp_path, monkeypatch):
    """启用用户鉴权 + admin 会话的隔离客户端；feedback_dir 指向 tmp。"""
    monkeypatch.setenv("BACKEND_ENV", "test")
    monkeypatch.setenv("BACKEND_USER_AUTH_ENABLED", "true")
    monkeypatch.setenv("BACKEND_ADMIN_USERNAME", "testadmin")
    monkeypatch.setenv("BACKEND_ADMIN_PASSWORD", "test-pass-123")
    monkeypatch.setenv("BACKEND_API_KEYS_ENABLED", "true")
    monkeypatch.setenv("BACKEND_API_KEY", "test-api-key")
    monkeypatch.setenv("BACKEND_API_KEY_ROLE", "admin")
    monkeypatch.setenv("BACKEND_DATA_ROOT", str(tmp_path / "data"))
    monkeypatch.setenv("BACKEND_OUTPUT_ROOT", str(tmp_path / "out"))
    monkeypatch.setenv("BACKEND_WORKFLOW_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("BACKEND_FEEDBACK_DIR", str(tmp_path / "feedback"))
    monkeypatch.setenv("BACKEND_DEV_AUTH_PREFILL", "false")

    import app.core.config as cfg_mod
    from dataclasses import replace
    from app.core.config import Settings

    cfg_mod.settings = replace(
        Settings(),
        admin_username="testadmin",
        admin_password="test-pass-123",
        environment="test",
        api_key="test-api-key",
        api_keys_enabled=True,
        api_key_role="admin",
        feedback_dir=str(tmp_path / "feedback"),
    )
    monkeypatch.setattr("app.core.config.settings", cfg_mod.settings)

    from app.services import user_repository as ur_mod
    from app.services.user_repository import UserRepository
    from app.main import create_app
    from app.services.auth_bootstrap import bootstrap_auth
    from app.services.effective_config import hydrate_effective_config

    repo = UserRepository(tmp_path / "state" / "users.sqlite3")
    from unittest.mock import patch

    with patch.object(ur_mod, "_repo", repo):
        hydrate_effective_config()
        bootstrap_auth()
        with TestClient(create_app()) as client:
            resp = client.post(
                "/auth/login",
                json={"username": "testadmin", "password": "test-pass-123"},
            )
            assert resp.status_code == 200, resp.text
            yield client


def _upload(client: TestClient, payload: dict):
    return client.post(
        "/feedback/api/reports",
        files={
            "file": (
                "export.json",
                json.dumps(payload).encode("utf-8"),
                "application/json",
            )
        },
    )


class TestUpload:
    def test_upload_ok_and_disk_layout(self, fb_client, tmp_path):
        resp = _upload(fb_client, _export())
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["reportId"] == "CGDA-BUG-20260820-TEST"
        assert body["token"]

        root = tmp_path / "feedback" / "CGDA-BUG-20260820-TEST"
        assert (root / "report.json").is_file()
        assert (root / "meta.json").is_file()
        assert (root / "response.json").exists() is False
        att = root / "attachments" / "shot.png"
        assert att.is_file()
        # base64 解包正确（PNG 魔数）
        assert att.read_bytes()[:4] == b"\x89PNG"

    def test_duplicate_upload_conflict(self, fb_client):
        assert _upload(fb_client, _export()).status_code == 201
        resp = _upload(fb_client, _export())
        assert resp.status_code == 409

    def test_invalid_json_rejected(self, fb_client):
        resp = fb_client.post(
            "/feedback/api/reports",
            files={"file": ("x.json", b"not json", "application/json")},
        )
        assert resp.status_code == 422

    def test_invalid_report_id_rejected(self, fb_client):
        payload = _export()
        payload["report"]["id"] = "../../etc/passwd"
        resp = _upload(fb_client, payload)
        assert resp.status_code == 422

    def test_traversal_attachment_name_sanitized(self, fb_client, tmp_path):
        payload = _export("CGDA-BUG-20260820-TRV1")
        payload["report"]["id"] = "CGDA-BUG-20260820-TRV1"
        payload["attachments"][0]["name"] = "../evil.png"
        resp = _upload(fb_client, payload)
        # 净化后文件名非法（去路径后为 ../ 剥离为空？→ 拒绝）或落盘为无害名
        if resp.status_code == 201:
            att_dir = tmp_path / "feedback" / "CGDA-BUG-20260820-TRV1" / "attachments"
            names = [p.name for p in att_dir.iterdir()]
            assert all(".." not in n and "/" not in n for n in names), names
        else:
            assert resp.status_code == 422


class TestResponseQuery:
    def test_query_requires_valid_token(self, fb_client):
        up = _upload(fb_client, _export()).json()
        rid = up["reportId"]
        # 无 token
        assert fb_client.get(f"/feedback/api/reports/{rid}/response").status_code == 401
        # 错 token
        resp = fb_client.get(f"/feedback/api/reports/{rid}/response?token=deadbeef")
        assert resp.status_code == 401
        # 正确 token（尚无进展）
        resp = fb_client.get(
            f"/feedback/api/reports/{rid}/response?token={up['token']}"
        )
        assert resp.status_code == 200
        assert resp.json()["response"] is None

    def test_query_unknown_report(self, fb_client):
        resp = fb_client.get(
            "/feedback/api/reports/CGDA-BUG-20260820-NOPE/response?token=x"
        )
        assert resp.status_code == 404


class TestAdminEndpoints:
    def test_unauthenticated_rejected(self, fb_client):
        # 登出后请求（新 client 无 cookie）
        from app.main import create_app

        with TestClient(create_app()) as anon:
            assert anon.get("/feedback/api/session").status_code == 401
            assert anon.get("/feedback/api/reports").status_code == 401
            assert (
                anon.get("/feedback/api/reports/CGDA-BUG-20260820-TEST").status_code
                == 401
            )

    def test_admin_list_and_detail(self, fb_client):
        _upload(fb_client, _export())
        lst = fb_client.get("/feedback/api/reports")
        assert lst.status_code == 200
        reports = lst.json()["reports"]
        assert len(reports) == 1
        assert reports[0]["reportId"] == "CGDA-BUG-20260820-TEST"
        assert reports[0]["attachmentCount"] == 1

        detail = fb_client.get("/feedback/api/reports/CGDA-BUG-20260820-TEST")
        assert detail.status_code == 200
        d = detail.json()
        assert d["report"]["title"] == "测试反馈标题"
        assert d["attachments"][0]["name"] == "shot.png"

    def test_attachment_download(self, fb_client):
        _upload(fb_client, _export())
        resp = fb_client.get(
            "/feedback/api/reports/CGDA-BUG-20260820-TEST/attachments/shot.png"
        )
        assert resp.status_code == 200
        assert resp.content[:4] == b"\x89PNG"
        # 路径穿越尝试
        resp2 = fb_client.get(
            "/feedback/api/reports/CGDA-BUG-20260820-TEST/attachments/..%2Freport.json"
        )
        assert resp2.status_code == 404

    def test_publish_response_flow(self, fb_client):
        up = _upload(fb_client, _export()).json()
        rid = up["reportId"]
        put = fb_client.put(
            f"/feedback/api/reports/{rid}/response",
            json={
                "status": "in_progress",
                "updatedAt": "2026-08-20 07:00",
                "assignee": {"name": "李工", "role": "后端工程师"},
                "timeline": [
                    {
                        "status": "in_progress",
                        "at": "2026-08-20 07:00",
                        "note": "已定位",
                    }
                ],
                "replies": [
                    {
                        "author": "李工",
                        "role": "后端工程师",
                        "body": "请补充日志",
                        "at": "2026-08-20 07:00",
                    }
                ],
            },
        )
        assert put.status_code == 200, put.text

        # 用户端凭 token 查询进展
        q = fb_client.get(f"/feedback/api/reports/{rid}/response?token={up['token']}")
        assert q.status_code == 200
        data = q.json()["response"]
        assert data["status"] == "in_progress"
        assert data["assignee"]["name"] == "李工"
        assert data["replies"][0]["body"] == "请补充日志"

    def test_publish_invalid_status_rejected(self, fb_client):
        up = _upload(fb_client, _export()).json()
        put = fb_client.put(
            f"/feedback/api/reports/{up['reportId']}/response",
            json={"status": "bogus"},
        )
        assert put.status_code == 422

    def test_publish_unknown_report(self, fb_client):
        put = fb_client.put(
            "/feedback/api/reports/CGDA-BUG-20260820-NOPE/response",
            json={"status": "received"},
        )
        assert put.status_code == 404


class TestStoreUnit:
    def test_report_id_validation(self):
        from app.services.feedback_store import validate_report_id

        assert validate_report_id("CGDA-BUG-20260820-A1B2")
        assert not validate_report_id("../CGDA-BUG-x")
        assert not validate_report_id("CGDA-BUG-")
        assert not validate_report_id("")
        assert not validate_report_id("CGDA-BUG-" + "A" * 100)

    def test_sanitize_attachment_name(self):
        from app.services.feedback_store import sanitize_attachment_name

        assert sanitize_attachment_name("a/b/c.png") == "c.png"
        assert sanitize_attachment_name("..\\..\\x.png") == "x.png"
        assert sanitize_attachment_name("") is None
        assert sanitize_attachment_name("...") is None
