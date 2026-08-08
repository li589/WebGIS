r"""NASA NSIDC SMAP 数据下载模块。

从 ``Tools/download_smap_nsidc.py`` 提取的核心逻辑，提供可 import 的 SMAP L3
SPL3SMP_E 数据下载函数，供工作流 ``nsidc_smap_download`` 节点调用。

主路径使用 ``earthaccess`` 库（NASA 官方推荐）；若未安装，自动回退到
``requests`` + CMR + HTTP Basic Auth 手动实现。

主要特性：
    - 日期范围下载
    - 增量下载：跳过本地已存在文件（按文件名 + 大小判断）
    - 断点续传（HTTP Range）
    - 失败自动重试（最多 3 次，指数退避）
    - 下载前磁盘空间检查
    - Earthdata 认证测试

用法::

    from ingest.nsidc_download import download_smap_range

    result = download_smap_range(
        start_date="2023-01-01",
        end_date="2023-01-31",
        local_dir=r"I:\Geograph_DataSet\Soil_Moisture\SMAP",
    )

凭据策略：
    优先使用显式传参；其次读取环境变量
    ``BACKEND_EARTHDATA_USERNAME`` / ``BACKEND_EARTHDATA_PASSWORD`` 与
    ``EARTHDATA_USERNAME`` / ``EARTHDATA_PASSWORD``。
    不再回退任何内置默认账号。
"""

from __future__ import annotations

import logging
import os
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

# ─── 常量 ────────────────────────────────────────────────────────────────────

SHORT_NAME = "SPL3SMP_E"
VERSION = "6"

MAX_RETRIES = 3
INITIAL_BACKOFF = 2.0
CHUNK_SIZE = 262144  # 256 KB
REQUEST_TIMEOUT = 60
DOWNLOAD_TIMEOUT = 3600
MIN_DISK_FREE_GB = 5.0
PROGRESS_INTERVAL = 2.0

DEFAULT_OUTPUT_DIR = Path(r"I:\Geograph_DataSet\Soil_Moisture\SMAP")

# 尝试导入 earthaccess
try:
    import earthaccess  # type: ignore

    _HAS_EARTHACCESS = True
except ImportError:  # pragma: no cover
    earthaccess = None  # type: ignore
    _HAS_EARTHACCESS = False


# ─── 数据类 ──────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Granule:
    """单个 granule 描述。"""

    name: str
    url: str
    size_mb: float | None = None


@dataclass
class DownloadResult:
    """下载任务结果统计。"""

    total_granules: int = 0
    downloaded: int = 0
    skipped: int = 0
    failed: int = 0
    downloaded_bytes: int = 0
    local_dir: str = ""
    granules: list[Granule] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def success(self) -> bool:
        """是否全部成功（无失败）。"""
        return self.failed == 0 and len(self.errors) == 0


# ─── 通用工具 ────────────────────────────────────────────────────────────────


def format_size(size_bytes: float) -> str:
    """将字节数格式化为易读字符串。"""
    if size_bytes <= 0:
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(size_bytes)
    idx = 0
    while size >= 1024 and idx < len(units) - 1:
        size /= 1024
        idx += 1
    return f"{size:.2f} {units[idx]}"


def load_credentials(
    username: str = "",
    password: str = "",
) -> tuple[str, str]:
    """读取 Earthdata 凭据。

    优先使用传入参数，其次环境变量；不使用内置默认账号。
    """
    env_user = os.environ.get("BACKEND_EARTHDATA_USERNAME") or os.environ.get(
        "EARTHDATA_USERNAME"
    )
    env_pass = os.environ.get("BACKEND_EARTHDATA_PASSWORD") or os.environ.get(
        "EARTHDATA_PASSWORD"
    )

    resolved_user = username or env_user or ""
    resolved_pass = password or env_pass or ""
    if resolved_user and resolved_pass:
        return resolved_user, resolved_pass

    missing: list[str] = []
    if not resolved_user:
        missing.append("username")
    if not resolved_pass:
        missing.append("password")
    raise ValueError(
        "Earthdata credentials are required; missing "
        + ", ".join(missing)
        + ". Set BACKEND_EARTHDATA_USERNAME/BACKEND_EARTHDATA_PASSWORD "
        + "or EARTHDATA_USERNAME/EARTHDATA_PASSWORD."
    )


def check_disk_space(
    path: Path, min_gb: float = MIN_DISK_FREE_GB
) -> tuple[bool, float]:
    """检查 path 所在磁盘可用空间，返回 (是否充足, 可用 GB)。"""
    try:
        path.mkdir(parents=True, exist_ok=True)
        usage = shutil.disk_usage(path)
        free_gb = usage.free / (1024**3)
        return free_gb >= min_gb, free_gb
    except OSError as exc:
        logger.error("磁盘空间检查失败: %s", exc)
        return False, 0.0


# ─── 认证 ────────────────────────────────────────────────────────────────────


def _earthaccess_login(username: str, password: str, *, persist: bool = True) -> Any:
    """Login via earthaccess 0.15+ API (environment strategy).

    Newer ``earthaccess.login`` no longer accepts ``username``/``password`` kwargs;
    credentials must be provided via ``EARTHDATA_USERNAME`` / ``EARTHDATA_PASSWORD``
    (or token / netrc / interactive).
    """
    if not _HAS_EARTHACCESS:
        raise RuntimeError("earthaccess is not installed")
    if username:
        os.environ["EARTHDATA_USERNAME"] = username
    if password:
        os.environ["EARTHDATA_PASSWORD"] = password
    # Prefer env strategy so non-interactive workers never fall into prompts.
    return earthaccess.login(strategy="environment", persist=persist)


def test_earthdata_auth(username: str, password: str) -> bool:
    """测试 Earthdata 登录是否可用。"""
    logger.info("测试 Earthdata 认证（用户: %s）...", username)
    if _HAS_EARTHACCESS:
        try:
            _earthaccess_login(username, password, persist=True)
            logger.info("earthaccess 认证成功")
            return True
        except Exception as exc:
            logger.error("earthaccess 认证失败: %s", exc)
            return False

    try:
        import requests  # type: ignore
        from requests.auth import HTTPBasicAuth  # type: ignore

        session = requests.Session()
        session.auth = HTTPBasicAuth(username, password)
        resp = session.get(
            "https://urs.earthdata.nasa.gov/profile",
            timeout=REQUEST_TIMEOUT,
            allow_redirects=True,
        )
        if resp.status_code == 200:
            logger.info("Earthdata 认证成功（requests 回退路径）")
            return True
        logger.error("Earthdata 认证失败，HTTP %s", resp.status_code)
        return False
    except Exception as exc:
        logger.error("Earthdata 认证失败: %s", exc)
        return False


# ─── Granule 搜索 ────────────────────────────────────────────────────────────


def search_granules(
    start_date: str,
    end_date: str,
    *,
    short_name: str = SHORT_NAME,
    version: str = VERSION,
    username: str = "",
    password: str = "",
) -> list[Granule]:
    """搜索 granule，返回 ``Granule`` 列表。

    Args:
        start_date: 起始日期 (YYYY-MM-DD)
        end_date: 结束日期 (YYYY-MM-DD)
        short_name: 产品短名（默认 SPL3SMP_E）
        version: 产品版本（默认 6）
        username: Earthdata 用户名
        password: Earthdata 密码

    Returns:
        Granule 列表
    """
    logger.info(
        "搜索 %s V%s，时间范围 %s ~ %s", short_name, version, start_date, end_date
    )
    if _HAS_EARTHACCESS:
        return _search_via_earthaccess(
            start_date, end_date, short_name, version, username, password
        )
    logger.warning("未安装 earthaccess，使用 requests + CMR 回退搜索路径。")
    return _search_via_cmr(start_date, end_date, short_name, version)


def _search_via_earthaccess(
    start_date: str,
    end_date: str,
    short_name: str,
    version: str,
    username: str,
    password: str,
) -> list[Granule]:
    """使用 earthaccess 搜索 granule。"""
    try:
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
        url = _granule_url(g)
        if not url:
            continue
        name = url.split("/")[-1]
        size_mb: float | None = None
        try:
            size_mb = float(g.size())
        except Exception:
            pass
        granules.append(Granule(name=name, url=url, size_mb=size_mb))

    logger.info("earthaccess 搜索到 %d 个 granule", len(granules))
    return granules


def _granule_url(granule: Any) -> str | None:
    """从 earthaccess DataGranule 提取 .h5 下载 URL。"""
    for access in ("external", "direct", None):
        try:
            if access is None:
                links = granule.data_links()
            else:
                links = granule.data_links(access=access)
        except Exception:
            continue
        if not links:
            continue
        for link in links:
            if link.lower().endswith(".h5"):
                return link
        return links[0]
    return None


def _search_via_cmr(
    start_date: str,
    end_date: str,
    short_name: str,
    version: str,
) -> list[Granule]:
    """使用 CMR UMM-JSON API 搜索 granule（earthaccess 不可用时回退）。"""
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
            url: str | None = None
            for r in related:
                if r.get("Type", "").startswith("GET DATA") and r.get(
                    "URL", ""
                ).lower().endswith(".h5"):
                    url = r.get("URL")
                    break
            if url is None:
                for r in related:
                    if r.get("Type", "").startswith("GET DATA"):
                        url = r.get("URL")
                        break
            if not url:
                continue

            name = url.split("/")[-1]
            size_mb: float | None = None
            dg = umm.get("DataGranule", {}) or {}
            sa = dg.get("ArchiveAndDistributionSize")
            if isinstance(sa, dict):
                try:
                    sz = float(sa.get("Size", 0))
                    unit = str(sa.get("Unit", "MB")).upper()
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


# ─── 下载 ────────────────────────────────────────────────────────────────────


def _get_download_session(username: str, password: str) -> Any:
    """返回带 Earthdata 认证的 requests.Session。"""
    if _HAS_EARTHACCESS:
        try:
            auth = _earthaccess_login(username, password, persist=True)
            session = auth.get_session()
            logger.debug("使用 earthaccess 认证 session 进行下载")
            return session
        except Exception as exc:
            logger.warning(
                "earthaccess session 获取失败，回退到 HTTPBasicAuth: %s", exc
            )

    import requests  # type: ignore
    from requests.auth import HTTPBasicAuth  # type: ignore

    session = requests.Session()
    session.auth = HTTPBasicAuth(username, password)
    session.headers.update({"User-Agent": "cgda-nsidc-download/1.0"})
    return session


def _download_single(
    session: Any,
    url: str,
    local_path: Path,
    progress_callback: Callable[[int, int], None] | None = None,
) -> tuple[bool, int]:
    """流式下载单个文件，支持断点续传。

    Returns:
        (是否成功, 本次下载字节数)
    """
    local_path.parent.mkdir(parents=True, exist_ok=True)
    existing = local_path.stat().st_size if local_path.exists() else 0

    headers: dict[str, str] = {}
    if existing > 0:
        headers["Range"] = f"bytes={existing}-"
        logger.info("  断点续传: 从 %s 开始", format_size(existing))

    resp = session.get(
        url,
        headers=headers,
        stream=True,
        timeout=DOWNLOAD_TIMEOUT,
        allow_redirects=True,
    )

    if resp.status_code == 416:
        resp.close()
        logger.info("  本地文件已完成，跳过")
        return True, 0

    if resp.status_code not in (200, 206):
        resp.close()
        raise RuntimeError(f"HTTP {resp.status_code} 下载失败: {url}")

    mode = "ab" if resp.status_code == 206 else "wb"
    if mode == "wb" and existing > 0:
        existing = 0

    content_length = int(resp.headers.get("Content-Length", 0))
    total = content_length + existing
    downloaded = 0
    last_report = time.time()

    try:
        with open(local_path, mode) as f:
            for chunk in resp.iter_content(chunk_size=CHUNK_SIZE):
                if not chunk:
                    continue
                f.write(chunk)
                downloaded += len(chunk)
                now = time.time()
                if now - last_report >= PROGRESS_INTERVAL:
                    cur = existing + downloaded
                    logger.info(
                        "  下载中 %s: %s / %s",
                        local_path.name,
                        format_size(cur),
                        format_size(total) if total else "?",
                    )
                    last_report = now
                if progress_callback:
                    progress_callback(downloaded, total)
    finally:
        resp.close()

    return True, downloaded


def _download_with_retry(
    session: Any,
    url: str,
    local_path: Path,
    expected_size_mb: float | None = None,
    progress_callback: Callable[[int, int], None] | None = None,
) -> bool:
    """带重试（指数退避）的下载封装。"""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            ok, _ = _download_single(session, url, local_path, progress_callback)
            if ok:
                final_size = local_path.stat().st_size if local_path.exists() else 0
                if final_size <= 0:
                    raise RuntimeError("下载后文件大小为 0")
                return True
        except Exception as exc:
            logger.warning("  尝试 %d/%d 失败: %s", attempt, MAX_RETRIES, exc)
            if attempt < MAX_RETRIES:
                backoff = INITIAL_BACKOFF * (2 ** (attempt - 1))
                logger.info("  等待 %.1fs 后重试...", backoff)
                time.sleep(backoff)
            else:
                logger.error("  已达最大重试次数，放弃: %s", local_path.name)
                return False
    return False


# ─── 主 API ──────────────────────────────────────────────────────────────────


def download_smap_range(
    start_date: str,
    end_date: str,
    local_dir: str | Path = DEFAULT_OUTPUT_DIR,
    *,
    version: str = VERSION,
    short_name: str = SHORT_NAME,
    username: str = "",
    password: str = "",
    dry_run: bool = False,
    max_files: int | None = None,
    progress_callback: Callable[[int, int, int], None] | None = None,
) -> DownloadResult:
    """从 NASA NSIDC 下载 SMAP L3 SPL3SMP_E 数据。

    Args:
        start_date: 起始日期 (YYYY-MM-DD)
        end_date: 结束日期 (YYYY-MM-DD)
        local_dir: 本地目标目录
        version: 产品版本（默认 6）
        short_name: 产品短名（默认 SPL3SMP_E）
        username: Earthdata 用户名（空则从环境变量读取）
        password: Earthdata 密码（空则从环境变量读取）
        dry_run: 仅预览不实际下载
        max_files: 限制单次下载文件数量
        progress_callback: 回调(current_file, total_files, downloaded_bytes)

    Returns:
        DownloadResult 统计信息
    """
    local_path = Path(local_dir)
    username, password = load_credentials(username, password)

    result = DownloadResult(local_dir=str(local_path))

    logger.info("=" * 60)
    logger.info("SMAP L3 SMAP_E 下载任务")
    logger.info("产品: %s V%s", short_name, version)
    logger.info("时间范围: %s ~ %s", start_date, end_date)
    logger.info("目标目录: %s", local_path)
    logger.info("earthaccess 可用: %s", _HAS_EARTHACCESS)
    logger.info("=" * 60)

    # 1) 认证测试
    if not test_earthdata_auth(username, password):
        result.errors.append("Earthdata 认证失败")
        return result

    # 2) 磁盘空间检查
    if not dry_run:
        ok, free_gb = check_disk_space(local_path)
        logger.info("可用磁盘空间: %.2f GB", free_gb)
        if not ok:
            result.errors.append(
                f"磁盘空间不足（需 >= {MIN_DISK_FREE_GB:.1f} GB，可用 {free_gb:.2f} GB）"
            )
            return result

    # 3) 搜索 granule
    granules = search_granules(
        start_date,
        end_date,
        short_name=short_name,
        version=version,
        username=username,
        password=password,
    )
    if not granules:
        logger.warning("未搜索到任何 granule")
        return result

    result.total_granules = len(granules)
    result.granules = granules

    # 4) 增量过滤
    todo: list[Granule] = []
    for g in granules:
        fp = local_path / g.name
        if fp.exists() and fp.stat().st_size > 0:
            result.skipped += 1
            logger.info("  跳过已存在: %s (%s)", g.name, format_size(fp.stat().st_size))
        else:
            todo.append(g)

    logger.info(
        "共 %d 个 granule，跳过 %d 个已存在，待下载 %d 个",
        len(granules),
        result.skipped,
        len(todo),
    )

    # 5) max_files 限制
    if max_files is not None and len(todo) > max_files:
        logger.info("应用 max_files=%d 限制", max_files)
        todo = todo[:max_files]

    # 6) dry-run
    if dry_run:
        logger.info("[dry-run] 将下载 %d 个文件", len(todo))
        return result

    # 7) 下载
    session = _get_download_session(username, password)

    for i, g in enumerate(todo, 1):
        fp = local_path / g.name
        logger.info("[%d/%d] %s", i, len(todo), g.name)

        def file_progress(dl: int, total: int) -> None:
            if progress_callback:
                progress_callback(i, len(todo), dl)

        success = _download_with_retry(session, g.url, fp, g.size_mb, file_progress)
        if success:
            result.downloaded += 1
            result.downloaded_bytes += fp.stat().st_size
            logger.info("  完成: %s", format_size(fp.stat().st_size))
        else:
            result.failed += 1
            result.errors.append(f"下载失败: {g.name}")
        time.sleep(0.2)

    logger.info("=" * 60)
    logger.info(
        "下载完成: 成功 %d, 失败 %d, 跳过 %d",
        result.downloaded,
        result.failed,
        result.skipped,
    )
    logger.info("总下载量: %s", format_size(result.downloaded_bytes))
    logger.info("=" * 60)

    return result
