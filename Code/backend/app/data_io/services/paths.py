"""导入存储路径与限额。

配额策略（永久层 vs 临时区）
---------------------------
- **永久层**：``imported-*`` 目录计入配额；默认上限 100 GiB，可用
  ``BACKEND_MAX_IMPORTS_TOTAL_BYTES`` 覆盖。
- **临时区**：``_staging`` / ``_tmp`` / ``_jobs`` / ``_documents`` / ``_exports`` /
  ``_locks`` **不计入**配额，避免上传/抽取把永久额度挤满。

回收策略（从不删除永久 ``imported-*``）
------------------------------------
按阶段执行，上一阶段腾出足够空间后提前结束：

1. **expired_staging**：未完成/过期 staging（TTL 24 h）
2. **completed_staging**：已 complete 但仍留在 staging 的会话（TTL 30 min）
3. **pressure_staging**：配额紧张时，未完成 staging 超过 1 h
4. **tmp**：``_tmp`` 过期文件（紧张时清空）
5. **exports**：``_exports`` 过期导出包（TTL 24 h）

软预留：断言配额时额外要求 ``SOFT_RESERVE_BYTES``（默认 1 GiB）空余，
避免顶格后无法覆盖写。
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import time
from pathlib import Path
from typing import Any

from app.data_io.services._meta_io import save_json_atomic
from app.core.config import settings
import contextlib

logger = logging.getLogger(__name__)


def _resolve_output_root() -> Path:
    """A-3：output_root 解析——production 空值 fail-fast，dev 兜底须显式告警。"""
    if settings.output_root:
        return Path(settings.output_root)
    env = (settings.environment or "").lower()
    if env not in {"development", "dev", "test", "testing"}:
        # 生产空根若静默 CWD 兜底，导入产物会落入仓库/工作目录
        raise RuntimeError(
            "BACKEND_OUTPUT_ROOT is required outside development "
            "(imports storage would silently fall back to the process CWD)."
        )
    fallback = Path.cwd() / "imports_output"
    logger.warning(
        "[paths] BACKEND_OUTPUT_ROOT 未配置，data_io 导入产物回退 CWD：%s"
        "（生产环境将拒绝启动，请显式配置）",
        fallback,
    )
    return fallback


_OUTPUT_ROOT = _resolve_output_root()
IMPORTS_DIR = _OUTPUT_ROOT / "imports"
STAGING_DIR = IMPORTS_DIR / "_staging"
JOBS_DIR = IMPORTS_DIR / "_jobs"
DOC_SESSIONS_DIR = IMPORTS_DIR / "_documents"

MAX_UPLOAD_BYTES = 512 * 1024 * 1024  # 512 MiB


def _env_bytes(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return max(1, int(raw))
    except ValueError:
        return default


# 默认 100 GiB（原 20 GiB 偏紧；可用环境变量覆盖）
MAX_IMPORTS_TOTAL_BYTES = _env_bytes(
    "BACKEND_MAX_IMPORTS_TOTAL_BYTES",
    100 * 1024 * 1024 * 1024,
)
# 断言配额时保留的软空余，避免顶格无法覆盖写
SOFT_RESERVE_BYTES = _env_bytes(
    "BACKEND_IMPORTS_SOFT_RESERVE_BYTES",
    1 * 1024 * 1024 * 1024,
)

CHUNK_SYNC_THRESHOLD_BYTES = 100 * 1024 * 1024  # >100 MiB → async job
STAGING_TTL_SECONDS = 24 * 3600
STAGING_PRESSURE_TTL_SECONDS = 3600
COMPLETED_STAGING_TTL_SECONDS = 30 * 60
TMP_TTL_SECONDS = 3600
EXPORTS_TTL_SECONDS = 24 * 3600
PREVIEW_FEATURE_LIMIT = 5000
DOC_PREVIEW_ROW_LIMIT = 5000


def ensure_imports_root() -> Path:
    IMPORTS_DIR.mkdir(parents=True, exist_ok=True)
    STAGING_DIR.mkdir(parents=True, exist_ok=True)
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    DOC_SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    return IMPORTS_DIR


def _is_ephemeral_import_child(name: str) -> bool:
    return name.startswith("_")


def dir_size_bytes(path: Path, *, include_ephemeral: bool = True) -> int:
    if not path.exists():
        return 0
    total = 0
    # 顶层配额统计时可跳过 _staging/_tmp 等临时目录
    if path.resolve() == IMPORTS_DIR.resolve() and not include_ephemeral:
        for child in path.iterdir():
            if not child.is_dir():
                if child.is_file():
                    with contextlib.suppress(OSError):
                        total += child.stat().st_size
                continue
            if _is_ephemeral_import_child(child.name):
                continue
            total += dir_size_bytes(child, include_ephemeral=True)
        return total

    for child in path.rglob("*"):
        if child.is_file():
            try:
                total += child.stat().st_size
            except OSError:
                continue
    return total


def effective_soft_reserve_bytes() -> int:
    """软预留不得超过配额的 10%，避免测试/小配额下预算变负。"""
    cap = max(0, MAX_IMPORTS_TOTAL_BYTES // 10)
    return min(max(0, SOFT_RESERVE_BYTES), cap)


def get_quota_usage() -> dict[str, Any]:
    """返回导入目录配额用量（仅计永久 imported-*，不含 staging/tmp）。"""
    ensure_imports_root()
    used = dir_size_bytes(IMPORTS_DIR, include_ephemeral=False)
    ephemeral = dir_size_bytes(IMPORTS_DIR) - used
    limit = MAX_IMPORTS_TOTAL_BYTES
    soft = effective_soft_reserve_bytes()
    free = max(0, limit - used)
    return {
        "used_bytes": used,
        "ephemeral_bytes": max(0, ephemeral),
        "limit_bytes": limit,
        "free_bytes": free,
        "soft_reserve_bytes": soft,
        "used_ratio": (used / limit) if limit else 1.0,
        "imports_dir": str(IMPORTS_DIR),
    }


def safe_import_child(child_id: str, *, root: Path | None = None) -> Path:
    """校验并拼接 imports 根（或指定 root）下的子路径，防路径穿越。

    安审 2026-08-21（S-1/S-2/P2-1）统一收敛点：
    - child_id 必须是纯目录名（``Path(child_id).name == child_id``），
      显式拒绝 ``..``、``/``、``\\``（Windows 路径分隔符，URL 参数
      ``%5C`` 解码后可注入）与 ``_`` 前缀系统目录（_staging/_jobs 等）；
    - resolve 后必须仍在 root 内（双保险）。

    Raises:
        ValueError: 校验失败。
    """
    target_root = root if root is not None else IMPORTS_DIR
    raw = str(child_id or "").strip()
    if (
        not raw
        or Path(raw).name != raw
        or ".." in raw
        or "/" in raw
        or "\\" in raw
        or raw.startswith("_")
    ):
        raise ValueError(f"非法 id: {child_id!r}")
    dest = target_root / raw
    try:
        resolved = dest.resolve()
        root_resolved = target_root.resolve()
        if not resolved.is_relative_to(root_resolved):
            raise ValueError(f"路径越界: {child_id!r}")
    except OSError as exc:  # resolve 失败（如网络盘暂不可达）→ fail-closed
        raise ValueError(f"路径校验失败: {child_id!r}") from exc
    return dest


def update_imported_layer_display_name(
    layer_id: str, display_name: str
) -> dict[str, Any]:
    """更新 imported-* 的 meta.json / bounds.json 显示名（不改物理文件名）。"""
    ensure_imports_root()
    lid = str(layer_id or "").strip()
    name = str(display_name or "").strip()
    if not lid.startswith("imported-"):
        raise ValueError("仅支持导入图层重命名")
    if not name:
        raise ValueError("显示名不能为空")
    dest = safe_import_child(lid)
    if not dest.is_dir():
        raise FileNotFoundError(f"导入图层不存在: {lid}")

    meta_path = dest / "meta.json"
    meta: dict[str, Any] = {}
    if meta_path.exists():
        try:
            loaded = json.loads(meta_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                meta = loaded
        except (OSError, json.JSONDecodeError):
            meta = {}
    meta["display_name"] = name
    meta["label"] = name
    save_json_atomic(meta_path, meta)

    bounds_path = dest / "bounds.json"
    if bounds_path.exists():
        try:
            bounds_data = json.loads(bounds_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            bounds_data = None
        if isinstance(bounds_data, dict):
            inner = bounds_data.get("meta")
            if isinstance(inner, dict):
                inner["display_name"] = name
                inner["label"] = name
            else:
                bounds_data["meta"] = {"display_name": name, "label": name}
            save_json_atomic(bounds_path, bounds_data)

    return {"layer_id": lid, "display_name": name, "kind": meta.get("kind")}


def stable_import_layer_id(*parts: str) -> str:
    """由业务键生成稳定 imported-* id（同键再导入可覆盖）。"""
    digest = hashlib.sha1("|".join(str(p) for p in parts).encode("utf-8")).hexdigest()[
        :12
    ]
    return f"imported-{digest}"


def _mtime(path: Path) -> float:
    try:
        return float(path.stat().st_mtime)
    except OSError:
        return 0.0


def _purge_dir_children(path: Path, *, older_than: float) -> int:
    """删除 path 下过期子项，返回释放的近似字节数。"""
    if not path.is_dir():
        return 0
    now = time.time()
    freed = 0
    for child in list(path.iterdir()):
        if now - _mtime(child) < older_than:
            continue
        size = (
            dir_size_bytes(child)
            if child.is_dir()
            else (child.stat().st_size if child.is_file() else 0)
        )
        try:
            if child.is_dir():
                shutil.rmtree(child, ignore_errors=True)
            else:
                child.unlink(missing_ok=True)
            freed += size
        except OSError:
            continue
    return freed


def _staging_meta(child: Path) -> tuple[float | None, bool]:
    """返回 (created_at, complete)。"""
    meta_path = child / "meta.json"
    created = None
    complete = False
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            complete = bool(meta.get("complete"))
            if meta.get("created_at") is not None:
                created = float(meta["created_at"])
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            created = None
    if created is None:
        created = _mtime(child)
    return created, complete


def _enough_free(needed_bytes: int) -> bool:
    usage = get_quota_usage()
    return (
        usage["free_bytes"]
        >= max(0, int(needed_bytes)) + effective_soft_reserve_bytes()
    )


def reclaim_import_space(
    needed_bytes: int = 0,
    *,
    aggressive: bool = False,
) -> dict[str, Any]:
    """按策略清理临时区，尽量腾出 needed_bytes + 软预留。

    **绝不**删除用户已导入的 ``imported-*`` 图层（覆盖/用户删除另论）。
    """
    ensure_imports_root()
    before = dir_size_bytes(IMPORTS_DIR)
    phases: list[dict[str, Any]] = []
    needed = max(0, int(needed_bytes))

    def _record(phase: str, freed: int, **extra: Any) -> None:
        phases.append({"phase": phase, "freed_bytes": int(freed), **extra})

    # Phase 1: 过期 staging（标准 TTL）
    removed_n = 0
    try:
        from app.data_io.services.upload import cleanup_expired_staging

        removed_n = cleanup_expired_staging(ttl_seconds=STAGING_TTL_SECONDS)
    except Exception:
        removed_n = 0
    mid = dir_size_bytes(IMPORTS_DIR)
    _record("expired_staging", max(0, before - mid), removed_sessions=removed_n)
    if needed and _enough_free(needed):
        after = dir_size_bytes(IMPORTS_DIR)
        return {
            "before_bytes": before,
            "after_bytes": after,
            "freed_bytes": max(0, before - after),
            "phases": phases,
            "stopped_early": True,
            "quota": get_quota_usage(),
        }

    # Phase 2: 已 complete 但仍滞留的 staging（可安全删，永久层已落盘）
    now = time.time()
    completed_freed = 0
    if STAGING_DIR.exists():
        for child in list(STAGING_DIR.iterdir()):
            if not child.is_dir():
                continue
            created, complete = _staging_meta(child)
            if not complete:
                continue
            if created is not None and now - created < COMPLETED_STAGING_TTL_SECONDS:
                continue
            size = dir_size_bytes(child)
            shutil.rmtree(child, ignore_errors=True)
            completed_freed += size
    _record("completed_staging", completed_freed)
    if needed and _enough_free(needed):
        after = dir_size_bytes(IMPORTS_DIR)
        return {
            "before_bytes": before,
            "after_bytes": after,
            "freed_bytes": max(0, before - after),
            "phases": phases,
            "stopped_early": True,
            "quota": get_quota_usage(),
        }

    usage = get_quota_usage()
    soft = effective_soft_reserve_bytes()
    pressure = aggressive or usage["free_bytes"] < needed + soft

    # Phase 3: 紧张时清理较旧的未完成 staging
    pressure_freed = 0
    if pressure and STAGING_DIR.exists():
        for child in list(STAGING_DIR.iterdir()):
            if not child.is_dir():
                continue
            created, complete = _staging_meta(child)
            if complete:
                continue
            if created is not None and now - created < STAGING_PRESSURE_TTL_SECONDS:
                continue
            size = dir_size_bytes(child)
            shutil.rmtree(child, ignore_errors=True)
            pressure_freed += size
    _record("pressure_staging", pressure_freed, applied=pressure)

    # Phase 4: _tmp
    tmp_ttl = 0 if (pressure and aggressive) else TMP_TTL_SECONDS
    tmp_freed = _purge_dir_children(IMPORTS_DIR / "_tmp", older_than=tmp_ttl)
    _record("tmp", tmp_freed, ttl_seconds=tmp_ttl)

    # Phase 5: _exports
    exports_freed = _purge_dir_children(
        IMPORTS_DIR / "_exports", older_than=EXPORTS_TTL_SECONDS
    )
    _record("exports", exports_freed)

    after = dir_size_bytes(IMPORTS_DIR)
    return {
        "before_bytes": before,
        "after_bytes": after,
        "freed_bytes": max(0, before - after),
        "phases": phases,
        "stopped_early": False,
        "quota": get_quota_usage(),
    }


def assert_quota_available(
    extra_bytes: int = 0,
    *,
    replace_bytes: int = 0,
) -> None:
    """检查配额；不足时先按策略回收临时区，仍不足则抛错。

    ``replace_bytes``：即将覆盖的旧图层体积，计入可用额度。
    """
    ensure_imports_root()
    net_extra = max(0, int(extra_bytes) - max(0, int(replace_bytes)))
    budget = MAX_IMPORTS_TOTAL_BYTES - effective_soft_reserve_bytes()
    used = dir_size_bytes(IMPORTS_DIR, include_ephemeral=False)
    projected = used - max(0, int(replace_bytes)) + max(0, int(extra_bytes))
    if projected <= budget:
        return

    reclaim_import_space(needed_bytes=net_extra, aggressive=True)
    used = dir_size_bytes(IMPORTS_DIR, include_ephemeral=False)
    projected = used - max(0, int(replace_bytes)) + max(0, int(extra_bytes))
    if projected <= budget:
        return

    usage = get_quota_usage()
    used_gb = usage["used_bytes"] / (1024**3)
    limit_gb = usage["limit_bytes"] / (1024**3)
    raise QuotaExceededError(
        f"导入存储配额已满（已用 {used_gb:.1f} / {limit_gb:.0f} GiB）。"
        f"同名图层可选择「覆盖」再导入；新图层请先删除旧导入，"
        f"或设置 BACKEND_MAX_IMPORTS_TOTAL_BYTES 提高上限。"
    )


class QuotaExceededError(RuntimeError):
    """Imports disk quota exceeded."""
