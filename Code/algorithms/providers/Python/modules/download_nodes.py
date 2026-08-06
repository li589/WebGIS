"""远程数据下载与预处理工作流节点。

注册下载/预处理节点，供工作流编排使用：

    - ``ssh_sync``        — 从远程服务器（HPC/Win11/NAS）增量同步数据
    - ``nsidc_smap_download`` — 从 NASA NSIDC 下载 SMAP L3 SPL3SMP_E 数据
    - ``gldas_download``  — 从 NASA GES DISC 下载 GLDAS NOAH025_3H ``.nc4``
    - ``gldas_nc4_to_mat`` — 将 GLDAS ``.nc4`` 重采样为 DUAL 温度 ``.mat``
    - ``fy_preprocess``   — FY-3B/3D MWRI HDF 亮温预处理（geolocation + 拼接 + 重投影）

所有节点输出 ``path``（本地路径）和 ``manifest``（ProductManifest artifact），
可直接作为下游算法节点的 datasource_selection 输入。
"""

from __future__ import annotations

from pathlib import Path

from contracts.product import ProductManifest, ProductRef
from modules.base import BaseModule
from modules.registry import register_module_decorator
from workflow.schemas import ArtifactRef, NodeExecutionContext, PortSpec


def _resolve_earthdata_portal_userpass(
    datasource_selection: dict[str, object],
) -> tuple[str, str]:
    """Resolve earthdata username/password from portal credentials (lazy)."""
    portal_creds = datasource_selection.get("portal_credentials")
    if not isinstance(portal_creds, dict):
        portal_creds = {}
    if (not portal_creds) and datasource_selection.get("portal_credentials_resolve"):
        try:
            from app.services.config_service import get_portal_credentials_runtime

            resolved = get_portal_credentials_runtime()
            if isinstance(resolved, dict):
                portal_creds = resolved
        except Exception:  # noqa: BLE001
            portal_creds = {}
    entry = portal_creds.get("earthdata")
    if not isinstance(entry, dict):
        return "", ""
    if entry.get("enabled") is False:
        return "", ""
    user = str(entry.get("username") or "").strip()
    password = str(entry.get("password") or "").strip()
    return user, password


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


# ─── SSH 远程同步节点 ─────────────────────────────────────────────────────────


@register_module_decorator(name="ssh_sync")
class SshSyncModule(BaseModule):
    name = "ssh_sync"
    description = (
        "从远程服务器（HPC SSH/SFTP、Win11 SSH 跳板、NAS FileBrowser）"
        "增量同步数据到本地目录。支持日期范围过滤和断点续传。"
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
        "server_type": "hpc",
        "host": "",
        "port": 22,
        "username": "",
        "password": "",
        "key_filename": "",
        "ssh_alias": "",
        "filebrowser_url": "",
        "proxy_command": "",
        "remote_path": "",
        "local_path": "",
        "date_start": "",
        "date_end": "",
        "dry_run": False,
    }

    def execute(
        self,
        inputs: dict[str, object],
        params: dict[str, object],
        ctx: NodeExecutionContext,
    ) -> dict[str, object]:
        from ingest.remote_sync import ServerConfig, sync_dataset

        ds = dict(inputs.get("datasource_selection", {}))
        ap = dict(inputs.get("algorithm_params", {}))
        resolved = {**self.default_params, **params, **ap, **ds}

        server_type = str(resolved.get("server_type") or "hpc").lower()
        host = str(resolved.get("host") or "").strip()
        port = int(resolved.get("port") or 22)
        username = str(resolved.get("username") or "").strip()
        password = str(resolved.get("password") or "").strip()
        key_filename = str(resolved.get("key_filename") or "").strip()
        ssh_alias = str(resolved.get("ssh_alias") or "").strip()
        filebrowser_url = str(resolved.get("filebrowser_url") or "").strip()
        proxy_command = str(resolved.get("proxy_command") or "").strip()

        remote_path = str(resolved.get("remote_path") or "").strip()
        local_path = str(resolved.get("local_path") or "").strip()
        if not remote_path:
            raise ValueError("ssh_sync requires remote_path")
        if not local_path:
            # 回退到 workspace
            local_path = str(ctx.workspace / "data_access" / "ssh_sync")

        # 构建 ServerConfig
        config = ServerConfig(
            server_type=server_type,
            host=host,
            port=port,
            username=username,
            password=password,
            key_filename=key_filename,
            ssh_alias=ssh_alias,
            filebrowser_url=filebrowser_url,
            proxy_command=proxy_command,
        )

        # 日期范围
        date_start = str(resolved.get("date_start") or "").strip()
        date_end = str(resolved.get("date_end") or "").strip()
        date_range: tuple[str, str] | None = None
        if date_start and date_end:
            date_range = (date_start, date_end)

        dry_run = bool(resolved.get("dry_run"))

        if ctx.logger_adapter is not None:
            ctx.logger_adapter.emit_stage_start(
                "ssh_sync",
                f"Sync {remote_path} -> {local_path} ({server_type})",
            )

        def _progress_cb(current: int, total: int, downloaded: int) -> None:
            if ctx.logger_adapter is not None:
                ctx.logger_adapter.emit_progress(
                    "ssh_sync", current / total if total else 0.0, f"File {current}/{total}"
                )

        result = sync_dataset(
            server_config=config,
            remote_path=remote_path,
            local_path=local_path,
            date_range=date_range,
            progress_callback=_progress_cb,
            dry_run=dry_run,
        )

        if ctx.logger_adapter is not None:
            ctx.logger_adapter.emit_stage_end(
                "ssh_sync",
                f"Synced: total={result.total_files} "
                f"downloaded={result.downloaded} skipped={result.skipped} "
                f"failed={result.failed}",
            )

        if result.failed > 0 and not result.success:
            error_summary = "; ".join(result.errors[:5]) if result.errors else "unknown"
            raise RuntimeError(
                f"ssh_sync completed with {result.failed} failures: {error_summary}"
            )

        return _store_path_manifest(
            ctx,
            module_name=self.name,
            path=local_path,
            product_type="ssh_synced_dir",
            extra={
                "server_type": server_type,
                "remote_path": remote_path,
                "total_files": result.total_files,
                "downloaded": result.downloaded,
                "skipped": result.skipped,
                "failed": result.failed,
                "downloaded_bytes": result.downloaded_bytes,
                "resumed": result.resumed,
            },
        )


# ─── NSIDC SMAP 下载节点 ──────────────────────────────────────────────────────


@register_module_decorator(name="nsidc_smap_download")
class NsidcSmapDownloadModule(BaseModule):
    name = "nsidc_smap_download"
    description = (
        "从 NASA NSIDC 下载 SMAP L3 SPL3SMP_E V6 土壤湿度数据。"
        "支持日期范围、增量下载、断点续传。"
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
        "start_date": "",
        "end_date": "",
        "local_dir": "",
        "version": "6",
        "short_name": "SPL3SMP_E",
        "username": "",
        "password": "",
        "dry_run": False,
        "max_files": None,
    }

    def execute(
        self,
        inputs: dict[str, object],
        params: dict[str, object],
        ctx: NodeExecutionContext,
    ) -> dict[str, object]:
        from ingest.nsidc_download import download_smap_range

        ds = dict(inputs.get("datasource_selection", {}))
        ap = dict(inputs.get("algorithm_params", {}))
        resolved = {**self.default_params, **params, **ap, **ds}

        start_date = str(resolved.get("start_date") or "").strip()
        end_date = str(resolved.get("end_date") or "").strip()
        if not start_date or not end_date:
            raise ValueError("nsidc_smap_download requires start_date and end_date")

        local_dir = str(resolved.get("local_dir") or "").strip()
        if not local_dir:
            local_dir = str(ctx.workspace / "data_access" / "smap_download")

        version = str(resolved.get("version") or "6")
        short_name = str(resolved.get("short_name") or "SPL3SMP_E")
        username = str(resolved.get("username") or "").strip()
        password = str(resolved.get("password") or "").strip()
        dry_run = bool(resolved.get("dry_run"))
        max_files_raw = resolved.get("max_files")
        max_files = int(max_files_raw) if max_files_raw else None

        if ctx.logger_adapter is not None:
            ctx.logger_adapter.emit_stage_start(
                "nsidc_smap_download",
                f"Download SMAP {short_name} V{version}: "
                f"{start_date} ~ {end_date} -> {local_dir}",
            )

        def _progress_cb(current: int, total: int, downloaded: int) -> None:
            if ctx.logger_adapter is not None:
                ctx.logger_adapter.emit_progress(
                    "nsidc_smap_download",
                    current / total if total else 0.0,
                    f"Granule {current}/{total}",
                )

        result = download_smap_range(
            start_date=start_date,
            end_date=end_date,
            local_dir=local_dir,
            version=version,
            short_name=short_name,
            username=username,
            password=password,
            dry_run=dry_run,
            max_files=max_files,
            progress_callback=_progress_cb,
        )

        if ctx.logger_adapter is not None:
            ctx.logger_adapter.emit_stage_end(
                "nsidc_smap_download",
                f"Downloaded: {result.downloaded}/{result.total_granules} "
                f"skipped={result.skipped} failed={result.failed}",
            )

        if result.failed > 0 and not result.success:
            error_summary = "; ".join(result.errors[:5]) if result.errors else "unknown"
            raise RuntimeError(
                f"nsidc_smap_download completed with {result.failed} failures: "
                f"{error_summary}"
            )

        return _store_path_manifest(
            ctx,
            module_name=self.name,
            path=local_dir,
            product_type="nsidc_smap_dir",
            extra={
                "start_date": start_date,
                "end_date": end_date,
                "short_name": short_name,
                "version": version,
                "total_granules": result.total_granules,
                "downloaded": result.downloaded,
                "skipped": result.skipped,
                "failed": result.failed,
                "downloaded_bytes": result.downloaded_bytes,
            },
        )


# ─── GLDAS 下载节点 ───────────────────────────────────────────────────────────


@register_module_decorator(name="gldas_download")
class GldasDownloadModule(BaseModule):
    name = "gldas_download"
    description = (
        "从 NASA GES DISC 下载 GLDAS NOAH025_3H V2.1 温度场（.nc4）。"
        "支持日期范围、增量下载、earthdata 认证；产出目录可再转 .mat 接入 DUAL。"
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
        "start_date": "",
        "end_date": "",
        "local_dir": "",
        "version": "2.1",
        "short_name": "GLDAS_NOAH025_3H",
        "username": "",
        "password": "",
        "dry_run": False,
        "max_files": None,
    }

    def execute(
        self,
        inputs: dict[str, object],
        params: dict[str, object],
        ctx: NodeExecutionContext,
    ) -> dict[str, object]:
        from ingest.gldas_download import download_gldas_range

        ds = dict(inputs.get("datasource_selection", {}))
        ap = dict(inputs.get("algorithm_params", {}))
        resolved = {**self.default_params, **params, **ap, **ds}

        start_date = str(resolved.get("start_date") or "").strip()
        end_date = str(resolved.get("end_date") or "").strip()
        if not start_date or not end_date:
            raise ValueError("gldas_download requires start_date and end_date")

        local_dir = str(resolved.get("local_dir") or "").strip()
        if not local_dir:
            local_dir = str(ctx.workspace / "data_access" / "gldas_download")

        version = str(resolved.get("version") or "2.1")
        short_name = str(resolved.get("short_name") or "GLDAS_NOAH025_3H")
        username = str(resolved.get("username") or "").strip()
        password = str(resolved.get("password") or "").strip()
        # Prefer settings-page earthdata portal credentials when node leaves
        # username/password blank (bridge sets portal_credentials_resolve).
        if not (username and password):
            portal_user, portal_pass = _resolve_earthdata_portal_userpass(ds)
            username = username or portal_user
            password = password or portal_pass
        dry_run = bool(resolved.get("dry_run"))
        max_files_raw = resolved.get("max_files")
        max_files = int(max_files_raw) if max_files_raw else None

        if ctx.logger_adapter is not None:
            ctx.logger_adapter.emit_stage_start(
                "gldas_download",
                f"Download {short_name} V{version}: "
                f"{start_date} ~ {end_date} -> {local_dir}",
            )

        def _progress_cb(current: int, total: int, downloaded: int) -> None:
            if ctx.logger_adapter is not None:
                ctx.logger_adapter.emit_progress(
                    "gldas_download",
                    current / total if total else 0.0,
                    f"Granule {current}/{total}",
                )

        result = download_gldas_range(
            start_date=start_date,
            end_date=end_date,
            local_dir=local_dir,
            version=version,
            short_name=short_name,
            username=username,
            password=password,
            dry_run=dry_run,
            max_files=max_files,
            progress_callback=_progress_cb,
        )

        if ctx.logger_adapter is not None:
            ctx.logger_adapter.emit_stage_end(
                "gldas_download",
                f"Downloaded: {result.downloaded}/{result.total_granules} "
                f"skipped={result.skipped} failed={result.failed}",
            )

        if result.failed > 0 and not result.success:
            error_summary = "; ".join(result.errors[:5]) if result.errors else "unknown"
            raise RuntimeError(
                f"gldas_download completed with {result.failed} failures: "
                f"{error_summary}"
            )

        return _store_path_manifest(
            ctx,
            module_name=self.name,
            path=local_dir,
            product_type="gldas_nc4_dir",
            extra={
                "start_date": start_date,
                "end_date": end_date,
                "short_name": short_name,
                "version": version,
                "total_granules": result.total_granules,
                "downloaded": result.downloaded,
                "skipped": result.skipped,
                "failed": result.failed,
                "downloaded_bytes": result.downloaded_bytes,
                "dry_run": dry_run,
            },
        )


# ─── GLDAS nc4 → mat 转换节点 ─────────────────────────────────────────────────


@register_module_decorator(name="gldas_nc4_to_mat")
class GldasNc4ToMatModule(BaseModule):
    name = "gldas_nc4_to_mat"
    description = (
        "将 GLDAS NOAH025_3H .nc4 重采样到 9 km 研究网格并写出 "
        "Ts_gldas/Tsoil1_gldas/Tsoil2_gldas .mat（YYYYMMDD_HHMM.mat）。"
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
        "input_dir": "",
        "output_dir": "",
        "ancillary_mat": "",
        "dry_run": False,
        "skip_existing": True,
        "max_files": None,
    }

    def execute(
        self,
        inputs: dict[str, object],
        params: dict[str, object],
        ctx: NodeExecutionContext,
    ) -> dict[str, object]:
        from ingest.gldas_nc4_to_mat import convert_gldas_nc4_directory

        ds = dict(inputs.get("datasource_selection", {}))
        ap = dict(inputs.get("algorithm_params", {}))
        resolved = {**self.default_params, **params, **ap, **ds}

        input_dir = str(resolved.get("input_dir") or "").strip()
        if not input_dir:
            raise ValueError("gldas_nc4_to_mat requires input_dir")
        output_dir = str(resolved.get("output_dir") or "").strip()
        if not output_dir:
            output_dir = str(ctx.workspace / "data_access" / "gldas_mat")

        ancillary_mat = str(resolved.get("ancillary_mat") or "").strip()
        if not ancillary_mat:
            anc_root = str(
                resolved.get("anc_root")
                or ds.get("anc_root")
                or ""
            ).strip()
            if anc_root:
                ancillary_mat = str(Path(anc_root) / "IGBP_9km_12.mat")
        if not ancillary_mat:
            raise ValueError(
                "gldas_nc4_to_mat requires ancillary_mat or anc_root/IGBP_9km_12.mat"
            )

        dry_run = bool(resolved.get("dry_run"))
        skip_existing = bool(resolved.get("skip_existing", True))
        max_files_raw = resolved.get("max_files")
        max_files = int(max_files_raw) if max_files_raw else None

        if ctx.logger_adapter is not None:
            ctx.logger_adapter.emit_stage_start(
                "gldas_nc4_to_mat",
                f"Convert nc4 {input_dir} -> {output_dir}",
            )

        result = convert_gldas_nc4_directory(
            input_dir=input_dir,
            output_dir=output_dir,
            ancillary_mat=ancillary_mat,
            dry_run=dry_run,
            skip_existing=skip_existing,
            max_files=max_files,
        )

        if ctx.logger_adapter is not None:
            ctx.logger_adapter.emit_stage_end(
                "gldas_nc4_to_mat",
                f"converted={result.converted} skipped={result.skipped} "
                f"failed={result.failed}",
            )

        if result.failed > 0 and not result.success:
            error_summary = "; ".join(result.errors[:5]) if result.errors else "unknown"
            raise RuntimeError(
                f"gldas_nc4_to_mat completed with {result.failed} failures: "
                f"{error_summary}"
            )

        return _store_path_manifest(
            ctx,
            module_name=self.name,
            path=output_dir,
            product_type="gldas_mat_dir",
            extra={
                "input_dir": input_dir,
                "ancillary_mat": ancillary_mat,
                "total_nc4": result.total_nc4,
                "converted": result.converted,
                "skipped": result.skipped,
                "failed": result.failed,
                "outputs": result.outputs[:20],
                "dry_run": dry_run,
            },
        )


# ─── FY 预处理节点 ────────────────────────────────────────────────────────────


@register_module_decorator(name="fy_preprocess")
class FyPreprocessModule(BaseModule):
    name = "fy_preprocess"
    description = (
        "FY-3B/3D MWRI HDF 亮温预处理：geolocation 校正、日内轨道拼接、"
        "多通道合并、重投影到 EPSG:4326。输出 HDF5/NetCDF/GeoTIFF。"
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
        "input_dir": "",
        "output_dir": "",
        "start_date": "",
        "end_date": "",
        "orbit_mode": "MWRID",
        "band_ids": [1, 2],
        "outfile_type": 2,
        "spatial_extent": 0,
    }

    def execute(
        self,
        inputs: dict[str, object],
        params: dict[str, object],
        ctx: NodeExecutionContext,
    ) -> dict[str, object]:
        from ingest.fy_preprocess import FyPreprocessor, FySatelliteConfig

        ds = dict(inputs.get("datasource_selection", {}))
        ap = dict(inputs.get("algorithm_params", {}))
        resolved = {**self.default_params, **params, **ap, **ds}

        satellite = str(resolved.get("satellite") or "FY3D").upper()
        input_dir = str(resolved.get("input_dir") or "").strip()
        output_dir = str(resolved.get("output_dir") or "").strip()
        start_date = str(resolved.get("start_date") or "").strip()
        end_date = str(resolved.get("end_date") or "").strip()
        orbit_mode = str(resolved.get("orbit_mode") or "MWRID")
        band_ids_raw = resolved.get("band_ids")
        band_ids = list(band_ids_raw) if band_ids_raw else [1, 2]
        outfile_type = int(resolved.get("outfile_type") or 2)
        spatial_extent = int(resolved.get("spatial_extent") or 0)

        if not input_dir:
            raise ValueError("fy_preprocess requires input_dir")
        if not output_dir:
            output_dir = str(ctx.workspace / "products" / "fy_preprocess")
        if not start_date or not end_date:
            raise ValueError("fy_preprocess requires start_date and end_date")

        # 构建卫星配置
        if satellite == "FY3B":
            sat_config = FySatelliteConfig.for_fy3b()
        else:
            sat_config = FySatelliteConfig.for_fy3d()

        preprocessor = FyPreprocessor(sat_config)

        if ctx.logger_adapter is not None:
            ctx.logger_adapter.emit_stage_start(
                "fy_preprocess",
                f"Preprocess {satellite}: {start_date} ~ {end_date} "
                f"orbit={orbit_mode} -> {output_dir}",
            )

        processed_days = preprocessor.process_date_range(
            input_dir=input_dir,
            output_dir=output_dir,
            start_date=start_date,
            end_date=end_date,
            orbit_mode=orbit_mode,
            band_ids=band_ids,
            outfile_type=outfile_type,
            spatial_extent=spatial_extent,
        )

        if ctx.logger_adapter is not None:
            ctx.logger_adapter.emit_stage_end(
                "fy_preprocess",
                f"Processed {len(processed_days)} days: "
                f"{', '.join(processed_days[:5])}{'...' if len(processed_days) > 5 else ''}",
            )

        return _store_path_manifest(
            ctx,
            module_name=self.name,
            path=output_dir,
            product_type="fy_preprocessed_dir",
            extra={
                "satellite": satellite,
                "input_dir": input_dir,
                "start_date": start_date,
                "end_date": end_date,
                "orbit_mode": orbit_mode,
                "band_ids": band_ids,
                "outfile_type": outfile_type,
                "spatial_extent": spatial_extent,
                "processed_days": processed_days,
                "n_processed_days": len(processed_days),
            },
        )
