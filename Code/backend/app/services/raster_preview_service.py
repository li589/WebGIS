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
    # Algorithm science products (omega_sf / SM / VOD)
    "cividis": [
        (0, 32, 77),
        (40, 86, 119),
        (102, 131, 122),
        (170, 166, 102),
        (224, 201, 90),
        (253, 231, 55),
    ],
    "viridis": [
        (68, 1, 84),
        (59, 82, 139),
        (33, 145, 140),
        (94, 201, 98),
        (253, 231, 37),
    ],
    "ylgnbu": [
        (255, 255, 217),
        (199, 233, 180),
        (127, 205, 187),
        (65, 182, 196),
        (29, 145, 192),
        (8, 29, 88),
    ],
}


def _mask_invalid_raster(numpy, band, *, nodata: float | None = None):
    """Mask nodata + non-finite samples so voids become transparent."""
    masked = numpy.ma.array(band, copy=False)
    invalid = ~numpy.isfinite(numpy.ma.filled(masked, numpy.nan))
    if nodata is not None and numpy.isfinite(nodata):
        invalid = invalid | numpy.isclose(
            numpy.ma.filled(masked, nodata), float(nodata), equal_nan=False
        )
    if numpy.ma.isMaskedArray(masked):
        invalid = invalid | numpy.ma.getmaskarray(masked)
    return numpy.ma.array(numpy.ma.filled(masked, numpy.nan), mask=invalid)


def _colorize_masked_band(
    numpy,
    masked_array,
    palette_colors,
    *,
    min_value: float | None,
    max_value: float | None,
):
    count = int(masked_array.count()) if hasattr(masked_array, "count") else 0
    if min_value is None:
        min_value = float(masked_array.min()) if count else 0.0
    if max_value is None:
        max_value = (
            float(masked_array.max()) if count else max(float(min_value) + 1.0, 1.0)
        )
    if not numpy.isfinite(min_value):
        min_value = 0.0
    if not numpy.isfinite(max_value) or max_value <= min_value:
        max_value = float(min_value) + 1.0

    fill = float(min_value)
    data = masked_array.filled(fill).astype("float32")
    data = numpy.where(numpy.isfinite(data), data, fill)
    norm = numpy.clip(
        (data - float(min_value)) / (float(max_value) - float(min_value)), 0.0, 1.0
    )
    anchors = numpy.linspace(0.0, 1.0, len(palette_colors), dtype="float32")
    red = numpy.interp(norm, anchors, palette_colors[:, 0]).astype("uint8")
    green = numpy.interp(norm, anchors, palette_colors[:, 1]).astype("uint8")
    blue = numpy.interp(norm, anchors, palette_colors[:, 2]).astype("uint8")
    alpha = numpy.where(numpy.ma.getmaskarray(masked_array), 0, 255).astype("uint8")
    return red, green, blue, alpha


def _finite_data_window_bounds(numpy, src_band, src_transform, *, pad_pixels: int = 8):
    """Return cropped source-CRS bounds covering finite pixels, or None.

    Used when valid data is a tiny fraction of a global grid so the preview
    and map fitBounds land on the actual patch instead of a black globe.
    """
    masked = _mask_invalid_raster(numpy, src_band)
    valid = ~numpy.ma.getmaskarray(masked)
    if not valid.any():
        return None
    valid_frac = float(valid.mean())
    if valid_frac >= 0.05:
        return None
    rows = numpy.where(valid.any(axis=1))[0]
    cols = numpy.where(valid.any(axis=0))[0]
    if rows.size == 0 or cols.size == 0:
        return None
    r0 = max(0, int(rows.min()) - pad_pixels)
    r1 = min(valid.shape[0] - 1, int(rows.max()) + pad_pixels)
    c0 = max(0, int(cols.min()) - pad_pixels)
    c1 = min(valid.shape[1] - 1, int(cols.max()) + pad_pixels)
    # pixel corners → source CRS
    xs = []
    ys = []
    for r, c in ((r0, c0), (r0, c1 + 1), (r1 + 1, c0), (r1 + 1, c1 + 1)):
        x, y = src_transform * (c, r)
        xs.append(float(x))
        ys.append(float(y))
    return min(xs), min(ys), max(xs), max(ys)


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

        masked_array = _mask_invalid_raster(numpy, band)
        red, green, blue, alpha = _colorize_masked_band(
            numpy,
            masked_array,
            palette_colors,
            min_value=min_value,
            max_value=max_value,
        )

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
        crop_to_data: bool = True,
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
            crop_to_data: 稀疏有效像元时是否裁到数据窗。时间序列全网格产品应关闭，
                否则各时刻裁剪范围不同 → 换时仅换 PNG 不换坐标时出现南北压缩/偏移。

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
            if src_nodata is None:
                # Float science rasters often store voids as NaN without nodata tag.
                src_nodata = float(-9999.0)

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

            # Sparse global products (e.g. max_pixels smoke runs): crop to the
            # finite-data window so the 1024px preview is not an empty globe.
            # Disable for multi-time full-grid science products (crop_to_data=False).
            if crop_to_data:
                crop = _finite_data_window_bounds(numpy, src_band, src_transform)
                if crop is not None:
                    sw, ss, se, sn = crop
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
            # 宽高必须按同一 scale 缩放：若各自 clamp 到 1024 会变成正方形，
            # 贴到 ~2:1 的全球地理框时就会「过度拉伸」。
            from rasterio.transform import from_bounds as _from_bounds

            fw = max(1, int(dst_width_full))
            fh = max(1, int(dst_height_full))
            scale = min(float(width) / fw, float(height) / fh, 1.0)
            dst_width = max(1, int(round(fw * scale)))
            dst_height = max(1, int(round(fh * scale)))
            dst_transform = _from_bounds(
                full_west, full_south, full_east, full_north, dst_width, dst_height
            )

            # 重投影：用普通 ndarray 作 destination（不能用 MaskedArray + 标量 mask）。
            # Fill NaN voids with src_nodata before warp so GDAL treats them as nodata.
            dst_nodata = float(src_nodata) if src_nodata is not None else float(-9999.0)
            src_for_warp = numpy.ma.filled(
                _mask_invalid_raster(numpy, src_band, nodata=src_nodata),
                dst_nodata,
            ).astype("float32")
            dst_band = numpy.full((dst_height, dst_width), dst_nodata, dtype="float32")
            warp.reproject(
                source=src_for_warp,
                destination=dst_band,
                src_transform=src_transform,
                src_crs=source_crs,
                dst_transform=dst_transform,
                dst_crs=target_crs,
                resampling=resampling.bilinear,
                src_nodata=dst_nodata,
                dst_nodata=dst_nodata,
                init_dest_nodata=True,
            )

        masked_array = _mask_invalid_raster(numpy, dst_band, nodata=dst_nodata)
        red, green, blue, alpha = _colorize_masked_band(
            numpy,
            masked_array,
            palette_colors,
            min_value=min_value,
            max_value=max_value,
        )

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
