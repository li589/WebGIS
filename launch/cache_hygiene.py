"""Local compile-cache hygiene for the CGDA launcher.

Separates **safe** local caches (``__pycache__``, Vite ``.vite``) from
**high-risk** ``flush`` (Redis + weather file cache). Start/restart may
auto-run the former; they must never call the latter.
"""

from __future__ import annotations

import argparse
import os
import shutil
from pathlib import Path

from launch.constants import (
    ALGORITHMS_DIR,
    BACKEND_DIR,
    FRONTEND_DIR,
    TEST_DIR,
    VITE_CACHE_DIR,
)
from launch.logging_setup import log


def should_prepare_caches(
    args: argparse.Namespace,
    component: str | None,
    *,
    was_gateway_hmr: bool = False,
) -> tuple[bool, bool]:
    """Return ``(do_pycache, do_vite)`` for start/restart auto hygiene.

    Matrix (plan):
    - ``--no-clean-cache`` → neither
    - ``--clean-cache`` → both (force full local compile clean)
    - ``all`` / ``backend`` / ``fastapi`` / ``beat`` / ``worker*`` → pycache
    - ``frontend`` or ``--vite`` → vite; full ``all --vite`` → both
    - static ``gateway`` / ``docker`` → neither, except restart leaving HMR
      (``was_gateway_hmr`` and not starting HMR) → vite to clear behind-gateway state
    """
    if bool(getattr(args, "no_clean_cache", False)):
        return False, False
    if bool(getattr(args, "clean_cache", False)):
        return True, True

    comp = (component or "all").strip().lower()
    use_vite = bool(getattr(args, "vite", False))
    if bool(getattr(args, "frontend_only", False)) and comp == "all":
        comp = "frontend"

    do_pycache = False
    do_vite = False

    if comp in ("all", "backend", "fastapi", "beat") or comp.startswith("worker"):
        do_pycache = True
    if comp == "frontend" or use_vite:
        do_vite = True
    if comp == "all" and use_vite:
        do_pycache = True
        do_vite = True
    if comp == "gateway" and use_vite:
        do_vite = True
    # Leaving HMR profile on restart gateway (static): clear Vite cache residue
    if (
        comp == "gateway"
        and not use_vite
        and was_gateway_hmr
    ):
        do_vite = True

    return do_pycache, do_vite


def prepare_launch_caches(
    *,
    pycache: bool = False,
    vite: bool = False,
    dry_run: bool = False,
) -> int:
    """Delete selected local compile caches. Never touches Redis / weather files.

    Returns 0 always (cleanup is best-effort; individual unlink failures warn).
    """
    if not pycache and not vite:
        return 0

    log.banner("预览本地编译缓存清理" if dry_run else "清理本地编译缓存")

    removed_dirs = 0
    removed_files = 0

    if pycache:
        roots = [BACKEND_DIR, ALGORITHMS_DIR, TEST_DIR]
        for root in roots:
            if not root.is_dir():
                log.warn("CleanCache", f"跳过不存在的目录: {root}")
                continue
            for dirpath, _dirnames, filenames in os.walk(root, topdown=False):
                base = Path(dirpath)
                parts_lower = [p.lower() for p in base.parts]
                if "node_modules" in parts_lower or ".venv" in parts_lower:
                    continue
                if base.name == "__pycache__":
                    if dry_run:
                        log.info("CleanCache", f"[dry-run] rmtree {base}")
                    else:
                        shutil.rmtree(base, ignore_errors=True)
                    removed_dirs += 1
                    continue
                for name in filenames:
                    if name.endswith((".pyc", ".pyo")):
                        target = base / name
                        if dry_run:
                            log.info("CleanCache", f"[dry-run] unlink {target}")
                        else:
                            try:
                                target.unlink(missing_ok=True)
                            except OSError as exc:
                                log.warn("CleanCache", f"无法删除 {target}: {exc}")
                        removed_files += 1

    if vite:
        vite_targets = [VITE_CACHE_DIR, FRONTEND_DIR / ".vite"]
        for cache_dir in vite_targets:
            if not cache_dir.exists():
                log.info("CleanCache", f"Vite 缓存不存在（跳过）: {cache_dir}")
                continue
            if dry_run:
                log.info("CleanCache", f"[dry-run] rmtree {cache_dir}")
            else:
                shutil.rmtree(cache_dir, ignore_errors=True)
            removed_dirs += 1

    log.ok(
        "CleanCache",
        f"{'将清理' if dry_run else '已清理'} dirs≈{removed_dirs} files≈{removed_files}"
        f"（pycache={'on' if pycache else 'off'}, vite={'on' if vite else 'off'}）",
    )
    log.info(
        "CleanCache",
        "提示: 与 flush 无关（不碰 Redis/天气缓存）。详见 Docs/07-工程保障/联调缓存与生效边界.md",
    )
    return 0


def apply_prepare_from_args(
    args: argparse.Namespace,
    component: str | None,
    *,
    was_gateway_hmr: bool = False,
    already_done: bool = False,
) -> bool:
    """Run matrix-based prepare unless ``already_done``. Returns whether it ran."""
    if already_done:
        return False
    do_py, do_vite = should_prepare_caches(
        args, component, was_gateway_hmr=was_gateway_hmr
    )
    if not do_py and not do_vite:
        log.info(
            "CleanCache",
            "跳过本地编译缓存清理（本组件默认不清理，或已 --no-clean-cache）",
        )
        return False
    prepare_launch_caches(pycache=do_py, vite=do_vite)
    return True
