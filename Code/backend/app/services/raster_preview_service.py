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
            raise ValueError(
                f"Raster preview dependencies unavailable: {exc.__class__.__name__}"
            ) from exc

        palette_colors = numpy.array(
            _PALETTES.get(palette) or _PALETTES["wind-blue"], dtype="float32"
        )
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
            max_value = (
                float(masked_array.max())
                if masked_array.count()
                else max(min_value + 1.0, 1.0)
            )
        if max_value <= min_value:
            max_value = min_value + 1.0

        data = masked_array.filled(min_value).astype("float32")
        norm = numpy.clip(
            (data - float(min_value)) / (float(max_value) - float(min_value)), 0.0, 1.0
        )
        anchors = numpy.linspace(0.0, 1.0, len(palette_colors), dtype="float32")

        red = numpy.interp(norm, anchors, palette_colors[:, 0]).astype("uint8")
        green = numpy.interp(norm, anchors, palette_colors[:, 1]).astype("uint8")
        blue = numpy.interp(norm, anchors, palette_colors[:, 2]).astype("uint8")
        alpha = numpy.where(numpy.ma.getmaskarray(masked_array), 0, 255).astype("uint8")

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

    def render_cog_preview_reprojected(
        self,
        *,
        cog_path: str | Path,
        palette: str,
        width: int,
        height: int,
        source_crs: str,
        target_crs: str = "EPSG:4326",
        min_value: float | None = None,
        max_value: float | None = None,
    ) -> tuple[bytes, tuple[float, float, float, float]]:
        """重投影栅格到 ``target_crs`` 后生成 PNG，返回 ``(png_bytes, target_bounds)``。

        内部用 ``rasterio.warp.calculate_default_transform`` + ``reproject``：
        1. 读源栅格 CRS/bounds
        2. ``calculate_default_transform(src_crs, dst_crs, ...)`` 得到目标 transform/尺寸
        3. ``reproject`` 把源 band 重采样到目标网格（bilinear）
        4. 按原 ``render_cog_preview`` 着色逻辑生成 PNG
        5. ``array_bounds(dst_height, dst_width, dst_transform)`` 得目标 bounds

        Args:
            cog_path: 源 GeoTIFF 路径
            palette: 配色方案（同 ``render_cog_preview``）
            width/height: 输出 PNG 尺寸上限（实际 dst 尺寸由 calculate_default_transform 决定）
            source_crs: 源 CRS code（如 'EPSG:32650'）
            target_crs: 目标 CRS code（默认 'EPSG:4326'）
            min_value/max_value: 着色值域，None 时自动从重投影后数据推断

        Returns:
            ``(png_bytes, (west, south, east, north))``，bounds 在 ``target_crs`` 下
        """
        try:
            numpy = importlib.import_module("numpy")
            rasterio = importlib.import_module("rasterio")
            memory_file_cls = importlib.import_module("rasterio.io").MemoryFile
            resampling = importlib.import_module("rasterio.enums").Resampling
            warp = importlib.import_module("rasterio.warp")
            array_bounds = importlib.import_module("rasterio.transform").array_bounds
        except Exception as exc:  # pragma: no cover - optional dependency path
            raise ValueError(
                f"Raster preview dependencies unavailable: {exc.__class__.__name__}"
            ) from exc

        palette_colors = numpy.array(
            _PALETTES.get(palette) or _PALETTES["wind-blue"], dtype="float32"
        )
        # width/height 仅作为 dst 计算的输入提示，最终由 calculate_default_transform 决定
        width = max(64, min(2048, int(width)))
        height = max(64, min(2048, int(height)))

        with rasterio.open(Path(cog_path)) as dataset:
            src_bounds = dataset.bounds  # (west, south, east, north) in source_crs
            src_transform = dataset.transform
            src_width = dataset.width
            src_height = dataset.height
            src_band = dataset.read(1, masked=True)
            src_nodata = dataset.nodata

            # 投影域钳位：避免 EASE 等全球网格因浮点越界导致东缘经度折返
            try:
                from app.data_io.services.grid_presets import (
                    clamp_projected_bounds_to_crs_domain,
                    normalize_geographic_bounds,
                )

                sw, ss, se, sn = clamp_projected_bounds_to_crs_domain(
                    float(src_bounds.left),
                    float(src_bounds.bottom),
                    float(src_bounds.right),
                    float(src_bounds.top),
                    source_crs,
                )
                src_span_hint = abs(se - sw)
            except Exception:
                sw, ss, se, sn = (
                    float(src_bounds.left),
                    float(src_bounds.bottom),
                    float(src_bounds.right),
                    float(src_bounds.top),
                )
                normalize_geographic_bounds = None  # type: ignore[assignment]
                src_span_hint = abs(se - sw)

            # 计算目标 CRS 下覆盖完整范围的 transform/尺寸
            dst_transform_full, dst_width_full, dst_height_full = (
                warp.calculate_default_transform(
                    source_crs,
                    target_crs,
                    src_width,
                    src_height,
                    sw,
                    ss,
                    se,
                    sn,
                )
            )
            full_west, full_south, full_east, full_north = array_bounds(
                dst_height_full, dst_width_full, dst_transform_full
            )

            # 限制预览像素尺寸，但必须用 from_bounds 重建 Affine，
            # 使缩略图仍覆盖完整地理范围（旧逻辑直接 min 尺寸却保留原 Affine，
            # 全球 EASE 会变成仅 NW 一角的错误 bounds）。
            from rasterio.transform import from_bounds as _from_bounds

            dst_width = max(1, min(width, int(dst_width_full)))
            dst_height = max(1, min(height, int(dst_height_full)))
            dst_transform = _from_bounds(
                full_west, full_south, full_east, full_north, dst_width, dst_height
            )

            # 重投影：用普通 ndarray 作 destination（不能用 MaskedArray + 标量 mask，
            # 否则 rasterio.warp.reproject 在 _warp.pyx 检查 mask 时报
            # "truth value of an array with more than one element is ambiguous"）。
            # 通过 dst_nodata + init_dest_nodata 让 reproject 把未映射像素填为 nodata，
            # 之后用 masked_values 重建掩码。
            dst_nodata = src_nodata if src_nodata is not None else float(-9999.0)
            dst_band = numpy.zeros((dst_height, dst_width), dtype="float32")
            warp.reproject(
                source=src_band,
                destination=dst_band,
                src_transform=src_transform,
                src_crs=source_crs,
                dst_transform=dst_transform,
                dst_crs=target_crs,
                resampling=resampling.bilinear,
                src_nodata=src_nodata,
                dst_nodata=dst_nodata,
                init_dest_nodata=True,
            )

        # 着色（与 render_cog_preview 一致）
        # masked_values 用容差比较浮点 nodata，避免 == 比较的精度问题；
        # 返回的 mask 在无 nodata 命中时为 nomask (False 标量)，下游已用
        # numpy.ma.getmaskarray() 兼容（见 alpha 计算行）。
        masked_array = numpy.ma.masked_values(dst_band, dst_nodata)
        if min_value is None:
            min_value = float(masked_array.min()) if masked_array.count() else 0.0
        if max_value is None:
            max_value = (
                float(masked_array.max())
                if masked_array.count()
                else max(min_value + 1.0, 1.0)
            )
        if max_value <= min_value:
            max_value = min_value + 1.0

        data = masked_array.filled(min_value).astype("float32")
        norm = numpy.clip(
            (data - float(min_value)) / (float(max_value) - float(min_value)), 0.0, 1.0
        )
        anchors = numpy.linspace(0.0, 1.0, len(palette_colors), dtype="float32")

        red = numpy.interp(norm, anchors, palette_colors[:, 0]).astype("uint8")
        green = numpy.interp(norm, anchors, palette_colors[:, 1]).astype("uint8")
        blue = numpy.interp(norm, anchors, palette_colors[:, 2]).astype("uint8")
        alpha = numpy.where(numpy.ma.getmaskarray(masked_array), 0, 255).astype("uint8")

        with memory_file_cls() as memory_file:
            with memory_file.open(
                driver="PNG",
                width=dst_width,
                height=dst_height,
                count=4,
                dtype="uint8",
            ) as dataset:
                dataset.write(red, 1)
                dataset.write(green, 2)
                dataset.write(blue, 3)
                dataset.write(alpha, 4)
            png_bytes = memory_file.read()

        # 目标 bounds：与重建后的 Affine 一致；地理系再做日界线/塌缩规范化
        west, south, east, north = array_bounds(dst_height, dst_width, dst_transform)
        if west > east:
            west, east = east, west
        if south > north:
            south, north = north, south
        if (
            target_crs in ("EPSG:4326", "EPSG:4490", "EPSG:4258")
            and normalize_geographic_bounds
        ):
            try:
                west, south, east, north = normalize_geographic_bounds(
                    float(west),
                    float(south),
                    float(east),
                    float(north),
                    source_span_hint=src_span_hint,
                )
            except ValueError:
                pass
        return png_bytes, (float(west), float(south), float(east), float(north))


raster_preview_service = RasterPreviewService()
