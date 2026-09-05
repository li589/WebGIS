"""风云卫星数据专用下载模块。

支持多源回退策略：
    - ``nsmc`` — 经 NSMC 新门户（DataPortal API）在线下载 FY-3 MWRI HDF 亮温数据
    - ``nas``  — 通过 NAS FileBrowser REST 直连拉取已落盘的 FY3D/FY3F 数据
    - ``auto`` — 优先 NSMC，失败自动回退 NAS

输出 ``path``（含数据文件的本地目录）和 ``manifest``（ProductManifest），
可直接作为 ``fy_preprocess`` 节点的输入。
"""

from __future__ import annotations

import contextlib
import os
import re
import time
from datetime import date, datetime, timedelta
from pathlib import Path

from contracts.product import ProductManifest, ProductRef
from modules.base import BaseModule
from modules.registry import register_module_decorator
from utils.request_time import resolve_time_bounds
from workflow.schemas import ArtifactRef, NodeExecutionContext, PortSpec

_MAX_RANGE_DAYS = 366
_HDF_SUFFIXES = {".hdf", ".h5", ".he5"}


def _coerce_byte_count(raw: object) -> int | None:
    """把 NSMC ``DATASIZE`` 等字段规整为正整数字节数；无法解析则返回 None。"""
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        n = int(raw)
        return n if n > 0 else None
    text = str(raw).strip().replace(",", "")
    if not text:
        return None
    match = re.fullmatch(r"([0-9]*\.?[0-9]+)\s*([KMGT]?B)?", text, flags=re.IGNORECASE)
    if match is None:
        try:
            n = int(float(text))
        except ValueError:
            return None
        return n if n > 0 else None
    value = float(match.group(1))
    unit = (match.group(2) or "B").upper()
    mult = {
        "": 1,
        "B": 1,
        "KB": 1024,
        "MB": 1024**2,
        "GB": 1024**3,
        "TB": 1024**4,
    }.get(unit, 1)
    n = int(value * mult)
    return n if n > 0 else None


def _nsmc_expected_bytes(item: dict[str, object]) -> int | None:
    for key in ("DATASIZE", "datasize", "FILESIZE", "filesize", "SIZE", "size"):
        parsed = _coerce_byte_count(item.get(key))
        if parsed is not None:
            return parsed
    return None


def _probe_h5_dataset(ds: object) -> None:
    """强制读一格；h5py Dataset 无 ``.flat``，按 ndim 取首元素。"""
    size = int(getattr(ds, "size", 0) or 0)
    if size <= 0:
        return
    ndim = int(getattr(ds, "ndim", 0) or 0)
    if ndim <= 0:
        _ = ds[()]  # type: ignore[index]
    else:
        _ = ds[tuple(0 for _ in range(ndim))]  # type: ignore[index]


def _hdf_file_readable(path: Path) -> bool:
    """轻量 HDF5 可读校验：打开根组；若有 MWRI 亮温数据集则读一格。"""
    try:
        import h5py
    except ImportError:
        return True  # 无 h5py 时不阻断下载主链
    path_str = str(path)
    try:
        if not h5py.is_hdf5(path_str):
            return False
        with h5py.File(path_str, "r") as handle:
            _ = list(handle.keys())[:1]
            # 截断文件常在 open 后读数据才暴露（与 GDAL translate_tb_vrt 同失败面）
            for ds_path in (
                "Calibration/EARTH_OBSERVE_BT_10_to_89GHz",
                "EARTH_OBSERVE_BT_10_to_89GHz",
            ):
                if ds_path not in handle:
                    continue
                _probe_h5_dataset(handle[ds_path])
                break
        return True
    except (OSError, ValueError, TypeError, KeyError, AttributeError, IndexError):
        return False


def _local_download_ok(path: Path, *, expected_bytes: int | None = None) -> bool:
    """本地成品是否可跳过重下：非空 +（可选）字节数一致 + HDF 可读。"""
    try:
        if not path.is_file():
            return False
        size = path.stat().st_size
    except OSError:
        return False
    if size <= 0:
        return False
    if expected_bytes is not None and size != expected_bytes:
        return False
    if path.suffix.lower() in _HDF_SUFFIXES:
        return _hdf_file_readable(path)
    return True


def _unlink_incomplete(path: Path) -> None:
    with contextlib.suppress(OSError):
        path.unlink(missing_ok=True)


def _purge_incomplete_orbit_hdf(target_dir: Path, day_ymd: str) -> list[str]:
    """删除 ``target_dir`` 下某日所有不可读的轨道 HDF。

    ``fy_download`` 每日仅校验 NSMC 检索到的 ``max_files_per_day`` 个文件，
    但 ``fy_preprocess`` / ``fy_plan`` 会拼接该日目录内**全部** ``.HDF``。历史半截
    轨道若不清理，会在 ``translate_tb_vrt`` 以 truncated HDF5 炸掉整条链。
    """
    if not target_dir.is_dir() or not day_ymd:
        return []
    removed: list[str] = []
    for path in sorted(target_dir.iterdir()):
        if not path.is_file():
            continue
        if path.suffix.lower() not in _HDF_SUFFIXES:
            continue
        if day_ymd not in path.name:
            continue
        if _local_download_ok(path):
            continue
        _unlink_incomplete(path)
        removed.append(path.name)
    return removed


def _iter_date_range(start_date: str, end_date: str) -> list[str]:
    """Expand ``start_date``..``end_date`` (inclusive) into ``YYYY-MM-DD`` days.

    Accepts ``YYYY-MM-DD`` / ``YYYY.MM.DD`` / ``YYYYMMDD``（节点模板与种子
    ``{YYYYMMDD}`` 占位符展开后为紧凑格式）。Empty ``end_date`` degrades to a
    single-day range (legacy behaviour).
    """
    if not start_date:
        return []

    def _parse(value: str) -> date:
        v = value.strip()
        if len(v) == 8 and v.isdigit():
            return datetime.strptime(v, "%Y%m%d").date()
        return datetime.strptime(v.replace(".", "-"), "%Y-%m-%d").date()

    start = _parse(start_date)
    end = _parse(end_date) if end_date else start
    if end < start:
        raise ValueError(
            f"fy_download: end_date ({end.isoformat()}) is before "
            f"start_date ({start.isoformat()})"
        )
    days = (end - start).days + 1
    if days > _MAX_RANGE_DAYS:
        raise ValueError(
            f"fy_download: date range spans {days} days "
            f"(max {_MAX_RANGE_DAYS}); refusing bulk download"
        )
    return [(start + timedelta(days=i)).isoformat() for i in range(days)]


def _store_path_manifest(
    ctx: NodeExecutionContext,
    *,
    module_name: str,
    path: str | Path,
    product_type: str,
    extra: dict[str, object] | None = None,
) -> dict[str, object]:
    path_str = str(path)
    manifest = ProductManifest(
        job_id=ctx.request.job_id,
        run_id=ctx.runtime_context.run_id,
        products=[
            ProductRef(
                name=Path(path_str).name or module_name,
                type=product_type,
                uri=path_str,
                variable=None,
                tags={"module": module_name},
            )
        ],
        main_layers=[],
        metadata_uri=None,
        extra={"module_name": module_name, "path": path_str, **(extra or {})},
    )
    artifact = ArtifactRef(
        artifact_id=f"{ctx.runtime_context.run_id}:{ctx.node_id}:manifest",
        artifact_type="product_manifest",
        format="python_object",
        uri=None,
        producer_node_id=ctx.node_id,
        schema_name="ProductManifest",
        metadata={"module_name": module_name},
    )
    ctx.artifact_store.put(artifact, payload=manifest)
    return {"manifest": artifact, "path": path_str}


# NSMC 单账号限额/频控：HTTP 401/403/429、门户中文频控提示或英文提示后进入冷却。
_ACCOUNT_COOLDOWN_SECONDS = 600.0
_account_cooldown_until: dict[str, float] = {}
_ACCOUNT_LIMIT_RE = re.compile(
    r"\b(401|403|429)\b|频率过于频繁|下载频繁|too often|rate.?limit", re.IGNORECASE
)


def _nsmc_accounts(entry: dict[str, object]) -> list[dict[str, str]]:
    """门户 entry → 账号列表（accounts 多账号优先，单凭据视作单元素）。"""
    accounts: list[dict[str, str]] = []
    raw_accounts = entry.get("accounts")
    if isinstance(raw_accounts, list):
        for item in raw_accounts:
            if not isinstance(item, dict):
                continue
            acc = {
                key: str(item.get(key) or "").strip()
                for key in ("username", "token", "password")
            }
            if acc["token"] or (acc["username"] and acc["password"]):
                accounts.append(acc)
    if not accounts:
        token = str(entry.get("token") or entry.get("access_token") or "").strip()
        password = str(entry.get("password") or entry.get("secret") or "").strip()
        username = str(entry.get("username") or "").strip()
        if token or (username and password):
            accounts.append(
                {"username": username, "token": token, "password": password}
            )
    return accounts


def _account_key(account: dict[str, str]) -> str:
    return account["token"] or account["username"] or "anonymous"


def _parse_int_param(
    resolved: dict[str, object], key: str, default: int, *, minimum: int | None = None
) -> int:
    """解析整型节点参数：None/缺失/非法回退默认值（显式 0 保留）。"""
    raw = resolved.get(key)
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    if minimum is not None and value < minimum:
        return default
    return value


def _parse_float_param(
    resolved: dict[str, object],
    key: str,
    default: float,
    *,
    minimum: float | None = None,
) -> float:
    """解析浮点节点参数：None/缺失/非法回退默认值（显式 0 保留）。"""
    raw = resolved.get(key)
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return default
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return default
    if minimum is not None and value < minimum:
        return default
    return value


def _nsmc_session_file() -> Path | None:
    """NSMC 会话持久化路径（工作流节点与 Tools/nsmc_online_probe.py 共享）。

    优先级：``CGDA_NSMC_SESSION_FILE`` > ``<BACKEND_DATA_ROOT>/_runtime/cache/
    nsmc_session.json`` > 不持久化（每次运行重新登录）。
    """
    explicit = os.getenv("CGDA_NSMC_SESSION_FILE", "").strip()
    if explicit:
        return Path(explicit)
    data_root = os.getenv("BACKEND_DATA_ROOT", "").strip()
    if data_root:
        return Path(data_root) / "_runtime" / "cache" / "nsmc_session.json"
    return None


def _download_from_nsmc(
    ctx: NodeExecutionContext,
    *,
    satellite: str,
    date_path: str,
    ds: dict[str, object],
    target_dir: Path,
    orbit_mode: str = "MWRID",
    max_files_per_day: int = 2,
    download_interval: float = 5.0,
) -> Path:
    """经 NSMC 新门户（DataPortal API）在线下载当日 MWRI 轨道 HDF。

    2026-08-20 重写：旧 ``{base}/{SAT}/MWRID/{date}/`` 直链已 404（旧
    PortalSite asmx 同步废弃）。新链路 = RSA 登录（fy4 center，验证码）→
    tokensync 跨域会话 → subfile 检索 → POST 表单直下（详见
    ``ingest/nsmc_portal.py`` 模块文档）。

    账号限额保护：
    - 单账号默认每日每产品只拉 ``max_files_per_day`` 个轨道文件（防频控），
      种子/algorithm_params 可覆盖；
    - 下载请求按 ``download_interval`` 秒节流；
    - HTTP 401/403/429 或频控错误 → 账号进入 600s 冷却并切换下一账号
      （auto 模式由上层回退 NAS）。
    """
    from ingest.nsmc_portal import (
        NSMC_PRODUCT_TEMPLATES,
        NsmcCaptchaRequired,
        NsmcDownloadError,
        NsmcPortalClient,
    )
    from modules.download_nodes import (
        _make_multi_file_progress_cb,
        _resolve_portal_entry,
    )

    template = NSMC_PRODUCT_TEMPLATES.get((satellite, orbit_mode))
    if template is None:
        raise ValueError(
            f"NSMC online 暂不支持 {satellite}/{orbit_mode}；"
            f"可用组合: {sorted(NSMC_PRODUCT_TEMPLATES)}"
        )

    day = date_path.replace(".", "-")
    day_ymd = day.replace("-", "")
    purged = _purge_incomplete_orbit_hdf(target_dir, day_ymd)
    if purged and ctx.logger_adapter is not None:
        ctx.logger_adapter.emit_warning(
            "fy_download",
            f"purged {len(purged)} incomplete orbit HDF for {day_ymd}: "
            + ", ".join(purged[:5])
            + ("…" if len(purged) > 5 else ""),
        )
    nsmc_entry = _resolve_portal_entry(ds, "nsmc") or _resolve_portal_entry(
        ds, "cma_nsmc"
    )
    accounts = _nsmc_accounts(nsmc_entry) if nsmc_entry else []
    if not accounts:
        raise NsmcDownloadError(
            "NSMC 在线下载需要门户凭据（portal entry 'cma_nsmc' accounts），"
            "请在前端设置页配置"
        )
    session_file = _nsmc_session_file()

    if ctx.logger_adapter is not None:
        ctx.logger_adapter.emit_stage_start(
            "fy_download:nsmc",
            f"NSMC online ({len(accounts)} account(s), "
            f"max {max_files_per_day} files/day): "
            f"{satellite}/{orbit_mode} {day} -> {target_dir}",
        )

    # 阶段进度：NSMC 登录/检索/整包 resp.read() 期间原先无事件，UI 会长时间停在 0%。
    # 本路径在会话、检索与每个文件开始前 emit；字节级流式进度留待后续。
    def _nsmc_phase(message: str, progress: float = 0.0, **extra: object) -> None:
        if ctx.logger_adapter is None:
            return
        ctx.logger_adapter.emit_progress(
            "fy_download:nsmc",
            progress,
            message,
            {"phase": "nsmc_wait", **extra},
        )

    now = time.monotonic()
    ordered = sorted(
        accounts, key=lambda acc: _account_cooldown_until.get(_account_key(acc), 0.0)
    )
    failures: list[str] = []
    last_error: Exception | None = None
    for account in ordered:
        key = _account_key(account)
        cooldown = _account_cooldown_until.get(key, 0.0)
        if cooldown > now:
            left = int(cooldown - now)
            failures.append(f"{key}: cooling down ({left}s left)")
            _nsmc_phase(
                f"跳过冷却中账号 {key}（剩余 {left}s）",
                0.0,
                account=key,
                cooldown_left_s=left,
            )
            continue
        client = NsmcPortalClient(
            session_file=session_file,
            username=account["username"],
            password=account["password"] or account["token"],
            download_interval=download_interval,
        )
        try:
            _nsmc_phase(f"校验/登录 NSMC 会话（账号 {key}）…", 0.0, account=key)
            client.ensure_session()
            _nsmc_phase(
                f"检索 NSMC 目录 {satellite}/{orbit_mode} {day}…",
                0.02,
                account=key,
            )
            files = client.search_daily_files(
                template, day, max_files=max_files_per_day
            )
        except NsmcCaptchaRequired as exc:
            # 验证码依赖人工预热，不属于账号问题：直接抛可诊断错误
            raise ValueError(
                f"NSMC 需要验证码登录且无自动识别能力。请先执行 "
                f"Tools/nsmc_online_probe.py prepare && login --code <验证码> "
                f"预热共享会话（{session_file}）后重试。原因: {exc}"
            ) from exc
        except NsmcDownloadError as exc:
            message = str(exc)
            if _ACCOUNT_LIMIT_RE.search(message):
                _account_cooldown_until[key] = (
                    time.monotonic() + _ACCOUNT_COOLDOWN_SECONDS
                )
                failures.append(
                    f"{key}: limited ({message[:160]}; "
                    f"cooldown {int(_ACCOUNT_COOLDOWN_SECONDS)}s)"
                )
                last_error = exc
                continue
            raise

        if not files:
            raise NsmcDownloadError(
                f"NSMC {satellite}/{orbit_mode} {day} 无匹配文件"
                f"（template={template}）"
            )

        total_files = min(len(files), max_files_per_day)
        _progress_cb = _make_multi_file_progress_cb(
            ctx.logger_adapter, "fy_download:nsmc"
        )
        downloaded: list[str] = []
        skipped: list[str] = []
        downloaded_bytes = 0
        try:
            for i, item in enumerate(files[:max_files_per_day], start=1):
                filename = str(item["ARCHIVENAME"])
                dest = target_dir / filename
                expected = _nsmc_expected_bytes(item)
                if _local_download_ok(dest, expected_bytes=expected):
                    skipped.append(filename)
                    downloaded.append(filename)
                    _progress_cb(
                        i, total_files, downloaded_bytes, filename, skipped=True
                    )
                    continue
                # 不完整/损坏的成品删掉后再下，避免永久跳过
                _unlink_incomplete(dest)
                # 传输开始前先报一次，避免整包 resp.read() 期间 UI 卡在上一阶段 0%
                start_frac = (i - 1) / total_files if total_files else 0.0
                _nsmc_phase(
                    f"开始下载文件 {i}/{total_files} · {filename}",
                    start_frac,
                    account=key,
                    current_item_name=filename,
                    downloaded_items=i - 1,
                    total_items=total_files,
                )
                _progress_cb(i - 1, total_files, downloaded_bytes, filename)
                client.download_file(
                    filename, dest, center_flag=str(item.get("CNETERFLAG") or "1")
                )
                if not _local_download_ok(dest, expected_bytes=expected):
                    actual = dest.stat().st_size if dest.exists() else 0
                    _unlink_incomplete(dest)
                    detail = (
                        f" expected={expected} actual={actual}"
                        if expected is not None
                        else f" actual={actual}"
                    )
                    raise NsmcDownloadError(
                        f"NSMC 下载后校验失败（大小/HDF 不可读）: {filename}{detail}"
                    )
                downloaded.append(filename)
                downloaded_bytes += dest.stat().st_size
                _progress_cb(i, total_files, downloaded_bytes, filename)
        except NsmcDownloadError as exc:
            message = str(exc)
            if _ACCOUNT_LIMIT_RE.search(message):
                _account_cooldown_until[key] = (
                    time.monotonic() + _ACCOUNT_COOLDOWN_SECONDS
                )
                failures.append(f"{key}: limited during download ({message[:160]})")
                last_error = exc
                continue
            raise

        if ctx.logger_adapter is not None:
            n_skip = len(skipped)
            n_new = len(downloaded) - n_skip
            ctx.logger_adapter.emit_stage_end(
                "fy_download:nsmc",
                f"Downloaded {n_new} file(s), skipped {n_skip}: "
                + ", ".join(downloaded[:5]),
            )
        return target_dir

    raise RuntimeError(
        "NSMC all accounts exhausted for "
        f"{satellite}/{orbit_mode} {day}: "
        + ("; ".join(failures) or f"last error: {last_error}" or "no account available")
    )


def _fetch_fy3f_tif_fallback(
    ctx: NodeExecutionContext,
    *,
    server,
    token: str,
    remote_dir: str,
    date_ymd: str,
    target_dir: Path,
) -> Path:
    """FY3F 合并 HDF 缺失时的单极化 TIF 对回退（10V + 10H）。

    NAS 3Ffinal 目录同时存在 FY3F_GBAL_L1_10V/10H_YYYYMMDD_ORBA_0.tif
    逐日单极化文件（与 fy.py 的 ``*.tif`` 回退分支输入契约一致）。
    """
    from ingest.remote_sync import _filebrowser_download
    from modules.download_nodes import (
        _emit_download_progress,
        _make_multi_file_progress_cb,
    )

    bands = ("10V", "10H")
    _progress_cb = _make_multi_file_progress_cb(ctx.logger_adapter, "fy_download:nas")
    if ctx.logger_adapter is not None:
        _emit_download_progress(
            ctx.logger_adapter,
            "fy_download:nas",
            0.0,
            f"FY3F 合并 HDF 缺失，回退单极化 TIF 对: {remote_dir} ({date_ymd})",
            {
                "download_mode": "multi_file",
                "downloaded_items": 0,
                "total_items": len(bands),
                "downloaded_bytes": 0,
                "phase": "downloading",
                "items_display": "filename",
            },
        )
    last_local: Path | None = None
    downloaded_bytes = 0
    for i, band in enumerate(bands, start=1):
        remote_name = f"FY3F_GBAL_L1_{band}_{date_ymd}_ORBA_0.tif"
        remote_path = f"{remote_dir.rstrip('/')}/{remote_name}"
        local_path = target_dir / remote_name
        if local_path.exists() and local_path.stat().st_size > 0:
            if _local_download_ok(local_path):
                _progress_cb(i, len(bands), downloaded_bytes, remote_name, skipped=True)
                last_local = local_path
                continue
            _unlink_incomplete(local_path)
        ok = _filebrowser_download(
            server.filebrowser_url, token, remote_path, local_path, remote_size=0
        )
        if not ok or not _local_download_ok(local_path):
            _unlink_incomplete(local_path)
            raise RuntimeError(f"NAS FileBrowser download failed: {remote_path}")
        downloaded_bytes += local_path.stat().st_size
        _progress_cb(i, len(bands), downloaded_bytes, remote_name)
        last_local = local_path
    if last_local is None:
        raise RuntimeError(f"NAS FY3F TIF 回退亦无文件: {remote_dir} ({date_ymd})")
    return last_local


def _fetch_from_nas(
    ctx: NodeExecutionContext,
    *,
    satellite: str,
    date_path: str,
    ds: dict[str, object],
    target_dir: Path,
) -> Path:
    """从 NAS FileBrowser 直连拉取 FY3D/FY3F 逐日数据（免目录列举）。

    2026-08-17 实测修正：NAS 侧唯一可用凭据是 FileBrowser profile
    （``nas_profile``，protocol=filebrowser），旧 smb:// RemoteSource 路径因
    协议不匹配永远失败。FileBrowser 目录含 3600+ 文件、列举 >30s 会超时，
    故按既知文件名走 ``GET /api/raw/{path}`` 直连下载（免列举）。

    2026-08-20 扩展 FY3F：NAS ``/Chenhaojun/Data/3Ffinal`` 实测有 224 天
    （2023-12-01..2024-08-09）逐日双极化合并 HDF
    （``FY3F_GBAL_L1_ORBA_10V10H_YYYYMMDD_ORBA.hdf``，TBv+TBh 单文件），
    命名与 ingest/fy.py 的 HDF 轨道识别（ORBA 升轨 + 8 位日期 + FY3F）
    兼容，可直接供 fy_preprocess 消费；HDF 缺失时回退 10H/10V 单极化
    TIF 对。FY3B 无 2020 年后数据（卫星退役）。
    """
    from ingest.remote_sync import _filebrowser_download, filebrowser_login
    from modules.download_nodes import _resolve_profile_server_config

    date_ymd = date_path.replace(".", "").replace("-", "")
    purged = _purge_incomplete_orbit_hdf(target_dir, date_ymd)
    if purged and ctx.logger_adapter is not None:
        ctx.logger_adapter.emit_warning(
            "fy_download",
            f"purged {len(purged)} incomplete orbit HDF for {date_ymd}: "
            + ", ".join(purged[:5])
            + ("…" if len(purged) > 5 else ""),
        )

    # 按卫星分派（远端目录, 逐日既知文件名）——免列举直连。
    if satellite == "FY3D":
        remote_dir = (
            str(
                ds.get("nas_remote_path") or os.getenv("CGDA_FY_NAS_PATH") or ""
            ).strip()
            or "/Chenhaojun/Data/fy3dhdf2425"
        )
        # 每日每波段一个文件（FY3D_GBAL_L1_10V_YYYYMMDD_MWRID_0.tif / 10H_…）；
        # omega 反演需 TBv+TBh 双极化，只拉 10H 会导致 fy_daily 缺 V 极化。
        band_names = ("10V", "10H")
        remote_names = tuple(
            f"FY3D_GBAL_L1_{band}_{date_ymd}_MWRID_0.tif" for band in band_names
        )
    elif satellite == "FY3F":
        remote_dir = (
            str(
                ds.get("nas_remote_path") or os.getenv("CGDA_FY3F_NAS_PATH") or ""
            ).strip()
            or "/Chenhaojun/Data/3Ffinal"
        )
        band_names = ("10V10H",)
        remote_names = (f"FY3F_GBAL_L1_ORBA_10V10H_{date_ymd}_ORBA.hdf",)
    else:
        raise ValueError(
            f"NAS source only holds FY3D/FY3F daily files (got {satellite}); "
            "FY3B retired in 2020; 其它卫星请经 NSMC 在线或本地目录供给"
        )
    # NAS FileBrowser profile：dataset 配置可经 nas_profile 覆盖；默认对齐
    # 「远程与存储」面板实际登记的 profile_id（nas-filebrowser，2026-08-21
    # 实测旧默认 "nas_profile" 在凭据库中不存在，导致 NSMC 回退 NAS 恒失败）。
    profile_id = str(ds.get("nas_profile") or "").strip() or "nas-filebrowser"

    if ctx.logger_adapter is not None:
        ctx.logger_adapter.emit_stage_start(
            "fy_download:nas",
            f"NAS FileBrowser fetch ({profile_id}): "
            f"{remote_dir}/({'+'.join(band_names)})_{date_ymd} -> {target_dir}",
        )

    server = _resolve_profile_server_config(profile_id)
    token = filebrowser_login(server.filebrowser_url, server.username, server.password)

    from modules.download_nodes import (
        _make_multi_file_progress_cb,
        _make_skip_complete_emit,
    )

    total_files = len(remote_names)
    _progress_cb = _make_multi_file_progress_cb(ctx.logger_adapter, "fy_download:nas")
    downloaded_bytes = 0

    last_local_path: Path | None = None
    done_count = 0
    for remote_name in remote_names:
        remote_path = f"{remote_dir.rstrip('/')}/{remote_name}"
        local_path = target_dir / remote_name
        if _local_download_ok(local_path):
            done_count += 1
            _progress_cb(
                done_count, total_files, downloaded_bytes, remote_name, skipped=True
            )
            last_local_path = local_path
            continue
        _unlink_incomplete(local_path)
        ok = _filebrowser_download(
            server.filebrowser_url, token, remote_path, local_path, remote_size=0
        )
        if not ok or not _local_download_ok(local_path):
            _unlink_incomplete(local_path)
            if satellite == "FY3F" and remote_name.endswith(".hdf"):
                last_local_path = _fetch_fy3f_tif_fallback(
                    ctx,
                    server=server,
                    token=token,
                    remote_dir=remote_dir,
                    date_ymd=date_ymd,
                    target_dir=target_dir,
                )
                break
            raise RuntimeError(
                f"NAS FileBrowser download failed: {remote_path}. "
                "The requested date/file may not be available on NAS; "
                "verify the FY3D archive date and NAS path before retrying."
            )
        done_count += 1
        downloaded_bytes += local_path.stat().st_size
        _progress_cb(done_count, total_files, downloaded_bytes, remote_name)
        last_local_path = local_path

    if done_count == 0 and total_files > 0 and ctx.logger_adapter is not None:
        _make_skip_complete_emit(
            ctx.logger_adapter,
            "fy_download:nas",
            total=total_files,
            skipped=total_files,
        )

    if ctx.logger_adapter is not None:
        fetched = ", ".join(str(target_dir / name) for name in remote_names)
        ctx.logger_adapter.emit_stage_end("fy_download:nas", f"Fetched to: {fetched}")
    return last_local_path or (target_dir / remote_names[-1])


@register_module_decorator(name="fy_download", template_overrides={"phase": "download"})
class FYDownloadModule(BaseModule):
    name = "fy_download"
    description = (
        "风云卫星数据专用下载模块：支持 NSMC 门户 HTTP 下载、NAS FileBrowser 直连拉取、"
        "auto 自动回退（NSMC→NAS）。下载 FY-3 MWRI 亮温数据供 fy_preprocess 处理。"
    )
    input_ports = [
        PortSpec(
            name="datasource_selection",
            kind="config",
            data_class="dict",
            required=False,
        ),
        PortSpec(
            name="algorithm_params", kind="config", data_class="dict", required=False
        ),
    ]
    output_ports = [
        PortSpec(name="path", kind="value", data_class="string"),
        PortSpec(name="manifest", kind="artifact", data_class="product_manifest"),
    ]
    default_params: dict[str, object] = {
        "satellite": "FY3D",
        "data_source": "auto",
        "start_date": "",
        "end_date": "",
        "local_dir": "",
        "band_ids": [1, 2],
        "orbit_mode": "MWRID",
        # NSMC 在线限额保护（详见 _download_from_nsmc docstring）
        "max_files_per_day": 2,
        "download_interval": 5.0,
    }

    def execute(
        self,
        inputs: dict[str, object],
        params: dict[str, object],
        ctx: NodeExecutionContext,
    ) -> dict[str, object]:
        ds = dict(inputs.get("datasource_selection", {}))
        ap = dict(inputs.get("algorithm_params", {}))
        resolved = {**self.default_params, **params, **ap, **ds}

        satellite = str(resolved.get("satellite") or "FY3D").upper()
        # 简写别名归一（fy_platform 风格 "3F" → "FY3F"）
        if satellite == "3B":
            satellite = "FY3B"
        elif satellite == "3D":
            satellite = "FY3D"
        elif satellite == "3F":
            satellite = "FY3F"
        data_source = str(resolved.get("data_source") or "auto").lower()
        start_date = str(resolved.get("start_date") or "").strip()
        end_date = str(resolved.get("end_date") or "").strip()
        local_dir = str(resolved.get("local_dir") or "").strip()

        # 分析框/图层提交常只带 job_request.time_range，种子节点未注入 start_date。
        # 与 fy_daily 对齐：缺参时从 time_range 回填，避免误报 requires start_date
        # 并被 HTTP 500 打成 transient_upstream 空转重试。
        if not start_date:
            try:
                start_dt, end_dt = resolve_time_bounds(
                    time_range=ctx.request.time_range,
                    algorithm_params=ap,
                    module_label="fy_download",
                )
                start_date = start_dt.strftime("%Y%m%d")
                end_date = end_date or end_dt.strftime("%Y%m%d")
            except ValueError as exc:
                raise ValueError(
                    "fy_download requires start_date "
                    "(set algorithm_params.start_date or job_request.time_range); "
                    f"{exc}"
                ) from exc

        if not local_dir:
            local_dir = str(ctx.workspace / "data_access" / "fy_download")
        target_dir = Path(local_dir)
        target_dir.mkdir(parents=True, exist_ok=True)

        days = _iter_date_range(start_date, end_date)
        if not days:
            raise ValueError(
                "fy_download requires start_date "
                "(set algorithm_params.start_date or job_request.time_range)"
            )

        orbit_mode = str(resolved.get("orbit_mode") or "MWRID").upper()
        # NSMC 账号限额保护：默认每日仅拉 2 个轨道文件（防频控），可经
        # 种子/algorithm_params 覆盖；下载请求节流间隔默认 5s（显式 0
        # 表示不节流，不被默认值短路覆盖）。
        max_files_per_day = _parse_int_param(resolved, "max_files_per_day", 2)
        download_interval = _parse_float_param(
            resolved, "download_interval", 5.0, minimum=0.0
        )

        sources_to_try: list[str] = []
        if data_source == "nsmc":
            sources_to_try = ["nsmc"]
        elif data_source == "nas":
            sources_to_try = ["nas"]
        else:
            sources_to_try = ["nsmc", "nas"]

        downloaded_days: list[str] = []
        used_sources: set[str] = set()
        from modules.download_nodes import (
            _emit_download_progress,
            _make_multi_file_progress_cb,
        )

        total_days = len(days)
        _day_cb = _make_multi_file_progress_cb(ctx.logger_adapter, "fy_download")
        for day_index, day in enumerate(days):
            date_path = day.replace("-", ".")
            day_error: Exception | None = None
            for source_name in sources_to_try:
                try:
                    if source_name == "nsmc":
                        _download_from_nsmc(
                            ctx,
                            satellite=satellite,
                            date_path=date_path,
                            ds=ds,
                            target_dir=target_dir,
                            orbit_mode=orbit_mode,
                            max_files_per_day=max_files_per_day,
                            download_interval=download_interval,
                        )
                    else:
                        _fetch_from_nas(
                            ctx,
                            satellite=satellite,
                            date_path=date_path,
                            ds=ds,
                            target_dir=target_dir,
                        )
                    downloaded_days.append(day)
                    used_sources.add(source_name)
                    day_error = None
                    break
                except Exception as exc:  # noqa: BLE001
                    day_error = exc
                    if ctx.logger_adapter is not None:
                        _emit_download_progress(
                            ctx.logger_adapter,
                            "fy_download",
                            day_index / total_days if total_days else 0.0,
                            f"[{day}] source '{source_name}' failed: {exc}; "
                            "trying next...",
                            {
                                "download_mode": "multi_file",
                                "downloaded_items": day_index,
                                "total_items": total_days,
                                "downloaded_bytes": 0,
                                "phase": "downloading",
                                "items_display": "filename",
                                "current_item_name": day,
                            },
                        )
            if day_error is not None:
                raise RuntimeError(
                    f"fy_download: all sources failed for {day}. "
                    f"Last error: {day_error} "
                    f"(downloaded {len(downloaded_days)}/{len(days)} days)"
                )
            _day_cb(day_index + 1, total_days, 0, day)

        return _store_path_manifest(
            ctx,
            module_name=self.name,
            path=target_dir,
            product_type="fy_download_dir",
            extra={
                "satellite": satellite,
                "data_source": "+".join(s for s in sources_to_try if s in used_sources),
                "start_date": days[0],
                "end_date": days[-1],
                "dates": downloaded_days,
                "day_count": len(downloaded_days),
                "local_dir": str(target_dir),
            },
        )
