"""D2 avg-omega 逐日反演模块编排。

``OmegaAvgDailyModule`` 编排 D2 四阶段流水线（见 ``algorithms/omega_avg.py``）：
Stage A 逐日 OMEGA 缓存 → Stage B DOY 气候态 → Stage C h/alpha 提取 →
Stage D 逐日 DDCA 回代（omega 固定为 OMEGA_AVG）。

数据源解析复用 ``modules/bundles.py`` 的 daily bundle 键映射（anc_root /
smap_folder / ndvi_folder 等），并追加 omega_avg 专有键（omega_block_dir /
avg_omega_doy_dir / omega_block_mat）。
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


# omega_avg 专有数据源键映射（daily bundle 键复用 bundles.py 的映射）
_OMEGA_AVG_DATASOURCE_KEY_MAP: dict[str, tuple[str, ...]] = {
    "omega_block_dir": ("omega_block_dir", "omega_block_output", "daily_omega_dir"),
    "avg_omega_doy_dir": ("avg_omega_doy_dir", "avg_omega_cache"),
    "omega_block_mat": ("omega_block_mat", "omega_block_result"),
    # DUAL 双温度：GLDAS 三温度目录 + 可选 UTC 过境模板（与 omega_sf_fenkuai 对齐）
    "gldas_mat_folder": ("gldas_mat_folder", "gldas_mat", "daily_mat_sources"),
    "gldas_template_mat": ("gldas_template_mat", "gldas_template", "daily_mat_sources"),
}


def _resolve_omega_avg_datasource_selection(
    datasource_selection: dict[str, object],
) -> dict[str, object]:
    """解析 D2 数据源选择：先复用 daily bundle 键映射，再解析 omega_avg 专有键。"""
    from modules.bundles import (
        _path_from_datasource_value,
        _resolve_bundle_datasource_selection,
    )

    # 1. 复用 daily bundle 键映射（anc_root / smap_folder / ndvi_folder / lin_pix_mat 等）
    resolved = _resolve_bundle_datasource_selection(dict(datasource_selection))

    # 2. 解析 omega_avg 专有键（omega_block_dir / avg_omega_doy_dir / omega_block_mat）
    for target_key, dataset_names in _OMEGA_AVG_DATASOURCE_KEY_MAP.items():
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


def _find_omega_block_mat(omega_block_dir: str | Path) -> Path | None:
    """在 omega_block 输出目录中查找 omega_block_{start}_{end}.mat 文件。"""
    omega_block_dir = Path(omega_block_dir)
    if not omega_block_dir.exists():
        return None
    # 优先直接在目录下查找
    candidates = sorted(omega_block_dir.glob("omega_block_*.mat"))
    if candidates:
        return candidates[-1]
    # 退化：查找 daily_omega 父目录
    parent = omega_block_dir.parent
    candidates = sorted(parent.glob("omega_block_*.mat"))
    if candidates:
        return candidates[-1]
    return None


def _redirect_omega_block_for_tb_source(
    omega_block_dir: Path,
    omega_block_mat_path: Path | None,
    tb_source: str,
    *,
    logger_adapter: object = None,
) -> tuple[Path, Path | None]:
    """tb_source != SMAP 时优先使用 tb 专属 omega_block 目录（2026-10-07）。

    历史问题：D1(FY) 与 D1(SMAP) 共写同一 ``Inversion_Results/omega_block``，
    交替跑两条链会互相覆盖 daily_omega 与 h/alpha（``_find_omega_block_mat``
    恒取字典序最新块）⇒ SMAP 在线链拿到 FY 的产物（或反之）。D1 侧已按
    tb_source 分目录落盘（见 ``modules/omega.py``）；本函数在 D2 消费侧做
    同步重定向：tb 专属目录**存在**才切换（兼容尚无 FY 专属目录的存量环境，
    此时保持原路径并原样工作）。
    """
    tb = tb_source.strip().upper()
    if tb in ("", "SMAP"):
        return omega_block_dir, omega_block_mat_path
    candidate = omega_block_dir.with_name(f"{omega_block_dir.name}_{tb.lower()}")
    if candidate.is_dir() and candidate != omega_block_dir:
        if logger_adapter is not None:
            try:
                logger_adapter.emit_stage_start(
                    "omega_avg_daily",
                    f"omega_block dir redirected for tb_source={tb}: "
                    f"{omega_block_dir} -> {candidate}",
                )
            except Exception:  # noqa: BLE001 - 日志失败不阻断主链
                pass
        redirected_mat = omega_block_mat_path
        if redirected_mat is not None:
            try:
                rel = redirected_mat.relative_to(omega_block_dir)
                redirected_mat = candidate / rel
            except ValueError:
                pass  # mat 不在共享目录下（显式指定），保持原样
        return candidate, redirected_mat
    return omega_block_dir, omega_block_mat_path


def _doy_cache_stale(
    omega_block_dir: Path, avg_omega_doy_dir: Path
) -> bool:
    """daily_omega 比已缓存 DOY 气候态新 → 需要增量重建（2026-10-07）。

    持久缓存（Fix：DOY 气候态不再放 run workspace）引入的新语义：缓存命中后
    D1 新产出的 daily_omega 不应被无视。以 ``daily_omega/*.mat`` 的最大 mtime
    对比 ``doy_*.mat`` 的最小 mtime 判断是否过期；目录缺失按"未过期"处理
    （调用方已有 missing 分支）。
    """
    daily_dir = Path(omega_block_dir) / "daily_omega"
    if not daily_dir.is_dir() or not avg_omega_doy_dir.is_dir():
        return False
    newest_daily = 0.0
    try:
        for entry in daily_dir.iterdir():
            if entry.suffix.lower() == ".mat":
                newest_daily = max(newest_daily, entry.stat().st_mtime)
    except OSError:
        return False
    if newest_daily <= 0.0:
        return False
    oldest_doy = None
    try:
        for entry in avg_omega_doy_dir.iterdir():
            if entry.name.startswith("doy_") and entry.suffix.lower() == ".mat":
                mtime = entry.stat().st_mtime
                oldest_doy = mtime if oldest_doy is None else min(oldest_doy, mtime)
    except OSError:
        return False
    if oldest_doy is None:
        return False
    return newest_daily > oldest_doy + 1.0  # 1s 容差，抗拷贝时间戳抖动


@register_module_decorator(
    name="omega_avg_daily",
    aliases=["omega_avg_daily_pipeline"],
    template_overrides={"phase": "inversion"},
)
class OmegaAvgDailyModule(BaseModule):
    name = "omega_avg_daily"
    description = (
        "Native module that runs D2 avg-omega daily retrieval: build DOY climatology "
        "from D1 omega_block output, then per-day DDCA with averaged omega."
    )
    mode_required_inputs = {
        "omega_avg_daily": (
            "omega_block_dir",
            "anc_root",
            "smap_folder",
            "ndvi_folder",
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
            name="smap_daily_mat",
            kind="data",
            data_class="mat",
            required=False,
            severity="soft",
            description=(
                "SMAP 日常 mat 上游产物（smap_daily 转换后落盘目录；与模板 data:mat 对齐）；"
                "用于建立转换→反演执行序依赖，数据读取仍走 datasource_selection。"
            ),
        ),
        PortSpec(
            name="fy_daily_mat",
            kind="data",
            data_class="mat",
            required=False,
            severity="soft",
            description=(
                "FY 日常 mat 上游产物（fy_daily 转换后落盘目录；与模板 data:mat 对齐）；"
                "用于建立转换→反演执行序依赖，数据读取仍走 datasource_selection。"
            ),
        ),
        PortSpec(
            name="gldas_mat",
            kind="data",
            data_class="mat",
            required=False,
            severity="soft",
            description=(
                "GLDAS 温度 mat 上游产物（gldas_nc4_to_mat 转换后落盘目录；与模板 data:mat 对齐）；"
                "用于建立转换→反演执行序依赖，数据读取仍走 datasource_selection。"
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
        from algorithms.omega_avg import (
            build_doy_omega_climatology,
            build_omega_avg_config,
            build_raw_omega_daily_cache,
            extract_halpha_maps,
            retrieve_daily_with_avg_omega,
        )
        from ingest.daily_bundle import (
            build_daily_bundle_config,
            load_lin_pix_selection,
        )

        datasource_selection = _resolve_omega_avg_datasource_selection(
            dict(inputs.get("datasource_selection", {}))
        )
        algorithm_params = dict(inputs.get("algorithm_params", {}))
        output_spec_extra = dict(inputs.get("output_spec_extra", {}))

        # 必需键校验
        missing_keys = [
            key
            for key in ("omega_block_dir", "anc_root", "smap_folder", "ndvi_folder")
            if not datasource_selection.get(key)
        ]
        if missing_keys:
            raise ValueError(
                f"omega_avg_daily requires datasource_selection keys: "
                f"{', '.join(sorted(missing_keys))}"
            )

        # 构建 D2 + daily bundle 配置
        config = build_omega_avg_config(algorithm_params)
        daily_bundle_config = build_daily_bundle_config(algorithm_params)
        target_year = int(
            algorithm_params.get("target_year", config.avg_build_end_year)
        )

        # 解析 lin_pix
        lin_pix = load_lin_pix_selection(
            lin_pix=algorithm_params.get("lin_pix"),
            lin_pix_mat=datasource_selection.get("lin_pix_mat"),
        )

        # 解析 grid_shape
        grid_shape = _resolve_grid_shape(algorithm_params, datasource_selection)

        # 解析输出目录：显式 reuse_output_dir（失败重试复用）优先，
        # 其次节点属性 output_dir、request output_spec_extra，缺省 run 工作区。
        # 按 tb_source 分目录，避免 FY 误 resume SMAP 旧日产物（地图空白 / 点查 N/A）。
        tb_source = (
            str(
                getattr(daily_bundle_config, "tb_source", None)
                or algorithm_params.get("tb_source")
                or "SMAP"
            )
            .strip()
            .upper()
            or "SMAP"
        )
        product_subdir = f"omega_avg_daily_{tb_source.lower()}"
        reuse_output_dir = algorithm_params.get("reuse_output_dir")
        if isinstance(reuse_output_dir, str) and reuse_output_dir.strip():
            output_dir = Path(reuse_output_dir.strip())
        else:
            output_dir = Path(
                str(params.get("output_dir") or "").strip()
                or output_spec_extra.get("output_dir")
                or (ctx.workspace / "products" / product_subdir)
            )
        output_dir.mkdir(parents=True, exist_ok=True)

        # 解析 omega_block 目录与 .mat 文件（先探测，tb 重定向后再做硬校验）
        omega_block_dir = Path(str(datasource_selection["omega_block_dir"]))
        omega_block_mat_path = datasource_selection.get("omega_block_mat")
        if omega_block_mat_path:
            omega_block_mat_path = Path(str(omega_block_mat_path))
        else:
            omega_block_mat_path = _find_omega_block_mat(omega_block_dir)

        # tb_source != SMAP 时重定向到 tb 专属 omega_block 目录（与 D1 侧
        # modules/omega.py 的分目录落盘配对，消除 FY/SMAP 互相覆盖）。
        omega_block_dir, omega_block_mat_path = _redirect_omega_block_for_tb_source(
            omega_block_dir,
            omega_block_mat_path,
            tb_source,
            logger_adapter=ctx.logger_adapter,
        )
        if omega_block_mat_path is None or not omega_block_mat_path.exists():
            omega_block_mat_path = _find_omega_block_mat(omega_block_dir)
        if omega_block_mat_path is None or not omega_block_mat_path.exists():
            raise FileNotFoundError(
                f"omega_block_*.mat not found under {omega_block_dir}; "
                "ensure D1 omega_block has run"
            )

        # DOY 气候态缓存目录：默认挂到 omega_block 输出目录下（**持久共享**，
        # 按 tb_source + 构建年份窗口键控），跨 run 复用；2026-10-07 之前默认
        # 在 run workspace 下导致每次全新 run 全量重建 Stage A+B。
        avg_omega_doy_dir = datasource_selection.get("avg_omega_doy_dir")
        if avg_omega_doy_dir:
            avg_omega_doy_dir = Path(str(avg_omega_doy_dir))
        else:
            avg_omega_doy_dir = (
                omega_block_dir
                / "doy_clim"
                / f"{tb_source.lower()}_{config.avg_build_start_year}_{config.avg_build_end_year}"
            )

        if ctx.logger_adapter is not None:
            ctx.logger_adapter.emit_stage_start(
                "omega_avg_daily",
                f"D2 avg-omega daily retrieval for year {target_year}",
            )

        # Stage A+B: 构建 DOY 气候态。持久缓存语义：缓存存在即跳过重建，
        # 但 daily_omega 有比缓存更新的产物时增量重建（_doy_cache_stale）。
        build_years = list(
            range(config.avg_build_start_year, config.avg_build_end_year + 1)
        )
        doy_files_exist = any(avg_omega_doy_dir.glob("doy_*.mat"))
        cache_stale = (not config.force_rebuild_avg) and _doy_cache_stale(
            omega_block_dir, avg_omega_doy_dir
        )
        if config.force_rebuild_avg or not doy_files_exist or cache_stale:
            if not doy_files_exist or config.force_rebuild_avg or cache_stale:
                cache_dir = (
                    omega_block_dir
                    / "raw_omega_cache"
                    / f"{tb_source.lower()}_{config.avg_build_start_year}_{config.avg_build_end_year}"
                )
                build_raw_omega_daily_cache(
                    omega_block_dir=omega_block_dir,
                    output_cache_dir=cache_dir,
                    years=build_years,
                    grid_shape=grid_shape,
                )
                build_doy_omega_climatology(
                    cache_dir=cache_dir,
                    output_doy_dir=avg_omega_doy_dir,
                    years=build_years,
                    grid_shape=grid_shape,
                )

        # Stage C: 提取 h/alpha map
        h_map, alpha_map = extract_halpha_maps(omega_block_mat_path, grid_shape)

        # Stage D: 逐日 DDCA 回代
        cancel_flag_path = algorithm_params.get("cancel_flag_path")
        if not cancel_flag_path:
            cancel_flag_path = ctx.runtime_context.env.get("cancel_flag_path")
        if not cancel_flag_path:
            cancel_flag_path = str(ctx.runtime_context.tmp_dir / "cancel.requested")

        stage_d_result = retrieve_daily_with_avg_omega(
            target_year=target_year,
            omega_avg_doy_dir=avg_omega_doy_dir,
            h_map=h_map,
            alpha_map=alpha_map,
            datasource_selection=datasource_selection,
            config=config,
            daily_bundle_config=daily_bundle_config,
            lin_pix=lin_pix,
            grid_shape=grid_shape,
            output_dir=output_dir,
            logger_adapter=ctx.logger_adapter,
            cancel_flag_path=cancel_flag_path,
        )

        # 构建 manifest
        days_processed = int(stage_d_result.get("days_processed", 0))
        days_resumed = int(stage_d_result.get("days_resumed", 0))
        products: list[ProductRef] = []
        # 全量 resume（processed=0, resumed>0）也必须发布三图层，否则前端
        # materialize 只有 SM/VOD 或缺产物，cleanup 会删掉 OMEGA 占位。
        has_daily_mats = False
        try:
            has_daily_mats = any(
                path.is_file() and path.suffix.lower() == ".mat" and path.stem.isdigit()
                for path in Path(output_dir).iterdir()
            )
        except OSError:
            has_daily_mats = False
        if days_processed > 0 or days_resumed > 0 or has_daily_mats:
            # 目标年逐日 SM/VOD/OMEGA 目录：复用 omega_sf_*_block_dir 类型，
            # 单日 YYYYMMDD.mat 由物化链按一天块发布为时间序列图层。
            for variable, layer in (("SM", "SM"), ("VOD", "VOD"), ("OMEGA", "OMEGA")):
                products.append(
                    ProductRef(
                        name=f"omega_avg_{variable.lower()}_{target_year}",
                        type=f"omega_sf_{variable.lower()}_block_dir",
                        uri=str(output_dir),
                        variable=variable,
                        tags={"module": self.name, "layer": layer},
                    )
                )

        if ctx.logger_adapter is not None:
            for product in products:
                ctx.logger_adapter.emit_artifact(
                    "omega_avg_daily", product.uri, product.type
                )
            ctx.logger_adapter.emit_stage_end(
                "omega_avg_daily",
                f"Generated avg-omega daily products for {days_processed} days",
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
                "target_year": target_year,
                "days_processed": days_processed,
                "days_skipped": int(stage_d_result.get("days_skipped", 0)),
                "freq_ghz": config.freq_ghz,
                "lambda_tau": config.lambda_tau,
                "temp_scheme": str(
                    getattr(daily_bundle_config, "temp_scheme", "ORIG_TS")
                ),
                "avg_build_years": build_years,
                "stage_d_start_date": config.stage_d_start_date,
                "stage_d_end_date": config.stage_d_end_date,
                "stage_d_max_days": int(config.stage_d_max_days),
            },
        )
        return _store_manifest(
            ctx,
            module_name=self.name,
            manifest=manifest,
            metadata={"product_count": len(products), "days_processed": days_processed},
        )
