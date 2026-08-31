r"""ECMWF CDS（Climate Data Store）数据集下载模块。

供工作流 ``cds_download`` 节点调用：按 dataset + request 拉取 ERA5 / ORAS5
等再分析产品到本地目录。

主路径（``use="auto"``，默认）：``cdsapi.Client(url=..., key=...)`` +
``retrieve(dataset, request, target)``，客户端内部处理排队轮询与重试。

回退路径（``use="legacy"``）：静态直链产品走通用 HTTP 下载，复用
``ingest/_http_resume.py`` 共享续传工具（Range 续传 + 指数退避）。

增量语义：目标文件已存在且非空时跳过（``force=True`` 强制重下）。

凭据策略（``load_cds_api_key``）：
    显式传参 > 环境变量 ``BACKEND_CDS_API_KEY`` > ``CDSAPI_KEY``。
    个人访问密钥来自 CDS 个人主页（形如 ``xxxxxx-xxxx-xxxx-xxxx-xxxxxxxx``）。
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from ingest._http_resume import check_disk_space, format_size

logger = logging.getLogger(__name__)

ByteStreamProgressCb = Callable[[int, int], None] | None

CDS_DEFAULT_URL = "https://cds.climate.copernicus.eu/api"
MIN_DISK_FREE_GB = 5.0

try:
    import cdsapi  # type: ignore

    _HAS_CDSAPI = True
except ImportError:  # pragma: no cover
    cdsapi = None  # type: ignore
    _HAS_CDSAPI = False


@dataclass
class CdsDownloadResult:
    """CDS 下载任务结果。"""

    dataset: str = ""
    target: str = ""
    downloaded_bytes: int = 0
    skipped: bool = False
    use: str = ""
    request: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return not self.errors


def load_cds_api_key(api_key: str = "") -> str:
    """读取 CDS 个人访问密钥：显式传参 > ``BACKEND_CDS_API_KEY`` > ``CDSAPI_KEY``。"""
    resolved = (
        api_key.strip()
        or os.environ.get("BACKEND_CDS_API_KEY", "").strip()
        or os.environ.get("CDSAPI_KEY", "").strip()
    )
    if resolved:
        return resolved
    raise ValueError(
        "CDS API key is required. Pass api_key explicitly, or set "
        "BACKEND_CDS_API_KEY / CDSAPI_KEY (key from CDS profile page)."
    )


def coerce_request(request: dict[str, Any] | str) -> dict[str, Any]:
    """把 ``request`` 规整为 dict：dict 原样透传，JSON 字符串解析。"""
    if isinstance(request, dict):
        return dict(request)
    text = str(request or "").strip()
    if not text:
        return {}
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"cds_download: invalid request JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ValueError(
            "cds_download: request must be a JSON object or dict, "
            f"got {type(parsed).__name__}"
        )
    return parsed


def _target_extension(request: dict[str, Any]) -> str:
    """按请求推断落盘扩展名。

    - ``download_format=unarchived``（单文件不打包）时按 ``data_format`` 落实际
      格式：netcdf* → ``.nc``、grib* → ``.grib``（未声明 data_format 时 CDS 默认 GRIB）；
    - 其余（zip 归档或未声明，CDS 默认打包）→ ``.zip``。
    """
    download_format = str(request.get("download_format", "")).strip().lower()
    if download_format != "unarchived":
        return ".zip"
    data_format = str(request.get("data_format", "")).strip().lower()
    if data_format.startswith("netcdf"):
        return ".nc"
    return ".grib"


def default_filename(dataset: str, request: dict[str, Any]) -> str:
    """确定性目标文件名：``{dataset 转义}_{请求指纹}.{实际格式扩展名}``。"""
    slug = dataset.strip().replace("/", "_").replace("\\", "_") or "cds_product"
    canonical = json.dumps(request, sort_keys=True, ensure_ascii=False)
    digest = hashlib.md5(canonical.encode("utf-8")).hexdigest()[:8]  # noqa: S324
    return f"{slug}_{digest}{_target_extension(request)}"


def download_via_cdsapi(
    dataset: str,
    request: dict[str, Any],
    target: Path,
    *,
    api_key: str,
    url: str = CDS_DEFAULT_URL,
) -> int:
    """主路径：cdsapi 检索 + 排队轮询下载，返回文件字节数。"""
    if not _HAS_CDSAPI:
        raise RuntimeError(
            "cdsapi is not installed; run pip install cdsapi or switch use='legacy' "
            "for static direct-link products."
        )
    logger.info("CDS cdsapi 检索: %s -> %s", dataset, target)
    client = cdsapi.Client(url=url, key=api_key, progress=False, quiet=False)
    client.retrieve(name=dataset, request=request, target=str(target))
    size = target.stat().st_size if target.exists() else 0
    logger.info("CDS 下载完成: %s (%s)", target.name, format_size(size))
    return size


def download_via_legacy(
    direct_url: str,
    target: Path,
    *,
    http_headers: dict[str, str] | None = None,
    progress_callback: ByteStreamProgressCb = None,
) -> int:
    """回退路径：静态直链下载（共享续传工具），返回文件字节数。"""
    import requests

    session = requests.Session()
    if http_headers:
        session.headers.update(http_headers)
    logger.info("CDS legacy 直链下载: %s -> %s", direct_url, target)
    if not download_resumable_with_retry(
        session, direct_url, target, progress_callback=progress_callback
    ):
        raise RuntimeError(f"CDS legacy download failed: {direct_url}")
    return target.stat().st_size if target.exists() else 0


def download_resumable_with_retry(
    session: Any,
    url: str,
    target: Path,
    *,
    progress_callback: ByteStreamProgressCb = None,
) -> bool:
    """共享续传工具薄封装（便于测试替换）。"""
    from ingest._http_resume import download_with_retry

    return download_with_retry(
        session, url, target, progress_callback=progress_callback
    )


def download_cds_dataset(
    dataset: str,
    request: dict[str, Any] | str,
    target_dir: str | Path,
    *,
    api_key: str = "",
    url: str = CDS_DEFAULT_URL,
    use: str = "auto",
    filename: str = "",
    direct_url: str = "",
    http_headers: dict[str, str] | None = None,
    force: bool = False,
    min_disk_free_gb: float = MIN_DISK_FREE_GB,
    progress_callback: ByteStreamProgressCb = None,
) -> CdsDownloadResult:
    """下载单个 CDS 数据集到 ``target_dir``。

    Args:
        dataset: CDS 数据集 id（如 ``reanalysis-era5-single-levels``）。
        request: 检索请求（dict 或 JSON 字符串；产品/变量/时间/区域等）。
        target_dir: 本地目标目录。
        api_key: CDS 个人访问密钥（空则从环境变量读取）。
        url: CDS API 端点（默认新版 ``/api``）。
        use: ``auto``（默认，cdsapi 主路径）/ ``cdsapi`` / ``legacy``（直链）。
        filename: 目标文件名（缺省按 dataset+request 指纹生成）。
        direct_url: legacy 路径的静态直链 URL。
        http_headers: legacy 路径附加请求头（门户 Bearer 等）。
        force: 目标已存在时是否强制重下。
        min_disk_free_gb: 下载前磁盘可用空间下限。

    Returns:
        CdsDownloadResult 统计信息。
    """
    dataset = str(dataset or "").strip()
    if not dataset:
        raise ValueError("cds_download requires a non-empty dataset")
    req = coerce_request(request)
    use_mode = str(use or "auto").strip().lower()
    if use_mode not in {"auto", "cdsapi", "legacy"}:
        raise ValueError(f"cds_download: invalid use={use!r} (auto|cdsapi|legacy)")

    target_path = Path(target_dir) / (
        filename.strip() or default_filename(dataset, req)
    )
    result = CdsDownloadResult(
        dataset=dataset,
        target=str(target_path),
        request=req,
        use=use_mode,
    )

    # 增量：已存在且非空则跳过
    if not force and target_path.exists() and target_path.stat().st_size > 0:
        logger.info("CDS 目标已存在，跳过: %s", target_path)
        result.skipped = True
        return result

    target_path.parent.mkdir(parents=True, exist_ok=True)
    ok, free_gb = check_disk_space(target_path.parent, min_gb=min_disk_free_gb)
    if not ok:
        raise RuntimeError(
            f"CDS download aborted: insufficient disk space "
            f"(need >= {min_disk_free_gb:.1f} GB, free {free_gb:.2f} GB)"
        )

    if use_mode == "legacy":
        if not direct_url.strip():
            raise ValueError(
                "cds_download: use='legacy' requires direct_url "
                "(static direct-link products only)"
            )
        result.downloaded_bytes = download_via_legacy(
            direct_url.strip(),
            target_path,
            http_headers=http_headers,
            progress_callback=progress_callback,
        )
    else:
        if not _HAS_CDSAPI:
            raise RuntimeError(
                "cdsapi is not installed (use='auto' cannot fall back to legacy "
                "for queued products). Install cdsapi or configure use='legacy' "
                "with a static direct_url."
            )
        result.downloaded_bytes = download_via_cdsapi(
            dataset, req, target_path, api_key=load_cds_api_key(api_key), url=url
        )

    return result
