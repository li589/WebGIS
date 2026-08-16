r"""Copernicus Data Space Ecosystem（CDSE）产品下载模块。

供工作流 ``cdse_download`` 节点调用：按 product_id（或 OData ``$filter``
检索）物化 Sentinel 等产品到本地目录。

主路径（``use="auto"``，默认，原生强化无新库）：
    1. token 交换：``identity.dataspace.copernicus.eu`` OpenID Connect
       password grant（copernicus 门户凭据 username/password → Bearer）；
    2. OData ``$value`` 内容下载，复用 ``ingest/_http_resume.py`` 共享
       续传工具（Range 续传 + 指数退避）。

回退路径（``use="legacy"``）：静态直链下载（现有 ``http_open_data``
语义；仅适用于免登录直链或已含签名 URL 的产品）。

检索结果入口：``search_portal`` / ``cmr_granule_search`` 风格条目
（``granule_id``/``data_link`` 字段）或显式 ``product_ids`` /
``odata_filter``。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ingest._http_resume import check_disk_space, download_with_retry, format_size

logger = logging.getLogger(__name__)

CDSE_TOKEN_URL = (
    "https://identity.dataspace.copernicus.eu/auth/realms/CDSE"
    "/protocol/openid-connect/token"
)
CDSE_ODATA_BASE = "https://catalogue.dataspace.copernicus.eu/odata/v1/Products"
CDSE_DOWNLOAD_ORIGIN = "https://download.dataspace.copernicus.eu"
CDSE_DOWNLOAD_URL_TEMPLATE = "{origin}/odata/v1/Products({product_id})/$value"

MIN_DISK_FREE_GB = 5.0
_TOKEN_TIMEOUT = 60
_ODATA_TIMEOUT = 60

_VALID_USE = frozenset({"auto", "cdse", "legacy"})


@dataclass
class CdseProduct:
    """单个 CDSE 产品描述。"""

    product_id: str
    name: str = ""
    size_bytes: int = 0


@dataclass
class CdseDownloadResult:
    """CDSE 下载任务结果。"""

    use: str = ""
    target_dir: str = ""
    products: list[CdseProduct] = field(default_factory=list)
    downloaded: int = 0
    skipped: int = 0
    failed: int = 0
    downloaded_bytes: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return self.failed == 0 and not self.errors


def build_download_url(product_id: str, *, origin: str = CDSE_DOWNLOAD_ORIGIN) -> str:
    """OData ``$value`` 内容下载 URL。"""
    return CDSE_DOWNLOAD_URL_TEMPLATE.format(
        origin=origin.rstrip("/"), product_id=product_id.strip()
    )


def coerce_product_ids(product_ids: list[str] | str) -> list[str]:
    """product_ids 规整为非空 id 列表（list / 逗号分隔字符串）。"""
    if isinstance(product_ids, str):
        parts = [p.strip() for p in product_ids.split(",")]
    elif isinstance(product_ids, (list, tuple)):
        parts = [str(p).strip() for p in product_ids]
    else:
        raise ValueError("cdse_download: product_ids must be list or comma string")
    return [p for p in parts if p]


def extract_products_from_search(
    search_results: dict[str, Any] | list[Any] | str,
) -> list[CdseProduct]:
    """从 search_portal / cmr_granule_search 风格检索结果提取产品。

    接受 ``{"results": [...]}``、裸 list 或含 ``granule_id`` 的单条 dict；
    条目 ``granule_id``/``product_id`` 为 CDSE 产品 Id，``title`` 为文件名。
    """
    if isinstance(search_results, str):
        import json

        try:
            search_results = json.loads(search_results)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"cdse_download: invalid search_results JSON: {exc}"
            ) from exc
    entries: list[Any]
    if isinstance(search_results, dict):
        raw = (
            search_results.get("results")
            if isinstance(search_results.get("results"), list)
            else [search_results]
        )
        entries = list(raw)
    elif isinstance(search_results, list):
        entries = search_results
    else:
        return []

    products: list[CdseProduct] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        pid = str(entry.get("granule_id") or entry.get("product_id") or "").strip()
        if not pid:
            continue
        try:
            size = int(float(entry.get("size_bytes") or 0))
        except (TypeError, ValueError):
            size = 0
        products.append(
            CdseProduct(
                product_id=pid,
                name=str(entry.get("title") or entry.get("name") or ""),
                size_bytes=size,
            )
        )
    return products


def exchange_cdse_token(
    username: str,
    password: str,
    *,
    token_url: str = CDSE_TOKEN_URL,
    timeout: int = _TOKEN_TIMEOUT,
    session: Any = None,
) -> str:
    """OpenID Connect password grant 换取 Bearer access_token。"""
    import requests

    sess = session or requests
    resp = sess.post(
        token_url,
        data={
            "grant_type": "password",
            "client_id": "cdse-public",
            "username": username,
            "password": password,
        },
        timeout=timeout,
    )
    if resp.status_code != 200:
        raise RuntimeError(
            f"CDSE token exchange failed: HTTP {resp.status_code} at {token_url}"
        )
    payload = resp.json()
    token = str(payload.get("access_token") or "")
    if not token:
        raise RuntimeError("CDSE token exchange returned no access_token")
    return token


def resolve_cdse_products(
    product_ids: list[str],
    *,
    odata_base: str = CDSE_ODATA_BASE,
    timeout: int = _ODATA_TIMEOUT,
    session: Any = None,
) -> list[CdseProduct]:
    """按 product_id 批量解析名称与大小（OData 目录公共端点）。"""
    import requests

    sess = session or requests
    products: list[CdseProduct] = []
    for pid in product_ids:
        product = CdseProduct(product_id=pid)
        try:
            resp = sess.get(
                f"{odata_base.rstrip('/')}({pid})",
                timeout=timeout,
            )
            if resp.status_code == 200:
                entry = resp.json()
                product.name = str(entry.get("Name") or "")
                try:
                    product.size_bytes = int(float(entry.get("ContentLength") or 0))
                except (TypeError, ValueError):
                    product.size_bytes = 0
            else:
                logger.warning("CDSE 元数据解析失败 HTTP %s: %s", resp.status_code, pid)
        except Exception as exc:  # noqa: BLE001
            logger.warning("CDSE 元数据解析异常 %s: %s", pid, exc)
        products.append(product)
    return products


def search_by_odata_filter(
    odata_filter: str,
    *,
    page_size: int = 20,
    odata_base: str = CDSE_ODATA_BASE,
    timeout: int = _ODATA_TIMEOUT,
    session: Any = None,
) -> list[CdseProduct]:
    """OData ``$filter`` 检索产品列表（公共端点）。"""
    import urllib.parse

    import requests

    sess = session or requests
    query = urllib.parse.urlencode({"$filter": odata_filter, "$top": str(page_size)})
    resp = sess.get(f"{odata_base.rstrip('/')}?{query}", timeout=timeout)
    if resp.status_code != 200:
        raise RuntimeError(f"CDSE OData filter search failed: HTTP {resp.status_code}")
    payload = resp.json()
    entries = payload.get("value") or []
    products: list[CdseProduct] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        pid = str(entry.get("Id") or "").strip()
        if not pid:
            continue
        try:
            size = int(float(entry.get("ContentLength") or 0))
        except (TypeError, ValueError):
            size = 0
        products.append(
            CdseProduct(
                product_id=pid,
                name=str(entry.get("Name") or ""),
                size_bytes=size,
            )
        )
    return products


def download_product_value(
    product: CdseProduct,
    target: Path,
    *,
    bearer_token: str,
    origin: str = CDSE_DOWNLOAD_ORIGIN,
    session: Any = None,
) -> int:
    """单个产品 ``$value`` 下载（共享续传工具），返回字节数。"""
    import requests

    sess = session or requests.Session()
    if bearer_token:
        token = (
            bearer_token
            if bearer_token.lower().startswith("bearer ")
            else f"Bearer {bearer_token}"
        )
        if isinstance(sess, requests.Session):
            sess.headers["Authorization"] = token
    url = build_download_url(product.product_id, origin=origin)
    if not download_with_retry(sess, url, target):
        raise RuntimeError(f"CDSE download failed: {product.product_id}")
    return target.stat().st_size if target.exists() else 0


def download_cdse_products(
    product_ids: list[str] | str = "",
    odata_filter: str = "",
    target_dir: str | Path = "",
    *,
    search_results: dict[str, Any] | list[Any] | str | None = None,
    username: str = "",
    password: str = "",
    bearer_token: str = "",
    use: str = "auto",
    legacy_urls: list[str] | str = "",
    force: bool = False,
    max_products: int | None = None,
    origin: str = CDSE_DOWNLOAD_ORIGIN,
    min_disk_free_gb: float = MIN_DISK_FREE_GB,
) -> CdseDownloadResult:
    """下载 CDSE 产品列表到 ``target_dir``。

    产品来源优先级：``product_ids`` > ``search_results`` > ``odata_filter``。

    Args:
        product_ids: 产品 Id 列表（或逗号分隔字符串）。
        odata_filter: OData ``$filter`` 检索字符串（无 Id 时在线解析）。
        target_dir: 本地目标目录（空则 BACKEND_DATA_ROOT 派生）。
        search_results: 检索节点结果（``granule_id`` 条目）。
        username/password: copernicus 门户凭据（token 交换）。
        bearer_token: 已有 Bearer token（跳过交换）。
        use: ``auto``（默认）/ ``cdse`` / ``legacy``（直链）。
        legacy_urls: legacy 直链列表（或换行/逗号分隔字符串）。
        force: 已存在文件是否强制重下（默认按大小增量跳过）。
        max_products: 单次下载产品数上限。
        origin: 下载域 origin。
        min_disk_free_gb: 磁盘可用空间下限。

    Returns:
        CdseDownloadResult 统计信息。
    """
    use_mode = str(use or "auto").strip().lower()
    if use_mode not in _VALID_USE:
        raise ValueError(f"cdse_download: invalid use={use!r} (auto|cdse|legacy)")

    ids = coerce_product_ids(product_ids)
    products: list[CdseProduct] = []
    if ids:
        products = resolve_cdse_products(ids)
    elif search_results is not None:
        products = extract_products_from_search(search_results)
    elif odata_filter.strip():
        products = search_by_odata_filter(odata_filter.strip())

    if use_mode == "legacy":
        target_path = (
            Path(target_dir)
            if str(target_dir or "").strip()
            else (_default_target_dir())
        )
        result = CdseDownloadResult(use=use_mode, target_dir=str(target_path))
        target_path.mkdir(parents=True, exist_ok=True)
        _run_legacy(legacy_urls, target_path, result)
        return result

    if not products:
        raise ValueError(
            "cdse_download: no products to download; provide product_ids, "
            "search_results, or odata_filter"
        )
    if max_products:
        products = products[: int(max_products)]

    target_path = (
        Path(target_dir) if str(target_dir or "").strip() else (_default_target_dir())
    )
    result = CdseDownloadResult(use=use_mode, target_dir=str(target_path))
    target_path.mkdir(parents=True, exist_ok=True)
    ok, free_gb = check_disk_space(target_path, min_gb=min_disk_free_gb)
    if not ok:
        raise RuntimeError(
            f"CDSE download aborted: insufficient disk space "
            f"(need >= {min_disk_free_gb:.1f} GB, free {free_gb:.2f} GB)"
        )

    token = bearer_token.strip()
    if not token:
        if not (username.strip() and password.strip()):
            raise ValueError(
                "CDSE download requires credentials: pass username/password "
                "(copernicus portal) or bearer_token; or switch use='legacy' "
                "for public direct links."
            )
        token = exchange_cdse_token(username.strip(), password.strip())

    for product in products:
        filename = product.name.strip() or f"cdse_{product.product_id}.zip"
        target = target_path / filename
        label = product.name.strip() or product.product_id
        try:
            if (
                not force
                and target.exists()
                and target.stat().st_size > 0
                and (
                    product.size_bytes <= 0
                    or target.stat().st_size >= product.size_bytes
                )
            ):
                logger.info("CDSE 目标已存在，跳过: %s", target.name)
                result.skipped += 1
                result.products.append(product)
                continue
            logger.info("CDSE 下载: %s -> %s", label, target)
            size = download_product_value(
                product, target, bearer_token=token, origin=origin
            )
            product.size_bytes = size
            result.products.append(product)
            result.downloaded += 1
            result.downloaded_bytes += size
            logger.info("CDSE 完成: %s (%s)", target.name, format_size(size))
        except Exception as exc:  # noqa: BLE001
            result.failed += 1
            result.errors.append(f"{label}: {exc}")
            logger.warning("CDSE 下载失败 %s: %s", label, exc)

    return result


def _run_legacy(
    legacy_urls: list[str] | str,
    target_path: Path,
    result: CdseDownloadResult,
) -> None:
    """legacy 直链下载（共享续传工具，免 token）。"""
    import requests

    if isinstance(legacy_urls, str):
        urls = [
            u.strip() for u in legacy_urls.replace("\n", ",").split(",") if u.strip()
        ]
    else:
        urls = [str(u).strip() for u in legacy_urls if str(u).strip()]
    if not urls:
        raise ValueError(
            "cdse_download: use='legacy' requires legacy_urls (public direct links)"
        )
    session = requests.Session()
    for i, url in enumerate(urls):
        name = url.rstrip("/").split("?")[0].split("/")[-1] or f"cdse_legacy_{i}.zip"
        target = target_path / name
        try:
            logger.info("CDSE legacy 下载: %s -> %s", url, target)
            if not download_with_retry(session, url, target):
                raise RuntimeError(f"download failed: {url}")
            size = target.stat().st_size if target.exists() else 0
            result.products.append(
                CdseProduct(product_id="", name=name, size_bytes=size)
            )
            result.downloaded += 1
            result.downloaded_bytes += size
        except Exception as exc:  # noqa: BLE001
            result.failed += 1
            result.errors.append(f"{name}: {exc}")
            logger.warning("CDSE legacy 失败 %s: %s", name, exc)


def _default_target_dir() -> Path:
    """独立运行默认目录：``BACKEND_DATA_ROOT`` 派生；test 环境退临时目录。"""
    import os

    root = os.getenv("BACKEND_DATA_ROOT", "").strip()
    if root:
        return Path(root) / "Remote_Sensing" / "Copernicus"
    be = (os.getenv("BACKEND_ENV") or os.getenv("ENVIRONMENT") or "").lower()
    if be in {"test", "testing"}:
        import tempfile

        return Path(tempfile.gettempdir()) / "cgda_cdse_download"
    raise RuntimeError(
        "BACKEND_DATA_ROOT is not set; cannot derive CDSE download target dir. "
        "Set BACKEND_DATA_ROOT or pass target_dir explicitly."
    )
