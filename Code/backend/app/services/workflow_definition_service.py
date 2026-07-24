"""工作流定义持久化服务

管理系统预设工作流（只读）和用户自定义工作流（可编辑），
以 JSON 文件形式存储在 .data/workflow_definitions/ 下。
"""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.config import settings

logger = logging.getLogger(__name__)


# ─── 自定义异常（供 router 层按类型映射 HTTP 状态码） ────────────────────────
class WorkflowNotFoundError(Exception):
    """工作流定义不存在。"""


class WorkflowExistsError(Exception):
    """工作流定义已存在（创建时 ID 冲突或并发竞态）。"""


# ─── 路径常量 ────────────────────────────────────────────────────────────────
# 基于 __file__ 解析 backend 根目录，避免依赖 CWD（FastAPI 进程 CWD 可能不是 Code/backend）
_BACKEND_ROOT = (
    Path(__file__).resolve().parents[2]
)  # app/services/x.py -> app/services -> app -> backend
_data_root_raw = settings.data_root or ".data"
_data_root = Path(_data_root_raw)
if not _data_root.is_absolute():
    _data_root = _BACKEND_ROOT / _data_root
_DEFINITIONS_ROOT = _data_root / "workflow_definitions"
_SYSTEM_DIR = _DEFINITIONS_ROOT / "system"
_USER_DIR = _DEFINITIONS_ROOT / "user"

# 合法的 workflow_id 字符集（防路径穿越）
_ID_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_\-]*$")


_SEED_SYSTEM_DIR = _BACKEND_ROOT / "workflow_seeds" / "system"


def _sync_system_seeds() -> None:
    """Copy packaged system workflow templates into the runtime system dir (fill missing only)."""
    if not _SEED_SYSTEM_DIR.is_dir():
        return
    for src in sorted(_SEED_SYSTEM_DIR.glob("*.json")):
        dest = _SYSTEM_DIR / src.name
        if dest.exists():
            continue
        try:
            dest.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
            logger.info("Seeded system workflow definition: %s", dest.name)
        except OSError as exc:
            logger.warning("Failed to seed workflow %s: %s", src.name, exc)


def _ensure_dirs() -> None:
    """确保目录存在，并同步仓库内 system 种子模板。"""
    _SYSTEM_DIR.mkdir(parents=True, exist_ok=True)
    _USER_DIR.mkdir(parents=True, exist_ok=True)
    (_USER_DIR / ".gitkeep").touch(exist_ok=True)
    _sync_system_seeds()


def _validate_id(workflow_id: str) -> None:
    """校验 workflow_id 格式，防路径穿越。"""
    if not _ID_PATTERN.match(workflow_id):
        raise ValueError(
            f"Invalid workflow_id: {workflow_id!r} (allowed: alphanumeric, dash, underscore)"
        )


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _build_meta(
    kind: str,
    engine: str,
    name: str,
    description: str | None,
    author: str = "user",
    linked_layer_id: str | None = None,
) -> dict[str, Any]:
    """构建 _meta 声明头。"""
    return {
        "kind": kind,  # "system" | "user"
        "engine": engine,  # "weather" | "python_provider" | "gee" | "common"
        "name": name,
        "description": description,
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
        "author": author,
        "readonly": kind == "system",
        "linked_layer_id": linked_layer_id,
    }


def _resolve_file(workflow_id: str) -> Path | None:
    """在 system/ 和 user/ 目录中查找工作流定义文件。"""
    _validate_id(workflow_id)
    sys_file = _SYSTEM_DIR / f"{workflow_id}.json"
    if sys_file.exists():
        return sys_file
    usr_file = _USER_DIR / f"{workflow_id}.json"
    if usr_file.exists():
        return usr_file
    return None


def _read_file(path: Path) -> dict[str, Any]:
    """读取并解析 JSON 文件。

    捕获 FileNotFoundError（TOCTOU：_resolve_file 检查 exists() 后文件被并发删除）
    并转换为 WorkflowNotFoundError，供 router 层映射为 404。
    """
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise WorkflowNotFoundError(
            f"Workflow definition file disappeared: {path.name}"
        ) from exc
    try:
        data = json.loads(text)
        if not isinstance(data, dict):
            raise ValueError(
                f"Workflow definition must be a JSON object, got {type(data)}"
            )
        return data
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in {path.name}: {exc}") from exc


def _write_file(path: Path, data: dict[str, Any], exclusive: bool = False) -> None:
    """原子写入 JSON 文件（UTF-8, 缩进 2）。

    Args:
        path: 目标文件路径
        data: 要写入的数据
        exclusive: True 时使用独占创建模式（O_CREAT | O_EXCL），文件已存在则抛
            FileExistsError，用于 create_definition 防止并发竞态覆盖。
            False 时（默认，用于 update_definition）使用临时文件 + os.replace
            原子替换，保证进程崩溃不会损坏已有文件。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, ensure_ascii=False, indent=2)

    if exclusive:
        # 独占创建：O_EXCL 保证文件不存在时才创建，防止并发覆盖
        # 注意：此分支写入非原子（进程崩溃留下空文件），但不会覆盖已有数据
        fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(text)
        except Exception:
            # 写入失败时清理占位文件
            try:
                os.unlink(path)
            except OSError:
                pass
            raise
    else:
        # 原子覆盖：写入同目录临时文件后 os.replace 原子替换
        # 进程崩溃时已有文件保持完整，临时文件残留为 .{name}.{random}.tmp
        tmp_fd, tmp_path = tempfile.mkstemp(
            dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp"
        )
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                f.write(text)
            os.replace(tmp_path, path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise


# ─── 公开接口 ────────────────────────────────────────────────────────────────
def list_definitions() -> list[dict[str, Any]]:
    """列出所有工作流定义（system + user），返回摘要列表。"""
    _ensure_dirs()
    results: list[dict[str, Any]] = []

    for directory, default_kind in [(_SYSTEM_DIR, "system"), (_USER_DIR, "user")]:
        if not directory.exists():
            continue
        for path in sorted(directory.glob("*.json")):
            try:
                data = _read_file(path)
                meta = data.get("_meta", {})
                results.append(
                    {
                        "workflow_id": data.get("workflow_id", path.stem),
                        "kind": meta.get("kind", default_kind),
                        "engine": meta.get("engine", "unknown"),
                        "name": meta.get("name", data.get("workflow_id", path.stem)),
                        "description": meta.get("description"),
                        "readonly": meta.get("readonly", default_kind == "system"),
                        "linked_layer_id": meta.get("linked_layer_id"),
                        "updated_at": meta.get("updated_at"),
                        "node_count": len(data.get("nodes", [])),
                    }
                )
            except Exception as exc:
                logger.warning("Failed to read workflow definition %s: %s", path, exc)

    return results


def get_definition(workflow_id: str) -> dict[str, Any] | None:
    """获取单个工作流定义的完整内容。"""
    path = _resolve_file(workflow_id)
    if path is None:
        return None
    return _read_file(path)


def create_definition(payload: dict[str, Any]) -> dict[str, Any]:
    """创建用户工作流定义。

    使用 O_EXCL 独占创建模式防止并发竞态：两个并发请求创建相同 workflow_id 时，
    仅一个成功，另一个抛 WorkflowExistsError（router 映射为 409 Conflict）。
    """
    _ensure_dirs()

    workflow_id = payload.get("workflow_id")
    if not workflow_id or not isinstance(workflow_id, str):
        raise ValueError("workflow_id is required and must be a string")
    _validate_id(workflow_id)

    # system 定义不会动态创建，预检查安全（无 TOCTOU 风险）
    sys_file = _SYSTEM_DIR / f"{workflow_id}.json"
    if sys_file.exists():
        raise WorkflowExistsError(
            f"workflow_id '{workflow_id}' is reserved by system definition"
        )

    usr_file = _USER_DIR / f"{workflow_id}.json"

    engine = payload.get("engine", "common")
    name = payload.get("name", workflow_id)
    description = payload.get("description")

    meta = _build_meta(
        kind="user",
        engine=engine,
        name=name,
        description=description,
        author="user",
        linked_layer_id=payload.get("linked_layer_id"),
    )

    definition = {
        "_meta": meta,
        "workflow_id": workflow_id,
        "name": name,
        "description": description,
        "nodes": payload.get("nodes", []),
        "links": payload.get("links", []),
        "extra": payload.get("extra", {}),
    }

    # exclusive=True：O_EXCL 保证独占创建，文件已存在时抛 FileExistsError
    # 移除前置 usr_file.exists() 检查，避免 TOCTOU 窗口
    try:
        _write_file(usr_file, definition, exclusive=True)
    except FileExistsError as exc:
        raise WorkflowExistsError(
            f"workflow_id '{workflow_id}' already exists. Use PUT to update."
        ) from exc
    logger.info("Created user workflow definition: %s", workflow_id)
    return definition


def update_definition(workflow_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """更新用户工作流定义。system 定义不可更新。"""
    _validate_id(workflow_id)

    path = _resolve_file(workflow_id)
    if path is None:
        raise WorkflowNotFoundError(f"Workflow definition not found: {workflow_id}")

    existing = _read_file(path)
    meta = existing.get("_meta", {})

    if meta.get("kind") == "system" or meta.get("readonly", False):
        raise ValueError(f"Cannot modify system workflow definition: {workflow_id}")

    # 更新字段
    meta["updated_at"] = _now_iso()
    if "name" in payload:
        meta["name"] = payload["name"]
    if "description" in payload:
        meta["description"] = payload["description"]
    if "engine" in payload:
        meta["engine"] = payload["engine"]
    if "linked_layer_id" in payload:
        meta["linked_layer_id"] = payload["linked_layer_id"]

    definition = {
        "_meta": meta,
        "workflow_id": workflow_id,
        "name": meta.get("name", workflow_id),
        "description": meta.get("description"),
        "nodes": payload.get("nodes", existing.get("nodes", [])),
        "links": payload.get("links", existing.get("links", [])),
        "extra": payload.get("extra", existing.get("extra", {})),
    }

    _write_file(path, definition)
    logger.info("Updated user workflow definition: %s", workflow_id)
    return definition


def delete_definition(workflow_id: str) -> bool:
    """删除用户工作流定义。system 定义不可删除。"""
    _validate_id(workflow_id)

    path = _resolve_file(workflow_id)
    if path is None:
        raise WorkflowNotFoundError(f"Workflow definition not found: {workflow_id}")

    existing = _read_file(path)
    meta = existing.get("_meta", {})

    if meta.get("kind") == "system" or meta.get("readonly", False):
        raise ValueError(f"Cannot delete system workflow definition: {workflow_id}")

    path.unlink()
    logger.info("Deleted user workflow definition: %s", workflow_id)
    return True


def duplicate_definition(
    source_id: str, new_id: str, new_name: str | None = None
) -> dict[str, Any]:
    """复制现有工作流定义为新的用户工作流。"""
    source = get_definition(source_id)
    if source is None:
        raise WorkflowNotFoundError(f"Source workflow not found: {source_id}")

    payload = {
        "workflow_id": new_id,
        "name": new_name or f"{source.get('_meta', {}).get('name', source_id)} (copy)",
        "description": source.get("_meta", {}).get("description"),
        "engine": source.get("_meta", {}).get("engine", "common"),
        "linked_layer_id": None,  # 副本不绑定图层
        "nodes": source.get("nodes", []),
        "links": source.get("links", []),
        "extra": source.get("extra", {}),
    }

    return create_definition(payload)
