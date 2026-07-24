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
}


def _resolve_omega_avg_datasource_selection(
    datasource_selection: dict[str, object],
) -> dict[str, object]:
    """解析 D2 数据源选择：先复用 daily bundle 键映射，再解析 omega_avg 专有键。"""
    from modules.bundles import _resolve_bundle_datasource_selection

    # 1. 复用 daily bundle 键映射（anc_root / smap_folder / ndvi_folder / lin_pix_mat 等）
    resolved = _resolve_bundle_datasource_selection(dict(datasource_selection))

    # 2. 解析 omega_avg 专有键（omega_block_dir / avg_omega_doy_dir / omega_block_mat）
    for target_key, dataset_names in _OMEGA_AVG_DATASOURCE_KEY_MAP.items():
        if target_key in resolved and resolved[target_key]:
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


@register_module_decorator(name="omega_avg_daily", aliases=["omega_avg_daily_pipeline"])
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

        _ = params
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

        # 解析输出目录
        output_dir = Path(
            output_spec_extra.get(
                "output_dir", ctx.workspace / "products" / "omega_avg_daily"
            )
        )
        output_dir.mkdir(parents=True, exist_ok=True)

        # 解析 omega_block 目录与 .mat 文件
        omega_block_dir = Path(str(datasource_selection["omega_block_dir"]))
        omega_block_mat_path = datasource_selection.get("omega_block_mat")
        if omega_block_mat_path:
            omega_block_mat_path = Path(str(omega_block_mat_path))
        else:
            omega_block_mat_path = _find_omega_block_mat(omega_block_dir)
        if omega_block_mat_path is None or not omega_block_mat_path.exists():
            raise FileNotFoundError(
                f"omega_block_*.mat not found under {omega_block_dir}; "
                "ensure D1 omega_block has run"
            )

        # DOY 气候态缓存目录
        avg_omega_doy_dir = datasource_selection.get("avg_omega_doy_dir")
        if avg_omega_doy_dir:
            avg_omega_doy_dir = Path(str(avg_omega_doy_dir))
        else:
            avg_omega_doy_dir = output_dir / "avg_omega_doy"

        if ctx.logger_adapter is not None:
            ctx.logger_adapter.emit_stage_start(
                "omega_avg_daily",
                f"D2 avg-omega daily retrieval for year {target_year}",
            )

        # Stage A+B: 构建 DOY 气候态（若缺失或强制重建）
        build_years = list(
            range(config.avg_build_start_year, config.avg_build_end_year + 1)
        )
        doy_files_exist = any(avg_omega_doy_dir.glob("doy_*.mat"))
        if config.force_rebuild_avg or not doy_files_exist:
            if not doy_files_exist or config.force_rebuild_avg:
                cache_dir = output_dir / "raw_omega_cache"
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
        )

        # 构建 manifest
        days_processed = int(stage_d_result.get("days_processed", 0))
        products: list[ProductRef] = []
        if days_processed > 0:
            # 汇总产品：目标年的逐日 SM/VOD/OMEGA 目录
            products.append(
                ProductRef(
                    name=f"omega_avg_daily_{target_year}",
                    type="omega_avg_daily_dir",
                    uri=str(output_dir),
                    variable="SM",
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
            },
        )
        return _store_manifest(
            ctx,
            module_name=self.name,
            manifest=manifest,
            metadata={"product_count": len(products), "days_processed": days_processed},
        )
