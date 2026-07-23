from __future__ import annotations

import struct
from pathlib import Path

from data_access.contracts import ResourceRef
from data_access.format_adapters.base import LocalFileFormatAdapter

_SHAPE_TYPE_NAMES = {
    0: "null",
    1: "point",
    3: "polyline",
    5: "polygon",
    8: "multipoint",
    11: "pointz",
    13: "polylinez",
    15: "polygonz",
    18: "multipointz",
    21: "pointm",
    23: "polylinem",
    25: "polygonm",
    28: "multipointm",
    31: "multipatch",
}


class ShapefileFormatAdapter(LocalFileFormatAdapter):
    name = "shapefile"
    supported_formats = ("shp",)

    def load(self, resource: ResourceRef) -> dict[str, object]:
        local_path = self._require_local_path(resource)
        shape_type_code, bbox = _read_shp_header(local_path)
        dbf_path = local_path.with_suffix(".dbf")
        feature_count = _read_dbf_record_count(dbf_path) if dbf_path.exists() else None
        return {
            "path": str(local_path),
            "feature_count": feature_count,
            "geometry_type": _SHAPE_TYPE_NAMES.get(
                shape_type_code, f"shape_type_{shape_type_code}"
            ),
            "bbox": bbox,
        }


def _read_shp_header(local_path: Path) -> tuple[int, dict[str, float]]:
    header = local_path.read_bytes()[:100]
    if len(header) < 100:
        raise ValueError(f"Shapefile header is incomplete: {local_path}")
    shape_type = struct.unpack("<i", header[32:36])[0]
    xmin, ymin, xmax, ymax = struct.unpack("<4d", header[36:68])
    return shape_type, {
        "xmin": float(xmin),
        "ymin": float(ymin),
        "xmax": float(xmax),
        "ymax": float(ymax),
    }


def _read_dbf_record_count(dbf_path: Path) -> int:
    header = dbf_path.read_bytes()[:32]
    if len(header) < 32:
        raise ValueError(f"DBF header is incomplete: {dbf_path}")
    return int(struct.unpack("<I", header[4:8])[0])
