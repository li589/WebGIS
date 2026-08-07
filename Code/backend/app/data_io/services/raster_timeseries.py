"""块目录 → 时间序列 overlay（运行中可增量追加 time_list）。"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from rasterio.warp import transform_bounds as _transform_bounds

from app.data_io.services import paths as import_paths
from app.data_io.services.raster_science import extract_variable_to_geotiff
from app.services.overlay_registry import (
    OverlaySpec,
    register_overlay,
    unregister_overlay,
)
from app.services.raster_preview_service import raster_preview_service

_BLOCK_MAT_RE = re.compile(r"^(\d{8})_(\d{8})\.mat$", re.IGNORECASE)


@contextmanager
def _exclusive_path_lock(
    lock_path: Path, *, timeout_s: float = 120.0
) -> Iterator[None]:
    """Cross-platform exclusive lock to serialize materialize into the same dest_dir."""
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fh = open(lock_path, "a+b")
    locked = False
    deadline = time.monotonic() + timeout_s
    try:
        while True:
            try:
                if os.name == "nt":
                    import msvcrt

                    fh.seek(0)
                    if fh.read(1) == b"":
                        fh.write(b"\0")
                        fh.flush()
                        fh.seek(0)
                    msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                locked = True
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise TimeoutError(
                        f"Timed out acquiring materialize lock: {lock_path}"
                    )
                time.sleep(0.05)
        yield
    finally:
        if locked:
            try:
                if os.name == "nt":
                    import msvcrt

                    fh.seek(0)
                    msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass
        fh.close()


def stable_imported_layer_id(*parts: str) -> str:
    digest = hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:12]
    return f"imported-{digest}"


def resolve_block_timeseries_layer_id(run_id: str, label: str, variable_id: str) -> str:
    """Stable overlay id; OMEGA_BLOCK 历史目录与新 OMEGA 标签共用同一层。"""
    label_u = (label or "").strip().upper()
    var_u = (variable_id or "").strip().upper()
    is_omega = (
        var_u == "OMEGA"
        or label_u in {"OMEGA", "OMEGA_BLOCK"}
        or "OMEGA_BLOCK" in label_u
    )
    canon_label = "OMEGA" if is_omega else label
    layer_id = stable_imported_layer_id(run_id, canon_label, variable_id)
    if not is_omega:
        return layer_id
    legacy = stable_imported_layer_id(run_id, "OMEGA_BLOCK", variable_id)
    legacy_dir = import_paths.IMPORTS_DIR / legacy
    new_dir = import_paths.IMPORTS_DIR / layer_id
    # 已有旧目录且尚未迁到新 id 时继续写旧目录，避免重复层
    if legacy_dir.is_dir() and not new_dir.is_dir():
        return legacy
    return layer_id


def _is_canonical_viirs8_block(block_start: str, block_end: str) -> bool:
    """Return whether a label is a canonical Jan-1 anchored VIIRS 8-day block.

    The final block of a year is truncated at Dec 31. This intentionally rejects
    stale partial-window artifacts such as ``20251219_20251220`` while accepting
    ``20251227_20251231``.
    """
    try:
        from datetime import datetime, timedelta

        start = datetime.strptime(block_start, "%Y%m%d")
        end = datetime.strptime(block_end, "%Y%m%d")
    except ValueError:
        return False
    if (start.timetuple().tm_yday - 1) % 8 != 0:
        return False
    year_end = datetime(start.year, 12, 31)
    expected_end = min(start + timedelta(days=7), year_end)
    return end == expected_end


def list_block_mats(
    block_dir: Path,
    *,
    time_start: str | None = None,
    time_end: str | None = None,
    canonical_viirs8_only: bool = False,
) -> list[tuple[str, Path]]:
    """Return sorted (time_label, path) for YYYYMMDD_YYYYMMDD.mat files.

    Optional ``time_start`` / ``time_end`` are ``YYYYMMDD`` inclusive filters
    against the block's own start/end dates (overlap with the window).
    ``canonical_viirs8_only`` rejects stale shortened blocks from older partial
    runs; use it for completed Omega-SF run publication, not progressive running.
    """
    if not block_dir.is_dir():
        return []
    start = (time_start or "").replace("-", "")[:8] or None
    end = (time_end or "").replace("-", "")[:8] or None
    out: list[tuple[str, Path]] = []
    for path in block_dir.iterdir():
        if not path.is_file():
            continue
        m = _BLOCK_MAT_RE.match(path.name)
        if not m:
            continue
        block_start, block_end = m.group(1), m.group(2)
        if canonical_viirs8_only and not _is_canonical_viirs8_block(
            block_start, block_end
        ):
            continue
        if start and block_end < start:
            continue
        if end and block_start > end:
            continue
        out.append((f"{block_start}_{block_end}", path))
    out.sort(key=lambda x: x[0])
    return out


def _slice_needs_refresh(
    mat_path: Path, tif_path: Path, png_path: Path, bounds_path: Path
) -> bool:
    """True when any output is missing or older than the source mat."""
    if not (png_path.exists() and tif_path.exists() and bounds_path.exists()):
        return True
    try:
        mat_mtime = mat_path.stat().st_mtime
        return any(
            path.stat().st_mtime < mat_mtime
            for path in (tif_path, png_path, bounds_path)
        )
    except OSError:
        return True


def upsert_block_dir_timeseries(
    block_dir: Path,
    *,
    variable_id: str,
    label: str,
    run_id: str,
    grid_preset: str = "ease2-global-9km",
    palette: str = "cividis",
    native_step: str = "8d",
    time_start: str | None = None,
    time_end: str | None = None,
    canonical_viirs8_only: bool = False,
    force: bool = False,
) -> dict[str, Any]:
    """Commit block mats under ``block_dir`` as one time-series overlay.

    Incremental: existing slices are kept when still newer than the source mat.
    Progressive runs rewrite mats in place; stale early TIFs are re-extracted.
    Overlay id is stable per (run_id, label); OMEGA 与历史 OMEGA_BLOCK 目录兼容。
    """
    block_dir = Path(block_dir)
    mats = list_block_mats(
        block_dir,
        time_start=time_start,
        time_end=time_end,
        canonical_viirs8_only=canonical_viirs8_only,
    )
    if not mats:
        raise FileNotFoundError(f"块目录无 YYYYMMDD_YYYYMMDD.mat: {block_dir}")

    display_label = (
        "OMEGA"
        if (
            (variable_id or "").upper() == "OMEGA"
            or (label or "").upper() in {"OMEGA", "OMEGA_BLOCK"}
            or "OMEGA_BLOCK" in (label or "").upper()
        )
        else label
    )
    layer_id = resolve_block_timeseries_layer_id(run_id, display_label, variable_id)
    dest_dir = import_paths.IMPORTS_DIR / layer_id
    dest_dir.mkdir(parents=True, exist_ok=True)
    lock_path = import_paths.IMPORTS_DIR / "_locks" / f"{layer_id}.lock"

    with _exclusive_path_lock(lock_path):
        return _upsert_block_dir_timeseries_locked(
            mats=mats,
            layer_id=layer_id,
            dest_dir=dest_dir,
            variable_id=variable_id,
            label=display_label,
            run_id=run_id,
            grid_preset=grid_preset,
            palette=palette,
            native_step=native_step,
            force=force,
        )


def _upsert_block_dir_timeseries_locked(
    *,
    mats: list[tuple[str, Path]],
    layer_id: str,
    dest_dir: Path,
    variable_id: str,
    label: str,
    run_id: str,
    grid_preset: str,
    palette: str,
    native_step: str,
    force: bool,
) -> dict[str, Any]:
    time_list: list[str] = []
    bounds_by_time: dict[str, list[float]] = {}
    source_crs = "EPSG:6933"

    for time_label, mat_path in mats:
        time_list.append(time_label)
        png_path = dest_dir / f"preview_{time_label}.png"
        tif_path = dest_dir / f"source_{time_label}.tif"
        bounds_path = dest_dir / f"bounds_{time_label}.json"

        if not force and not _slice_needs_refresh(
            mat_path, tif_path, png_path, bounds_path
        ):
            try:
                data = json.loads(bounds_path.read_text(encoding="utf-8"))
                b = data.get("bounds")
                if isinstance(b, list) and len(b) == 4:
                    bounds_by_time[time_label] = [float(x) for x in b]
            except (OSError, json.JSONDecodeError, TypeError, ValueError):
                pass
            continue

        tmp_tif = import_paths.IMPORTS_DIR / "_tmp" / f"{layer_id}_{time_label}.tif"
        tmp_tif.parent.mkdir(parents=True, exist_ok=True)
        extract_meta = extract_variable_to_geotiff(
            mat_path,
            variable_id=variable_id,
            output_tif=tmp_tif,
            grid_preset=grid_preset,
        )
        shutil.copy2(tmp_tif, tif_path)
        tmp_tif.unlink(missing_ok=True)

        # 时间序列必须用全网格框（勿按有效像元裁剪），否则各时刻 bounds 不一致。
        # 预览渲染到 EPSG:3857：MapLibre 底图为 Web Mercator，ImageSource 按 WGS84
        # 四角线性贴图；若 PNG 是 equirectangular（4326），全球框会南北严重拉伸。
        # 导出仍用 source_*.tif 原网格（EPSG:6933），与显示无关。
        png_bytes, mercator_bounds = (
            raster_preview_service.render_cog_preview_reprojected(
                cog_path=tif_path,
                palette=palette,
                width=2048,
                height=2048,
                source_crs=str(extract_meta.get("crs") or source_crs),
                target_crs="EPSG:3857",
                crop_to_data=False,
            )
        )
        png_path.write_bytes(png_bytes)
        west, south, east, north = _transform_bounds(
            "EPSG:3857",
            "EPSG:4326",
            float(mercator_bounds[0]),
            float(mercator_bounds[1]),
            float(mercator_bounds[2]),
            float(mercator_bounds[3]),
            densify_pts=21,
        )
        slice_bounds = [float(west), float(south), float(east), float(north)]
        bounds_by_time[time_label] = slice_bounds
        bounds_path.write_text(
            json.dumps(
                {
                    "bounds": slice_bounds,
                    "meta": {
                        "layer_id": layer_id,
                        "time": time_label,
                        "variable_id": variable_id,
                        "native_step": native_step,
                        "science_source": mat_path.name,
                    },
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    if not time_list:
        raise RuntimeError("未能物化任何时间切片")

    default_time = time_list[-1]
    bounds_wgs84 = bounds_by_time.get(default_time)
    if bounds_wgs84 is None:
        for time_label in reversed(time_list):
            if time_label in bounds_by_time:
                bounds_wgs84 = bounds_by_time[time_label]
                break
    # Shared bounds.json for registry meta
    shared_bounds = {
        "bounds": bounds_wgs84 or [-180.0, -85.0, 180.0, 85.0],
        "meta": {
            "layer_id": layer_id,
            "category": "time-series",
            "palette": palette,
            "time_list": time_list,
            "default_time": default_time,
            "current_time": default_time,
            "native_step": native_step,
            "variable_id": variable_id,
            "label": label,
            "run_id": run_id,
            "follow_policy": "containing",
        },
    }
    (dest_dir / "bounds.json").write_text(
        json.dumps(shared_bounds, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (dest_dir / "meta.json").write_text(
        json.dumps(
            {
                "layer_id": layer_id,
                "kind": "raster",
                "category": "time-series",
                "native_step": native_step,
                "time_list": time_list,
                "variable_id": variable_id,
                "label": label,
                "run_id": run_id,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    try:
        unregister_overlay(layer_id)
    except Exception:
        pass

    register_overlay(
        OverlaySpec(
            layer_id=layer_id,
            overlay_dir=dest_dir,
            category="time-series",
            time_pattern="preview_{time}.png",
            bounds_pattern="bounds_{time}.json",
            bounds_filename="bounds.json",
            time_list=list(time_list),
            default_time=default_time,
            palette=palette,
            opacity=0.8,
            crs="EPSG:4326",
            source_pattern=str(dest_dir / "source_{time}.tif"),
            source_reader="geotiff",
            unit=label,
        )
    )

    return {
        "layer_id": layer_id,
        "title": f"Algorithm Map Layer: {label}",
        "product_tag": label,
        "bounds": bounds_wgs84,
        "source_crs": "EPSG:4326",
        "time_list": time_list,
        "default_time": default_time,
        "native_step": native_step,
        "cog_preview_url": f"/overlay-preview/{layer_id}",
    }
