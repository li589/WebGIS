from __future__ import annotations

from scipy.io import whosmat

from data_access.contracts import ResourceRef
from data_access.format_adapters.base import LocalFileFormatAdapter


class MatFormatAdapter(LocalFileFormatAdapter):
    name = "mat"
    supported_formats = ("mat",)

    def load(self, resource: ResourceRef) -> dict[str, object]:
        local_path = self._require_local_path(resource)
        variables = tuple(
            {
                "name": str(name),
                "shape": tuple(shape),
                "matlab_class": str(matlab_class),
            }
            for name, shape, matlab_class in whosmat(local_path)
        )
        return {
            "path": str(local_path),
            "variable_names": tuple(variable["name"] for variable in variables),
            "variables": variables,
        }
