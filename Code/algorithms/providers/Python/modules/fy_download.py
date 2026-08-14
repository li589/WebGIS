"""风云卫星数据专用下载模块。

支持多源回退策略：
    - ``nsmc`` — 通过 NSMC 门户 HTTP 下载 FY-3 MWRI HDF 亮温数据
    - ``nas``  — 通过 SMB/NAS 远程拉取已落盘的 FY 数据
    - ``auto`` — 优先 NSMC，失败自动回退 NAS

输出 ``path``（含 HDF 文件的本地目录）和 ``manifest``（ProductManifest），
可直接作为 ``fy_preprocess`` 节点的输入。
"""

from __future__ import annotations

from pathlib import Path

from contracts.product import ProductManifest, ProductRef
from modules.base import BaseModule
from modules.registry import register_module_decorator
from workflow.schemas import ArtifactRef, NodeExecutionContext, PortSpec


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

    ds_presets = ds.get("open_data_presets")
    presets: dict[str, str] = {}
    if isinstance(ds_presets, dict):
        presets = {str(k): str(v) for k, v in ds_presets.items()}
    base = presets.get("cma_nsmc", "https://satellite.nsmc.org.cn/")

    rel = f"{satellite.upper()}/MWRID/{date_path}/"
    url = urljoin(base if base.endswith("/") else base + "/", rel.lstrip("/"))

    portal_creds = ds.get("portal_credentials")
    if not isinstance(portal_creds, dict):
        portal_creds = {}
    if (not portal_creds) and ds.get("portal_credentials_resolve"):
        try:
            from app.services.config_service import get_portal_credentials_runtime

            resolved = get_portal_credentials_runtime()
            if isinstance(resolved, dict):
                portal_creds = resolved
        except Exception:  # noqa: BLE001
            portal_creds = {}

    nsmc_entry = portal_creds.get("nsmc") or portal_creds.get("cma_nsmc")
    metadata: dict[str, object] = {"force_refresh": False}
    if isinstance(nsmc_entry, dict):
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

        date_path = start_date.replace("-", ".") if start_date else ""

        sources_to_try: list[str] = []
        if data_source == "nsmc":
            sources_to_try = ["nsmc"]
        elif data_source == "nas":
            sources_to_try = ["nas"]
        else:
            sources_to_try = ["nsmc", "nas"]

        last_error: Exception | None = None
        for source_name in sources_to_try:
            try:
                if source_name == "nsmc":
                    result_path = _download_from_nsmc(
                        ctx,
                        satellite=satellite,
                        date_path=date_path,
                        ds=ds,
                        target_dir=target_dir,
                    )
                else:
                    result_path = _fetch_from_nas(
                        ctx,
                        date_path=date_path,
                        ds=ds,
                        target_dir=target_dir,
                    )
                return _store_path_manifest(
                    ctx,
                    module_name=self.name,
                    path=result_path,
                    product_type="fy_download_dir",
                    extra={
                        "satellite": satellite,
                        "data_source": source_name,
                        "start_date": start_date,
                        "end_date": end_date,
                        "local_dir": str(result_path),
                    },
                )
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                if ctx.logger_adapter is not None:
                    ctx.logger_adapter.emit_progress(
                        "fy_download",
                        0.0,
                        f"Source '{source_name}' failed: {exc}; trying next...",
                    )

        raise RuntimeError(f"fy_download: all sources failed. Last error: {last_error}")
