"""NASA GES DISC GLDAS 温度场下载模块。

供工作流 ``gldas_download`` 节点调用：按日期范围拉取
``GLDAS_NOAH025_3H``（默认 V2.1，``.nc4``）到本地目录。

主路径优先 ``earthaccess``；未安装时回退 CMR UMM-JSON + requests
（Earthdata Basic Auth），与 ``nsidc_download`` 策略一致。

产出目录可再经 ``.nc4 → .mat`` 预处理后接入 D2 DUAL（``gldas_mat``）。
本模块只负责在线拉取接口，不做科学重投影/变量改名。
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Any
from collections.abc import Callable

from ingest._http_resume import download_with_retry
from ingest.nsidc_download import (
    DOWNLOAD_TIMEOUT,
    MAX_RETRIES,
    MIN_DISK_FREE_GB,
    REQUEST_TIMEOUT,
    DownloadResult,
    Granule,
    check_disk_space,
    format_size,
    load_credentials,
)
import contextlib

logger = logging.getLogger(__name__)

try:
    import earthaccess  # type: ignore

    _HAS_EARTHACCESS = True
except ImportError:  # pragma: no cover
    earthaccess = None  # type: ignore
    _HAS_EARTHACCESS = False

SHORT_NAME = "GLDAS_NOAH025_3H"
VERSION = "2.1"
_NC4_SUFFIXES = (".nc4", ".nc")

# GLDAS 下载目录相对数据根的子路径（数据盘模板：Meteorological/Weather/GLDAS_Download）
_GLDAS_SUBDIR = ("Meteorological", "Weather", "GLDAS_Download")


def _default_output_dir() -> Path:
    """独立运行的默认输出目录：``BACKEND_DATA_ROOT`` 派生；未设且非 test 环境 fail-fast。

    工作流路径不使用此默认——``gldas_download`` 节点显式传 ``local_dir``。
    """
    root = os.getenv("BACKEND_DATA_ROOT", "").strip()
    if root:
        return Path(root).joinpath(*_GLDAS_SUBDIR)
    be = (os.getenv("BACKEND_ENV") or os.getenv("ENVIRONMENT") or "").lower()
    if be in {"test", "testing"}:
        import tempfile

        return Path(tempfile.gettempdir()) / "cgda_gldas_download"
    raise RuntimeError(
        "BACKEND_DATA_ROOT is not set; cannot derive GLDAS download output dir. "
        "Set BACKEND_DATA_ROOT (deployment config center /deployment) or pass "
        "local_dir explicitly."
    )


def _normalize_date(value: str) -> str:
    """Accept YYYYMMDD or YYYY-MM-DD → YYYY-MM-DD."""
    text = str(value or "").strip()
    if not text:
        return ""
    if len(text) == 8 and text.isdigit():
        return f"{text[:4]}-{text[4:6]}-{text[6:8]}"
    return text


def search_gldas_granules(
    start_date: str,
    end_date: str,
    *,
    short_name: str = SHORT_NAME,
    version: str = VERSION,
    username: str = "",
    password: str = "",
) -> list[Granule]:
    """Search GLDAS granules for the given UTC day range."""
    start = _normalize_date(start_date)
    end = _normalize_date(end_date)
    logger.info("搜索 %s V%s，时间范围 %s ~ %s", short_name, version, start, end)
    if _HAS_EARTHACCESS:
        return _search_via_earthaccess(
            start, end, short_name, version, username, password
        )
    logger.warning("未安装 earthaccess，使用 requests + CMR 回退搜索路径。")
    return _search_via_cmr(start, end, short_name, version)


def _prefer_nc4_url(urls: list[str]) -> str | None:
    if not urls:
        return None
    for url in urls:
        lower = url.lower()
        if any(lower.endswith(suf) for suf in _NC4_SUFFIXES):
            return url
    return urls[0]


def _search_via_earthaccess(
    start_date: str,
    end_date: str,
    short_name: str,
    version: str,
    username: str,
    password: str,
) -> list[Granule]:
    try:
        from ingest.nsidc_download import _earthaccess_login

        _earthaccess_login(username, password, persist=True)
    except Exception as exc:
        logger.error("earthaccess 登录失败: %s", exc)
        raise

    results = earthaccess.search_data(
        short_name=short_name,
        version=version,
        temporal=(start_date, end_date),
    )
    granules: list[Granule] = []
    for g in results:
        links: list[str] = []
        for access in ("external", "direct", None):
            try:
                if access is None:
                    found = list(g.data_links() or [])
                else:
                    found = list(g.data_links(access=access) or [])
            except Exception:
                continue
            links.extend(str(x) for x in found if x)
        url = _prefer_nc4_url(links)
        if not url:
            continue
        name = url.split("/")[-1]
        size_mb: float | None = None
        with contextlib.suppress(Exception):
            size_mb = float(g.size())
        granules.append(Granule(name=name, url=url, size_mb=size_mb))
    logger.info("earthaccess 搜索到 %d 个 granule", len(granules))
    return granules


def _search_via_cmr(
    start_date: str,
    end_date: str,
    short_name: str,
    version: str,
) -> list[Granule]:
    import requests  # type: ignore

    cmr_url = "https://cmr.earthdata.nasa.gov/search/granules.umm_json"
    temporal = f"{start_date}T00:00:00Z,{end_date}T23:59:59Z"
    granules: list[Granule] = []
    page_num = 1
    session = requests.Session()

    while True:
        params = {
            "short_name": short_name,
            "version": version,
            "temporal": temporal,
            "page_size": 2000,
            "page_num": page_num,
        }
        resp = session.get(cmr_url, params=params, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        items = data.get("items", [])
        if not items:
            break

        for item in items:
            umm = item.get("umm", {})
            related = umm.get("RelatedUrls", []) or []
            candidates: list[str] = []
            for r in related:
                if not str(r.get("Type", "")).startswith("GET DATA"):
                    continue
                url = str(r.get("URL") or "").strip()
                if url:
                    candidates.append(url)
            url = _prefer_nc4_url(candidates)
            if not url:
                continue
            name = url.split("/")[-1]
            size_mb: float | None = None
            dg = umm.get("DataGranule", {}) or {}
            sa = dg.get("ArchiveAndDistributionInformation") or dg.get(
                "ArchiveAndDistributionSize"
            )
            if isinstance(sa, list) and sa:
                sa = sa[0]
            if isinstance(sa, dict):
                try:
                    sz = float(sa.get("Size", 0))
                    unit = str(sa.get("SizeUnit") or sa.get("Unit") or "MB").upper()
                    if unit == "GB":
                        size_mb = sz * 1024
                    elif unit == "KB":
                        size_mb = sz / 1024
                    else:
                        size_mb = sz
                except (TypeError, ValueError):
                    pass
            granules.append(Granule(name=name, url=url, size_mb=size_mb))

        if len(items) < 2000:
            break
        page_num += 1
        if page_num > 50:
            break

    logger.info("CMR 搜索到 %d 个 granule", len(granules))
    return granules


def _get_download_session(username: str, password: str) -> Any:
    """Reuse NSIDC Earthdata session helper (earthaccess → BasicAuth fallback).

    GES DISC rejects bare HTTP BasicAuth on data URLs with HTTP 401; the
    earthaccess-backed session carries URS cookies/tokens needed for download.
    """
    from ingest.nsidc_download import _get_download_session as _nsidc_session

    return _nsidc_session(username, password)


def _download_with_retry(
    session: Any,
    url: str,
    dest: Path,
    progress_callback: Callable[[int, int], None] | None,
) -> bool:
    """共享续传下载 + ``.part`` 临时文件原子替换，避免部分文件污染跳过逻辑。"""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    if not download_with_retry(
        session,
        url,
        tmp,
        max_retries=MAX_RETRIES,
        timeout=DOWNLOAD_TIMEOUT,
        progress_callback=progress_callback,
    ):
        return False
    tmp.replace(dest)
    return True


def download_gldas_range(
    *,
    start_date: str,
    end_date: str,
    local_dir: str | Path | None = None,
    version: str = VERSION,
    short_name: str = SHORT_NAME,
    username: str = "",
    password: str = "",
    dry_run: bool = False,
    max_files: int | None = None,
    progress_callback: Callable[[int, int, int], None] | None = None,
) -> DownloadResult:
    """Download GLDAS NOAH025_3H granules for ``start_date``..``end_date``."""
    user, pwd = load_credentials(username, password)
    local_path = Path(local_dir) if local_dir else _default_output_dir()
    local_path.mkdir(parents=True, exist_ok=True)

    result = DownloadResult(local_dir=str(local_path))
    ok, free_gb = check_disk_space(local_path, MIN_DISK_FREE_GB)
    if not ok:
        result.errors.append(
            f"磁盘剩余空间不足: {free_gb:.1f} GB < {MIN_DISK_FREE_GB} GB"
        )
        result.failed = 1
        return result

    granules = search_gldas_granules(
        start_date,
        end_date,
        short_name=short_name,
        version=version,
        username=user,
        password=pwd,
    )
    if not granules:
        logger.warning("未搜索到任何 GLDAS granule")
        return result

    result.total_granules = len(granules)
    result.granules = granules

    todo: list[Granule] = []
    for g in granules:
        fp = local_path / g.name
        if fp.exists() and fp.stat().st_size > 0:
            result.skipped += 1
        else:
            todo.append(g)

    if max_files is not None and len(todo) > max_files:
        todo = todo[:max_files]

    if dry_run:
        logger.info("[dry-run] 将下载 %d 个 GLDAS 文件到 %s", len(todo), local_path)
        return result

    session = _get_download_session(user, pwd)
    for i, g in enumerate(todo, 1):
        fp = local_path / g.name
        logger.info("[%d/%d] %s", i, len(todo), g.name)

        def file_progress(dl: int, total: int) -> None:
            if progress_callback:
                progress_callback(i, len(todo), dl)

        if _download_with_retry(session, g.url, fp, file_progress):
            result.downloaded += 1
            result.downloaded_bytes += fp.stat().st_size
            logger.info("  完成: %s", format_size(fp.stat().st_size))
        else:
            result.failed += 1
            result.errors.append(f"下载失败: {g.name}")
        time.sleep(0.2)

    logger.info(
        "GLDAS 下载完成: 成功 %d, 失败 %d, 跳过 %d, 总量 %s",
        result.downloaded,
        result.failed,
        result.skipped,
        format_size(result.downloaded_bytes),
    )
    return result
