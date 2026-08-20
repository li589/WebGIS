"""问题反馈服务端存储（/feedback/api/* 的文件系统落盘）。

目录布局（``settings.feedback_dir``，默认 ``<_runtime>/feedback``）::

    feedback/
      CGDA-BUG-20260820-A1B2/       # 目录名 = 校验过的 reportId（天然防路径穿越）
        report.json                 # 用户导出的完整反馈 JSON（净化，附件 base64 已剥离）
        meta.json                   # token / 上传时间 / 上传 IP（原子写）
        attachments/                # base64 解包后的附件文件
        response.json               # 工程师发布的处理进展（admin 写入）

安全要点：
- reportId 白名单正则 ``^CGDA-BUG-[A-Za-z0-9-]{3,60}$``，作为目录名前后再校验，
  杜绝 ``../`` 路径穿越。
- 附件文件名净化（去路径、控制字符）。
- token 校验用 ``secrets.compare_digest``（防时序侧信道）。
- 所有 JSON 写入走临时文件 + ``os.replace`` 原子替换（防并发半写）。
- 存储层不鉴权：鉴权在路由层（上传匿名+限流；读改走 admin / token）。
- 单例的 root 每次调用动态解析 ``settings.feedback_dir``（frozen dataclass +
  测试 ``dataclasses.replace`` 的既定约定，monkeypatch 后无需 reset）。
"""

from __future__ import annotations

import base64
import binascii
import json
import logging
import os
import re
import secrets
import shutil
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

#: 反馈编号白名单（与前端生成规则一致：CGDA-BUG-YYYYMMDD-XXXX，宽松兼容手写）
REPORT_ID_RE = re.compile(r"^CGDA-BUG-[A-Za-z0-9-]{3,60}$")

#: 单附件解包大小上限（base64 解码后字节数）
MAX_ATTACHMENT_BYTES = 45 * 1024 * 1024
#: 单报告附件数量上限
MAX_ATTACHMENTS = 20
#: 上传 JSON 原始文本上限
MAX_UPLOAD_JSON_BYTES = 60 * 1024 * 1024

_FORBIDDEN_NAME_CHARS = re.compile(r"[\x00-\x1f\x7f]")


def sanitize_attachment_name(name: str) -> str | None:
    """净化附件文件名：去路径与控制字符；返回 None 表示拒绝。"""
    raw = str(name or "").replace("\\", "/")
    base = raw.split("/")[-1]
    base = _FORBIDDEN_NAME_CHARS.sub("", base).strip().lstrip(".")
    if not base or len(base) > 100:
        return None
    return base


def validate_report_id(report_id: str) -> bool:
    return bool(report_id) and bool(REPORT_ID_RE.match(report_id))


def _settings_feedback_dir() -> Path:
    """动态读取 settings（新模块动态读约定）。"""
    from app.core.config import settings

    return Path(settings.feedback_dir)


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def _clip(value: Any, limit: int) -> str:
    return str(value)[:limit] if value is not None else ""


class FeedbackStore:
    """反馈文件系统存储（原子写 + 目录级隔离；root 由 provider 动态解析）。"""

    def __init__(self, root_provider: Callable[[], Path]) -> None:
        self._root_provider = root_provider

    @property
    def root(self) -> Path:
        return self._root_provider()

    # ---- 路径辅助 ----
    def _dir(self, report_id: str) -> Path:
        if not validate_report_id(report_id):
            raise ValueError(f"invalid report id: {report_id!r}")
        return self.root / report_id

    # ---- 写入 ----
    def save_report(
        self,
        report_id: str,
        payload: dict[str, Any],
        *,
        uploader_ip: str,
    ) -> str:
        """保存用户上传的导出 JSON（含 base64 附件解包）。返回访问 token。

        目录已存在时抛 ``FileExistsError``（防同编号覆盖他人数据）。
        """
        report_dir = self._dir(report_id)
        self.root.mkdir(parents=True, exist_ok=True)
        if report_dir.exists():
            raise FileExistsError(f"report already exists: {report_id}")

        attachments = payload.get("attachments")
        if attachments is None:
            attachments = []
        if not isinstance(attachments, list) or len(attachments) > MAX_ATTACHMENTS:
            raise ValueError(f"attachments must be a list of <= {MAX_ATTACHMENTS}")

        token = secrets.token_hex(16)
        report_dir.mkdir(parents=True)
        try:
            # 1) 解包附件（先做可失败部分，失败整体回滚目录）
            if attachments:
                att_dir = report_dir / "attachments"
                att_dir.mkdir()
                for att in attachments:
                    if not isinstance(att, dict):
                        raise ValueError("attachment entry must be an object")
                    name = sanitize_attachment_name(str(att.get("name") or ""))
                    if not name:
                        raise ValueError("attachment has invalid filename")
                    data_b64 = att.get("dataBase64")
                    if data_b64 is None:
                        # 元数据型条目（导出时未含二进制）：占位说明文件
                        (att_dir / f"{name}.missing.txt").write_text(
                            "binary content not included in export", encoding="utf-8"
                        )
                        continue
                    if not isinstance(data_b64, str):
                        raise ValueError("attachment dataBase64 must be a string")
                    try:
                        data = base64.b64decode(data_b64, validate=True)
                    except (binascii.Error, ValueError) as exc:
                        raise ValueError(f"attachment {name}: invalid base64") from exc
                    if len(data) > MAX_ATTACHMENT_BYTES:
                        raise ValueError(f"attachment {name} exceeds size limit")
                    (att_dir / name).write_bytes(data)

            # 2) report.json（剥离 base64 大字段；保留导出结构供处理台渲染）
            slim = dict(payload)
            slim["attachments"] = [
                {k: v for k, v in att.items() if k != "dataBase64"}
                for att in attachments
                if isinstance(att, dict)
            ]
            _atomic_write_json(report_dir / "report.json", slim)

            # 3) meta.json（token / 时间 / IP）
            _atomic_write_json(
                report_dir / "meta.json",
                {
                    "reportId": report_id,
                    "token": token,
                    "uploadedAt": datetime.now(UTC).isoformat(),
                    "uploaderIp": uploader_ip,
                    "attachmentCount": len(attachments),
                },
            )
        except Exception:
            shutil.rmtree(report_dir, ignore_errors=True)
            raise
        return token

    # ---- 读取 ----
    def exists(self, report_id: str) -> bool:
        try:
            return self._dir(report_id).exists()
        except ValueError:
            return False

    def list_summaries(self) -> list[dict[str, Any]]:
        """扫描全部反馈，返回摘要（不含正文全文与附件二进制）。"""
        root = self.root
        if not root.exists():
            return []
        out: list[dict[str, Any]] = []
        for child in sorted(root.iterdir()):
            if not child.is_dir() or not validate_report_id(child.name):
                continue
            report = self._read_json(child / "report.json")
            if report is None:
                continue
            inner = self._inner_report(report)
            meta = self._read_json(child / "meta.json") or {}
            att_dir = child / "attachments"
            out.append(
                {
                    "reportId": child.name,
                    "title": _clip(inner.get("title"), 200),
                    "severity": _clip(inner.get("severity"), 20),
                    "categoryLabel": _clip(inner.get("categoryLabel"), 40),
                    "createdAt": _clip(inner.get("createdAt"), 40),
                    "submittedBy": _clip(self._contact_name(inner), 60),
                    "attachmentCount": (
                        len([p for p in att_dir.iterdir()]) if att_dir.exists() else 0
                    ),
                    "uploadedAt": _clip(meta.get("uploadedAt"), 40),
                    "hasResponse": (child / "response.json").exists(),
                }
            )
        return out

    def get_report(self, report_id: str) -> dict[str, Any] | None:
        """返回完整报告（导出原文 + 内层 report + 附件清单 + response）。"""
        report_dir = self._dir(report_id)
        report = self._read_json(report_dir / "report.json")
        if report is None:
            return None
        attachments: list[dict[str, Any]] = []
        att_dir = report_dir / "attachments"
        if att_dir.exists():
            for p in sorted(att_dir.iterdir()):
                if p.is_file():
                    attachments.append({"name": p.name, "size": p.stat().st_size})
        return {
            "reportId": report_id,
            "report": self._inner_report(report),
            "export": report,
            "attachments": attachments,
            "response": self._read_json(report_dir / "response.json"),
        }

    def attachment_path(self, report_id: str, name: str) -> Path | None:
        """附件绝对路径（净化文件名；不存在返回 None）。"""
        safe = sanitize_attachment_name(name)
        if not safe:
            return None
        path = self._dir(report_id) / "attachments" / safe
        if not path.is_file():
            return None
        return path

    def verify_token(self, report_id: str, token: str) -> bool:
        meta = self._read_json(self._dir(report_id) / "meta.json")
        stored = str((meta or {}).get("token") or "")
        if not stored or not token:
            return False
        return secrets.compare_digest(stored, token)

    # ---- 处理进展 ----
    def read_response(self, report_id: str) -> dict[str, Any] | None:
        return self._read_json(self._dir(report_id) / "response.json")

    def write_response(self, report_id: str, response: dict[str, Any]) -> None:
        report_dir = self._dir(report_id)
        if not report_dir.exists():
            raise FileNotFoundError(f"report not found: {report_id}")
        _atomic_write_json(report_dir / "response.json", response)

    # ---- 内部 ----
    @staticmethod
    def _inner_report(payload: dict[str, Any]) -> dict[str, Any]:
        """导出文件取 ``.report``，裸 report 对象取自身。"""
        inner = payload.get("report")
        if isinstance(inner, dict):
            return inner
        return payload

    @staticmethod
    def _contact_name(inner: dict[str, Any]) -> str | None:
        contact = inner.get("contact")
        if isinstance(contact, dict):
            return str(contact.get("name") or "")
        return None

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any] | None:
        try:
            with path.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
            return data if isinstance(data, dict) else None
        except FileNotFoundError:
            return None
        except (OSError, json.JSONDecodeError):
            logger.warning("feedback store: unreadable json %s", path)
            return None


_lock = threading.Lock()
_instance: FeedbackStore | None = None


def get_feedback_store() -> FeedbackStore:
    """进程内单例（root 动态解析 settings.feedback_dir）。"""
    global _instance
    if _instance is None:
        with _lock:
            if _instance is None:
                _instance = FeedbackStore(_settings_feedback_dir)
    return _instance
