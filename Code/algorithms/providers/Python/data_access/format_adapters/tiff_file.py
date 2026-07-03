from __future__ import annotations

import rasterio

from data_access.contracts import ResourceRef
from data_access.format_adapters.base import LocalFileFormatAdapter


class TiffFormatAdapter(LocalFileFormatAdapter):
    name = "tiff"
    supported_formats = ("tif", "tiff")

    def load(self, resource: ResourceRef) -> dict[str, object]:
        local_path = self._require_local_path(resource)
        with rasterio.open(local_path) as dataset:
            bounds = dataset.bounds
            crs = None if dataset.crs is None else dataset.crs.to_string()
            return {
                "path": str(local_path),
                "width": int(dataset.width),
                "height": int(dataset.height),
                "band_count": int(dataset.count),
                "dtypes": tuple(str(value) for value in dataset.dtypes),
                "crs": crs,
                "bounds": {
                    "left": float(bounds.left),
                    "bottom": float(bounds.bottom),
                    "right": float(bounds.right),
                    "top": float(bounds.top),
                },
            }
