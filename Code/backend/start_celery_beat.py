"""Celery Beat 定时任务调度器 — 驱动 weather_schedule_enabled 定时任务。

Windows 上 PersistentScheduler 使用 shelve（celerybeat-schedule.dat/.dir/.bak）。
进程被强杀时文件常半截写入，下次启动报 ``UnpicklingError: pickle data was truncated``
并立刻退出；Launcher monitor 会每 5s 刷一次 ERROR。启动前校验并必要时重建。
"""

from __future__ import annotations

import sys
from pathlib import Path

backend_root = Path(__file__).parent
code_path = backend_root.parent
gee_src = backend_root / "app" / "gee" / "core" / "src"

for p in (str(code_path), str(gee_src)):
    if p not in sys.path:
        sys.path.insert(0, str(p))

from app.core.celery_app import celery_app


def beat_schedule_path() -> Path:
    """Schedule 落在 .data/，避免污染 backend 根目录。"""
    return backend_root / ".data" / "celerybeat-schedule"


def legacy_beat_schedule_path() -> Path:
    """旧版默认 cwd 调度库（Code/backend/celerybeat-schedule）。"""
    return backend_root / "celerybeat-schedule"


def _related_schedule_files(prefix: Path) -> list[Path]:
    parent = prefix.parent
    if not parent.is_dir():
        return []
    return sorted(parent.glob(f"{prefix.name}*"))


def reset_beat_schedule(prefix: Path, *, reason: str) -> None:
    """删除 shelve 旁路文件，让 Beat 下次启动时重建。"""
    files = _related_schedule_files(prefix)
    if not files:
        return
    print(
        f"[beat] resetting schedule at {prefix} ({reason}); "
        f"removing {len(files)} file(s)",
        file=sys.stderr,
        flush=True,
    )
    for path in files:
        try:
            path.unlink(missing_ok=True)
        except OSError as exc:
            print(f"[beat] failed to remove {path}: {exc}", file=sys.stderr, flush=True)


def ensure_beat_schedule(prefix: Path) -> None:
    """若调度库可读则保留；损坏 / 截断则删除旁路文件。"""
    prefix.parent.mkdir(parents=True, exist_ok=True)
    related = _related_schedule_files(prefix)
    if not related:
        return
    try:
        import shelve

        db = shelve.open(str(prefix), flag="r")
        try:
            entries = db.get("entries")
            # Force unpickle of entry payloads (truncation often surfaces here).
            if isinstance(entries, dict):
                for _key, value in list(entries.items()):
                    _ = value
            _ = db.get("__version__")
        finally:
            db.close()
    except Exception as exc:
        reset_beat_schedule(prefix, reason=f"{type(exc).__name__}: {exc}")


if __name__ == "__main__":
    # 旧 cwd 调度库易在强杀后损坏；迁移到 .data 并清掉 legacy，避免双份。
    legacy = legacy_beat_schedule_path()
    if _related_schedule_files(legacy):
        reset_beat_schedule(legacy, reason="migrate to .data/")

    schedule = beat_schedule_path()
    ensure_beat_schedule(schedule)

    # 显式传入 'beat' 子命令，避免 sys.argv[0]（脚本名）被 Celery 误判为命令名
    celery_app.start(
        [
            "beat",
            f"--schedule={schedule}",
            *sys.argv[1:],
        ]
    )
