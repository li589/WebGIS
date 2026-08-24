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

import re
import time
from pathlib import Path

from contracts.product import ProductManifest, ProductRef
from modules.base import BaseModule
from modules.registry import register_module_decorator
from workflow.schemas import ArtifactRef, NodeExecutionContext, PortSpec

# 下载进度 emit 节流间隔（秒）：_http_resume 每 256KB chunk 回调一次，
# 不节流会形成 node_progress 事件风暴（每 MB 4 个事件全部落库转发）。
_DOWNLOAD_EMIT_INTERVAL = 2.0


def _make_download_progress_cb(
    logger_adapter: object | None,
    stage: str,
):
    """构造统一下载进度回调（2026-08-25 下载进度可视化优化）。

    消费 ingest 下载器的 (current_file, total_files, downloaded_bytes)：
    - 2s 节流（含文件边界立即上报）
    - message: 文件 i/N · 已下载 bytes · 网速
    - detail: speed_bps / downloaded_items / total_items / downloaded_bytes
      （前端 WorkflowStatusPanel 渲染为「文件 2/5 · 156.3 MB · 1.8 MB/s」）
    """
    from ingest._http_resume import format_size, format_speed, get_last_speed_bps

    last_emit = [0.0]

    def _cb(current: int, total: int, downloaded: int) -> None:
        now = time.monotonic()
        is_file_boundary = current != getattr(_cb, "_last_file", 0)  # noqa: SLF001
        if not is_file_boundary and now - last_emit[0] < _DOWNLOAD_EMIT_INTERVAL:
            return
        last_emit[0] = now
        _cb._last_file = current  # type: ignore[attr-defined]  # noqa: SLF001
        if logger_adapter is None:
            return
        bps = get_last_speed_bps()
        speed_txt = f" · {format_speed(bps)}" if bps else ""
        logger_adapter.emit_progress(
            stage,
            current / total if total else 0.0,
            f"文件 {current}/{total} · 已下载 {format_size(downloaded)}{speed_txt}",
            {
                "speed_bps": bps,
                "downloaded_items": current,
                "total_items": total,
                "downloaded_bytes": downloaded,
            },
        )

    return _cb


def _resolve_portal_entry(
    datasource_selection: dict[str, object], portal_key: str
) -> dict[str, object]:
    """解析指定门户的凭证 entry（统一入口，供 fy/earthdata/nsmc 等模块复用）。

    优先 ``datasource_selection.portal_credentials``（随作业下发）；
    为空且 ``portal_credentials_resolve`` 为真时，lazy 回退后端
    ``config_service.get_portal_credentials_runtime()``（provider 进程内才可用）。
    返回 entry dict；缺失或 ``enabled is False`` 返回空 dict。
    """
    portal_creds = datasource_selection.get("portal_credentials")
    if not isinstance(portal_creds, dict):
        portal_creds = {}
    if (not portal_creds) and datasource_selection.get("portal_credentials_resolve"):
        # P3 分层收口（2026-08-23）：经 _backend_bridge 边界桥解析门户凭据
        from _backend_bridge import get_portal_credentials

        resolved = get_portal_credentials()
        if isinstance(resolved, dict):
            portal_creds = resolved
    entry = portal_creds.get(portal_key)
    if not isinstance(entry, dict) or entry.get("enabled") is False:
        return {}
    return entry


def _resolve_earthdata_portal_userpass(
    datasource_selection: dict[str, object],
) -> tuple[str, str]:
    """Resolve earthdata username/password from portal credentials (lazy)."""
    entry = _resolve_portal_entry(datasource_selection, "earthdata")
    if not entry:
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


_OUTFILE_TYPE_NAMES: dict[str, int] = {
    "gtiff": 0,
    "geotiff": 0,
    "tif": 0,
    "tiff": 0,
    "netcdf": 1,
    "nc": 1,
    "hdf5": 2,
    "h5": 2,
    "hdf": 2,
}


def _coerce_outfile_type(value: object) -> int:
    """Coerce outfile_type to int (0:GTiff, 1:NetCDF, 2:HDF5).

    Accepts ints, numeric strings ("0"/"1"/"2"), and format names
    ("hdf5"/"netcdf"/"gtiff" etc.) so seed JSON can use either form.
    """
    if isinstance(value, int):
        return value
    text = str(value or "2").strip().lower()
    if text in _OUTFILE_TYPE_NAMES:
        return _OUTFILE_TYPE_NAMES[text]
    try:
        return int(text)
    except ValueError:
        return 2  # default to HDF5


_SPATIAL_EXTENT_NAMES: dict[str, int] = {
    "global": 0,
    "world": 0,
    "point": 1,
    "single_point": 1,
    "bbox": 2,
    "rectangle": 2,
    "rect": 2,
    "shapefile": 3,
    "shp": 3,
}


def _coerce_spatial_extent(value: object) -> int:
    """Coerce spatial_extent to int (0:global, 1:point, 2:rect, 3:shapefile).

    Accepts ints, numeric strings, and descriptive names so seed JSON can
    use either form.
    """
    if isinstance(value, int):
        return value
    text = str(value or "0").strip().lower()
    if text in _SPATIAL_EXTENT_NAMES:
        return _SPATIAL_EXTENT_NAMES[text]
    try:
        return int(text)
    except ValueError:
        return 0  # default to global


# ─── SSH 远程同步节点 ─────────────────────────────────────────────────────────

_SSH_SYNC_LEGACY_SERVERS = frozenset({"hpc", "win11", "nas"})


def _resolve_profile_server_config(profile_id: str) -> object:
    """把「远程与存储」profile id 解析为 ServerConfig（凭据懒加载，不入作业负载）。

    支持 ssh/sftp（paramiko，含私钥 PEM）与 filebrowser（REST）；
    manual/auto 模式下 failover_state.active=alt 时使用备用路径。
    """
    from ingest.remote_sync import ServerConfig

    # P3 分层收口（2026-08-23）：经 _backend_bridge 边界桥获取远程存储仓库
    from _backend_bridge import get_remote_storage_repository

    repo = get_remote_storage_repository()
    bundle = repo.get_secret_bundle(profile_id)
    if bundle is None:
        raise ValueError(f"远程存储 profile 不存在或已禁用: {profile_id}")

    extra = bundle.get("extra") or {}
    alt = extra.get("alt") if isinstance(extra.get("alt"), dict) else {}
    state = (
        extra.get("failover_state")
        if isinstance(extra.get("failover_state"), dict)
        else {}
    )
    use_alt = bool(
        alt
        and state.get("active") == "alt"
        and any(alt.get(k) for k in ("host", "url"))
    )

    protocol = str(bundle.get("protocol") or "").lower()
    if protocol in ("ssh", "sftp"):
        host = str(bundle.get("host") or "")
        port = bundle.get("port")
        if use_alt and alt.get("host"):
            host = str(alt["host"])
            if alt.get("port") is not None:
                port = alt["port"]
        return ServerConfig(
            server_type="hpc",
            host=host,
            port=int(port or 22),
            username=str(bundle.get("username") or ""),
            password=str(bundle.get("secret") or ""),
            private_key_pem=str(bundle.get("private_key_pem") or ""),
        )
    if protocol == "filebrowser":
        url = str(extra.get("base_url") or bundle.get("host") or "")
        if use_alt and alt.get("url"):
            url = str(alt["url"])
        return ServerConfig(
            server_type="nas",
            host="",
            port=0,
            username=str(bundle.get("username") or ""),
            password=str(bundle.get("secret") or ""),
            filebrowser_url=url,
        )
    raise ValueError(
        f"profile '{profile_id}' 协议 {protocol} 暂不支持 ssh_sync（支持 ssh/sftp/filebrowser）"
    )


@register_module_decorator(name="ssh_sync", template_overrides={"phase": "download"})
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
        # 与前端 SshSyncForm / 其它下载节点对齐；date_* 为历史别名
        "start_date": "",
        "end_date": "",
        "date_start": "",
        "date_end": "",
        "file_filter": [],
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

        server_type = str(resolved.get("server_type") or "hpc").strip()
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

        # 构建 ServerConfig：hpc/win11/nas 走显式连接参数，其余视为
        # 「远程与存储」profile id（凭据由后端仓库解密，不落作业负载）
        if server_type.lower() in _SSH_SYNC_LEGACY_SERVERS:
            server_type = server_type.lower()
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
        else:
            config = _resolve_profile_server_config(server_type)

        # 日期范围：优先 start_date/end_date（表单），兼容 date_start/date_end
        date_start = str(
            resolved.get("start_date") or resolved.get("date_start") or ""
        ).strip()
        date_end = str(
            resolved.get("end_date") or resolved.get("date_end") or ""
        ).strip()
        date_range: tuple[str, str] | None = None
        if date_start and date_end:
            date_range = (date_start, date_end)

        raw_filter = resolved.get("file_filter")
        file_filter: frozenset[str] | None = None
        if isinstance(raw_filter, str) and raw_filter.strip():
            # 模板/表单以字符串传入（如 ".mat,.h5"）
            raw_filter = [
                tok for tok in re.split(r"[,;\s]+", raw_filter.strip()) if tok
            ]
        if isinstance(raw_filter, (list, tuple, set, frozenset)) and raw_filter:
            normalized = {
                (e if str(e).startswith(".") else f".{e}").lower()
                for e in raw_filter
                if str(e).strip()
            }
            if normalized:
                file_filter = frozenset(normalized)

        dry_run = bool(resolved.get("dry_run"))

        if ctx.logger_adapter is not None:
            ctx.logger_adapter.emit_stage_start(
                "ssh_sync",
                f"Sync {remote_path} -> {local_path} ({server_type})",
            )

        # 下载进度可视化（2026-08-25）：bytes + 网速 + 2s 节流
        # （此前每 256KB chunk 无节流 emit + 忽略 downloaded bytes，
        #  前端只见 items 进度卡 0% 忽然结束）
        _progress_cb = _make_download_progress_cb(ctx.logger_adapter, "ssh_sync")

        result = sync_dataset(
            server_config=config,
            remote_path=remote_path,
            local_path=local_path,
            date_range=date_range,
            file_filter=file_filter,
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


@register_module_decorator(
    name="nsidc_smap_download", template_overrides={"phase": "download"}
)
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
                "nsidc_smap_download",
                f"Download SMAP {short_name} V{version}: "
                f"{start_date} ~ {end_date} -> {local_dir}",
            )

        _progress_cb = _make_download_progress_cb(
            ctx.logger_adapter, "nsidc_smap_download"
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

        # 前置失败（认证/磁盘）errors 非空但 failed=0，旧条件会静默 0/0 通过，
        # 下游 smap_daily 才报误导性的 "No SMAP HDF5 files found"。
        if (
            result.failed > 0 or (result.errors and result.total_granules == 0)
        ) and not (result.success):
            error_summary = "; ".join(result.errors[:5]) if result.errors else "unknown"
            raise RuntimeError(
                f"nsidc_smap_download failed: {error_summary} "
                f"(downloaded={result.downloaded}/{result.total_granules}, "
                f"skipped={result.skipped}, failed={result.failed})"
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


@register_module_decorator(
    name="gldas_download", template_overrides={"phase": "download"}
)
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

        _progress_cb = _make_download_progress_cb(
            ctx.logger_adapter, "gldas_download"
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
            anc_root = str(resolved.get("anc_root") or ds.get("anc_root") or "").strip()
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


@register_module_decorator(
    name="fy_preprocess", template_overrides={"phase": "preprocess"}
)
class FyPreprocessModule(BaseModule):
    name = "fy_preprocess"
    description = (
        "FY-3B/3D MWRI HDF 亮温预处理：geolocation 校正、日内轨道拼接、"
        "多通道合并、重投影到 EPSG:4326。输出 HDF5/NetCDF/GeoTIFF。"
    )
    input_ports = [
        PortSpec(
            name="data",
            kind="data",
            data_class="string",
            required=False,
            description="上游数据目录（如 fy_download.path）；命中时优先于 input_dir 参数。",
        ),
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

    @staticmethod
    def _coerce_upstream_dir(value: object) -> str:
        """上游端口值（str / {path,uri} dict / ArtifactRef）→ 目录字符串。"""
        if value is None:
            return ""
        if isinstance(value, dict):
            for key in ("path", "uri", "input_dir", "local_path"):
                text = str(value.get(key) or "").strip()
                if text:
                    return text
            return ""
        uri = getattr(value, "uri", None)
        return str(uri if uri else value).strip()

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
        upstream_dir = self._coerce_upstream_dir(inputs.get("data"))
        if upstream_dir:
            resolved["input_dir"] = upstream_dir

        satellite = str(resolved.get("satellite") or "FY3D").upper()
        input_dir = str(resolved.get("input_dir") or "").strip()
        output_dir = str(resolved.get("output_dir") or "").strip()
        start_date = str(resolved.get("start_date") or "").strip()
        end_date = str(resolved.get("end_date") or "").strip()
        orbit_mode = str(resolved.get("orbit_mode") or "MWRID")
        band_ids_raw = resolved.get("band_ids")
        band_ids = list(band_ids_raw) if band_ids_raw else [1, 2]
        outfile_type = _coerce_outfile_type(resolved.get("outfile_type", 2))
        spatial_extent = _coerce_spatial_extent(resolved.get("spatial_extent", 0))

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
