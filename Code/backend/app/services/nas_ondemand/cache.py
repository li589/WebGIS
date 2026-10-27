"""帧缓存管理：2000 帧上限 + LRU 淘汰 + 四道免死金牌。

═══════════════════════════════════════════════════════════════════════════
淘汰规则（用户 2026-10-27 定稿）
═══════════════════════════════════════════════════════════════════════════
* 总量 ≤ 2000 帧 ⇒ 一个都不删。
* 总量 > 2000 帧 ⇒ 按 ``last_used`` 从旧到新删，删到 1800 帧就停。
* 免死金牌（四条，任何情况都不删）：
  1. 根 ``bounds.json`` / ``meta.json`` —— 图层的"户口本"，删了整层显示不出来；
  2. 调用方指定的当前帧（``keep_tags``）；
  3. 最近 7 天打开过的帧；
  4. 每个图层各自最常用的 30 帧（防止一个图层刷满把别的层挤空）。
* 只遍历 ``imported-nas-*`` 目录；其它 ``imported-*``（admin 既有产物）一概不看。
═══════════════════════════════════════════════════════════════════════════

⚠ 单帧 bounds 的处理：删一帧时必须把 ``bounds_<tag>.json`` 连同 PNG 一起删，
并从 meta.time_list 里移除该 tag。否则前端时间轴仍会去请求已删的 PNG →
404 → 触发前端 boundsMissCache 负缓存，整层在本会话内都不显示。
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Iterable

from app.services.nas_ondemand import config

logger = logging.getLogger(__name__)

STATE_FILENAME = "cache_state.json"


# ── 目录遍历（只认白名单前缀）────────────────────────────────────────────────
def _imports_root() -> Path:
    from app.data_io.services.paths import imports_dir

    return imports_dir()


def iter_layer_dirs() -> Iterable[Path]:
    """遍历 ``imports/imported-nas-*`` 图层目录（跳过系统目录与其它导入层）。"""
    root = _imports_root()
    if not root.is_dir():
        return []
    out: list[Path] = []
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        if not child.name.startswith(config.LOCAL_LAYER_PREFIX):
            continue
        out.append(child)
    return out


def _is_layer_dir(path: Path) -> bool:
    """白名单硬校验：只允许操作 imported-nas-* 目录。"""
    return (
        path.is_dir()
        and path.name.startswith(config.LOCAL_LAYER_PREFIX)
        and path.parent.resolve() == _imports_root().resolve()
    )


# ── 状态读写 ──────────────────────────────────────────────────────────────────
def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    tmp = path.with_suffix(path.suffix + ".part")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def _state_path(layer_dir: Path) -> Path:
    return layer_dir / STATE_FILENAME


def _read_state(layer_dir: Path) -> dict[str, Any]:
    state = _read_json(_state_path(layer_dir))
    last_used = state.get("last_used")
    if not isinstance(last_used, dict):
        state["last_used"] = {}
    return state


def touch(layer_id: str, layer_dir: Path, tag: str) -> None:
    """记录「这个图层的这一帧刚被打开」，供 LRU 判新旧。"""
    if not _is_layer_dir(layer_dir):
        return
    state = _read_state(layer_dir)
    state["last_used"][str(tag)] = time.time()
    state["layer_id"] = layer_id
    try:
        _write_json(_state_path(layer_dir), state)
    except OSError as exc:  # 状态文件写不进去不该影响出图
        logger.warning("写缓存状态失败 layer=%s tag=%s: %s", layer_id, tag, exc)


def forget(layer_id: str, layer_dir: Path, tag: str) -> None:
    if not _is_layer_dir(layer_dir):
        return
    state = _read_state(layer_dir)
    if state["last_used"].pop(str(tag), None) is not None:
        _write_json(_state_path(layer_dir), state)


# ── 统计 ──────────────────────────────────────────────────────────────────────
def _frame_files(layer_dir: Path) -> list[Path]:
    return sorted(layer_dir.glob("preview_*.png"))


def _layer_meta(layer_dir: Path) -> dict[str, Any]:
    return _read_json(layer_dir / "meta.json")


def collect_frames() -> list[dict[str, Any]]:
    """收集全部 imported-nas-* 图层的帧，附带 last_used 与占用字节。"""
    frames: list[dict[str, Any]] = []
    for layer_dir in iter_layer_dirs():
        state = _read_state(layer_dir)
        last_used = state.get("last_used") or {}
        layer_id = str(state.get("layer_id") or layer_dir.name)
        for png in _frame_files(layer_dir):
            tag = png.stem.removeprefix("preview_")
            size = 0
            for candidate in (
                png,
                layer_dir / f"bounds_{tag}.json",
                layer_dir / f"source_{tag}.tif",
            ):
                try:
                    size += candidate.stat().st_size
                except OSError:
                    pass
            frames.append(
                {
                    "layer_dir": layer_dir,
                    "layer_id": layer_id,
                    "tag": tag,
                    "last_used": float(last_used.get(tag) or 0.0),
                    "bytes": size,
                }
            )
    return frames


def cache_state() -> dict[str, Any]:
    """缓存现状摘要（给验证接口/CLI 用）。"""
    frames = collect_frames()
    by_layer: dict[str, dict[str, Any]] = {}
    for f in frames:
        bucket = by_layer.setdefault(
            f["layer_id"], {"frames": 0, "bytes": 0, "oldest_used": float("inf")}
        )
        bucket["frames"] += 1
        bucket["bytes"] += f["bytes"]
        bucket["oldest_used"] = min(bucket["oldest_used"], f["last_used"] or 0.0)
    for bucket in by_layer.values():
        if bucket["oldest_used"] == float("inf"):
            bucket["oldest_used"] = 0.0
        bucket["oldest_used_human"] = _human_ts(bucket["oldest_used"])
    oldest = sorted(frames, key=lambda x: x["last_used"])[:5]
    return {
        "max_frames": config.CACHE_MAX_FRAMES,
        "target_frames": config.CACHE_TARGET_FRAMES,
        "per_layer_floor": config.PER_LAYER_FLOOR,
        "protect_recent_days": config.PROTECT_RECENT_DAYS,
        "total_frames": len(frames),
        "total_bytes": sum(f["bytes"] for f in frames),
        "total_bytes_human": _human_bytes(sum(f["bytes"] for f in frames)),
        "layers": by_layer,
        "oldest_frames": [
            {
                "layer_id": f["layer_id"],
                "tag": f["tag"],
                "last_used": _human_ts(f["last_used"]),
            }
            for f in oldest
        ],
    }


def _human_bytes(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024 or unit == "TB":
            return f"{n:.2f} {unit}"
        n /= 1024.0
    return f"{n:.2f} TB"


def _human_ts(ts: float) -> str:
    if not ts:
        return "从未打开"
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(ts))


# ── 淘汰 ──────────────────────────────────────────────────────────────────────
def _protected_tags(
    frames: list[dict[str, Any]], keep_tags: Iterable[str]
) -> set[tuple[str, str]]:
    """计算免死名单，返回 {(layer_id, tag)} 集合。"""
    keep = {str(t) for t in keep_tags}
    cutoff = time.time() - config.PROTECT_RECENT_DAYS * 86400.0
    protected: set[tuple[str, str]] = set()

    # 免死 4：每图层各自最常用的 N 帧（先算，保证每层都有底仓）
    by_layer: dict[str, list[dict[str, Any]]] = {}
    for f in frames:
        by_layer.setdefault(f["layer_id"], []).append(f)
    for layer_id, items in by_layer.items():
        newest = sorted(items, key=lambda x: x["last_used"], reverse=True)
        for f in newest[: config.PER_LAYER_FLOOR]:
            protected.add((layer_id, f["tag"]))

    # 免死 2（调用方点名）+ 免死 3（最近 N 天打开过）
    for f in frames:
        if f["tag"] in keep or f["last_used"] >= cutoff:
            protected.add((f["layer_id"], f["tag"]))

    return protected


def ensure_capacity(
    *, keep_tags: Iterable[str] = (), dry_run: bool = False
) -> dict[str, Any]:
    """总量超上限时按 LRU 淘汰，删到目标帧数即停。

    Args:
        keep_tags: 当前正在看的帧（永不删）。
        dry_run: True 时只返回「打算删谁」，不动任何文件。

    Returns:
        {total_before, total_after, deleted: [...], dry_run}
    """
    frames = collect_frames()
    total = len(frames)
    if total <= config.CACHE_MAX_FRAMES:
        return {
            "total_before": total,
            "total_after": total,
            "deleted": [],
            "dry_run": dry_run,
            "skipped": "未超过上限，不需要清理",
        }

    protected = _protected_tags(frames, keep_tags)
    candidates = [f for f in frames if (f["layer_id"], f["tag"]) not in protected]
    candidates.sort(key=lambda x: x["last_used"])  # 最久没打开的排最前

    need = total - config.CACHE_TARGET_FRAMES
    to_delete = candidates[:need] if need > 0 else []

    deleted: list[dict[str, Any]] = []
    remaining = total
    for f in to_delete:
        entry = {
            "layer_id": f["layer_id"],
            "tag": f["tag"],
            "bytes": f["bytes"],
            "last_used": _human_ts(f["last_used"]),
        }
        if not dry_run:
            try:
                delete_frame(f["layer_dir"], f["tag"], layer_id=f["layer_id"])
            except OSError as exc:
                logger.warning(
                    "淘汰失败 layer=%s tag=%s: %s", f["layer_id"], f["tag"], exc
                )
                continue
        deleted.append(entry)
        remaining -= 1
        if remaining <= config.CACHE_TARGET_FRAMES:
            break

    return {
        "total_before": total,
        "total_after": remaining,
        "deleted": deleted,
        "dry_run": dry_run,
    }


def delete_frame(layer_dir: Path, tag: str, *, layer_id: str | None = None) -> None:
    """删除一帧：先摘 meta.time_list，再删 PNG/单帧 bounds/source，最后失效注册缓存。

    顺序很重要 —— 先摘 meta 再删文件，保证任何时刻前端都不会拿到
    「time_list 里有、但 PNG 不存在」的组合（那会触发 bounds 负缓存）。
    """
    if not _is_layer_dir(layer_dir):
        raise OSError(f"拒绝删除非 imported-nas-* 目录：{layer_dir}")
    tag = str(tag)

    meta_path = layer_dir / "meta.json"
    meta = _read_json(meta_path)
    time_list = [str(t) for t in (meta.get("time_list") or [])]
    if tag in time_list:
        time_list.remove(tag)
        meta["time_list"] = time_list
        if str(meta.get("default_time") or "") == tag:
            meta["default_time"] = time_list[-1] if time_list else None
        _write_json(meta_path, meta)

    for candidate in (
        layer_dir / f"preview_{tag}.png",
        layer_dir / f"bounds_{tag}.json",
        layer_dir / f"source_{tag}.tif",
    ):
        try:
            candidate.unlink(missing_ok=True)
        except OSError as exc:
            logger.warning("删除 %s 失败：%s", candidate.name, exc)

    forget(layer_id or layer_dir.name, layer_dir, tag)

    # meta 变了 ⇒ 进程内 _REGISTRY 缓存必须失效，否则时间轴仍看得见已删的 tag
    try:
        from app.services.overlay_registry import unregister_overlay

        unregister_overlay(layer_id or layer_dir.name)
    except Exception as exc:  # noqa: BLE001 - 注册表不可用不该阻断淘汰
        logger.warning("失效 overlay 注册缓存失败：%s", exc)
