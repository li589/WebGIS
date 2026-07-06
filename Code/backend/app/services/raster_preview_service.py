from __future__ import annotations

import importlib
from pathlib import Path


_PALETTES: dict[str, list[tuple[int, int, int]]] = {
    "thermal-orange": [
        (49, 93, 255),
        (54, 197, 255),
        (124, 231, 176),
        (255, 209, 102),
        (255, 123, 84),
        (255, 77, 77),
    ],
    "precip-cyan": [
        (22, 50, 79),
        (28, 109, 208),
        (30, 200, 255),
        (112, 240, 255),
        (183, 255, 245),
        (245, 255, 255),
    ],
    "wind-blue": [
        (16, 49, 75),
        (29, 111, 165),
        (75, 185, 255),
        (132, 221, 255),
        (196, 243, 255),
    ],
}


class RasterPreviewService:
    def render_cog_preview(
        self,
        *,
        cog_path: str | Path,
        palette: str,
        width: int,
        height: int,
        min_value: float | None = None,
        max_value: float | None = None,
    ) -> bytes:
        try:
            numpy = importlib.import_module("numpy")
            rasterio = importlib.import_module("rasterio")
            memory_file_cls = importlib.import_module("rasterio.io").MemoryFile
            resampling = importlib.import_module("rasterio.enums").Resampling
        except Exception as exc:  # pragma: no cover - optional dependency path
            raise ValueError(f"Raster preview dependencies unavailable: {exc.__class__.__name__}") from exc

        palette_colors = numpy.array(_PALETTES.get(palette) or _PALETTES["wind-blue"], dtype="float32")
        width = max(64, min(2048, int(width)))
        height = max(64, min(2048, int(height)))

        with rasterio.open(Path(cog_path)) as dataset:
            band = dataset.read(
                1,
                out_shape=(height, width),
                resampling=resampling.bilinear,
                masked=True,
            )

        masked_array = numpy.ma.array(band, copy=False)
        if min_value is None:
            min_value = float(masked_array.min()) if masked_array.count() else 0.0
        if max_value is None:
            max_value = float(masked_array.max()) if masked_array.count() else max(min_value + 1.0, 1.0)
        if max_value <= min_value:
            max_value = min_value + 1.0

        data = masked_array.filled(min_value).astype("float32")
        norm = numpy.clip((data - float(min_value)) / (float(max_value) - float(min_value)), 0.0, 1.0)
        anchors = numpy.linspace(0.0, 1.0, len(palette_colors), dtype="float32")

        red = numpy.interp(norm, anchors, palette_colors[:, 0]).astype("uint8")
        green = numpy.interp(norm, anchors, palette_colors[:, 1]).astype("uint8")
        blue = numpy.interp(norm, anchors, palette_colors[:, 2]).astype("uint8")
        alpha = numpy.where(masked_array.mask, 0, 255).astype("uint8")

        with memory_file_cls() as memory_file:
            with memory_file.open(
                driver="PNG",
                width=width,
                height=height,
                count=4,
                dtype="uint8",
            ) as dataset:
                dataset.write(red, 1)
                dataset.write(green, 2)
                dataset.write(blue, 3)
                dataset.write(alpha, 4)
            return memory_file.read()


raster_preview_service = RasterPreviewService()
