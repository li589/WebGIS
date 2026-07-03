from __future__ import annotations

from typing import Any

import h5py

from data_access.contracts import ResourceRef
from data_access.format_adapters.base import LocalFileFormatAdapter


class HdfFormatAdapter(LocalFileFormatAdapter):
    name = "hdf5"
    supported_formats = ("hdf", "h5")

    def load(self, resource: ResourceRef) -> dict[str, object]:
        local_path = self._require_local_path(resource)
        group_names: list[str] = []
        datasets: list[dict[str, Any]] = []
        with h5py.File(local_path, "r") as handle:
            handle.visititems(lambda name, node: _collect_hdf_item(name, node, group_names, datasets))
        return {
            "path": str(local_path),
            "group_names": tuple(group_names),
            "dataset_names": tuple(dataset["name"] for dataset in datasets),
            "datasets": tuple(datasets),
        }


def _collect_hdf_item(
    name: str,
    node: h5py.Dataset | h5py.Group,
    group_names: list[str],
    datasets: list[dict[str, Any]],
) -> None:
    if isinstance(node, h5py.Group):
        if name:
            group_names.append(str(name))
        return
    datasets.append(
        {
            "name": str(name),
            "shape": tuple(node.shape),
            "dtype": str(node.dtype),
        }
    )
