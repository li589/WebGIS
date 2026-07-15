"""数据导出模块 — 将上游产物或独立文件导出为 MAT/NetCDF/GeoTIFF/CSV 格式。

支持输入:
  - manifest (上游模块产物，含 ProductManifest)
  - datasource_selection (独立文件路径: input_path 或 input_dir)

支持导出格式 (algorithm_params["format"]):
  - mat:     MAT v5/v6 (scipy.io.savemat)
  - netcdf:  NetCDF4 (netCDF4.Dataset)
  - geotiff: Cloud-Optimized GeoTIFF (rasterio)
  - csv:     CSV 表格 (pandas)

可选参数:
  - variables: 逗号分隔的变量名列表 (仅导出指定变量)
  - output_dir: 输出目录 (默认 ctx.workspace / "products" / "export")
"""
from __future__ import annotations

from pathlib import Path

from contracts.product import ProductManifest, ProductRef
from data_access.universal_reader import UniversalDataReader
from modules.base import BaseModule
from modules.registry import register_module_decorator
from workflow.schemas import ArtifactRef, NodeExecutionContext, PortSpec


def _store_manifest(
    ctx: NodeExecutionContext,
    *,
    module_name: str,
    manifest: ProductManifest,
    metadata: dict[str, object],
) -> dict[str, object]:
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


def _collect_input_files(inputs: dict[str, object]) -> list[Path]:
    """从 manifest 或 datasource_selection 收集待导出的源文件路径。"""
    files: list[Path] = []

    # 优先从上游 manifest 提取产物文件
    manifest_artifact = inputs.get("manifest")
    if manifest_artifact is not None:
        # manifest_artifact 可能是 ArtifactRef，需从 artifact_store 加载
        try:
            artifact_id = getattr(manifest_artifact, "artifact_id", None)
            if artifact_id and hasattr(ctx_ref := inputs, "get"):
                pass  # ctx 不可在此获取，留到 execute 中处理
        except Exception:
            pass

    # 从 datasource_selection 提取文件路径
    datasource_selection = dict(inputs.get("datasource_selection", {}))
    input_path = datasource_selection.get("input_path")
    if input_path:
        p = Path(str(input_path))
        if p.is_file():
            files.append(p)
        elif p.is_dir():
            files.extend(sorted(p.glob("**/*.mat")))
            files.extend(sorted(p.glob("**/*.nc")))
            files.extend(sorted(p.glob("**/*.h5")))
            files.extend(sorted(p.glob("**/*.tif")))

    input_dir = datasource_selection.get("input_dir")
    if input_dir:
        d = Path(str(input_dir))
        if d.is_dir():
            for ext in ("*.mat", "*.nc", "*.h5", "*.tif"):
                files.extend(sorted(d.glob(ext)))

    # 去重
    seen: set[str] = set()
    unique: list[Path] = []
    for f in files:
        key = str(f)
        if key not in seen:
            seen.add(key)
            unique.append(f)
    return unique


def _export_to_mat(data_dict: dict, output_path: Path) -> None:
    from scipy.io import savemat
    savemat(output_path, data_dict, do_compression=True)


def _export_to_netcdf(data_dict: dict, output_path: Path) -> None:
    from netCDF4 import Dataset
    import numpy as np

    with Dataset(output_path, "w", format="NETCDF4") as ds:
        for name, arr in data_dict.items():
            if not isinstance(arr, np.ndarray):
                continue
            if arr.ndim == 0:
                continue
            # 创建维度
            dims = [f"{name}_dim_{i}" for i in range(arr.ndim)]
            for i, (d, s) in enumerate(zip(dims, arr.shape)):
                ds.createDimension(d, s)
            var = ds.createVariable(name, arr.dtype, dimensions=dims)
            var[:] = arr


def _export_to_geotiff(data_dict: dict, output_path: Path, transform=None) -> None:
    import numpy as np
    import rasterio
    from rasterio.transform import from_bounds

    # 仅导出第一个二维数组
    for name, arr in data_dict.items():
        if isinstance(arr, np.ndarray) and arr.ndim == 2:
            height, width = arr.shape
            if transform is None:
                transform = from_bounds(-180.0, -90.0, 180.0, 90.0, width, height)
            with rasterio.open(
                output_path, "w",
                driver="GTiff",
                height=height,
                width=width,
                count=1,
                dtype=arr.dtype,
                crs="EPSG:4326",
                transform=transform,
            ) as dst:
                dst.write(arr.astype(np.float32), 1)
            return


def _export_to_csv(data_dict: dict, output_path: Path) -> None:
    import numpy as np
    try:
        import pandas as pd
        rows = {}
        for name, arr in data_dict.items():
            if isinstance(arr, np.ndarray):
                rows[name] = arr.ravel()
        df = pd.DataFrame({k: pd.Series(v) for k, v in rows.items() if len(v) > 0})
        df.to_csv(output_path, index=False)
        return
    except ImportError:
        pass
    # 纯 numpy 降级
    import csv
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        for name, arr in data_dict.items():
            if isinstance(arr, np.ndarray):
                writer.writerow([name] + arr.ravel().tolist())


@register_module_decorator(name="data_export", aliases=["data_export_pipeline"])
class DataExportModule(BaseModule):
    name = "data_export"
    description = "Export upstream products or standalone files to MAT/NetCDF/GeoTIFF/CSV formats."
    input_ports = [
        PortSpec(name="manifest", kind="artifact", data_class="product_manifest", required=False),
        PortSpec(name="datasource_selection", kind="config", data_class="dict", required=False),
        PortSpec(name="algorithm_params", kind="config", data_class="dict", required=False),
        PortSpec(name="output_spec_extra", kind="config", data_class="dict", required=False),
    ]
    output_ports = [PortSpec(name="manifest", kind="artifact", data_class="product_manifest")]

    def execute(self, inputs: dict[str, object], params: dict[str, object], ctx: NodeExecutionContext) -> dict[str, object]:
        algorithm_params = dict(inputs.get("algorithm_params", {}))
        output_spec_extra = dict(inputs.get("output_spec_extra", {}))

        export_format = str(algorithm_params.get("format", "mat")).lower()
        variables_filter = str(algorithm_params.get("variables", "")).strip()
        variable_names = [v.strip() for v in variables_filter.split(",") if v.strip()] if variables_filter else []

        output_dir = Path(output_spec_extra.get("output_dir", ctx.workspace / "products" / "export"))
        output_dir.mkdir(parents=True, exist_ok=True)

        # 收集源文件
        input_files = _collect_input_files(inputs)

        # 也从 manifest artifact 提取产物 URI
        manifest_artifact = inputs.get("manifest")
        if manifest_artifact is not None:
            try:
                loaded = ctx.artifact_store.load(getattr(manifest_artifact, "artifact_id", ""))
                if isinstance(loaded, ProductManifest):
                    for product in loaded.products:
                        if product.uri:
                            p = Path(product.uri)
                            if p.is_file() and p not in input_files:
                                input_files.append(p)
            except Exception:
                pass

        if not input_files:
            raise ValueError("data_export: 未找到输入文件 (需要 manifest 或 datasource_selection.input_path/input_dir)")

        if ctx.logger_adapter is not None:
            ctx.logger_adapter.emit_stage_start("data_export", f"Export {len(input_files)} files to {export_format}")

        products: list[ProductRef] = []
        for src_path in input_files:
            try:
                reader = UniversalDataReader(src_path)
                available_vars = reader.list_variables()
                target_vars = variable_names if variable_names else available_vars[:5]
                data_dict: dict[str, object] = {}
                for var_name in target_vars:
                    if var_name in available_vars or src_path.suffix.lower() in (".tif", ".tiff"):
                        try:
                            da = reader.read_variable(variable=var_name if src_path.suffix.lower() not in (".tif", ".tiff") else None)
                            data_dict[var_name] = da.values
                        except Exception:
                            continue

                if not data_dict:
                    continue

                out_name = src_path.stem
                if export_format == "mat":
                    out_path = output_dir / f"{out_name}.mat"
                    _export_to_mat(data_dict, out_path)
                elif export_format == "netcdf":
                    out_path = output_dir / f"{out_name}.nc"
                    _export_to_netcdf(data_dict, out_path)
                elif export_format == "geotiff":
                    out_path = output_dir / f"{out_name}.tif"
                    _export_to_geotiff(data_dict, out_path)
                elif export_format == "csv":
                    out_path = output_dir / f"{out_name}.csv"
                    _export_to_csv(data_dict, out_path)
                else:
                    raise ValueError(f"不支持的导出格式: {export_format} (可选 mat|netcdf|geotiff|csv)")

                products.append(ProductRef(
                    name=out_name,
                    type=f"exported_{export_format}",
                    uri=str(out_path),
                    variable=",".join(data_dict.keys()),
                    tags={"source": src_path.name, "format": export_format},
                ))
                if ctx.logger_adapter is not None:
                    ctx.logger_adapter.emit_artifact("data_export", str(out_path), f"exported_{export_format}")
            except Exception as e:
                if ctx.logger_adapter is not None:
                    ctx.logger_adapter.emit_artifact("data_export", str(src_path), f"error: {e}")
                continue

        if ctx.logger_adapter is not None:
            ctx.logger_adapter.emit_stage_end("data_export", f"Exported {len(products)} files to {export_format}")

        manifest = ProductManifest(
            job_id=ctx.request.job_id,
            run_id=ctx.runtime_context.run_id,
            products=products,
            main_layers=[p.name for p in products],
            metadata_uri=None,
            extra={
                "module_name": self.name,
                "output_dir": str(output_dir),
                "format": export_format,
                "count": len(products),
            },
        )
        return _store_manifest(ctx, module_name=self.name, manifest=manifest, metadata={
            "product_count": len(products),
            "format": export_format,
        })
