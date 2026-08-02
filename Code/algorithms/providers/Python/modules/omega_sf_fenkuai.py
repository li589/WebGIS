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


# omega_sf 专有数据源键映射（daily bundle 键复用 bundles.py 的映射）
_OMEGA_SF_DATASOURCE_KEY_MAP: dict[str, tuple[str, ...]] = {
    "fy3d_folder": ("fy3d_folder", "fy_daily_mat", "daily_mat_sources"),
    "fy3b_folder": ("fy3b_folder", "fy_daily_mat", "daily_mat_sources"),
    "gldas_mat_folder": ("gldas_mat_folder", "gldas_mat", "daily_mat_sources"),
    "ddca_sm_folder": ("ddca_sm_folder", "ddca_sm", "daily_mat_sources"),
    "ndvi_clim_folder": ("ndvi_clim_folder", "ndvi_clim", "daily_mat_sources"),
}


def _resolve_omega_sf_datasource_selection(
    datasource_selection: dict[str, object],
) -> dict[str, object]:
    """解析 omega_sf 数据源选择：先复用 daily bundle 键映射，再解析 omega_sf 专有键。"""
    from modules.bundles import _resolve_bundle_datasource_selection

    # 1. 复用 daily bundle 键映射（anc_root / smap_folder / ndvi_folder / lin_pix_mat 等）
    resolved = _resolve_bundle_datasource_selection(dict(datasource_selection))

    # 2. 解析 omega_sf 专有键（fy3d_folder / fy3b_folder / gldas_mat_folder / ddca_sm_folder）
    for target_key, dataset_names in _OMEGA_SF_DATASOURCE_KEY_MAP.items():
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


@register_module_decorator(name="omega_sf_fenkuai", aliases=["omega_sf_fenkuai_pipeline"])
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

        # 构建配置
        config = OmegaSfConfig.from_params(algorithm_params)

        # 解析 grid_shape
        grid_shape = _resolve_grid_shape(algorithm_params, datasource_selection)

        # 解析输出目录
        output_dir = Path(
            output_spec_extra.get(
                "output_dir", ctx.workspace / "products" / "omega_sf_fenkuai"
            )
        )
        output_dir.mkdir(parents=True, exist_ok=True)

        # 可选数据源
        ndvi_clim_folder = str(datasource_selection.get("ndvi_clim_folder") or "")
        ndvi_folder = str(datasource_selection.get("ndvi_folder") or "")
        fy3d_folder = str(datasource_selection.get("fy3d_folder") or "")
        fy3b_folder = str(datasource_selection.get("fy3b_folder") or "")
        gldas_mat_folder = str(datasource_selection.get("gldas_mat_folder") or "")
        ddca_sm_folder = str(datasource_selection.get("ddca_sm_folder") or "")

        if ctx.logger_adapter is not None:
            ctx.logger_adapter.emit_stage_start(
                "omega_sf_fenkuai",
                f"SF block inversion: TB_SOURCE={config.tb_source}, "
                f"SM_SOURCE={config.sm_source}, "
                f"{config.start_date}~{config.end_date}",
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
            ratio = (
                pixels_done / pixels_total
                if pixels_total
                else (processed / total if total else 0.0)
            )
            emit = ctx.logger_adapter.emit_progress
            try:
                emit("omega_sf_fenkuai", ratio, msg, detail=detail)
            except TypeError:
                emit("omega_sf_fenkuai", ratio, msg)

        # 执行主反演
        result = retrieve_omega_sf_daily(
            config=config,
            smap_folder=str(datasource_selection["smap_folder"]),
            anc_root=str(datasource_selection["anc_root"]),
            ndvi_clim_folder=ndvi_clim_folder,
            ndvi_folder=ndvi_folder,
            fy3d_folder=fy3d_folder,
            fy3b_folder=fy3b_folder,
            gldas_mat_folder=gldas_mat_folder,
            ddca_sm_folder=ddca_sm_folder,
            grid_shape=grid_shape,
            output_dir=str(output_dir),
            progress_callback=_progress_callback,
        )

        # 构建三个产品图层引用
        products: list[ProductRef] = []

        # OMEGA pixel 图层
        omega_pix_path = result.output_paths.get("omega_pixel", "")
        if omega_pix_path:
            products.append(
                ProductRef(
                    name="omega_sf_omega_pixel",
                    type="omega_sf_omega_pixel",
                    uri=omega_pix_path,
                    variable="OMEGA",
                    tags={"module": self.name, "layer": "OMEGA"},
                )
            )

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
                    tags={"module": self.name, "layer": "OMEGA_BLOCK"},
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
