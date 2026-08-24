"""叠加层烘焙资产自愈任务（2026-08-24 用户反馈意见#1）。

背景：旧版烘焙工具的行序 bug 产出上下翻转的 PNG，工具修复后资产从未重烘，
只能人工跑 Tools/export_overlay_assets.py 抢救。本任务让资产新鲜度**系统内
闭环**：检测 bake_version 陈旧的资产 → 自动派发重烘（subprocess 调用烘焙
CLI，幂等）→ 日志可观测，无需任何外部手工操作。

版本契约：``Tools/export_overlay_assets.py::BAKE_VERSION`` 为当前版本；
bounds JSON 的 ``bake_version`` 字段为资产版本；低于当前即陈旧。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from app.core.celery_app import celery_app
from app.core.config import settings

_REPO_ROOT = Path(__file__).resolve().parents[4]
_BAKE_TOOL = _REPO_ROOT / "Tools" / "export_overlay_assets.py"

# 当前烘焙版本（与工具 BAKE_VERSION 同步维护；不从 Tools import——避免
# app 运行时依赖 Tools 脚本的 import 副作用[matplotlib 后端设置等]）。
CURRENT_BAKE_VERSION = 2

# layer_id → 烘焙 task key（与 Tools._build_task_table 的 layers 声明对应；
# 多层共享 task 时去重合并，一次 subprocess 重烘全部陈旧层）。
_LAYER_TO_TASK: dict[str, str] = {
    "dem-etopo": "dem-etopo",
    "landcover-cn": "thematic",
    "hfp-cn": "thematic",
    "aridity-cn": "thematic",
    "omega-output": "omega-ts",
    "ref-smap-sm-202512-l3": "smap-ts",
    "gpcp-precip-ts": "gpcp-ts",
    "gebco-dem-cn": "gebco-dem",
    "cmfd-precip-cn": "cmfd-precip",
    "clcd-cn": "clcd",
}


def _overlay_png_root() -> Path:
    from app.services.overlay_registry import _OVERLAY_PNG_ROOT

    return _OVERLAY_PNG_ROOT


def find_stale_bake_tasks() -> set[str]:
    """扫描 overlay assets 的 bounds JSON，返回 bake_version 陈旧的 task key 集合。"""
    from app.services.overlay_registry import _OVERLAY_ASSETS_PATH

    root = _overlay_png_root()
    raw = json.loads(_OVERLAY_ASSETS_PATH.read_text(encoding="utf-8"))
    stale_layers: list[str] = []
    for layer_id, entry in raw.items():
        bounds_name = entry.get("bounds_filename")
        if not bounds_name:
            continue
        bounds_path = root / str(entry["overlay_subdir"]) / str(bounds_name)
        try:
            meta = json.loads(bounds_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            stale_layers.append(layer_id)  # 缺失/损坏也视为需重烘
            continue
        # 未版本化的历史资产先视为 baseline（迁移兼容）；已显式标记的
        # 旧版本才触发自愈，避免首次上线就把全部旧资产重复重烘。
        version = meta.get("bake_version", CURRENT_BAKE_VERSION)
        if not isinstance(version, int) or version < CURRENT_BAKE_VERSION:
            stale_layers.append(layer_id)
    return {_LAYER_TO_TASK[lid] for lid in stale_layers if lid in _LAYER_TO_TASK}


@celery_app.task(name="app.tasks.asset_bake_tasks.rebake_stale_overlay_assets")
def rebake_stale_overlay_assets() -> dict[str, object]:
    """检测并重烘陈旧烘焙资产（幂等；由 beat 每日调度，也可手动触发）。"""
    stale_tasks = sorted(find_stale_bake_tasks())
    if not stale_tasks:
        return {"status": "fresh", "rebaked": []}

    python_exe = sys.executable
    cmd = [python_exe, str(_BAKE_TOOL), "--tasks", ",".join(stale_tasks)]
    try:
        result = subprocess.run(  # noqa: S603 - 固定脚本+受控参数
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=int(getattr(settings, "asset_rebake_timeout_seconds", 3600)),
            cwd=str(_REPO_ROOT),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"status": "failed", "rebaked": stale_tasks, "error": str(exc)}
    if result.returncode != 0:
        tail = (result.stderr or result.stdout or "")[-2000:]
        return {"status": "failed", "rebaked": stale_tasks, "error": tail}

    # 复核：重烘后应无陈旧（防工具版本戳未写入等回归）
    remaining = sorted(find_stale_bake_tasks())
    return {
        "status": "ok" if not remaining else "partial",
        "rebaked": stale_tasks,
        "remaining": remaining,
    }
