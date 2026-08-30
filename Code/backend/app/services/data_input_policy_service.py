"""数据输入策略（时间窗对齐 soft 输入 + 本地优先源路由）。

种子：``app/policy_seeds/data_input_policies.json``
运行时覆盖：``{DATA_ROOT}/_runtime/data_input_policies.json``（mtime 热载）

合并规则：同 ``id`` 时 runtime 覆盖 seed；不同 id 追加。
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any, Literal

from app.core.config import settings

logger = logging.getLogger(__name__)

PolicyMode = Literal["deny", "allow_with_confirm", "allow_silent"]
PolicyScope = Literal["module", "workflow_id", "layer_id", "*"]

INPUT_KEY_TIME_WINDOW_ALIGN = "time_window_align_on_zero_intersection"
INPUT_KEY_SOURCE_ROUTE_LOCAL_FIRST = "source_route_local_first"

_SEED_PATH = Path(__file__).resolve().parents[1] / "policy_seeds" / "data_input_policies.json"

_cache: dict[str, Any] | None = None
_cache_mtimes: tuple[float | None, float | None] = (None, None)


def _runtime_override_path() -> Path:
    root = Path(settings.data_root or settings.workflow_state_dir or ".")
    return root / "_runtime" / "data_input_policies.json"


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"version": 1, "policies": []}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Failed to load data_input_policies from %s: %s", path, exc)
        return {"version": 1, "policies": []}
    if not isinstance(raw, dict):
        return {"version": 1, "policies": []}
    policies = raw.get("policies")
    if not isinstance(policies, list):
        raw["policies"] = []
    return raw


def _mtime(path: Path) -> float | None:
    try:
        return path.stat().st_mtime if path.is_file() else None
    except OSError:
        return None


def _normalize_policy(item: Any) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    policy_id = str(item.get("id") or "").strip()
    input_key = str(item.get("input_key") or "").strip()
    mode = str(item.get("mode") or "deny").strip()
    scope = str(item.get("scope") or "*").strip()
    if not policy_id or not input_key:
        return None
    if mode not in ("deny", "allow_with_confirm", "allow_silent"):
        mode = "deny"
    if scope not in ("module", "workflow_id", "layer_id", "*"):
        scope = "*"
    return {
        "id": policy_id,
        "scope": scope,
        "scope_id": str(item.get("scope_id") or "").strip() or None,
        "input_key": input_key,
        "mode": mode,
        "notes": str(item.get("notes") or "").strip() or None,
    }


def _merge_policies(
    seed_policies: list[Any], runtime_policies: list[Any]
) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for raw in seed_policies + runtime_policies:
        normalized = _normalize_policy(raw)
        if normalized is None:
            continue
        merged[normalized["id"]] = normalized
    return list(merged.values())


def load_data_input_policies(*, force: bool = False) -> dict[str, Any]:
    """加载合并后的策略文档（seed ≺ runtime）。"""
    global _cache, _cache_mtimes
    seed_m = _mtime(_SEED_PATH)
    runtime_path = _runtime_override_path()
    runtime_m = _mtime(runtime_path)
    if (
        not force
        and _cache is not None
        and _cache_mtimes == (seed_m, runtime_m)
    ):
        return _cache

    seed = _read_json(_SEED_PATH)
    runtime = _read_json(runtime_path)
    version = int(runtime.get("version") or seed.get("version") or 1)
    seed_policies = _merge_policies(seed.get("policies") or [], [])
    runtime_policies = _merge_policies([], runtime.get("policies") or [])
    policies = _merge_policies(seed.get("policies") or [], runtime.get("policies") or [])
    doc = {
        "version": version,
        "policies": policies,
        "seed_policies": seed_policies,
        "runtime_policies": runtime_policies,
        "seed_path": str(_SEED_PATH),
        "runtime_path": str(runtime_path),
        "runtime_override_present": runtime_path.is_file(),
    }
    _cache = doc
    _cache_mtimes = (seed_m, runtime_m)
    return doc


def resolve_policy_mode(
    input_key: str,
    *,
    module: str | None = None,
    workflow_id: str | None = None,
    layer_id: str | None = None,
) -> PolicyMode:
    """按 scope 优先级解析某 input_key 的模式。

    优先级（高→低）：layer_id → workflow_id → module → ``*``。
    未命中时默认 ``deny``（fail-closed：不可静默放宽）。
    """
    doc = load_data_input_policies()
    best: tuple[int, PolicyMode] | None = None
    rank = {"layer_id": 3, "workflow_id": 2, "module": 1, "*": 0}
    for policy in doc.get("policies") or []:
        if policy.get("input_key") != input_key:
            continue
        scope = policy.get("scope") or "*"
        scope_id = policy.get("scope_id")
        if scope == "layer_id":
            if not layer_id or scope_id != layer_id:
                continue
        elif scope == "workflow_id":
            if not workflow_id or scope_id != workflow_id:
                continue
        elif scope == "module":
            if not module or scope_id != module:
                continue
        elif scope != "*":
            continue
        mode = policy.get("mode") or "deny"
        if mode not in ("deny", "allow_with_confirm", "allow_silent"):
            mode = "deny"
        r = rank.get(scope, -1)
        if best is None or r > best[0]:
            best = (r, mode)  # type: ignore[assignment]
    return best[1] if best else "deny"


def should_apply_time_window_align(
    *,
    relax_flags: dict[str, Any] | None,
    module: str | None = None,
    workflow_id: str | None = None,
    layer_id: str | None = None,
) -> bool:
    """是否允许执行零交集时间窗对齐。

    - 请求 ``relax_flags.time_window_align_on_zero_intersection=true`` → 允许（用户确认）
    - 策略 ``allow_silent`` → 允许
    - 其余 → 不允许
    """
    flags = relax_flags if isinstance(relax_flags, dict) else {}
    if flags.get(INPUT_KEY_TIME_WINDOW_ALIGN) is True:
        return True
    mode = resolve_policy_mode(
        INPUT_KEY_TIME_WINDOW_ALIGN,
        module=module,
        workflow_id=workflow_id,
        layer_id=layer_id,
    )
    return mode == "allow_silent"


def save_runtime_data_input_policies(
    *,
    version: int,
    policies: list[dict[str, Any]],
) -> dict[str, Any]:
    """原子写入 runtime 覆盖文件，并返回合并后的策略文档。

    ``policies`` 为 runtime 层条目（同 id 覆盖 seed）；不修改 seed 文件。
    热载：下次 ``load_data_input_policies`` 因 mtime 变化自动重读，无需重启。
    """
    normalized: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for raw in policies:
        item = _normalize_policy(raw)
        if item is None:
            continue
        if item["id"] in seen_ids:
            raise ValueError(f"duplicate policy id: {item['id']}")
        seen_ids.add(item["id"])
        normalized.append(item)

    runtime_path = _runtime_override_path()
    runtime_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"version": int(version), "policies": normalized}
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"

    fd, tmp_name = tempfile.mkstemp(
        prefix="data_input_policies_",
        suffix=".json.tmp",
        dir=str(runtime_path.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, runtime_path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise

    clear_policy_cache()
    return load_data_input_policies(force=True)


def clear_policy_cache() -> None:
    """测试用：清空 mtime 缓存。"""
    global _cache, _cache_mtimes
    _cache = None
    _cache_mtimes = (None, None)
