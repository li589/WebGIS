from __future__ import annotations

from pathlib import Path
from typing import Any

from data_access.contracts import ResourceRef
from data_access.format_adapters.base import LocalFileFormatAdapter


class MatFormatAdapter(LocalFileFormatAdapter):
    name = "mat"
    supported_formats = ("mat",)

    def load(self, resource: ResourceRef) -> dict[str, object]:
        local_path = self._require_local_path(resource)
        # 尝试 scipy.io.whosmat (v5/v6)
        try:
            from scipy.io import whosmat
            info = whosmat(local_path)
            variables = tuple(
                {
                    "name": str(name),
                    "shape": tuple(shape),
                    "matlab_class": str(matlab_class),
                }
                for name, shape, matlab_class in info
            )
            return {
                "path": str(local_path),
                "mat_version": "v5/v6",
                "variable_names": tuple(variable["name"] for variable in variables),
                "variables": variables,
            }
        except NotImplementedError:
            # v7.3 文件 (HDF5-based)，使用 h5py
            return _load_mat_v73(local_path)


def _load_mat_v73(local_path: Path) -> dict[str, object]:
    """读取 MAT v7.3 文件 (HDF5 格式)。"""
    import h5py

    variables: list[dict[str, Any]] = []
    with h5py.File(local_path, "r") as handle:
        # 收集根级数据集
        def _collect(name: str, node: h5py.Dataset | h5py.Group) -> None:
            if isinstance(node, h5py.Dataset):
                variables.append(
                    {
                        "name": str(name),
                        "shape": tuple(node.shape),
                        "matlab_class": str(node.dtype),
                    }
                )

        handle.visititems(_collect)
    return {
        "path": str(local_path),
        "mat_version": "v7.3",
        "variable_names": tuple(variable["name"] for variable in variables),
        "variables": tuple(variables),
    }
