"""风云卫星数据专用下载模块。

支持多源回退策略：
    - ``nsmc`` — 通过 NSMC 门户 HTTP 下载 FY-3 MWRI HDF 亮温数据
    - ``nas``  — 通过 SMB/NAS 远程拉取已落盘的 FY 数据
    - ``auto`` — 优先 NSMC，失败自动回退 NAS

输出 ``path``（含 HDF 文件的本地目录）和 ``manifest``（ProductManifest），
可直接作为 ``fy_preprocess`` 节点的输入。
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path

from contracts.product import ProductManifest, ProductRef
from modules.base import BaseModule
from modules.registry import register_module_decorator
from workflow.schemas import ArtifactRef, NodeExecutionContext, PortSpec

_MAX_RANGE_DAYS = 366


def _iter_date_range(start_date: str, end_date: str) -> list[str]:
    """Expand ``start_date``..``end_date`` (inclusive) into ``YYYY-MM-DD`` days.

    Accepts ``YYYY-MM-DD`` or ``YYYY.MM.DD``. Empty ``end_date`` degrades to a
    single-day range (legacy behaviour).
    """
    if not start_date:
        return []

    def _parse(value: str) -> date:
        return datetime.strptime(value.strip().replace(".", "-"), "%Y-%m-%d").date()

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


def _download_from_nsmc(
    ctx: NodeExecutionContext,
    *,
    satellite: str,
    date_path: str,
    ds: dict[str, object],
    target_dir: Path,
) -> Path:
    """Download FY HDF data from NSMC portal via HttpSource."""
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
    metadata: dict[str, object] = {"force_refresh": False}
    if nsmc_entry:
        token = str(nsmc_entry.get("token") or "").strip()
        if token:
            metadata["http_headers"] = {"Authorization": f"Bearer {token}"}

    if ctx.logger_adapter is not None:
        ctx.logger_adapter.emit_stage_start(
            "fy_download:nsmc",
            f"NSMC download: {url} -> {target_dir}",
        )

    source = HttpSource()
    resource = source.locate(url, metadata=metadata)
    local_path = source.materialize(resource, target_dir=target_dir)

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


def _fetch_from_nas(
    ctx: NodeExecutionContext,
    *,
    date_path: str,
    ds: dict[str, object],
    target_dir: Path,
) -> Path:
    """Fetch FY HDF data from NAS via RemoteSource (SMB)."""
    from data_access.sources.remote import RemoteSource

    # 默认 URI 为本实验室 NAS 兜底（ds 未注入 nas_uri 时生效）；
    # 生产经工作流 datasource_selection.nas_uri 或「远程与存储」profile 覆盖。
    nas_uri = ds.get("nas_uri", "")
    if not nas_uri:
        nas_uri = f"smb://nas/Chenhaojun/fy/{date_path}/?cred=nas_profile"

    if ctx.logger_adapter is not None:
        ctx.logger_adapter.emit_stage_start(
            "fy_download:nas",
            f"NAS fetch: {nas_uri} -> {target_dir}",
        )

    source = RemoteSource()
    resource = source.locate(nas_uri)
    local_path = source.materialize(resource, target_dir=target_dir)

    if ctx.logger_adapter is not None:
        ctx.logger_adapter.emit_stage_end(
            "fy_download:nas",
            f"Fetched to: {local_path}",
        )

    return (
        Path(local_path.uri.replace("file://", ""))
        if hasattr(local_path, "uri")
        else target_dir
    )


@register_module_decorator(name="fy_download")
class FYDownloadModule(BaseModule):
    name = "fy_download"
    description = (
        "风云卫星数据专用下载模块：支持 NSMC 门户 HTTP 下载、NAS SMB 远程拉取、"
        "auto 自动回退（NSMC→NAS）。下载 FY-3 MWRI HDF 亮温数据供 fy_preprocess 处理。"
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
