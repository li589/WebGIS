from __future__ import annotations


from data_access.contracts import ResourceRef
from data_access.format_adapters.base import LocalFileFormatAdapter


class NetcdfFormatAdapter(LocalFileFormatAdapter):
    name = "netcdf"
    supported_formats = ("nc",)

    def load(self, resource: ResourceRef) -> dict[str, object]:
        local_path = self._require_local_path(resource)
        try:
            return _load_with_netcdf4(local_path)
        except ImportError:
            return _load_with_scipy(local_path)


def _load_with_netcdf4(local_path) -> dict[str, object]:
    from netCDF4 import Dataset

    with Dataset(local_path) as dataset:
        dimensions = {
            name: len(dimension) for name, dimension in dataset.dimensions.items()
        }
        variables = tuple(
            {
                "name": str(name),
                "dimensions": tuple(str(value) for value in variable.dimensions),
                "shape": tuple(int(value) for value in variable.shape),
                "dtype": str(variable.dtype),
            }
            for name, variable in dataset.variables.items()
        )
    return {
        "path": str(local_path),
        "dimension_names": tuple(dimensions.keys()),
        "dimensions": dimensions,
        "variable_names": tuple(variable["name"] for variable in variables),
        "variables": variables,
    }


def _load_with_scipy(local_path) -> dict[str, object]:
    from scipy.io import netcdf_file

    with netcdf_file(local_path, "r") as dataset:
        dimensions = {str(name): int(size) for name, size in dataset.dimensions.items()}
        variables = tuple(
            {
                "name": str(name),
                "dimensions": tuple(
                    str(value) for value in getattr(variable, "dimensions", ())
                ),
                "shape": tuple(
                    int(value) for value in getattr(variable.data, "shape", ())
                ),
                "dtype": str(getattr(variable.data, "dtype", "")),
            }
            for name, variable in dataset.variables.items()
        )
    return {
        "path": str(local_path),
        "dimension_names": tuple(dimensions.keys()),
        "dimensions": dimensions,
        "variable_names": tuple(variable["name"] for variable in variables),
        "variables": variables,
    }
