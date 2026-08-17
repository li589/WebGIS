from __future__ import annotations

from data_access.contracts import ResourceRef
from data_access.format_adapters.base import LocalFileFormatAdapter


class GribFormatAdapter(LocalFileFormatAdapter):
    name = "grib"
    supported_formats = ("grib",)

    def load(self, resource: ResourceRef) -> dict[str, object]:
        local_path = self._require_local_path(resource)
        try:
            import xarray as xr
        except ImportError as exc:  # pragma: no cover - 可选依赖环境差异
            raise RuntimeError(
                "读取 GRIB 需要安装可选依赖 xarray 与 cfgrib，请安装后重试。"
            ) from exc
        try:
            dataset = xr.open_dataset(str(local_path), engine="cfgrib")
        except Exception as exc:  # noqa: BLE001 — cfgrib 引擎/格式错误统一汇总
            raise RuntimeError(f"无法打开 GRIB 文件 {local_path}: {exc}") from exc
        try:
            variables = tuple(
                {
                    "name": str(name),
                    "dimensions": tuple(str(dim) for dim in dataset[name].dims),
                    "shape": tuple(int(size) for size in dataset[name].shape),
                    "dtype": str(dataset[name].dtype),
                }
                for name in dataset.data_vars
            )
            dimensions = {str(name): int(dataset[name].size) for name in dataset.dims}
        finally:
            dataset.close()
        return {
            "path": str(local_path),
            "dimension_names": tuple(dimensions.keys()),
            "dimensions": dimensions,
            "variable_names": tuple(variable["name"] for variable in variables),
            "variables": variables,
        }
