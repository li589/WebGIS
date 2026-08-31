r"""NCEP NOMADS GRIB2 数据下载模块。

供工作流 ``nomads_grib_download`` 节点调用：按 model/product/cycle/fxx
物化 GFS/GEFS 等 GRIB2 文件（或字段子集）到本地目录。

主路径（``use="auto"``，默认）：``herbie`` 库（参数化检索 + 本地缓存 +
字段子集过滤）。

回退路径（``use="legacy"``）：NOMADS 直连 HTTP（完整 GRIB2 文件或
``cgi-bin/filter_*.pl`` 过滤直链），复用 ``ingest/_http_resume.py``
共享续传工具（Range 续传 + 指数退避；已完整文件经 416 语义自动跳过）。

URL 模板占位符：``{yyyymmdd}``（起报日）、``{hh}``（起报时 UTC 两位）、
``{fxx3}``（预报时效三位）。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from ingest._http_resume import check_disk_space, format_size

logger = logging.getLogger(__name__)

# multi_file: (current, total, downloaded_bytes[, item_name])
MultiFileProgressCb = Callable[[int, int, int, str | None], None] | None
# byte_stream: (downloaded, total_bytes)
ByteStreamProgressCb = Callable[[int, int], None] | None

MIN_DISK_FREE_GB = 5.0
_VALID_USE = frozenset({"auto", "herbie", "legacy"})

try:
    from herbie import Herbie  # type: ignore

    _HAS_HERBIE = True
except ImportError:  # pragma: no cover
    Herbie = None  # type: ignore
    _HAS_HERBIE = False


@dataclass
class NomadsFile:
    """单个 GRIB2 文件描述。"""

    name: str
    path: str
    size_bytes: int = 0
    member: str = ""
    fxx: int = 0


@dataclass
class NomadsDownloadResult:
    """NOMADS 下载任务结果。"""

    model: str = ""
    date: str = ""
    use: str = ""
    files: list[NomadsFile] = field(default_factory=list)
    downloaded: int = 0
    skipped: int = 0
    failed: int = 0
    downloaded_bytes: int = 0
    target_dir: str = ""
    errors: list[str] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return self.failed == 0 and not self.errors


def normalize_cycle(date: str) -> datetime:
    """把 ``YYYY-MM-DD HH:MM``（或 ``latest`` 的当前时刻）规整为 UTC datetime。"""
    text = str(date or "").strip()
    if not text or text.lower() == "latest":
        now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
        return now - timedelta(hours=6)  # 留出 NOMADS 上传延迟
    normalized = text.replace("T", " ").replace("/", "-")
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H", "%Y-%m-%d"):
        try:
            return datetime.strptime(normalized, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    raise ValueError(
        f"nomads_download: invalid date {date!r}; expected 'YYYY-MM-DD HH:MM'"
    )


def expand_url_template(url: str, cycle: datetime, fxx: int) -> str:
    """展开直链模板占位符：``{yyyymmdd}`` / ``{hh}`` / ``{fxx3}``。"""
    return (
        url.replace("{yyyymmdd}", cycle.strftime("%Y%m%d"))
        .replace("{hh}", cycle.strftime("%H"))
        .replace("{fxx3}", f"{fxx:03d}")
        .replace("{fxx2}", f"{fxx:02d}")
    )


def download_via_herbie(
    cycle: datetime,
    *,
    model: str,
    product: str,
    fxx: int,
    member: str,
    search_string: str,
    target_dir: Path,
    overwrite: bool,
) -> Path:
    """主路径：herbie 物化单个 GRIB2（或字段子集），返回本地路径。

    默认源全部失败时（如 RDA 无 .idx 或网络不可达），回退 ``use='aws'``
    重试一次——AWS Open Data 源提供完整 index 且全球可达。
    """
    if not _HAS_HERBIE:
        raise RuntimeError(
            "herbie is not installed; run pip install herbie-data or switch "
            "use='legacy' with NOMADS direct URLs."
        )
    kwargs: dict[str, Any] = {}
    if product.strip():
        kwargs["product"] = product.strip()
    if member.strip():
        kwargs["member"] = member.strip()
    search = search_string.strip() or None
    try:
        h = Herbie(
            date=cycle.strftime("%Y-%m-%d %H:%M"),
            model=model.strip(),
            fxx=int(fxx),
            save_dir=target_dir,
            overwrite=overwrite,
            verbose=False,
            **kwargs,
        )
        return h.download(searchString=search, errors="raise")
    except Exception as first_err:  # noqa: BLE001 — 默认源失败回退 AWS
        logger.warning(
            "NOMADS herbie 默认源失败（%s），回退 use='aws' 重试", first_err
        )
        h = Herbie(
            date=cycle.strftime("%Y-%m-%d %H:%M"),
            model=model.strip(),
            fxx=int(fxx),
            save_dir=target_dir,
            overwrite=overwrite,
            verbose=False,
            use="aws",
            **kwargs,
        )
        return h.download(searchString=search, errors="raise")


def download_via_legacy(
    url: str,
    target: Path,
    *,
    progress_callback: ByteStreamProgressCb = None,
) -> int:
    """回退路径：共享续传工具下载直链，返回文件字节数。"""
    import requests

    from ingest._http_resume import download_with_retry

    session = requests.Session()
    if not download_with_retry(session, url, target, progress_callback=progress_callback):
        raise RuntimeError(f"NOMADS legacy download failed: {url}")
    return target.stat().st_size if target.exists() else 0


def _coerce_fxx_list(fxx: int | list[int] | str) -> list[int]:
    """fxx 参数规整为 int 列表（int / list / 逗号分隔字符串）。"""
    if isinstance(fxx, bool):
        raise ValueError("nomads_download: invalid fxx")
    if isinstance(fxx, int):
        return [fxx]
    if isinstance(fxx, str):
        parts = [p.strip() for p in fxx.split(",") if p.strip()]
        if not parts:
            return [0]
        try:
            return [int(p) for p in parts]
        except ValueError as exc:
            raise ValueError(
                f"nomads_download: invalid fxx {fxx!r} (int or comma-separated ints)"
            ) from exc
    if isinstance(fxx, (list, tuple)):
        try:
            values = [int(v) for v in fxx]  # type: ignore[arg-type]
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"nomads_download: invalid fxx {fxx!r} (int or list of ints)"
            ) from exc
        return values or [0]
    raise ValueError(f"nomads_download: invalid fxx {fxx!r}")


def download_nomads_grib(
    date: str,
    model: str = "gfs",
    *,
    product: str = "",
    fxx: int | list[int] | str = 0,
    search_string: str = "",
    members: list[str] | None = None,
    target_dir: str | Path = "",
    use: str = "auto",
    legacy_url: str = "",
    overwrite: bool = False,
    min_disk_free_gb: float = MIN_DISK_FREE_GB,
    progress_callback: MultiFileProgressCb = None,
    byte_stream_callback: ByteStreamProgressCb = None,
) -> NomadsDownloadResult:
    """下载 NOMADS GRIB2 文件（member × fxx 笛卡尔积）到 ``target_dir``。

    Args:
        date: 起报时间 ``YYYY-MM-DD HH:MM``（或 ``latest``）。
        model: NOMADS 模型（gfs/gefs/gdas/nam/hrrr 等，herbie 命名）。
        product: 产品层级（如 GFS ``pgrb2.0p25``；空则模型默认）。
        fxx: 预报时效（int / list / 逗号分隔字符串）。
        search_string: GRIB 字段子集过滤（herbie searchString，如
            ``:TMP:2 m above ground:``；空则整文件）。
        members: 集合成员列表（GEFS 等；空列表/None 表示确定性预报）。
        target_dir: 本地目标目录（空则 BACKEND_DATA_ROOT 派生，test 环境临时目录）。
        use: ``auto``（默认）/ ``herbie`` / ``legacy``。
        legacy_url: legacy 直链模板（支持 ``{yyyymmdd}/{hh}/{fxx3}`` 占位符）。
        overwrite: 已存在文件是否强制重下。
        min_disk_free_gb: 下载前磁盘可用空间下限。

    Returns:
        NomadsDownloadResult 统计信息。
    """
    cycle = normalize_cycle(date)
    model = str(model or "gfs").strip()
    use_mode = str(use or "auto").strip().lower()
    if use_mode not in _VALID_USE:
        raise ValueError(f"nomads_download: invalid use={use!r} (auto|herbie|legacy)")
    fxx_list = _coerce_fxx_list(fxx)
    member_list = [str(m or "").strip() for m in (members or [])] or [""]

    target_path = Path(target_dir) if str(target_dir).strip() else _default_target_dir()
    result = NomadsDownloadResult(
        model=model,
        date=cycle.strftime("%Y-%m-%d %H:%M"),
        use=use_mode,
        target_dir=str(target_path),
    )

    target_path.mkdir(parents=True, exist_ok=True)
    ok, free_gb = check_disk_space(target_path, min_gb=min_disk_free_gb)
    if not ok:
        raise RuntimeError(
            f"NOMADS download aborted: insufficient disk space "
            f"(need >= {min_disk_free_gb:.1f} GB, free {free_gb:.2f} GB)"
        )

    if use_mode == "legacy":
        if not legacy_url.strip():
            raise ValueError(
                "nomads_download: use='legacy' requires legacy_url template "
                "(full GRIB2 or cgi-bin filter direct link)"
            )
        _run_legacy(
            legacy_url,
            cycle,
            fxx_list,
            target_path,
            result,
            progress_callback=progress_callback,
            byte_stream_callback=byte_stream_callback,
        )
    else:
        if use_mode == "herbie" and not _HAS_HERBIE:
            raise RuntimeError(
                "herbie is not installed but use='herbie' requested; "
                "pip install herbie-data or use legacy_url."
            )
        if not _HAS_HERBIE:
            if not legacy_url.strip():
                raise RuntimeError(
                    "herbie is not installed and no legacy_url provided; "
                    "install herbie-data or supply NOMADS direct URLs."
                )
            logger.warning("未安装 herbie，auto 回退 NOMADS 直连（无字段子集过滤）。")
            result.use = "legacy"
            _run_legacy(
                legacy_url,
                cycle,
                fxx_list,
                target_path,
                result,
                progress_callback=progress_callback,
                byte_stream_callback=byte_stream_callback,
            )
        else:
            _run_herbie(
                cycle,
                model=model,
                product=product,
                fxx_list=fxx_list,
                member_list=member_list,
                search_string=search_string,
                target_path=target_path,
                overwrite=overwrite,
                result=result,
                progress_callback=progress_callback,
            )

    return result


def _default_target_dir() -> Path:
    """独立运行默认目录：``BACKEND_DATA_ROOT`` 派生；test 环境退临时目录。"""
    import os

    root = os.getenv("BACKEND_DATA_ROOT", "").strip()
    if root:
        return Path(root) / "Meteorological" / "Weather" / "NOMADS"
    be = (os.getenv("BACKEND_ENV") or os.getenv("ENVIRONMENT") or "").lower()
    if be in {"test", "testing"}:
        import tempfile

        return Path(tempfile.gettempdir()) / "cgda_nomads_download"
    raise RuntimeError(
        "BACKEND_DATA_ROOT is not set; cannot derive NOMADS download target dir. "
        "Set BACKEND_DATA_ROOT or pass target_dir explicitly."
    )


def _run_herbie(
    cycle: datetime,
    *,
    model: str,
    product: str,
    fxx_list: list[int],
    member_list: list[str],
    search_string: str,
    target_path: Path,
    overwrite: bool,
    result: NomadsDownloadResult,
    progress_callback: MultiFileProgressCb = None,
) -> None:
    total = len(member_list) * len(fxx_list)
    idx = 0
    downloaded_bytes = 0
    for member in member_list:
        for fxx in fxx_list:
            idx += 1
            label = f"model={model} member={member or '-'} fxx={fxx:03d}"
            try:
                logger.info("NOMADS herbie 下载: %s", label)
                local = download_via_herbie(
                    cycle,
                    model=model,
                    product=product,
                    fxx=fxx,
                    member=member,
                    search_string=search_string,
                    target_dir=target_path,
                    overwrite=overwrite,
                )
                size = Path(local).stat().st_size if Path(local).exists() else 0
                result.files.append(
                    NomadsFile(
                        name=Path(local).name,
                        path=str(local),
                        size_bytes=size,
                        member=member,
                        fxx=fxx,
                    )
                )
                result.downloaded += 1
                result.downloaded_bytes += size
                downloaded_bytes += size
                if progress_callback is not None:
                    progress_callback(
                        idx, total, downloaded_bytes, Path(local).name
                    )
                logger.info(
                    "NOMADS herbie 完成: %s (%s)", Path(local).name, format_size(size)
                )
            except Exception as exc:  # noqa: BLE001
                result.failed += 1
                result.errors.append(f"{label}: {exc}")
                logger.warning("NOMADS herbie 失败 %s: %s", label, exc)


def _run_legacy(
    legacy_url: str,
    cycle: datetime,
    fxx_list: list[int],
    target_path: Path,
    result: NomadsDownloadResult,
    *,
    progress_callback: MultiFileProgressCb = None,
    byte_stream_callback: ByteStreamProgressCb = None,
) -> None:
    total = len(fxx_list)
    downloaded_bytes = 0
    for i, fxx in enumerate(fxx_list, start=1):
        url = expand_url_template(legacy_url, cycle, fxx)
        name = url.rstrip("/").split("?")[0].split("/")[-1] or f"nomads_f{fxx:03d}"
        if not Path(name).suffix:
            name = f"{name}_f{fxx:03d}.grib2"
        target = target_path / name
        try:
            logger.info("NOMADS legacy 下载: %s -> %s", url, target)
            size = download_via_legacy(
                url, target, progress_callback=byte_stream_callback
            )
            result.files.append(
                NomadsFile(name=name, path=str(target), size_bytes=size, fxx=fxx)
            )
            result.downloaded += 1
            result.downloaded_bytes += size
            downloaded_bytes += size
            if progress_callback is not None:
                progress_callback(i, total, downloaded_bytes, name)
        except Exception as exc:  # noqa: BLE001
            result.failed += 1
            result.errors.append(f"fxx={fxx:03d}: {exc}")
            logger.warning("NOMADS legacy 失败 fxx=%03d: %s", fxx, exc)
