"""omega_sf_fenkuai 工作流模块注册。

``OmegaSfFenkuaiModule`` 编排 SF（茎干因子）块反演流水线（见
``algorithms/omega_sf.py``）：构建时间序列 → 8 天分块 → 逐日 SF 倒推 →
逐块 h/alpha 反演 + OMEGA 识别 → 逐日 SM/VOD 反演 → 汇总 PFT/pixel OMEGA。

输出三个产品图层：
    - SM   — 块级土壤水分均值网格
    - VOD  — 块级植被光学厚度均值网格
    - OMEGA — 逐像元 OMEGA 中位数网格

数据源解析复用 ``modules/bundles.py`` 的 daily bundle 键映射（anc_root /
smap_folder / ndvi_folder 等），并追加 omega_sf 专有键（fy3d_folder /
fy3b_folder / gldas_mat_folder / ddca_sm_folder）。
"""

from __future__ import annotations

from pathlib import Path

from contracts.product import ProductManifest, ProductRef
from data_access import resolve_prepared_local_path
from modules.base import BaseModule
from modules.registry import register_module_decorator
from workflow.schemas import ArtifactRef, NodeExecutionContext, PortSpec


def _store_manifest(
    ctx: NodeExecutionContext,
    *,
    module_name: str,
    manifest: ProductManifest,
    metadata: dict[str, object],
) -> dict[object, object]:
    artifact = ArtifactRef(
        artifact_id=f"{ctx.runtime_context.run_id}:{ctx.node_id}:manifest",
        artifact_type="product_manifest",
        format="python_object",
        uri=None,
        producer_node_id=ctx.node_id,
        schema_name="ProductManifest",
        metadata={"module_name": module_name, **metadata},
    )
    ctx.artifact_store.put(artifact, payload=manifest)
    return {"manifest": artifact}


def _align_window_to_available(
    algorithm_params: dict[str, object],
    smap_folder: str,
    ctx: NodeExecutionContext,
    *,
    allow_align: bool,
) -> dict[str, object]:
    """请求窗口与本地 SMAP 数据零交集时，可选对齐到最新可用窗。

    仅当 ``allow_align=True``（来自 relax_flags 或策略 allow_silent）时改窗；
    否则 raise ``ValueError``（``error_code=coverage_gap``）fail-closed。
    """
    from datetime import datetime, timedelta

    start_raw = str(algorithm_params.get("start_date") or "").strip()
    end_raw = str(algorithm_params.get("end_date") or "").strip()
    if len(start_raw) < 8 or len(end_raw) < 8:
        return algorithm_params

    try:
        from algorithms.omega_sf import _scan_folder_dates

        available = _scan_folder_dates(smap_folder)
    except Exception:
        return algorithm_params
    if not available:
        return algorithm_params

    try:
        start = datetime.strptime(start_raw[:8], "%Y%m%d")
        end = datetime.strptime(end_raw[:8], "%Y%m%d")
    except ValueError:
        return algorithm_params

    if any(start <= t <= end for t in available):
        return algorithm_params  # 有交集：保持请求窗口

    if not allow_align:
        message = (
            "error_code=coverage_gap "
            f"时间窗与本地 SMAP 零交集（请求 {start:%Y%m%d}~{end:%Y%m%d}，"
            f"本地最新 {max(available):%Y%m%d}）；未启用对齐放宽。"
        )
        if ctx.logger_adapter is not None:
            try:
                ctx.logger_adapter.emit_stage_start("omega_sf_fenkuai", message)
            except Exception:
                pass
        # fail-closed：缺数不可静默继续，供桥接层归类为 coverage_gap
        raise ValueError(message)

    latest = max(available)
    window_days = max((end - start).days, 7)  # 至少 8 天（含端点）
    new_end = latest
    new_start = new_end - timedelta(days=window_days)

    message = (
        f"时间窗自动对齐：请求 {start:%Y%m%d}~{end:%Y%m%d} 本地无数据，"
        f"回退到最新可用窗 {new_start:%Y%m%d}~{new_end:%Y%m%d}"
        f"（本地最新 {latest:%Y%m%d}；机器时钟与数据可用性不匹配时以数据为准）"
    )
    if ctx.logger_adapter is not None:
        try:
            ctx.logger_adapter.emit_stage_start("omega_sf_fenkuai", message)
        except Exception:
            pass

    aligned = dict(algorithm_params)
    aligned["start_date"] = f"{new_start:%Y%m%d}"
    aligned["end_date"] = f"{new_end:%Y%m%d}"
    return aligned


def _block_mat_usable(path: Path) -> bool:
    """块 mat 可用：存在且含 SM/VOD/OMEGA（对齐 omega_avg Stage D）。"""
    if not path.is_file() or path.stat().st_size <= 0:
        return False
    try:
        from ingest.mat_bundle import load_mat_file

        payload = load_mat_file(path)
    except (OSError, ValueError, KeyError):
        return False
    for key in ("SM", "VOD", "OMEGA"):
        if key not in payload:
            return False
    return True


def _required_block_keys(start_date: str, end_date: str, block_days: int) -> list[str]:
    """与 make_viirs8_blocks 一致的块日期键列表。"""
    from datetime import datetime, timedelta

    from algorithms.omega_sf import make_viirs8_blocks

    start = datetime.strptime(start_date[:8], "%Y%m%d")
    end = datetime.strptime(end_date[:8], "%Y%m%d")
    tvec = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    block_struct = make_viirs8_blocks(tvec, block_days=block_days)
    keys: list[str] = []
    for i in range(len(block_struct.starts)):
        d0 = block_struct.starts[i].strftime("%Y%m%d")
        d1 = block_struct.ends[i].strftime("%Y%m%d")
        keys.append(f"{d0}_{d1}")
    return keys


def _try_hydrate_blocks_from_sibling_cache(
    *,
    output_root: Path,
    output_dir: Path,
    start_date: str,
    end_date: str,
    block_days: int,
    tb_source: str,
    sm_source: str,
) -> dict[str, str] | None:
    """跨 run 块缓存：同 output_root 下其它 run 若已有完整可用块，复制到本 run。

    返回 output_paths（含 block_dir）表示命中；None 表示需重新反演。
    仅当请求窗内**全部**块键均可复用时短路（部分缺口仍走完整反演）。
    """
    import shutil

    try:
        keys = _required_block_keys(start_date, end_date, block_days)
    except Exception:
        return None
    if not keys or not output_root.is_dir():
        return None

    found: dict[str, Path] = {}
    # 优先同参数内容键缓存目录
    cache_key = (
        f"_cache_{str(tb_source).upper()}_{str(sm_source).upper()}"
        f"_{start_date[:8]}_{end_date[:8]}"
    )
    preferred = [output_root / cache_key]
    siblings = [
        p
        for p in sorted(output_root.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True)
        if p.is_dir() and p.resolve() != output_dir.resolve() and not p.name.startswith(".")
    ]
    search_dirs = preferred + [p for p in siblings if p not in preferred]

    for run_dir in search_dirs:
        for key in keys:
            if key in found:
                continue
            src = run_dir / f"{key}.mat"
            if _block_mat_usable(src):
                found[key] = src
        if len(found) == len(keys):
            break

    if len(found) != len(keys):
        return None

    output_dir.mkdir(parents=True, exist_ok=True)
    output_paths: dict[str, str] = {"block_dir": str(output_dir)}
    for idx, key in enumerate(keys):
        src = found[key]
        dest = output_dir / f"{key}.mat"
        if src.resolve() != dest.resolve():
            shutil.copy2(src, dest)
        compat = output_dir / f"block_{idx:03d}.mat"
        if compat.resolve() != dest.resolve():
            shutil.copy2(dest, compat)
        output_paths[key] = str(dest)
        output_paths[f"block_{idx:03d}"] = str(compat)

    # 内容键缓存：下次同窗直接命中
    cache_dir = output_root / cache_key
    if cache_dir.resolve() != output_dir.resolve():
        cache_dir.mkdir(parents=True, exist_ok=True)
        for key in keys:
            dest = cache_dir / f"{key}.mat"
            src = output_dir / f"{key}.mat"
            if src.is_file() and (
                not dest.exists() or dest.stat().st_mtime < src.stat().st_mtime
            ):
                shutil.copy2(src, dest)

    return output_paths


def _publish_blocks_to_content_cache(
    *,
    output_root: Path,
    output_dir: Path,
    start_date: str,
    end_date: str,
    tb_source: str,
    sm_source: str,
) -> None:
    """将本 run 成功块写入内容键缓存目录，供后续同窗短路。"""
    import shutil

    cache_key = (
        f"_cache_{str(tb_source).upper()}_{str(sm_source).upper()}"
        f"_{start_date[:8]}_{end_date[:8]}"
    )
    cache_dir = output_root / cache_key
    if cache_dir.resolve() == output_dir.resolve():
        return
    if not output_dir.is_dir():
        return
    cache_dir.mkdir(parents=True, exist_ok=True)
    for mat in output_dir.glob("*_*.mat"):
        name = mat.name
        if name.startswith("block_"):
            continue
        # YYYYMMDD_YYYYMMDD.mat
        stem = mat.stem
        parts = stem.split("_")
        if len(parts) != 2 or not all(len(p) == 8 and p.isdigit() for p in parts):
            continue
        if not _block_mat_usable(mat):
            continue
        dest = cache_dir / name
        if not dest.exists() or dest.stat().st_mtime < mat.stat().st_mtime:
            shutil.copy2(mat, dest)


# omega_sf 专有数据源键映射（daily bundle 键复用 bundles.py 的映射）
_OMEGA_SF_DATASOURCE_KEY_MAP: dict[str, tuple[str, ...]] = {
    "fy3d_folder": ("fy3d_folder", "fy_daily_mat", "daily_mat_sources"),
    "fy3b_folder": ("fy3b_folder", "fy_daily_mat", "daily_mat_sources"),
    "gldas_mat_folder": ("gldas_mat_folder", "gldas_mat", "daily_mat_sources"),
    "gldas_template_mat": ("gldas_template_mat", "gldas_template", "daily_mat_sources"),
    "ddca_sm_folder": ("ddca_sm_folder", "ddca_sm", "daily_mat_sources"),
    "ndvi_clim_folder": ("ndvi_clim_folder", "ndvi_clim", "daily_mat_sources"),
}


def _resolve_omega_sf_datasource_selection(
    datasource_selection: dict[str, object],
) -> dict[str, object]:
    """解析 omega_sf 数据源选择：先复用 daily bundle 键映射，再解析 omega_sf 专有键。"""
    from modules.bundles import (
        _path_from_datasource_value,
        _resolve_bundle_datasource_selection,
    )

    # 1. 复用 daily bundle 键映射（anc_root / smap_folder / ndvi_folder / lin_pix_mat 等）
    resolved = _resolve_bundle_datasource_selection(dict(datasource_selection))

    # 2. 解析 omega_sf 专有键（fy3d_folder / fy3b_folder / gldas_mat_folder / ddca_sm_folder）
    for target_key, dataset_names in _OMEGA_SF_DATASOURCE_KEY_MAP.items():
        if resolved.get(target_key):
            continue
        for name in dataset_names:
            path = _path_from_datasource_value(resolved.get(name))
            if path:
                resolved[target_key] = path
                break
        if resolved.get(target_key):
            continue
        local_path = resolve_prepared_local_path(
            resolved,
            dataset_names,
            preferred_resource_keys=(target_key,),
        )
        if local_path is not None:
            resolved[target_key] = str(local_path)
    return resolved


def _resolve_grid_shape(
    algorithm_params: dict[str, object],
    datasource_selection: dict[str, object],
) -> tuple[int, int]:
    """解析 grid_shape：优先 algorithm_params，否则从 landcover 辅助 mat 推断。"""
    import numpy as np

    raw = algorithm_params.get("grid_shape")
    if raw is not None:
        values = list(raw)
        if len(values) >= 2:
            return int(values[0]), int(values[1])

    # 从 landcover 辅助 mat 推断（IGBP_9km_12.mat 存 2D grid）
    anc_root = datasource_selection.get("anc_root")
    if anc_root:
        lc_path = Path(str(anc_root)) / "IGBP_9km_12.mat"
        if lc_path.exists():
            from ingest.mat_bundle import load_mat_file

            payload = load_mat_file(lc_path)
            for alias in ("IGBP_9km_12", "LC", "landcover"):
                if alias in payload:
                    arr = np.asarray(payload[alias])
                    if arr.ndim == 2:
                        return int(arr.shape[0]), int(arr.shape[1])
    raise ValueError(
        "grid_shape could not be resolved: provide algorithm_params['grid_shape'] "
        "or ensure anc_root/IGBP_9km_12.mat exists with a 2D landcover grid"
    )


@register_module_decorator(
    name="omega_sf_fenkuai",
    aliases=["omega_sf_fenkuai_pipeline"],
    template_overrides={
        "phase": "inversion",
        "datasource_severity": {
            "time_window_align_on_zero_intersection": "soft",
            "smap_folder": "hard",
            "anc_root": "hard",
            "fy3d_folder": "hard",
            "fy3b_folder": "hard",
        },
    },
)
class OmegaSfFenkuaiModule(BaseModule):
    name = "omega_sf_fenkuai"
    description = (
        "Native module that runs SF block inversion and OMEGA identification: "
        "build 8-day blocks, per-day SF inversion, block-level h/alpha retrieval, "
        "OMEGA optimization, then per-day DDCA SM/VOD retrieval. "
        "Outputs three layer products: SM, VOD, OMEGA."
    )
    mode_required_inputs = {
        "omega_sf_fenkuai": (
            "smap_folder",
            "anc_root",
        ),
    }
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
        PortSpec(
            name="output_spec_extra", kind="config", data_class="dict", required=False
        ),
        PortSpec(
            name="time_window_align_on_zero_intersection",
            kind="config",
            data_class="bool",
            required=False,
            severity="soft",
            description=(
                "When request window has zero intersection with local SMAP dates, "
                "align to the latest available window (requires relax_flags or "
                "allow_silent policy)."
            ),
        ),
    ]
    output_ports = [
        PortSpec(name="manifest", kind="artifact", data_class="product_manifest")
    ]

    def execute(
        self,
        inputs: dict[str, object],
        params: dict[str, object],
        ctx: NodeExecutionContext,
    ) -> dict[object, object]:
        from algorithms.omega_sf import OmegaSfConfig, retrieve_omega_sf_daily

        _ = params
        datasource_selection = _resolve_omega_sf_datasource_selection(
            dict(inputs.get("datasource_selection", {}))
        )
        algorithm_params = dict(inputs.get("algorithm_params", {}))
        output_spec_extra = dict(inputs.get("output_spec_extra", {}))

        # 必需键校验
        missing_keys = [
            key
            for key in ("smap_folder", "anc_root")
            if not datasource_selection.get(key)
        ]
        if missing_keys:
            raise ValueError(
                f"omega_sf_fenkuai requires datasource_selection keys: "
                f"{', '.join(sorted(missing_keys))}"
            )

        # 时间窗对齐仅在 relax_flags / 策略 allow_silent 时启用（默认 fail-closed）
        relax_flags = algorithm_params.get("relax_flags")
        if not isinstance(relax_flags, dict):
            relax_flags = {}
        allow_align = bool(
            relax_flags.get("time_window_align_on_zero_intersection") is True
        )
        algorithm_params = _align_window_to_available(
            algorithm_params,
            str(datasource_selection["smap_folder"]),
            ctx,
            allow_align=allow_align,
        )

        # 构建配置
        config = OmegaSfConfig.from_params(algorithm_params)

        # 解析 grid_shape
        grid_shape = _resolve_grid_shape(algorithm_params, datasource_selection)

        # 每个 workflow run 使用独立目录，防止不同传感器/时间窗口复用旧块产物。
        # 显式 reuse_output_dir 仅供同一 run 的失败重试复用已有块缓存。
        reuse_output_dir = algorithm_params.get("reuse_output_dir")
        if isinstance(reuse_output_dir, str) and reuse_output_dir.strip():
            output_dir = Path(reuse_output_dir.strip())
        else:
            configured_output_dir = output_spec_extra.get("output_dir")
            output_root = (
                Path(str(configured_output_dir))
                if isinstance(configured_output_dir, str)
                and configured_output_dir.strip()
                else ctx.workspace / "products" / "omega_sf_fenkuai"
            )
            output_dir = output_root / ctx.runtime_context.run_id
        output_dir.mkdir(parents=True, exist_ok=True)
        if ctx.logger_adapter is not None:
            ctx.logger_adapter.emit_stage_start(
                "omega_sf_fenkuai",
                f"Using isolated output directory: {output_dir}",
            )

        cancel_flag_path = algorithm_params.get("cancel_flag_path")
        if not cancel_flag_path:
            cancel_flag_path = ctx.runtime_context.env.get("cancel_flag_path")
        if not cancel_flag_path:
            cancel_flag_path = str(ctx.runtime_context.tmp_dir / "cancel.requested")

        reuse_block_cache = algorithm_params.get("reuse_block_cache", True)
        if isinstance(reuse_block_cache, str):
            reuse_block_cache = reuse_block_cache.strip().lower() not in {
                "0",
                "false",
                "no",
            }

        # 可选数据源
        ndvi_clim_folder = str(datasource_selection.get("ndvi_clim_folder") or "")
        ndvi_folder = str(datasource_selection.get("ndvi_folder") or "")
        fy3d_folder = str(datasource_selection.get("fy3d_folder") or "")
        fy3b_folder = str(datasource_selection.get("fy3b_folder") or "")
        gldas_mat_folder = str(datasource_selection.get("gldas_mat_folder") or "")
        gldas_template_mat = str(datasource_selection.get("gldas_template_mat") or "")
        ddca_sm_folder = str(datasource_selection.get("ddca_sm_folder") or "")

        if ctx.logger_adapter is not None:
            ctx.logger_adapter.emit_stage_start(
                "omega_sf_fenkuai",
                f"SF block inversion: TB_SOURCE={config.tb_source}, "
                f"SM_SOURCE={config.sm_source}, "
                f"{config.start_date}~{config.end_date}",
            )

        # 跨 run 块缓存：同窗全部块已存在则直接复制，跳过 heavy 反演
        cached_paths: dict[str, str] | None = None
        if reuse_block_cache:
            configured_output_dir = output_spec_extra.get("output_dir")
            output_root = (
                Path(str(configured_output_dir))
                if isinstance(configured_output_dir, str)
                and configured_output_dir.strip()
                else ctx.workspace / "products" / "omega_sf_fenkuai"
            )
            # output_dir 可能是 reuse_output_dir；仍用标准 root 搜兄弟 run
            search_root = (
                output_dir.parent
                if output_dir.parent.name == "omega_sf_fenkuai"
                or output_dir.parent.name.startswith("omega_sf")
                else output_root
            )
            cached_paths = _try_hydrate_blocks_from_sibling_cache(
                output_root=search_root,
                output_dir=output_dir,
                start_date=config.start_date,
                end_date=config.end_date,
                block_days=int(config.block_days or 8),
                tb_source=str(config.tb_source),
                sm_source=str(config.sm_source),
            )
            if cached_paths and ctx.logger_adapter is not None:
                ctx.logger_adapter.emit_stage_start(
                    "omega_sf_fenkuai",
                    f"Reused {len(cached_paths) - 1} cached block mats "
                    f"(skip inversion) → {output_dir}",
                )

        # 进度回调（含 chunk/pixel detail）
        def _progress_callback(
            processed: int, total: int, detail: dict | None = None
        ) -> None:
            if ctx.logger_adapter is None:
                return
            detail = detail or {}
            chunks_done = int(detail.get("chunks_done", 0) or 0)
            chunks_total = int(detail.get("chunks_total", 0) or 0)
            pixels_done = int(detail.get("pixels_done", processed) or 0)
            pixels_total = int(detail.get("pixels_total", total) or 0)
            phase = str(detail.get("phase") or "inversion")
            msg = (
                f"chunk {chunks_done}/{chunks_total} · "
                f"pixel {pixels_done}/{pixels_total} · {phase}"
                if chunks_total
                else f"Pixel {processed}/{total}"
            )
            # Prefer chunk progress so early chunks do not round to 0%
            # against a multi-million-pixel grid denominator.
            if chunks_total > 0:
                ratio = max(0.0, min(1.0, chunks_done / chunks_total))
            elif pixels_total > 0:
                ratio = max(0.0, min(1.0, pixels_done / pixels_total))
            elif total > 0:
                ratio = max(0.0, min(1.0, processed / total))
            else:
                ratio = 0.0
            emit = ctx.logger_adapter.emit_progress
            try:
                emit("omega_sf_fenkuai", ratio, msg, detail=detail)
            except TypeError:
                emit("omega_sf_fenkuai", ratio, msg)

        # 执行主反演（或缓存短路）
        if cached_paths:
            import numpy as np
            from algorithms.omega_sf import OmegaSfResult

            n_blocks = sum(1 for k in cached_paths if k.startswith("block_") and k != "block_dir")
            # 成功像元数用占位（产品已可用）；避免 0 触发 coverage_gap
            result = OmegaSfResult(
                omega_pft=np.array([]),
                omega_pixel_map=np.zeros(grid_shape, dtype=np.float64),
                omega_pixel_count=np.zeros(grid_shape, dtype=np.int32),
                sm_maps={i: np.zeros(grid_shape) for i in range(n_blocks)},
                vod_maps={i: np.zeros(grid_shape) for i in range(n_blocks)},
                omega_maps={i: np.zeros(grid_shape) for i in range(n_blocks)},
                n_pixels_total=int(np.prod(grid_shape)),
                n_pixels_success=max(n_blocks, 1),
                n_pixels_failed=0,
                output_paths=cached_paths,
            )
        else:
            result = retrieve_omega_sf_daily(
                config=config,
                smap_folder=str(datasource_selection["smap_folder"]),
                anc_root=str(datasource_selection["anc_root"]),
                ndvi_clim_folder=ndvi_clim_folder,
                ndvi_folder=ndvi_folder,
                fy3d_folder=fy3d_folder,
                fy3b_folder=fy3b_folder,
                gldas_mat_folder=gldas_mat_folder,
                gldas_template_mat=gldas_template_mat,
                ddca_sm_folder=ddca_sm_folder,
                grid_shape=grid_shape,
                output_dir=str(output_dir),
                progress_callback=_progress_callback,
                cancel_flag_path=cancel_flag_path,
                reuse_block_cache=bool(reuse_block_cache),
            )
            # 成功后写入内容键缓存，供后续同窗复用
            if reuse_block_cache and int(result.n_pixels_success or 0) > 0:
                configured_output_dir = output_spec_extra.get("output_dir")
                output_root = (
                    Path(str(configured_output_dir))
                    if isinstance(configured_output_dir, str)
                    and configured_output_dir.strip()
                    else ctx.workspace / "products" / "omega_sf_fenkuai"
                )
                _publish_blocks_to_content_cache(
                    output_root=output_root,
                    output_dir=output_dir,
                    start_date=config.start_date,
                    end_date=config.end_date,
                    tb_source=str(config.tb_source),
                    sm_source=str(config.sm_source),
                )

        # Fail-closed：零有效像元仍写全 NaN 块文件时，桥接层会标 success 并
        # 物化「空白」图层 → 用户看到「已完成但地图无显示」。无有效像元视为失败。
        if int(result.n_pixels_success or 0) <= 0:
            message = (
                "error_code=coverage_gap "
                f"SF 反演无有效像元（0/{int(result.n_pixels_total or 0)} succeeded；"
                f"TB_SOURCE={config.tb_source}, SM_SOURCE={config.sm_source}, "
                f"{config.start_date}~{config.end_date}）。"
                "请检查该时间窗 FY/SMAP/辅助数据是否对齐可用，勿将空结果当成功上图。"
            )
            if ctx.logger_adapter is not None:
                try:
                    ctx.logger_adapter.emit_stage_end("omega_sf_fenkuai", message)
                except Exception:
                    pass
            raise ValueError(message)

        # 构建三个产品图层引用
        products: list[ProductRef] = []

        # omega_pixel / omega_pft 是反演中间诊断产物；地图仅发布块级
        # SM / VOD / OMEGA，以保证一个 workflow run 对应一个三层时间序列组。

        # OMEGA PFT 图层
        omega_pft_path = result.output_paths.get("omega_pft", "")
        if omega_pft_path:
            products.append(
                ProductRef(
                    name="omega_sf_omega_pft",
                    type="omega_sf_omega_pft",
                    uri=omega_pft_path,
                    variable="OMEGA",
                    tags={"module": self.name, "layer": "OMEGA_PFT"},
                )
            )

        # 块级 SM / VOD / OMEGA 目录
        block_dir = result.output_paths.get("block_dir", "")
        if block_dir:
            products.append(
                ProductRef(
                    name="omega_sf_sm_blocks",
                    type="omega_sf_sm_block_dir",
                    uri=block_dir,
                    variable="SM",
                    tags={"module": self.name, "layer": "SM"},
                )
            )
            products.append(
                ProductRef(
                    name="omega_sf_vod_blocks",
                    type="omega_sf_vod_block_dir",
                    uri=block_dir,
                    variable="VOD",
                    tags={"module": self.name, "layer": "VOD"},
                )
            )
            products.append(
                ProductRef(
                    name="omega_sf_omega_blocks",
                    type="omega_sf_omega_block_dir",
                    uri=block_dir,
                    variable="OMEGA",
                    tags={"module": self.name, "layer": "OMEGA"},
                )
            )

        if ctx.logger_adapter is not None:
            for product in products:
                ctx.logger_adapter.emit_artifact(
                    "omega_sf_fenkuai", product.uri, product.type
                )
            ctx.logger_adapter.emit_stage_end(
                "omega_sf_fenkuai",
                f"SF block inversion completed: "
                f"{result.n_pixels_success}/{result.n_pixels_total} pixels succeeded, "
                f"{len(result.sm_maps)} blocks generated",
            )

        manifest = ProductManifest(
            job_id=ctx.request.job_id,
            run_id=ctx.runtime_context.run_id,
            products=products,
            main_layers=["SM", "VOD", "OMEGA"],
            metadata_uri=None,
            extra={
                "module_name": self.name,
                "output_dir": str(output_dir),
                "tb_source": config.tb_source,
                "sm_source": config.sm_source,
                "fy_platform": config.fy_platform,
                "temp_scheme": config.temp_scheme,
                "sf_mode": config.sf_mode,
                "ndvi_mode": config.ndvi_mode,
                "omega_fixed_mode": config.omega_fixed_mode,
                "start_date": config.start_date,
                "end_date": config.end_date,
                "block_days": config.block_days,
                "n_pixels_total": result.n_pixels_total,
                "n_pixels_success": result.n_pixels_success,
                "n_pixels_failed": result.n_pixels_failed,
                "n_blocks": len(result.sm_maps),
                "grid_shape": list(grid_shape),
                "freq_ghz": config.freq_ghz,
            },
        )
        return _store_manifest(
            ctx,
            module_name=self.name,
            manifest=manifest,
            metadata={
                "product_count": len(products),
                "n_pixels_success": result.n_pixels_success,
                "n_pixels_total": result.n_pixels_total,
                "n_blocks": len(result.sm_maps),
            },
        )
