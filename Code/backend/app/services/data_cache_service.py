"""静态 materialize 缓存概览与清理。"""

from __future__ import annotations

import os
import shutil
import time
from pathlib import Path
from typing import Any

from app.core.config import settings


def resolve_static_cache_root() -> Path:
    override = os.getenv("BACKEND_STATIC_CACHE_ROOT", "").strip()
    if override:
        return Path(override)
    workspace = Path(
        settings.python_provider_workspace
        or settings.output_root
        or settings.data_root
        or "."
    )
    return workspace / "data_access" / "materialized"


def static_cache_ttl_seconds() -> int:
    """0 = never expire."""
    raw = os.getenv("BACKEND_STATIC_CACHE_TTL_SECONDS", "0").strip()
    try:
        return max(0, int(raw))
    except ValueError:
        return 0


def _dir_size_bytes(root: Path) -> int:
    total = 0
    if not root.exists():
        return 0
    for path in root.rglob("*"):
        if path.is_file():
            try:
                total += path.stat().st_size
            except OSError:
                continue
    return total


def scan_data_root_datasets() -> list[dict[str, Any]]:
    """List top-level logical dataset folders under BACKEND_DATA_ROOT."""
    root = Path(settings.data_root) if settings.data_root else None
    if root is None or not root.exists():
        return []
    items: list[dict[str, Any]] = []
    try:
        for child in sorted(root.iterdir()):
            if not child.is_dir():
                continue
            file_count = 0
            try:
                file_count = sum(1 for p in child.rglob("*") if p.is_file())
            except OSError:
                file_count = 0
            items.append(
                {
                    "name": child.name,
                    "path": str(child),
                    "file_count": file_count,
                }
            )
    except OSError:
        return []
    return items


def get_data_cache_overview() -> dict[str, Any]:
    cache_root = resolve_static_cache_root()
    entries: list[dict[str, Any]] = []
    total_bytes = 0
    if cache_root.exists():
        for path in sorted(cache_root.iterdir()):
            if not path.is_file() and not path.is_dir():
                continue
            try:
                size = path.stat().st_size if path.is_file() else _dir_size_bytes(path)
                mtime = path.stat().st_mtime
            except OSError:
                continue
            total_bytes += size
            entries.append(
                {
                    "name": path.name,
                    "path": str(path),
                    "size_bytes": size,
                    "mtime": mtime,
                    "age_seconds": max(0, int(time.time() - mtime)),
                }
            )
    return {
        "cache_root": str(cache_root),
        "ttl_seconds": static_cache_ttl_seconds(),
        "ttl_unlimited": static_cache_ttl_seconds() == 0,
        "entry_count": len(entries),
        "total_bytes": total_bytes,
        "entries": entries[:200],
        "data_root": settings.data_root or "",
        "output_root": settings.output_root or "",
        "discovered_datasets": scan_data_root_datasets(),
    }


def evict_data_cache(
    *, uri_or_name: str | None = None, older_than_seconds: int | None = None
) -> dict[str, Any]:
    cache_root = resolve_static_cache_root()
    removed: list[str] = []
    if not cache_root.exists():
        return {"removed": [], "cache_root": str(cache_root)}

    now = time.time()
    ttl = static_cache_ttl_seconds()
    age_limit = older_than_seconds
    if age_limit is None and ttl > 0:
        age_limit = ttl

    for path in list(cache_root.iterdir()):
        try:
            name = path.name
            if uri_or_name:
                needle = uri_or_name.strip()
                if needle not in name and needle not in str(path):
                    continue
            if age_limit is not None:
                age = now - path.stat().st_mtime
                if age < age_limit and not uri_or_name:
                    continue
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink(missing_ok=True)
            removed.append(str(path))
        except OSError:
            continue
    return {
        "removed": removed,
        "cache_root": str(cache_root),
        "removed_count": len(removed),
    }


DEFAULT_OPEN_DATA_PRESETS: dict[str, str] = {
    "noaa_nomads": "https://nomads.ncep.noaa.gov/",
    "noaa_goes": "https://cdn.star.nesdis.noaa.gov/",
    "nasa_earthdata": "https://data.lpdaac.earthdatacloud.nasa.gov/",
    "nasa_cmr": "https://cmr.earthdata.nasa.gov/",
    "nsidc_data": "https://n5eil01u.ecs.nsidc.org/",
    "esa_copernicus": "https://catalogue.dataspace.copernicus.eu/",
    "esa_download": "https://download.dataspace.copernicus.eu/",
}

OPEN_DATA_PRESET_LABELS: dict[str, str] = {
    "noaa_nomads": "NOAA NOMADS 数值产品",
    "noaa_goes": "NOAA GOES 影像 CDN",
    "nasa_earthdata": "NASA Earthdata / LP DAAC 云端对象",
    "nasa_cmr": "NASA CMR 元数据（二期检索预留）",
    "nsidc_data": "NSIDC 数据下载",
    "esa_copernicus": "欧空局 Copernicus 目录",
    "esa_download": "欧空局 Copernicus 下载 CDN",
}
