"""风云卫星数据专用下载模块。

支持多源回退策略：
    - ``nsmc`` — 通过 NSMC 门户 HTTP 下载 FY-3 MWRI HDF 亮温数据
    - ``nas``  — 通过 NAS FileBrowser REST 直连拉取已落盘的 FY3D 数据
    - ``auto`` — 优先 NSMC，失败自动回退 NAS

输出 ``path``（含数据文件的本地目录）和 ``manifest``（ProductManifest），
可直接作为 ``fy_preprocess`` 节点的输入。
"""

from __future__ import annotations

import os
import re
from datetime import date, datetime, timedelta
from pathlib import Path

from contracts.product import ProductManifest, ProductRef
from modules.base import BaseModule
from modules.registry import register_module_decorator
from workflow.schemas import ArtifactRef, NodeExecutionContext, PortSpec

_MAX_RANGE_DAYS = 366


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


class _DownloadError(Exception):
    """Raised when a download source fails."""


# NSMC 单账号限额：HTTP 401/403/429 后进入冷却，期间优先其他账号。
_ACCOUNT_COOLDOWN_SECONDS = 600.0
_account_cooldown_until: dict[str, float] = {}
_ACCOUNT_LIMIT_RE = re.compile(r"\b(401|403|429)\b")


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


def _download_from_nsmc(
    ctx: NodeExecutionContext,
    *,
    satellite: str,
    date_path: str,
    ds: dict[str, object],
    target_dir: Path,
) -> Path:
    """Download FY HDF data from NSMC portal via HttpSource.

    多账号轮换：优先非冷却账号；HTTP 401/403/429（限额/拒绝）标记冷却并
    切换下一账号；全部耗尽抛可诊断错误（auto 模式由上层回退 NAS）。
    鉴权头遵循门户目录 token_header（cma_nsmc 为自定义 ``token`` 头）。
    """
    import time
    from urllib.parse import urljoin

    from data_access.sources.http import HttpSource
    from modules.download_nodes import _resolve_portal_entry

    # open_data_presets 真源：app/services/portal_catalog.py 的 cma_nsmc（base_url）。
    # fallback 仅在 ds 未注入 presets（本地裸跑）时生效，须与真源保持一致。
    ds_presets = ds.get("open_data_presets")
    presets: dict[str, str] = {}
    if isinstance(ds_presets, dict):
        presets = {str(k): str(v) for k, v in ds_presets.items()}
    base = presets.get("cma_nsmc", "https://satellite.nsmc.org.cn/")

    rel = f"{satellite.upper()}/MWRID/{date_path}/"
    url = urljoin(base if base.endswith("/") else base + "/", rel.lstrip("/"))

    nsmc_entry = _resolve_portal_entry(ds, "nsmc") or _resolve_portal_entry(
        ds, "cma_nsmc"
    )
    accounts = _nsmc_accounts(nsmc_entry) if nsmc_entry else []
    if not accounts:
        accounts = [{"username": "", "token": "", "password": ""}]
    token_header = str((nsmc_entry or {}).get("token_header") or "token").strip()

    if ctx.logger_adapter is not None:
        ctx.logger_adapter.emit_stage_start(
            "fy_download:nsmc",
            f"NSMC download ({len(accounts)} account(s)): {url} -> {target_dir}",
        )

    source = HttpSource()
    now = time.monotonic()
    ordered = sorted(
        accounts, key=lambda acc: _account_cooldown_until.get(_account_key(acc), 0.0)
    )
    failures: list[str] = []
    for account in ordered:
        key = _account_key(account)
        cooldown = _account_cooldown_until.get(key, 0.0)
        if cooldown > now:
            failures.append(f"{key}: cooling down ({int(cooldown - now)}s left)")
            continue
        metadata: dict[str, object] = {"force_refresh": False}
        if account["token"]:
            metadata["http_headers"] = {token_header: account["token"]}
        try:
            resource = source.locate(url, metadata=metadata)
            local_path = source.materialize(resource, target_dir=target_dir)
        except Exception as exc:  # noqa: BLE001
            message = str(exc)
            if _ACCOUNT_LIMIT_RE.search(message):
                _account_cooldown_until[key] = (
                    time.monotonic() + _ACCOUNT_COOLDOWN_SECONDS
                )
                failures.append(
                    f"{key}: limited ({message[:160]}; "
                    f"cooldown {int(_ACCOUNT_COOLDOWN_SECONDS)}s)"
                )
                continue
            raise
        if ctx.logger_adapter is not None:
            ctx.logger_adapter.emit_stage_end(
                "fy_download:nsmc",
                f"Downloaded to: {local_path}",
            )
        return (
            Path(local_path.uri.replace("file://", ""))
            if hasattr(local_path, "uri")
            else target_dir
        )

    raise RuntimeError(
        "NSMC all accounts exhausted for "
        f"{url}: {'; '.join(failures) or 'no account available'}"
    )


def _fetch_from_nas(
    ctx: NodeExecutionContext,
    *,
    satellite: str,
    date_path: str,
    ds: dict[str, object],
    target_dir: Path,
) -> Path:
    """从 NAS FileBrowser 直连拉取 FY3D 逐日 MWRI GeoTIFF。

    2026-08-17 实测修正：NAS 侧唯一可用凭据是 FileBrowser profile
    （``nas_profile``，protocol=filebrowser），旧 smb:// RemoteSource 路径因
    协议不匹配永远失败。FileBrowser 目录含 3600+ 文件、列举 >30s 会超时，
    故按既知文件名走 ``GET /api/raw/{path}`` 直连下载（免列举）。
    FY3B 无 2020 年后数据（卫星退役），非 FY3D 直接报错由上层处理。
    """
    from ingest.remote_sync import _filebrowser_download, filebrowser_login
    from modules.download_nodes import _resolve_profile_server_config

    if satellite != "FY3D":
        raise ValueError(
            f"NAS source only holds FY3D daily files (got {satellite}); "
            "FY3B retired in 2020 and has no modern-date data"
        )

    date_ymd = date_path.replace(".", "").replace("-", "")
    remote_dir = (
        str(ds.get("nas_remote_path") or os.getenv("CGDA_FY_NAS_PATH") or "").strip()
        or "/Chenhaojun/Data/fy3dhdf2425"
    )
    # 每日每波段一个文件（FY3D_GBAL_L1_10V_YYYYMMDD_MWRID_0.tif / 10H_…）；
    # omega 反演需 TBv+TBh 双极化，只拉 10H 会导致 fy_daily 缺 V 极化。
    band_names = ("10V", "10H")
    remote_names = tuple(
        f"FY3D_GBAL_L1_{band}_{date_ymd}_MWRID_0.tif" for band in band_names
    )
    profile_id = str(ds.get("nas_profile") or "").strip() or "nas_profile"

    if ctx.logger_adapter is not None:
        ctx.logger_adapter.emit_stage_start(
            "fy_download:nas",
            f"NAS FileBrowser fetch ({profile_id}): "
            f"{remote_dir}/({'+'.join(band_names)})_{date_ymd} -> {target_dir}",
        )

    server = _resolve_profile_server_config(profile_id)
    token = filebrowser_login(server.filebrowser_url, server.username, server.password)

    last_local_path: Path | None = None
    for remote_name in remote_names:
        remote_path = f"{remote_dir.rstrip('/')}/{remote_name}"
        local_path = target_dir / remote_name
        if local_path.exists() and local_path.stat().st_size > 0:
            continue
        ok = _filebrowser_download(
            server.filebrowser_url, token, remote_path, local_path, remote_size=0
        )
        if not ok or not local_path.exists() or local_path.stat().st_size == 0:
            local_path.unlink(missing_ok=True)
            raise RuntimeError(f"NAS FileBrowser download failed: {remote_path}")
        last_local_path = local_path

    if ctx.logger_adapter is not None:
        fetched = ", ".join(str(target_dir / name) for name in remote_names)
        ctx.logger_adapter.emit_stage_end("fy_download:nas", f"Fetched to: {fetched}")
    return last_local_path or (target_dir / remote_names[-1])


@register_module_decorator(name="fy_download")
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
        data_source = str(resolved.get("data_source") or "auto").lower()
        start_date = str(resolved.get("start_date") or "").strip()
        end_date = str(resolved.get("end_date") or "").strip()
        local_dir = str(resolved.get("local_dir") or "").strip()

        if not local_dir:
            local_dir = str(ctx.workspace / "data_access" / "fy_download")
        target_dir = Path(local_dir)
        target_dir.mkdir(parents=True, exist_ok=True)

        days = _iter_date_range(start_date, end_date)
        if not days:
            raise ValueError("fy_download requires start_date")

        sources_to_try: list[str] = []
        if data_source == "nsmc":
            sources_to_try = ["nsmc"]
        elif data_source == "nas":
            sources_to_try = ["nas"]
        else:
            sources_to_try = ["nsmc", "nas"]

        downloaded_days: list[str] = []
        used_sources: set[str] = set()
        for day_index, day in enumerate(days):
            date_path = day.replace("-", ".")
            day_error: Exception | None = None
            day_source = ""
            for source_name in sources_to_try:
                try:
                    if source_name == "nsmc":
                        _download_from_nsmc(
                            ctx,
                            satellite=satellite,
                            date_path=date_path,
                            ds=ds,
                            target_dir=target_dir,
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
                    day_source = source_name
                    day_error = None
                    break
                except Exception as exc:  # noqa: BLE001
                    day_error = exc
                    if ctx.logger_adapter is not None:
                        ctx.logger_adapter.emit_progress(
                            "fy_download",
                            day_index / len(days),
                            f"[{day}] source '{source_name}' failed: {exc}; "
                            "trying next...",
                        )
            if day_error is not None:
                raise RuntimeError(
                    f"fy_download: all sources failed for {day}. "
                    f"Last error: {day_error} "
                    f"(downloaded {len(downloaded_days)}/{len(days)} days)"
                )
            if ctx.logger_adapter is not None:
                ctx.logger_adapter.emit_progress(
                    "fy_download",
                    (day_index + 1) / len(days),
                    f"[{day}] downloaded via {day_source} "
                    f"({day_index + 1}/{len(days)} days)",
                )

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
